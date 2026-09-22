# Mac Image Lab — Gold Implementation Plan

> **For Hermes:** Use the subagent-driven-development skill when delegating implementation. Execute this plan task by task; default to one builder and focused review, not an expensive multi-model swarm.

**Goal:** Turn the current local prototype into a beautiful, reliable, image-first Mac workspace usable from Alastair’s Tailscale-connected computers and phone, with an inexpensive extension path for future validated generators.

**Architecture:** Keep Flask/Jinja and lightweight JavaScript; do not rewrite as a SPA. A production web process and a separate single generation worker share a local SQLite database; immutable run evidence and image files remain on disk. Tailscale Serve proxies only the loopback application; ComfyUI stays private on loopback.

**Tech stack:** Python, Flask, Jinja, Pillow, sqlite3, Waitress, local ComfyUI on Apple MPS, vanilla JavaScript/CSS, pytest, browser tests, macOS launchd, explicit boto3-verified R2 archives.

**Document status:** Build completed and Gold release packaged on 2026-09-22. T01–T24 are implemented and verified; authoritative evidence is in `docs/plans/BUILD-STATE.md` and `docs/releases/gold-release.md`. Explicit residual acceptance gaps are limited to a second-computer walkthrough, one physical post-deployment iPhone **Save Image** report, and the separately approval-gated reboot/FileVault exercise.

---

## 1. Product decisions — do not reopen these during the build

- Personal creative testing, not a product-sales system.
- Alastair has Tailscale on all computers and his phone. **Tailscale-only access; drop the separate authenticated LAN endpoint.** No public exposure, Funnel, port forwarding, additional LAN listener, or mandatory second login system.
- Preserve the existing HTTPS URL: `https://alastairs-mac-mini.tail97e4dc.ts.net/`.
- All generation runs on the Mac. Other devices are browser clients; no replicated model installs or browser-local inference.
- Keep Qwen-Image-2.1 as the only enabled model. Build the adapter interface now; do not install/download/activate another generator.
- Installed-but-unvalidated models are not selectable. Future online providers stay disconnected, require secure local credentials and explicit cost controls, and never run silently.
- Keep one heavyweight generation active at a time; model switching eventually requires explicit unload/health verification.
- Image-first Library landing page; Create, Compare, Queue, Settings, plus contextual Guides.
- Improve the current dark olive/charcoal, warm gold, muted green identity. Avoid a generic admin dashboard or giant marketing headlines.
- Keep image families, transparent lineage, reproducible receipts, safe Finder collections, explicit R2 archival, and best-effort reference-edit wording.
- Do not auto-archive user-generated/reference images. Build/release documents and evidence are separately archived explicitly.
- No model switch of the assistant is part of this plan. Alastair will select the lower-usage builder himself.

## 2. Starting point and evidence

Project root (`ROOT` in this plan):
`/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab`

Repository: `https://github.com/AgenticBotSitter/mac-image-lab`
Baseline main commit: `081de8f0db5939a8339c0552e82fcd1a85b3b82f`
Baseline verification: `.venv/bin/python -m pytest -q` -> **9 passed** on 2026-09-21.
Working tree at plan creation contains untracked `validation/`; preserve it. Do not blanket-add it to Git.

Current code: `app/app.py`, `app/templates/*.html`, `app/static/style.css`, `tests/test_app.py`.
Current listeners: app `127.0.0.1:7864`, ComfyUI `127.0.0.1:8188`.
ComfyUI root: `/Users/alastairfraser/hermes-data/Marvin/Projects/Local Image Generation/Qwen-Image-2.1/ComfyUI`.
User-facing library: `~/Documents/Mac Image Lab/Generated Images/`.
Technical runs: `ROOT/runs/<run-id>/`.
Canonical R2 bucket/key prefix: `hermes-data` / `Marvin/Mac Image Lab/`.

The previous review inspected source/templates/CSS and live health. It did NOT visually inspect rendered pages on actual devices: the browser tool blocked the private address. Capture real screenshots during the build; do not invent visual QA.

### Confirmed defects to cover with regression tests

1. `validate_and_create`: parent width/height/steps override a newly selected larger profile.
2. `execute_run`: 420 polling waits of 3 seconds can expire before the advertised 35-minute maximum generation; timed-out jobs can still run in ComfyUI.
3. In-memory queue and daemon worker do not recover after restart.
4. Transform starts a new family even for a would-be existing source; detail-page Edit action remains disabled.
5. `archive_run` excludes the reference source.
6. Transform lacks equivalent server-side steps/seed/profile validation; unknown profiles silently fall back.
7. Receipt/note writes are direct, non-atomic, and can race with other updates.
8. Gallery loads originals without lazy loading/pagination; counts include runs without images.
9. Generation/archive states are conflated; actual transform output dimensions are not consistently shown.
10. Existing model guidance and legacy reference route contradict enabled editing.
11. Flask development server is used; no matching user LaunchAgent was found during review. Recheck all supervisors before replacing anything.
12. Browser write actions lack CSRF protection; session-key fallback is fixed.
13. Finder reveal executes on host Mac even when requested remotely.
14. Upload processing writes files before all validation completes; avoid orphan writes.
15. Gallery filtering sets `hidden` while tile CSS explicitly sets display; verify computed visibility in a real browser and enforce `[hidden]{display:none!important}` if needed.

## 3. Scope boundaries and approvals

Allowed in the later approved build: staged local code, tests, data migration with backups, controlled local test generations, documentation. Use explicit file lists for commits. Do not assume permission to push private evidence to public GitHub.

Ask before: interrupting active user generation, live service cutover affecting current use, reboot/logout test, new device/ACL policy changes, secret rotation, destructive cleanup, or any spend over $5. No live cron edits. Do not accept secrets in chat/browser configuration forms; local approved secret storage only.

Human checkpoints are limited to: first rendered design direction, disruptive cutover timing, actual-device usability verification, and final acceptance. Do not ask about routine reversible implementation details.

Out of scope: extra models, paid generation, Electron/Swift rewrite, Kubernetes/Redis/Celery, public sharing, SMB shares, multi-user billing, automatic prompt LLM, batch candidate generation, masking/inpainting without validated backend support, unrelated Hermes work.

## 4. Target file map and boundaries

Use a new `imagelab/` package to avoid the existing `import app` ambiguity. Preserve `app/app.py` as a thin compatibility entry point after extraction.

- `imagelab/__init__.py`: app factory; importing it never starts a worker.
- `imagelab/config.py`: validated paths, trusted hosts/origins, secret source, limits.
- `imagelab/db.py`, `imagelab/migrations/001_initial.sql`: database and migrations.
- `imagelab/repository.py`: transactions, jobs, library queries, revision checks.
- `imagelab/validation.py`, `imagelab/storage.py`: validated inputs, safe paths, atomic evidence writes.
- `imagelab/models/contracts.py`, `registry.py`, `qwen21.py`: typed adapter boundary and verified registry.
- `imagelab/services/generation.py`, `recovery.py`, `archive.py`, `library.py`, `media.py`: application services.
- `imagelab/worker.py`: only generation worker; OS lock plus transactional claim.
- `imagelab/web/routes.py`, `security.py`: HTTP surface and request protection.
- `app/templates/base.html`, `library.html`, `create.html`, `compare.html`, `queue.html`, `settings.html`, existing detail/family/style/error templates.
- `app/static/style.css`, `workspace.js`, `viewer.js`, `manifest.webmanifest`, local icon assets.
- `scripts/migrate_legacy.py`, `scripts/verify_install.py`, `scripts/release_check.py`.
- `deploy/launchd/`: reviewed example plists; no credentials or machine-specific secrets.
- `tests/`: unit/integration; `tests/browser/`: UI acceptance.
- `docs/operations.md`, `docs/model-adapters.md`, `docs/plans/BUILD-STATE.md`.

Runtime paths (Git-ignored): `state/library.sqlite3`, `state/worker.lock`, `cache/thumbnails/`, `runs/`, `references/`, `exports/`, `logs/`, `backups/`.

### Data ownership

SQLite is authoritative for job state and mutable library metadata. Files are authoritative for original media and immutable execution artifacts. Final `receipt.json` snapshots serialize completed execution truth; new annotations do not rewrite original generation facts. Read legacy receipts with a compatibility importer; never dual-write competing mutable truth indefinitely.

Suggested tables:
- `schema_migrations(version, applied_at)`.
- `runs(id, family_id, parent_run_id, relationship, model_id, request_json, created_at, completed_at, generation_state, archive_state, output_path, output_sha256, output_width, output_height, title, favorite, trashed_at, revision)`.
- `jobs(id, run_id UNIQUE, state, backend_prompt_id, submission_token UNIQUE, submitted_at, heartbeat_at, error_json)`.
- `job_events(id, job_id, event, payload_json, created_at)`.
- `collections(id, relative_path UNIQUE)`, `run_collections(run_id, collection_id, copy_relative_path)`.
- `model_notes(model_id PRIMARY KEY, note, revision)`; `recipes(id, model_id, capability, name, version, recipe_json)`.
- `family_choices(family_id PRIMARY KEY, preferred_run_id)`; `archive_attempts(id, run_id, state, manifest_path, error_json)`.

Use foreign keys, WAL on local disk only, busy timeout, explicit transaction boundaries, schema versions, and parameterized SQL. Media paths must be resolved beneath approved roots; database values are not automatically trusted paths.

### State machine and crash policy

Job states: `queued -> submitting -> running -> succeeded|failed|cancelled`; exceptional recovery state `needs_attention`. Archive state separately: `local_only|archiving|verified|failed`.

Persist submission intent and a unique client correlation token BEFORE contacting ComfyUI. Save prompt ID immediately. Restart recovery checks both backend queue and history. If a crash occurs between remote acceptance and saving its ID, locate by correlation metadata where supported. If ambiguous, mark `needs_attention` and block further heavyweight submissions until resolved; **never blindly resubmit**. Exactly-once execution cannot be assumed across two systems.

Do not declare a job failed merely because the app lost connectivity or a wall-clock threshold was crossed. Keep tracking/reconciling the backend; expose disconnected or overdue status. Use a configurable deadline informed by the profile, with a conservative default above maximum validated runtime. A deadline requires reconciliation, not automatic duplicate generation.

Queued cancel is safe and transactional. Running cancel must target the exact owned backend job. If ComfyUI only supports global interrupt, allow it only after proving the active queue belongs exclusively to that job; otherwise explain why cancellation is unavailable. Unknown/manual backend work means the Lab waits rather than treating itself as sole owner.

## 5. Model extension contract — implement once, not a plugin marketplace

Define immutable records for ModelSpec, GenerationRequest, BackendJob, BackendStatus, and OutputArtifact. ModelSpec includes id/version, source category, adapter id, installed/validated/available state, capability flags, preset dimensions, parameter bounds, guidance, artifact manifest/hashes, and runtime estimate provenance.

Adapter responsibilities:
`probe()`, `validate(request)`, `build_workflow(request)`, `submit(request, correlation_id)`, `inspect(job)`, `collect(job)`, `cancel(job)` where safe, and `unload()` where supported.

The worker owns queue policy; adapters do not start independent queues. The web layer never constructs Qwen nodes. UI controls and guidance derive from ModelSpec. Capability flags must gate BOTH rendering and server validation.

Minimal protocol shape (illustrative contract, not a pretend functional backend):

```python
from typing import Protocol

class GeneratorAdapter(Protocol):
    def probe(self) -> dict: ...
    def validate(self, request: dict) -> dict: ...
    def build_workflow(self, request: dict) -> dict: ...
    def submit(self, request: dict, correlation_id: str) -> dict: ...
    def inspect(self, job: dict) -> dict: ...
    def collect(self, job: dict) -> list[dict]: ...
    def cancel(self, job: dict) -> dict: ...
    def unload(self) -> dict: ...
```

Use typed dataclasses rather than loose dictionaries in production. Unsupported methods return explicit unsupported results; never fake success. Tests may use a clearly named fake adapter isolated from production registration.

Adding a future model should require one adapter or workflow implementation, one registry entry, capability tests, a real serial local run, visual QA, and an evidence manifest—not changes across page templates. Document this recipe. No second functional adapter required for this release.

## 6. Visual specification and interaction contract

### Shared shell

Desktop: compact persistent navigation, content area, unobtrusive active-job pill. Phone: compact header and five clearly labeled navigation actions; labels remain accessible, not icons alone. No horizontal overflow at 390 CSS pixels. Use consistent page titles, active state, focus rings, error/success messaging, and spacing tokens.

Palette: retain charcoal/olive background, warm off-white foreground, gold primary action, green secondary status; red reserved for errors/destructive actions. Use a restrained serif for short titles and system sans-serif for controls. Verify WCAG AA contrast instead of assuming the palette passes. Respect reduced motion; targets at least 44px where practical.

### Library (`/`, `/gallery` compatibility redirect)

Image grid starts near top, not below a hero/form. Recent default 40 completed, non-trashed images; server-side pagination for all images. Toolbar: search, collection, model, family view, favorite, density, natural/cropped layout. Separate incomplete jobs from image count. Empty and filtered-empty states differ.

Generate small/medium thumbnails with aspect ratios and dimensions. Lazy load below fold; originals load only in viewer/download. Save harmless density/view preferences locally. Avoid storing private full prompts in localStorage by default.

### Create (`/create`, `/transform` preset mode)

Desktop controls left; reference/live-result panel right. Phone preview then collapsible settings. Modes Text / Transform. Prompt, model, quality and aspect presets, collection; advanced controls collapsed. Show expected time with estimate wording and active queue state. Explicit submit creates exactly one result; dedupe repeated click/retry with an idempotency key.

Show upload preview, size, dimensions, remove/replace, drag/drop plus accessible file picker. Default recipe actually populates the instruction; changing a recipe must not silently discard user-edited text. Explain unsupported formats, especially iPhone HEIC; first release must either safely decode via an explicitly tested dependency or clearly guide export to JPEG—no misleading accept-all picker.

Aspect presets: square, portrait, landscape, custom; adapter selects valid dimensions under a pixel/memory budget. Changing quality must not silently change aspect. Advanced overrides are explicit; validation has one implementation across Text and Transform.

### Viewer and detail

Large contained image, fullscreen/zoom/pan, keyboard arrows/Escape, touch controls, metadata drawer. Actions: Transform, Repeat exactly, New variation, Generate larger, Compare, Favorite, Export. Explain that same seed/settings is a repeat request, not a guarantee of bit-identical MPS output. Actual output dimensions always shown.

Technical evidence is collapsed. Use human state labels. “Download to this device” and “Save in Mac library” are distinct. “Open on host Mac” must be explicitly labeled and hidden by default for remote use; do not guess locality solely from loopback proxy addresses.

### Compare and families

Choose two related versions, original/result labels, side-by-side and slider modes, synchronized zoom when geometries permit, visible settings diff, preferred family version. Warn when aspect ratios differ; do not stretch images to pretend alignment. Preserve references as first-class source assets and render them alongside transformed results.

### Queue, Settings, Guides

Queue: job position, backend state, elapsed time, model loading/working/disconnected distinction, queued cancel, safe running cancel, explicit retry as a new attempt linked to original. Poll compact JSON initially; do not force SSE complexity. No four-second full-page refresh.

Settings: model availability/capabilities, per-model notes, host/library/storage status, safe diagnostics, connection status. Secrets remain state-only. Guides: model-specific recipes with vetted existing visual examples, insert into Create, never auto-run. No extra model calls to create guidance.

PWA: manifest/icons/install instructions and responsive shell. Do not introduce offline generation or service-worker caching of private images/API responses. Offline screen should state the Mac is unreachable and preserve only the current in-memory unsent form where possible.

## 7. Ordered implementation tasks

**Ownership:** All numbered tasks are AI builder-owned unless marked Human + AI. Implement sequentially on one branch. A task is a work packet, not a promised duration. Within each packet perform the small steps below separately: write failing assertion; run targeted test; implement only that behavior; rerun; inspect diff; commit. Split further if a packet cannot fit one focused context.

**Common TDD command:** from ROOT run `.venv/bin/python -m pytest tests/<named_file>.py -q`; expected RED before implementation and GREEN after. Record actual results, not a predicted number. For browser behavior use the selected installed local browser runner after discovering it; never invent a nonexistent runner command. Do not generate synthetic evidence disguised as production results.

### M0 — Preserve and establish the baseline

**T01. Backup and inventory.** Files: create `scripts/verify_install.py`, `docs/plans/BUILD-STATE.md`; test `tests/test_install.py`. Capture commit, dirty paths, real receipt counts/hashes, library locations, active queue/backend IDs, runtime processes, and dependencies without secrets. Make local consistent backup of receipts/metadata and current source; do not copy huge model weights. Tests ensure diagnostics redact secrets and do not modify runtime. Gate: baseline tests pass; backup manifest and restore instructions exist; untracked validation untouched.

**T02. Add regression tests for current defects.** Modify `tests/test_app.py`; add `tests/test_regressions.py`. Use tmp roots and mocked backend responses. Tests: larger profile chooses new size; transform invalid values reject before writes; reference archive includes source; status displays output dimensions; no duplicate enqueue. Keep each new failing assertion paired with its fix in T03 onward; record which failures are intentional. Do not commit a final milestone with failing tests.

### M1 — Correct inputs, evidence, and model boundaries

**T03. Normalize generation requests.** Create `imagelab/validation.py`; modify `app/app.py`; test `tests/test_validation.py`. Rules: profile defaults then explicit overrides; parent prompt/settings are copied only by explicit repeat/variation action semantics. Larger keeps aspect and chooses strictly greater validated pixel area unless already maximum (then explain). Validate seed, steps, prompt, model, capability, profile, dimensions AND area before filesystem writes. Tests cover portrait/square/landscape, maximum ceiling, unknown profiles, empty versus explicit zero seed, and inherited profile regression.

**T04. Harden image ingestion.** Create `imagelab/storage.py`; test `tests/test_uploads.py`. Bound compressed bytes and decoded pixel count; turn Pillow bomb warnings into rejected uploads; decode/verify, reopen and fully load; reject unsupported animation. EXIF transpose the inference derivative, preserve original privately with hash, and strip sensitive metadata from normal exports. Record derivative hash and conversion. Stage temporary writes; cleanup on all validation failures. Test forged MIME, corrupt/truncated image, huge dimensions, orientation, unsupported HEIC, path tricks, 413 response and no orphan directories. Reference HTML escaping remains enabled.

**T05. Extract model registry and Qwen adapter.** Create `imagelab/models/{contracts,registry,qwen21}.py`; test `tests/test_adapters.py`. Move exact validated graphs without creative reinterpretation. Contract tests compare graph wiring, model filenames, source-conditioned latent connections, unsupported capability rejection, availability and guidance binding. Update stale pending-edit strings and retire or route `/reference/upload` through the safe source-ingestion service. Gate: real Qwen graph unchanged except required normalized inputs; only Qwen selectable.

**T06. Atomic evidence and consistent archival.** Create `imagelab/services/archive.py`; extend storage; test `tests/test_archive.py`. Snapshot immutable artifacts, include original and inference reference, workflow, model manifest, submission, history, final receipt and lineage. Explicit archive action queues a bounded operation without holding a web request for the entire transfer. Verify every uploaded key via head_object length/hash metadata; final manifest identifies receipt version. Credential failure must mark archive failed, not leave archiving forever. Retry idempotently. Tests inject missing source, upload failure, head mismatch, credentials failure, partial completion; generation success never changes to failed.

### M2 — Durable state and safe execution

**T07. Introduce SQLite and migration.** Create DB/repository/migration files and `scripts/migrate_legacy.py`; test `tests/test_migration.py`. Dry-run first; import legacy receipts without rewriting them. Preserve IDs, hashes, parents, family, library copies, notes, archive facts; quarantine/report malformed rows rather than silently dropping them. Re-running migration is idempotent. Verify count/hash reconciliation; use SQLite backup API for live DB backups. Gate: rollback rehearsed on temporary copy, no lost records.

**T08. Persist jobs and split worker.** Create `imagelab/worker.py`, `services/generation.py`; test `tests/test_queue.py`. Worker claim in transaction, unique run/submission keys, OS single-worker lock, no worker in web import. Two concurrent enqueue requests with same idempotency key yield one job. A second worker refuses leadership. Terminal web response returns job URL immediately. Serialize generation while allowing concurrent reads. Backend occupied by unrelated job -> wait/visible state.

**T09. Reconcile interruptions and long jobs.** Create `services/recovery.py`; test `tests/test_recovery.py`. Persist submitting intent, reconcile queue/history, handle success before app reconnects, preserve active jobs across web restart, restart worker without resubmission, unknown backend history -> needs_attention. Simulate long runtimes with fake clock (no 35-minute sleep). Test backend disconnect/recovery, submission timeout after acceptance, output file lost, stale heartbeat, worker death at every submission boundary. Gate: no automatic duplicate and no next heavyweight job during unresolved active state.

**T10. Queue controls and telemetry.** Create queue APIs in `web/routes.py`, `queue.html`, `workspace.js`; test `tests/test_queue_api.py`. Expose compact job states, progress where backend reports it, estimate provenance, safe cancellation, explicit new-attempt retry. Use backoff polling and visible reconnect state. Reject cancellation of unrelated backend jobs. Friendly errors must retain full safe diagnostics locally, not expose raw secrets/paths to client.

### M3 — Secure, maintainable browser application

**T11. App factory and request protection.** Create factory/config/security/routes files; slim `app/app.py`; test `tests/test_security.py`. CSRF token on all mutations (including upload/archive/reveal), origin checks, trusted host allowlist, session secret from secure local source with fail-closed production startup, HttpOnly/SameSite cookies and Secure in HTTPS mode, security headers/CSP compatible with external local JS. Reject spoofed proxy/identity headers. Trust only the actual local proxy boundary; verify Tailscale identity integration before using headers for authorization. Restrict permitted tailnet identities if verified identity enforcement is used; never infer identity from user-provided headers. No new password UX unless network trust requirements change.

**T12. Shared shell and route compatibility.** Create `base.html`; modify all templates, CSS and route map; test `tests/test_routes.py`. `/` Library, `/create` generation, `/transform` mode, `/compare`, `/queue`, `/settings`, `/styles`; keep old run/family URLs and redirect legacy gallery safely. Move inline JS into local files. Return proper error/empty/loading states. Test escaping, invalid IDs, host/origin rejection, duplicate submit, and back-navigation retaining deliberate form state. No unsafe referrer redirects.

### M4 — Image-first library and detail experience

**T13. Thumbnail pipeline and scalable queries.** Create `services/media.py`, `services/library.py`; test `tests/test_media.py`, `tests/test_library.py`. Derived thumbnails keyed by output hash and size; orientation/aspect preserved, atomic creation, cache invalidation on hash change. Paginated DB query supports filters/sort with bounded input. Correct completed-image/family counts. Thumbnail response has dimensions, cache validators and private cache policy; no originals fetched in grid. Load metadata without scanning every receipt/folder on every request.

**T14. Build the visual shell and Library.** Create `library.html`, design tokens and responsive CSS; add browser assertions in `tests/browser/test_library.py`. Implement natural/cropped modes, density persistence, collection/model/favorite/search/family filters, accessible controls and empty states. Test real computed visibility, no overflow at 390/768/1440px, keyboard focus, image lazy loading, no original PNG downloads in grid. **Human + AI checkpoint:** capture Library and Create desktop/phone screenshots; ask Alastair for one visual-direction review, then proceed with the chosen direction.

**T15. Fullscreen viewer and detail.** Modify `run.html`, add `viewer.js`; test `tests/browser/test_viewer.py`. Zoom/pan, touch, arrows/Escape, focus trap/restoration, metadata drawer, original resolution on demand. Clear actual size/archive labels; repeated actions are safe. Show receipt downloads only when they exist. Test reduced motion, keyboard-only use, long prompts, tall/wide images, failed jobs and disconnected backend.

### M5 — Complete create/transform/compare loop

**T16. Unified Create and visual recipes.** Create `create.html`, adapt guides and controls; test `tests/browser/test_create.py`. Model-driven controls, quality versus aspect, advanced override indicators, upload preview and replacement, initial recipe text, user-edited prompt protection, queue estimate and disabled-in-flight submit. Test upload from phone-sized UI and keyboard, invalid inputs, model guidance switch via test-only registry, no inference until explicit submit. Save versioned named recipes with schema validation and per-model notes revisions; tests `tests/test_recipes.py`.

**T17. Source lineage and explicit iteration modes.** Extend generation/library services and family template; test `tests/test_lineage.py`. Existing image -> Transform child with same family/parent; external upload -> source asset/new family. Store relationship enum `original|reference_transform|variation|repeat|regenerate_larger|resized_export`. Repeating a transform retains source-conditioned workflow instead of accidentally using text-to-image. Families include exact source and preferred version. Tests ensure parent immutability, distinct IDs, preserved provenance and no source/output substitution.

**T18. Compare interface.** Create `compare.html`, extend viewer JS; test `tests/browser/test_compare.py`. Two-version chooser, side-by-side/slider, synchronized zoom when valid, settings diff, preferred-version action. Actual source available for transformed run; different aspect ratios handled without distortion. Invalid/missing/trashed selections get a useful message. No extra generation is triggered by browsing/comparing.

**T19. Collections, favorites, trash and exports.** Extend library/media services, routes/settings; test `tests/test_organization.py`, `tests/test_exports.py`. Safe nested collections, titles, favorites, family manifest in Finder; duplicate-safe copy names. Folder traversal and symlink escapes rejected. Trash is reversible DB visibility, not destructive file deletion; no automatic purge. Exports: PNG original, JPEG with explicit alpha background, WebP, resized copy with recorded dimensions/relationship and stripped GPS metadata. No false new-detail claim. Label local-versus-remote actions clearly. ZIP family/evidence download has safe filenames and bounded size. Concurrent metadata edits use revision checks rather than silent last-writer wins.

### M6 — Mac operations and Tailscale polish

**T20. Production serving and supervised worker/backend.** Add pinned compatible Waitress dependency after inspecting current requirements; create reviewed launchd templates and `docs/operations.md`; test `tests/test_install.py`. Separate web, worker, existing ComfyUI service; absolute venv paths and working directory, loopback binds, single ownership, bounded restart/logging, no debug/reloader. Use approved local credential provisioning; never embed secrets in plists/source. Check existing agents/daemons/process managers to avoid duplicate backend. **Human + AI checkpoint:** request safe cutover window, drain active work, switch, verify listeners, routes, worker and existing Tailscale mapping; keep rollback commands.

**T21. Sleep/reboot semantics and diagnostics.** Extend worker/operations/verify script; test `tests/test_runtime.py`. Prevent idle system sleep only during owned active generation, release assertion on completion/failure; avoid global power changes. State whether chosen LaunchAgents require login after reboot (including FileVault); do not promise pre-login availability. Add cheap liveness versus backend readiness checks, resource/storage status, redacted diagnostics, and log rotation without a new cron. Reboot/logout experiment requires approval; otherwise mark it unverified explicitly.

**T22. Installable device experience.** Add manifest/icons and install guide; test `tests/browser/test_devices.py`. Same HTTPS URL everywhere; no LAN work. No caching of private images by a service worker. Show offline/unreachable state and preserve unsent input safely. **Human + AI verification:** Mac browser, at least one other computer, phone over Wi-Fi and phone off Wi-Fi through Tailscale: browse, submit one shared controlled test as appropriate, observe same queue, download to requesting device, confirm host-only Finder label. Record device/browser and observed outcome; agent cannot claim remote-device tests from a Mac-only request.

### M7 — Real end-to-end release

**T23. End-to-end generation and recovery.** Create `scripts/release_check.py`; expand integration tests. Run one fast real text generation and one controlled reference transform using an approved non-sensitive source, serially, through the new UI. Verify workflow/submission/history/output/receipt/family/download and visually compare source/result. Do not archive personal source images silently; use an explicitly approved validation bundle for R2. Exercise actual larger request with affordable settings or schedule maximum separately; a graph assertion is not a completed maximum run. Restart web while work runs, verify reconnection; controlled worker restart only after safety test/reconciliation logic passes. Record truthful runtime and limitations.

**T24. Restore, archive, and handoff.** Add operations recovery docs and `docs/releases/gold-release.md`. Test migration rollback and restore to isolated directories, verify source/output hashes and family relationships. Run whole test suite, browser checks, security tests, dependency audit and secret scan. Package only explicit source allowlist; omit credentials, weights, venvs, runtime DB, logs, generated/private images. Archive release docs/source/evidence explicitly under canonical R2 prefix with head_object on every object; log verification. Publish source only when authorized and verify remote commit. Update BUILD-STATE with acceptance gaps, next task or done. No “done” if major acceptance criterion remains unverified.

## 8. Test and acceptance matrix

Every milestone must pass its own gate plus prior regression suite. Unit tests may mock systems; release claims require real evidence.

- Correctness: profile inheritance fixed; quality/aspect orthogonal; dimensions/seed/steps validated; transform source retained; exact relationships preserved; actual sizes displayed.
- Durability: queued work persists; web restart harmless; worker recovery reconciles without duplicate; unknown submission blocks safely; DB migration idempotent and reversible.
- Security: malformed host/origin/CSRF rejected; uploads decoded safely; symlink/traversal blocked; cookies secure; secrets absent; ComfyUI private; source images not publicly exposed.
- UI: consistent shell, artwork near top, responsive views, accessible focus/labels/contrast, no horizontal overflow, genuine image comparisons, no dead pending-edit button.
- Performance: measure initial Library transfer/DOM on existing images; ensure grid requests thumbnails only, bounded page size, no full-history scans. Target responsive interaction at representative 40-image page; record actual timings rather than fabricating a universal threshold.
- Storage: mutations concurrent-safe; imports reconcile counts; archive manifest covers source/derivative/output/evidence; failed archive retry works; local generation unaffected by unavailable R2; restore exercised.
- Operations: one worker, one backend owner, supervised restart, documented login/sleep limits, safe cutover/rollback, installed tailnet URL works across real devices.
- Extensibility: test-only second ModelSpec changes guidance/capabilities without template edits; unsupported operation rejected server-side; production still only validated Qwen.

## 9. Migration, rollout and rollback playbook

1. Inventory dirty tree and active backend queue; never overwrite unrelated user work.
2. Branch `gold-workspace` from verified current baseline; document any drift.
3. Back up source/config metadata and legacy receipts; DB backup via API once introduced. Keep model weights in place.
4. Develop/test against temporary state roots and a different loopback port; production data untouched by tests. Backend stub only for unit tests, never production proof.
5. Dry-run migration, compare counts/IDs/hashes, exercise legacy reader and rollback in isolation.
6. Review first screenshots and corrected workflows before large UX polish.
7. Ask for cutover, drain jobs, stop old worker exactly, migrate, start supervised services, validate through existing HTTPS.
8. If rollout fails before new production writes, restore baseline services/state. After new writes, do not blindly restore an old DB: preserve/export new runs and run a compatibility reconciliation first.
9. Never kill all Python processes or globally restart Hermes. Identify exact owned process/launch label.
10. Do not modify Tailscale configuration unless inspection shows it genuinely necessary; report and request approval for ACL or exposure changes.

## 10. Builder efficiency and continuity

Load this document, BUILD-STATE, and only skills/files relevant to the current milestone. Do not reread the entire historical chat. No full-code rewrite in one turn. Prefer focused tests and a full suite at milestone gates. Do not use a multi-agent swarm for routine plumbing. A reviewer may inspect completed milestones without changing shared files.

At each task completion update BUILD-STATE:
- task ID / status / commit;
- exact commands and actual outputs;
- local evidence and verified R2 keys;
- known failures or blocked approval;
- next task and required files;
- active run IDs and runtime state if relevant.

Never mark a task completed solely because its code exists. Source changes, tests, visible UI, and live validation are different gates. Keep builder summaries concise; full details in files.

## 11. Final user acceptance walkthrough

Alastair opens the same tailnet URL on his Mac, another computer, and phone. Library appears promptly with artwork, not a large instruction form. He creates one image, leaves/reopens the page without losing the job, transforms that result directly, compares it to its parent, selects a favorite, puts it in a named collection, and downloads it on the requesting device. The Mac retains readable artwork folders and exact technical evidence. Explicit archival restores the full image family including the source. A service restart does not lose or duplicate work. A future model has a documented adapter onboarding route but is not falsely presented as installed or validated.

**Definition of done:** all applicable acceptance gates above passed with real evidence, remaining user-device or reboot checks explicitly identified rather than hidden, release artifacts local and R2-verified, and a concise operating guide delivered. No new model, paid provider, or separate LAN endpoint added.
