"""Typed generator contracts shared by registry, adapters, worker, and UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from imagelab.validation import GenerationRequest


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    version: str
    source: str
    adapter_id: str
    installed: bool
    validated: bool
    available: bool
    capabilities: frozenset[str]
    profiles: Mapping[str, Mapping[str, Any]]
    guidance: Mapping[str, Any]
    warnings: tuple[str, ...]
    artifacts: Mapping[str, str]
    runtime_estimate_provenance: str


@dataclass(frozen=True)
class BackendJob:
    prompt_id: str
    correlation_id: str


@dataclass(frozen=True)
class BackendStatus:
    state: str
    progress: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class OutputArtifact:
    path: Path
    width: int
    height: int
    sha256: str


@dataclass(frozen=True)
class UnsupportedOperation:
    operation: str
    reason: str
    supported: bool = False


class GeneratorAdapter(Protocol):
    spec: ModelSpec

    def probe(self) -> Mapping[str, Any] | UnsupportedOperation: ...
    def validate(self, request: GenerationRequest) -> GenerationRequest: ...
    def build_workflow(self, request: GenerationRequest, *, prefix: str, input_name: str | None = None) -> dict[str, Any]: ...
    def submit(self, request: GenerationRequest, correlation_id: str) -> BackendJob | UnsupportedOperation: ...
    def inspect(self, job: BackendJob) -> BackendStatus | UnsupportedOperation: ...
    def collect(self, job: BackendJob) -> tuple[OutputArtifact, ...] | UnsupportedOperation: ...
    def cancel(self, job: Mapping[str, Any] | BackendJob) -> Mapping[str, Any] | UnsupportedOperation: ...
    def unload(self) -> Mapping[str, Any] | UnsupportedOperation: ...
