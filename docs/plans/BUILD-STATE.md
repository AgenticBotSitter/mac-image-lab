# Mac Image Lab Gold Build State

Updated: 2026-09-21 MDT
Branch: `gold-workspace`
Baseline commit: `081de8f0db5939a8339c0552e82fcd1a85b3b82f`
Plan: `docs/plans/GOLD-BUILD-PLAN.md`

## Current task

### T06 — Atomic evidence and complete archival: completed locally

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

T07 — Introduce the local SQLite source of truth and idempotent legacy migration with dry-run, malformed-record quarantine, count/hash reconciliation, SQLite backup, and isolated rollback rehearsal.

## Constraints carried forward

- Preserve untracked `validation/`; never blanket-add it.
- Keep Tailscale-only access and loopback-only app/backend listeners.
- Keep Qwen-Image-2.1 as the only selectable generator.
- Do not interrupt live work, cut over services, or modify Tailscale without the plan's approval checkpoint.
- Explicit R2 archive only; never silently upload personal source images.
