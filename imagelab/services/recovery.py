"""Crash-safe reconciliation of local jobs with the generation backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from imagelab.repositories.jobs import JobRepository


class BackendDisconnected(RuntimeError):
    """The backend cannot currently be reached; ownership remains unchanged."""


class SubmissionUncertain(RuntimeError):
    """A submission may have been accepted but returned no durable identifier."""


@dataclass(frozen=True)
class BackendSnapshot:
    state: str
    progress: float | None = None
    detail: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class RecoverableBackend(Protocol):
    def find_by_correlation(self, token: str) -> str | None: ...
    def submit(self, run_id: str, token: str) -> str: ...
    def inspect(self, backend_job_id: str) -> BackendSnapshot: ...
    def collect(self, run_id: str, backend_job_id: str, snapshot: BackendSnapshot) -> bool: ...


class RecoveryCoordinator:
    """Advance one persisted job without ever blindly resubmitting it."""

    def __init__(self, repository: JobRepository, backend: RecoverableBackend):
        self.repository = repository
        self.backend = backend

    def step(self, job: dict[str, Any]) -> None:
        if job["state"] == "needs_attention":
            return
        if job["state"] == "submitting":
            self._submit_or_reconcile(job)
            return
        if job["state"] == "running":
            self._inspect(job)
            return
        raise ValueError(f"job state is not recoverable: {job['state']}")

    def _submit_or_reconcile(self, job: dict[str, Any]) -> None:
        had_intent = self.repository.has_event(job["id"], "submission_intent")
        if had_intent:
            try:
                recovered_id = self.backend.find_by_correlation(job["idempotency_key"])
            except SubmissionUncertain as exc:
                self.repository.mark_needs_attention(job["id"], str(exc))
                return
            except BackendDisconnected as exc:
                self.repository.note_event(job["id"], "backend_disconnected", {"message": str(exc)})
                return
            if recovered_id:
                self.repository.record_backend_acceptance(job["id"], recovered_id)
                return
            self.repository.mark_needs_attention(
                job["id"],
                "Submission intent exists but backend ownership cannot be proven; automatic resubmission is blocked.",
            )
            return

        self.repository.record_submission_intent(job["id"])
        try:
            backend_job_id = self.backend.submit(job["run_id"], job["idempotency_key"])
        except SubmissionUncertain as exc:
            self.repository.mark_needs_attention(job["id"], str(exc))
            return
        except BackendDisconnected as exc:
            # Intent crossed the durable boundary. A retry must reconcile by correlation first.
            self.repository.note_event(job["id"], "backend_disconnected", {"message": str(exc)})
            return
        self.repository.record_backend_acceptance(job["id"], backend_job_id)

    def _inspect(self, job: dict[str, Any]) -> None:
        backend_job_id = job.get("backend_job_id")
        if not backend_job_id:
            self.repository.mark_needs_attention(job["id"], "Running job has no backend identifier.")
            return
        try:
            snapshot = self.backend.inspect(backend_job_id)
        except BackendDisconnected as exc:
            self.repository.note_event(job["id"], "backend_disconnected", {"message": str(exc)})
            return

        if snapshot.state in {"queued", "running"}:
            detail: dict[str, Any] = {"backend_state": snapshot.state}
            if snapshot.progress is not None:
                detail["progress"] = snapshot.progress
            self.repository.heartbeat(job["id"], detail)
            return
        if snapshot.state == "succeeded":
            if not self.backend.collect(job["run_id"], backend_job_id, snapshot):
                self.repository.mark_needs_attention(job["id"], "Backend completed but the output artifact is missing.")
                return
            self.repository.succeed(job["id"])
            return
        if snapshot.state == "failed":
            self.repository.fail(job["id"], RuntimeError(snapshot.detail or "backend generation failed"))
            return
        self.repository.mark_needs_attention(
            job["id"], f"Backend history is unavailable or ambiguous for {backend_job_id}."
        )
