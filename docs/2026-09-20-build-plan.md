# Mac Image Lab — Build Plan

**Date:** 2026-09-20
**Status:** approved for planning; no service or cron changes applied
**Owner:** Marvin / M4 Pro Mac mini
**R2 home:** `hermes-data/Marvin/Mac Image Lab/`

## 1. Objective

Build a private local web application that makes the existing Qwen-Image-2.1 ComfyUI/MPS installation usable as a reproducible image lab: one clear generation form, persistent local history, exact run records, image reuse/reference workflows, and explicit R2 archival.

This is a research/evaluation tool. It will not publish to stores or social accounts, place orders, spend money, or expose a public URL.

## 2. Proven starting point

The inference backend already exists and has passed a local test:

- Host: Apple M4 Pro Mac mini with 48GB unified memory.
- Backend: official ComfyUI with the official Qwen-Image-2.1 INT8 ConvRot model set.
- Backend address: `http://127.0.0.1:8188` only.
- Proven nodes: `UNETLoader`, `CLIPLoader`, `VAELoader`, `TextEncodeQwenImage21`, `KSampler`, `VAEDecode`, `SaveImage`.
- Proven smoke run: 768×768, 8 Euler steps.
- Proven high-quality run: 1024×1024, 20 Euler steps.

Spark Image Lab is a useful UX reference, but its code cannot be run here: it requires CUDA and NVIDIA GB10/DGX Spark Docker infrastructure. Mac Image Lab will use the same product pattern while treating ComfyUI as the local generation service.

## 3. Scope

### Included in v1

- Loopback-only web UI at a new local port, separate from ComfyUI.
- Text-to-image form: prompt, aspect-ratio preset, custom dimensions, steps, seed, sampler, and safe profile.
- Three run profiles:
  - **Fast preview:** 768px, 8 steps, Euler.
  - **Standard:** 1024px, 20 steps, Euler.
  - **Maximum native:** Qwen’s 2K native target, used only after an explicit size/time warning.
- Strict request validation before the job reaches ComfyUI.
- A single in-process job queue; one active generation at a time.
- Live status polling from ComfyUI and an honest elapsed-time display.
- Local run ledger and gallery with newest-first history.
- A complete receipt for every successful run: prompt, workflow, input parameters, ComfyUI prompt ID/history, output hash, dimensions, runtime, local paths, model identifiers, and archive state.
- “Reuse result as reference” preparation. Actual reference/image-edit execution becomes available only after a tested Qwen edit workflow is added.
- Explicit **Archive to R2** action for a completed run, plus an optional archive-at-completion setting that is off until tested.
- R2 verification using `head_object` for every artifact before showing `Archived`.
- Download of the output PNG and a JSON receipt.

### Explicitly excluded from v1

- Public web hosting, LAN binding, Gradio public share, multi-user accounts, and remote unauthenticated access.
- Automatic social publishing, Etsy listing creation, Printify activity, advertising, checkout, or payment actions.
- Model download/upgrade controls in the UI.
- A generic ComfyUI node-graph editor.
- Untested image-edit/reference workflows.
- Automated upscaling claims. The receipt will distinguish native generated pixels from any interpolated delivery export.

## 4. Architecture

```text
Browser on Mac
  └─ Mac Image Lab UI — 127.0.0.1:<new-port>
       ├─ local run ledger / thumbnails / receipt JSON
       ├─ loopback API client
       └─ explicit R2 archiver
            └─ hermes-data/Marvin/Mac Image Lab/runs/<run-id>/

ComfyUI — 127.0.0.1:8188
  └─ Qwen-Image-2.1 model runtime and output directory
```

### Component choices

- **Python 3.12 virtual environment:** isolated from ComfyUI and from ambient macOS Python.
- **Gradio:** simple single-owner internal UI; no sharing feature enabled.
- **ComfyUI HTTP API:** `/prompt`, `/history/{prompt_id}`, and image retrieval through the local ComfyUI output path.
- **JSON files:** append-only per-run receipts; no database required for v1.
- **Pillow:** thumbnails, output inspection, dimensions, alpha data, and SHA-256 inputs.
- **boto3/R2 helper:** archival only; credentials loaded from approved local environment files and never written into UI state, receipts, source code, or logs.

## 5. Local and R2 layout

```text
~/hermes-data/Marvin/Mac Image Lab/
  PROJECT.md
  docs/
  app/
  workflows/
  runs/
    <run-id>/
      output.png
      receipt.json
      workflow.json
      comfy-history.json
      archive.json
  logs/
  tests/

hermes-data/Marvin/Mac Image Lab/
  PROJECT.md
  docs/
  runs/<run-id>/
    output.png
    receipt.json
    workflow.json
    comfy-history.json
    archive.json
  releases/
```

`archive.json` records the exact R2 keys, byte sizes, SHA-256 values, and `head_object` verification time. An archive cannot be marked complete without every required file passing verification.

## 6. Milestones and acceptance criteria

### M0 — Project declaration and plan

- Create `PROJECT.md` and this plan locally.
- Mirror both to the R2 project home and verify with `head_object`.
- Record the upstream Spark Image Lab commit used only as a UX reference.

**Done when:** project and plan exist locally and R2 verification succeeds.

### M1 — Minimal local shell

- Create an isolated Python 3.12 environment and pinned requirements.
- Implement application configuration: loopback host, unique port, approved ComfyUI endpoint, local data root.
- Add a start command, health endpoint, and graceful shutdown.
- Bind `127.0.0.1` only; disable Gradio sharing and telemetry.

**Done when:** local browser can load the shell; the health check proves it cannot bind to a non-loopback interface.

### M2 — Safe text-to-image execution

- Implement profile-to-workflow mapping for Fast preview and Standard.
- Generate a ComfyUI API graph from explicit form inputs.
- Submit to `/prompt`, poll history, capture the resulting image, and write a run receipt.
- Enforce one active job and show queue state.
- Return errors without fabricated completion states.

**Done when:** a 768px Fast preview is generated through the website; its receipt contains the exact ComfyUI prompt ID and copied output hash.

### M3 — History and reproducibility

- Build newest-first gallery and run list.
- Restore prompt and settings from a selected receipt without submitting a job.
- Offer PNG and receipt downloads.
- Add local validation for prompt presence, dimensions, steps, seed range, and output containment.

**Done when:** an existing run can be opened, its settings restored, and a fixed-seed rerun submitted intentionally.

### M4 — R2 archival and verification

- Add per-run archive action.
- Upload only final retained artifacts: output, workflow, receipt, ComfyUI history, and archive report.
- Hash before upload; run `head_object` on every exact key after upload.
- Expose `Local only`, `Archiving`, `Archived`, or `Archive failed` state in the UI.

**Done when:** one successful website-originated run is present in the R2 run folder with every exact key verified.

### M5 — Controlled reference/edit workflow

- Research and test an official Qwen-Image-2.1 edit/reference ComfyUI workflow on this MPS installation.
- Add reference upload containment, format/size checks, local hash-based storage, and receipt references.
- Do not expose the UI control until one local edit test and R2 evidence package pass.

**Done when:** one reference-guided test completes with a reproducible run receipt and visual QA.

### M6 — Hardening and handoff

- Add regression tests for workflow generation, input validation, receipt schema, archive-state transitions, and R2 verification failures.
- Add launch/troubleshooting documentation and a small operator guide.
- Create a release manifest with source hashes and test evidence.

**Done when:** clean-start test, one full generation, one archive verification, and test suite all pass.

## 7. Security and operational controls

- Service and ComfyUI remain loopback-only.
- No `share=True`, public tunnel, or automatic remote access.
- The app accepts no passwords, payment data, API tokens, or social account credentials.
- R2 credentials are server-side only; browser state never receives them.
- Reference uploads remain local/private and are never automatically published.
- A local output is not called complete until its archive status and `head_object` data are recorded when archival is requested.
- No cron is created or changed as part of this plan.

## 8. Testing strategy

1. Unit-test workflow generation for all profiles.
2. Unit-test path traversal and invalid-parameter rejection.
3. Smoke-test local HTTP shell on loopback.
4. Generate one Fast preview end-to-end.
5. Inspect dimensions, format, SHA-256, and receipt linkage.
6. Archive artifacts to R2 and verify every object with `head_object`.
7. Intentionally simulate an archive failure and confirm it cannot appear as `Archived`.
8. Visual-review output for prompt fit, unwanted text/watermarks, and anatomy/object defects where applicable.

## 9. Known risks and mitigations

- **2K Qwen runs are slow on MPS.** Keep the maximum-native profile explicit and show expected elapsed time; the Fast and Standard profiles remain default.
- **ComfyUI workflow compatibility can change.** Pin proven model filenames and nodes; test any ComfyUI upgrade separately.
- **Reference-edit graphs are not yet proven on this Mac.** Keep them out of v1 execution until a tested workflow exists.
- **R2 success responses are insufficient proof.** Require exact-object `head_object` verification.
- **Large local image files accumulate.** Use clear run folders and document retention before any automatic cleanup policy.

## 10. Next action

Begin M1 only after this plan’s local/R2 declaration is verified. The first implementation deliverable will be a loopback-only shell plus health check; no external service, public URL, or scheduled job is needed.
