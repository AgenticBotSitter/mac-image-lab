# Mac Image Lab Gold Build State

Updated: 2026-09-21 MDT
Branch: `gold-workspace`
Baseline commit: `081de8f0db5939a8339c0552e82fcd1a85b3b82f`
Plan: `docs/plans/GOLD-BUILD-PLAN.md`

## Current task

### T02 — Regression tests: completed

Added `tests/test_regressions.py` with five strict expected-failure tests covering:
- explicit larger profile versus inherited parent dimensions/steps;
- transform profile validation before any run/backend writes;
- reference source inclusion in explicit archives;
- actual output dimensions in the run detail;
- duplicate browser submission enqueueing.

RED evidence: `.venv/bin/python -m pytest tests/test_regressions.py --runxfail -q` produced five expected failures and exit 1, each at the confirmed defect. Normal strict-xfail gate: `5 xfailed`. Full suite: `12 passed, 5 xfailed in 0.25s`. These tests are temporary executable debt markers; remove each xfail only with its T03, T06, T08, or T12 fix.

### T01 — Backup and inventory: completed locally

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

T03 — Normalize text and transform generation requests with one validated input path. Remove the first two strict xfails only after they pass normally; add boundary tests for dimensions, area, steps, seeds (including explicit zero), unknown profiles, and larger aspect handling.

## Constraints carried forward

- Preserve untracked `validation/`; never blanket-add it.
- Keep Tailscale-only access and loopback-only app/backend listeners.
- Keep Qwen-Image-2.1 as the only selectable generator.
- Do not interrupt live work, cut over services, or modify Tailscale without the plan's approval checkpoint.
- Explicit R2 archive only; never silently upload personal source images.
