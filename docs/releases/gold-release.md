# Mac Image Lab Gold release

**Release status:** Shipped
**Release date:** 2026-09-22 MDT
**Branch:** `gold-workspace`
**Validated generator:** `qwen-image-2.1-local` only
**Private URL:** `https://alastairs-mac-mini.tail97e4dc.ts.net/`

## What shipped

Mac Image Lab now supports the full local-first workflow:

**create → transform → compare → favorite → organize → export**

- Image-first Library with bounded SQLite queries and private thumbnails.
- Durable generation queue with one separately supervised worker.
- Qwen-Image-2.1 text generation and best-effort reference transforms.
- Family lineage, comparison, preferred versions, favorites, reversible Trash, and safe Finder collections.
- Original PNG, JPEG/WebP, resized child runs, and bounded family ZIP exports.
- Separate iPhone **Save to Photos** and **Download to Files** actions.
- Loopback-only Waitress and ComfyUI behind private Tailscale HTTPS.
- LaunchAgent supervision, generation-scoped sleep prevention, bounded logs, diagnostics, backup, and restore procedures.
- Explicit per-run R2 archival with SHA-256 metadata and `head_object` verification.

## Gold proof

### Real create

- Run: `60a94575-0936-4aa1-a252-27bfb5d06565`
- Result: succeeded, 768×768.
- Request: cobalt-blue ceramic mug on a warm neutral pedestal.
- Recovery: Waitress was restarted while the job was active; the job continued and the web endpoint reconnected healthy.
- Visual QA: coherent requested subject, color, pedestal, and studio lighting; no text, logo, watermark, or rendering failure.

### Real transform

- Run: `66d1df1a-8d2b-400b-8309-3357fadb98f3`
- Parent: `60a94575-0936-4aa1-a252-27bfb5d06565`
- Relationship: `reference_transform`
- Result: succeeded, 768×768.
- Recovery: the worker was restarted while the backend job was active; reconciliation completed without duplicate submission.
- Visual QA: requested blue-to-forest-green change succeeded, but composition retention was imperfect. The mug shape, pedestal, framing, and background changed materially. This confirms the documented best-effort limitation rather than exact edit preservation.

### Real regenerate-larger

- Run: `d5aa8644-9e56-43ce-83f6-57a24de2fd36`
- Parent: `60a94575-0936-4aa1-a252-27bfb5d06565`
- Relationship: `regenerate_larger`
- Result: succeeded at 1024×1024 with an affordable 8-step request.
- Visual QA: coherent cobalt-blue mug concept and studio image; composition changed as expected for a new model run; no text, logo, watermark, or rendering failure.

All three runs passed `scripts/release_check.py`: required evidence exists, JSON is valid, output hashes and dimensions match receipts, and child family lineage matches the parent. HTTPS downloads matched local output SHA-256 hashes.

## R2 evidence

The three Gold proof runs were explicitly archived under:

`hermes-data/Marvin/Mac Image Lab/runs/<run-id>/`

Independent `head_object` verification passed for all 26 archived objects, including each output, workflow, backend submission/history, model manifest, lineage record, final receipt, archive record, and the transform's retained source evidence.

## Release gates

- Full automated suite: 155 passed.
- Focused security/upload/archive/organization suite: 30 passed.
- Python compilation: passed.
- JavaScript syntax checks: passed.
- `git diff --check`: passed.
- Dependency audit after upgrades: no known vulnerabilities.
- Tracked-source allowlist: no credentials, runtime DB, logs, generated images, validation evidence, virtual environment, model weights, or secret files.
- Secret-pattern scan: no findings.
- Restore rehearsal: integrity and rollback passed in isolated directories.
- Production health: Waitress and ComfyUI remain loopback-only; Tailscale HTTPS is the only trusted-device route.

## Device acceptance

Confirmed by Alastair:

- Image Lab opens on iPhone through Tailscale over Wi-Fi.
- Image Lab opens on iPhone through Tailscale with Wi-Fi disabled.
- Image downloads reach iPhone Files/Downloads.
- **Open on host Mac** is visibly labeled as a host-Mac-only action.

Implemented but not explicitly reported after deployment:

- One physical iPhone **Save to Photos → Save Image** result.
- A separate second-computer walkthrough.

These are user-device acceptance gaps, not unimplemented code paths. Browser/device tests verify the implementation; they do not substitute for physical-device confirmation.

## Known limits

- Identity, object, and composition retention during transforms is best effort.
- Maximum native 2K generation remains deliberately expensive in time; Gold proved a real 1024×1024 larger run instead.
- Per-user LaunchAgents require the `alastairfraser` GUI session and are unavailable before FileVault unlock.
- Real logout/reboot recovery was not exercised because it is disruptive and requires separate approval.
- No additional generator, public endpoint, LAN fallback, or paid online provider was added.

## Operating references

- Daily operation and diagnostics: `docs/operations.md`
- Backup and restore: `docs/restore.md`
- Trusted-device setup: `docs/device-install.md`
- Build record: `docs/plans/BUILD-STATE.md`
- Gold plan: `docs/plans/GOLD-BUILD-PLAN.md`
- Release verifier: `scripts/release_check.py`
