# Mac Image Lab — Builder Handoff

## Start here

Read `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab/docs/plans/GOLD-BUILD-PLAN.md` before changing code. It is the self-contained specification, with architecture, target files, ordered T01–T24 work packets, tests, migration rules, security boundaries and acceptance gates.

Planning is complete; implementation has NOT started. Wait for Alastair's build instruction after his chosen model switch. Do not switch models yourself or assume spoken model names are provider identifiers.

## Locked direction

- Tailscale is installed on every user device. Use existing HTTPS; NO separate LAN endpoint.
- Keep Flask/Jinja; SQLite persistent queue/library; one separate worker; production serving and macOS supervision.
- Library-first image-forward UI, unified Create/Transform, proper lineage and comparison, collections/favorites/export, mobile usability.
- Only existing validated Qwen-Image-2.1 is active. Add a small typed adapter/registry seam for future generators, not new models now.
- Local-first artwork; explicit archive only. Never silently upload personal reference photos.
- Preserve all legacy runs, IDs, artwork and untracked validation evidence.

## Baseline recorded during planning

Root: `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab`
Git: `081de8f0db5939a8339c0552e82fcd1a85b3b82f`
Tests: 9 passed. Untracked `validation/` exists; do not add it wholesale to Git.
App: `127.0.0.1:7864`; ComfyUI: `127.0.0.1:8188`.
Tailnet: `https://alastairs-mac-mini.tail97e4dc.ts.net/`.
Recheck these before implementation; they are a planning snapshot, not eternal runtime truth.

## Execution loop

1. Load `mac-image-workspace`, `writing-plans`, and appropriate testing/project-operation skills. For delegated tasks load `subagent-driven-development`.
2. Read BUILD-STATE if it exists. Start at the first incomplete task, not the beginning of the whole project.
3. Inventory active work and dirty files. Use branch `gold-workspace`; preserve unrelated changes.
4. Work sequentially, RED -> minimal implementation -> GREEN -> diff review -> focused commit. Avoid costly broad fan-out.
5. Update BUILD-STATE per task with actual evidence, next task and approval blockers. Mirror meaningful milestone records to canonical R2.
6. Ask only at defined taste/cutover/device/disruptive-operation checkpoints; routine reversible details are builder-owned.
7. Never claim real browser/device/model validation based solely on mock tests or source inspection.

## First milestone

M0: inventory, backup, baseline diagnostics and targeted regression tests. Then M1: fix profile/transform/archive correctness and extract the validated Qwen adapter. Do not begin with a visual rewrite or additional model download.

## Durable locations

Bucket: `hermes-data`
Plan key: `Marvin/Mac Image Lab/docs/plans/GOLD-BUILD-PLAN.md`
Handoff key: `Marvin/Mac Image Lab/docs/plans/BUILDER-HANDOFF.md`
Verification key: `Marvin/Mac Image Lab/docs/plans/PLAN-VERIFICATION.json`
Credentials: approved local configuration only; see r2-storage skill. Verify every uploaded object with boto3.head_object.

## Suggested instruction after switching models

Read the Mac Image Lab GOLD-BUILD-PLAN.md and BUILDER-HANDOFF.md in the project's docs/plans directory. Begin M0 and continue sequentially through the plan, maintaining BUILD-STATE.md with real tests and evidence. Preserve existing data, keep Tailscale-only access, do not add models, and stop for the plan's explicit approval checkpoints. Do not restart planning from scratch.
