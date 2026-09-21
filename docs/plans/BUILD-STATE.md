# Mac Image Lab Gold Build State

Updated: 2026-09-21 MDT
Branch: `gold-workspace`
Baseline commit: `081de8f0db5939a8339c0552e82fcd1a85b3b82f`
Plan: `docs/plans/GOLD-BUILD-PLAN.md`

## Current task

### T10 — Queue controls and telemetry: completed locally

Commit: `dd33141092a4e140f7cfc6aa60e379a43bf21afc`

Implemented:
- Compact allowlisted `GET /api/jobs` telemetry exposes job state, timestamps, attempts, sanitized status, and persisted backend progress without exposing submission tokens, receipt paths, workflows, or raw backend payloads.
- Queued cancellation uses a conditional SQLite state transition. Running cancellation is attempted only when the exact owned ComfyUI prompt is the sole active backend job; otherwise the API returns a safe conflict.
- Retry creates a distinct run and job linked through `job_retries`; it never reuses the original run directory.
- `/queue` polls compact JSON, shows active/recovery states, backs off visibly on disconnection, and offers only state-appropriate cancel/retry actions.

TDD evidence:
- RED: the new queue API tests initially failed because the queue route and controls did not exist; persisted heartbeat progress was initially omitted from the allowlisted response.
- GREEN: focused queue/job/recovery suite `23 passed`; full suite `87 passed, 1 xfailed in 0.47s`; Python compile and diff checks passed.
- The remaining strict expected failure belongs to T12 actual-output display.
- No live worker restart or production service cutover was performed.

### T09 — Interruption reconciliation and long-job safety: completed locally

Commit: `b600f939b39de950b167ff325a868498c5e9f1ba`

Implemented:
- Durable submission intent is recorded before contacting ComfyUI; correlation tokens are reused to find accepted work after a crash.
- Worker startup resumes `submitting` or `running` jobs before claiming new work. A `needs_attention` job blocks the heavyweight queue.
- ComfyUI recovery searches history and queue by correlation token, persists prompt IDs immediately, and inspects backend state without a fixed wall-clock failure deadline.
- Backend disconnects preserve ownership and emit local diagnostic events. Ambiguous submission, multiple matches, vanished history, missing output, or an unowned running record becomes `needs_attention` rather than triggering a duplicate.
- Completed backend work can be collected after worker restart. Output discovery no longer assumes a fixed ComfyUI output-node ID.
- Generation state in SQLite follows backend acceptance, success, failure, and recovery-required transitions; archival state remains independent.
- Stale heartbeats are queryable for diagnostics but do not automatically fail or resubmit long-running work.

TDD evidence:
- RED: recovery tests initially failed because `imagelab.services.recovery` did not exist; the first active-job claim implementation allowed a second heavyweight claim; ambiguous correlation exceptions escaped instead of blocking safely; stale-heartbeat inspection was absent.
- GREEN: focused recovery/job/app suite `29 passed`; full suite `81 passed, 1 xfailed in 0.48s`; compile and diff checks passed.
- Tests cover each submission boundary, restart without resubmission, completion before reconnect, disconnect/recovery, uncertain acceptance, unknown history, missing output, stale heartbeat, and dynamic output-node discovery.
- No live worker restart or production service cutover was performed; service-level recovery is deferred to the approved T20/T23 exercises.

### T08 — Persistent generation jobs and standalone worker: completed locally

Commit: `a47f26a6118dc38e71c866e3f944dd430f8b6dab`

Implemented:
- Durable SQLite generation jobs and ordered job events with unique idempotency keys and one generation job per run.
- Transactional `BEGIN IMMEDIATE` queue claims; an unresolved `submitting`, `running`, or `needs_attention` job blocks the next heavyweight claim.
- A standalone `imagelab.worker` process with a non-blocking macOS advisory lock, one-shot mode, and injectable execution for tests.
- Web submissions now persist jobs and return immediately. Importing or running the web app does not create a generation worker thread.
- Browser retries with the same hidden idempotency key return the original run and do not create a second run directory or job.
- Text generation, reference transforms, and Explore submissions use the persistent queue; queue depth comes from SQLite.
- Existing in-memory generation queue and daemon thread were removed. The separate bounded archive queue is unchanged.

TDD evidence:
- RED: `tests/test_jobs.py` initially failed collection because `imagelab.repositories.jobs` did not exist; the existing duplicate-submit regression remained a strict expected failure. A later running-job test proved the first claim implementation incorrectly claimed a second heavyweight job.
- GREEN: focused job/regression suite `9 passed`; full suite `69 passed, 1 xfailed in 0.42s`; compile and diff checks passed.
- The remaining strict xfail belongs to T12 actual-output display.
- No live worker or service cutover was performed; that remains behind the T20 approval checkpoint.

### T07 — SQLite source of truth and legacy migration: completed locally

Commit: `27bb90db201d379a4922a797fa174c71640260c0`

Implemented:
- Versioned SQLite schema with WAL, foreign keys, busy timeout, indexed runs/families/states, jobs/events, collections, model notes, recipes, family choices, and archive attempts.
- `RunRepository` for idempotent receipt upserts, indexed reads/search, collection mappings, and favorite state.
- Application receipt writes now atomically update evidence and SQLite; production reads use SQLite with a legacy-file fallback only when a database has not yet been created.
- Dry-run-first migration with source receipt SHA-256 inventory, explicit malformed-record reporting/quarantine, schema-v1 Qwen model inference from recorded asset filenames only, idempotent reruns, collection/model-note import, and hash reconciliation.
- SQLite online backup and isolated restore rehearsal.
- Operator documentation in `docs/database-and-migration.md`.

Real migration evidence:
- Dry run: 3 valid receipts, 0 malformed, 0 hash mismatches; no database write.
- Apply: 3 imported, 3 database rows, all 3 receipt hashes reconciled.
- `PRAGMA integrity_check`: `ok`.
- Backup: 122,880 bytes; isolated restore: 3 rows and integrity `ok`.

TDD evidence:
- RED: migration tests initially failed because `imagelab.db` did not exist; repository tests initially failed because `imagelab.repositories` did not exist; legacy-v1 inference initially reported the valid archived Qwen run as malformed.
- GREEN: focused migration/repository/app/regression suite `19 passed, 2 xfailed`; full suite `60 passed, 2 xfailed in 0.36s`; compile and diff checks passed.
- Remaining strict xfails belong to T08 persistent idempotent enqueue and T12 actual-output display.

### T06 — Atomic evidence and complete archival: completed locally

Commit: `948d7fe62fb91c782ba264eb74eb93f82638aae8`

Implemented:
- Atomic replacement for mutable receipts and model notes.
- Separate `generation_state` and `archive_state`, with compatibility normalization for legacy receipts. Archive failure no longer turns a successful generation into a failed generation.
- `imagelab/services/archive.py` snapshots output, workflow, Comfy submission/history, original reference, normalized inference reference, model manifest, and lineage manifest when applicable.
- Every uploaded evidence object is verified through `head_object` length and SHA-256 metadata. Final receipt and archive manifest are also uploaded and head-verified.
- Explicit archival is idempotent over deterministic keys. Partial upload, missing evidence, head mismatch, and credential-factory failures persist a sanitized failed archive state and can be retried.
- Browser archive requests now enqueue bounded archive work and return immediately rather than holding the HTTP request through the transfer.
- The reference-archive regression is now a normal passing test.

TDD evidence:
- RED: `tests/test_archive.py` initially failed because `imagelab.services.archive` did not exist; the reference-source regression previously failed under `--runxfail`.
- GREEN: archive/regression/app target suite `17 passed, 2 xfailed`; full suite `53 passed, 2 xfailed in 0.31s`; Python compile passed.
- Remaining strict xfails belong to T08 persistent idempotent enqueue and T12 actual-output display.

### T05 — Model contracts, registry, and Qwen adapter: completed locally

Commit: `3c7eaa2510dd53ac827de53e092a2950b61b9a94`

Implemented:
- Typed immutable model, backend-job/status, output-artifact, unsupported-operation, and adapter contracts.
- A verified registry that only exposes models marked installed, validated, and available.
- Qwen-Image-2.1 metadata, profiles, capabilities, warnings, guidance, artifact identities, and runtime-estimate provenance now live in its model specification.
- Exact validated text-to-image and reference-conditioned ComfyUI graphs moved from the Flask web layer into `Qwen21Adapter` without node rewiring.
- Existing compatibility helpers dispatch through the registry, so a future model needs an adapter and registry entry rather than template-specific workflow code.
- The contradictory write-only `/reference/upload` endpoint now returns HTTP 410 and directs clients to `/transform` without writing files.
- `docs/model-adapters.md` documents the evidence-gated onboarding route for future local or online models. No second model was installed or enabled.

TDD evidence:
- RED: adapter tests initially failed collection because `imagelab.models.qwen21` and the registry did not exist.
- GREEN: adapter/app/validation target suite `28 passed`; full suite `47 passed, 3 xfailed in 0.32s`; Python compile and diff checks passed.
- Contract tests cover exact Qwen filenames/wiring, source-conditioned latent shape, required source name, explicit unsupported operations, registry availability truth, future-model metadata behavior, and legacy-route retirement.

### T04 — Harden image ingestion: completed locally

Commit: `545642a69d95dafd1e20bd73fee4945555137c02`

Implemented:
- `imagelab/storage.py` performs compressed-size, declared/decoded format, full-decode, decoded-pixel, still-image, and corruption checks.
- EXIF orientation is applied to a normalized PNG derivative; ordinary inference/export derivative metadata is stripped.
- Original and derivative bytes retain independent SHA-256 provenance. The original upload is stored privately with a fixed internal name; the browser filename is never used as a path.
- Original, derivative, workflow, and receipt are written atomically in a staged run directory. The normalized derivative is atomically copied to ComfyUI input; failures clean the staged run and backend file.
- Transform receipts now distinguish original source from inference derivative and record normalized dimensions, format, mode, orientation handling, and both hashes.
- HEIC remains explicitly unsupported in this release rather than misleadingly accepted.

TDD evidence:
- RED: `tests/test_uploads.py` first failed because `imagelab/storage.py` did not exist. Integration tests then failed because the old transform saved only raw uploads and surfaced Pillow errors directly.
- GREEN: upload suite `14 passed`; Python compile passed; full suite `40 passed, 3 xfailed in 0.29s`.
- Coverage includes forged MIME, corrupt/truncated input, 20 MiB/413 limit, 50-million decoded-pixel limit, animation, EXIF orientation, metadata removal, traversal, atomic writes, malicious browser filename, staged cleanup, and simulated backend-write failure.

### T03 — Normalize generation requests: completed locally

Commit: `bb1d905c9f50cee6378777d61541d42140c59d4d`

Implemented:
- Immutable `GenerationRequest` and one pure normalization path in `imagelab/validation.py`.
- Explicit profiles now override parent dimensions/steps; variation/repeat inheritance is action-specific.
- Explicit seed `0` is preserved; repeat may reuse a parent seed; variation gets a fresh seed.
- Dimensions, 32-pixel alignment, steps, seed, model, profile, action, and validated pixel-area ceiling are checked before run files are created.
- Regenerate-larger preserves square, portrait, or landscape aspect ratio while increasing pixel area within the selected validated profile.
- Text and reference-transform requests use the same normalizer. Unknown transform profiles now fail before run/backend writes.
- Explore submits an explicit `variation` or `regenerate_larger` action.

TDD evidence:
- RED: `tests/test_validation.py` initially failed collection because the module did not exist; the two paired regression tests previously failed under `--runxfail`.
- GREEN: targeted tests `14 passed, 3 xfailed`; full suite `26 passed, 3 xfailed in 0.25s`; Python compile passed.
- Remaining strict xfails belong to T06 archive completeness, T08 idempotent persistent enqueue, and T12 actual-output display.

### T02 — Regression tests: completed

Commit: `3ca2e8bd1a05aed12a5b5030755a7c418f16246e`

Added `tests/test_regressions.py` with five strict expected-failure tests covering:
- explicit larger profile versus inherited parent dimensions/steps;
- transform profile validation before any run/backend writes;
- reference source inclusion in explicit archives;
- actual output dimensions in the run detail;
- duplicate browser submission enqueueing.

RED evidence: `.venv/bin/python -m pytest tests/test_regressions.py --runxfail -q` produced five expected failures and exit 1, each at the confirmed defect. Normal strict-xfail gate: `5 xfailed`. Full suite: `12 passed, 5 xfailed in 0.25s`. These tests are temporary executable debt markers; remove each xfail only with its T03, T06, T08, or T12 fix.

### T01 — Backup and inventory: completed locally

Commit: `b3fddd8147894fec9096a988c810164368172049`

Implemented:
- Read-only, JSON diagnostics at `scripts/verify_install.py`.
- Allowlisted local source and metadata backup with SHA-256 manifest.
- Secret-minimization, read-only, exclusion, manifest-hash, and Git-path regression tests.
- Runtime Git ignores for `backups/`, `state/`, thumbnail cache, references, and exports.
- Pytest collection restricted to `tests/` so ignored backup source is not collected as duplicate tests.

TDD evidence:
- RED: `.venv/bin/python -m pytest tests/test_install.py -q` failed during collection because `scripts/verify_install.py` did not exist.
- GREEN: targeted suite passed: `3 passed in 0.13s`.
- Full suite initially exposed backup test collection as a real integration defect; adding `pytest.ini` fixed it.
- Final full suite: `.venv/bin/python -m pytest -q` -> `12 passed in 0.21s`.

Inventory snapshot:
- Branch `gold-workspace`; source baseline commit above.
- Three legacy run receipts were found and SHA-256 inventoried without rewriting them.
- ComfyUI queue: zero running and zero pending jobs.
- App listener: PID 73756, loopback TCP 7864.
- ComfyUI listener: PID 37424, loopback TCP 8188.
- Dependencies inventoried by package name and pinned version only.
- Dirty paths before the focused commit: `.gitignore`, approved `docs/plans/`, `pytest.ini`, `scripts/`, `tests/test_install.py`, and preserved untracked `validation/`.
- No live service, Tailscale setting, receipt, generated image, or validation artifact was changed.

Local backup used for rollback:
- Directory: `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab/backups/gold-baseline-20260921T152631Z`
- Manifest: `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab/backups/gold-baseline-20260921T152631Z/manifest.json`
- Manifest contents: 45 allowlisted files, 192754 bytes.
- Excluded: credentials/environment files, virtual environments, model weights, generated images, validation evidence, logs, and release archives.

Restore procedure:
1. Stop before restoring if production has gained new runs; reconcile those runs first.
2. Verify the selected backup file SHA-256 values against `manifest.json`.
3. Copy only the required paths from the backup `files/` tree to the manifest `source_root`.
4. Do not replace the whole project, overwrite runtime data, or restart services blindly.

R2 status:
- No T01 runtime backup was uploaded. The backup is local by design; the approved plan/handoff already have separately verified R2 copies.

## Next task

T11 — App factory and request protection: extract configuration/security/routes, add CSRF and origin/host enforcement, secure cookies and headers, and keep production startup fail-closed.

## Constraints carried forward

- Preserve untracked `validation/`; never blanket-add it.
- Keep Tailscale-only access and loopback-only app/backend listeners.
- Keep Qwen-Image-2.1 as the only selectable generator.
- Do not interrupt live work, cut over services, or modify Tailscale without the plan's approval checkpoint.
- Explicit R2 archive only; never silently upload personal source images.
