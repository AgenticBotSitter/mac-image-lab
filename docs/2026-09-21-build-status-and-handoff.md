# Mac Image Lab — Build Status and Handoff

**Date:** 2026-09-21
**Status:** operational text-to-image release; reference/edit execution remains intentionally disabled pending its separate validated graph test.
**Local URL:** `http://127.0.0.1:7864`
**Local root:** `~/hermes-data/Marvin/Mac Image Lab/`
**R2 project root:** `hermes-data/Marvin/Mac Image Lab/`

## What is built

Mac Image Lab is a private, local web control plane for the existing Qwen-Image-2.1 ComfyUI/MPS runtime on the M4 Pro Mac mini.

- Flask web UI, bound exclusively to `127.0.0.1:7864`.
- No public share feature, LAN binding, public tunnel, social publishing, store operation, payment, cron, or model-download control.
- ComfyUI remains local at `127.0.0.1:8188`.
- Three explicit profiles:
  - Fast preview: 768×768, 8 Euler/simple steps.
  - Standard: 1024×1024, 20 Euler/simple steps.
  - Maximum native: 1696×2528, 25 Euler/simple steps, with an explicit MPS-duration warning.
- Custom dimensions restricted to 512–2752px, multiples of 32; steps restricted to 1–80; seed validated.
- Single worker queue—only one generation is active at a time.
- Per-run local receipt with the prompt, exact ComfyUI API workflow, model filenames, parameters, prompt ID, timing, copied output hash, output dimensions, and status.
- Run history and downloadable output, receipt, workflow, and ComfyUI history.
- Explicit R2 archive action. It uploads and exact-key verifies retained output, workflow, receipt, ComfyUI history, submit receipt, and archive report using `head_object`.
- Reference image upload staging is available for PNG/JPEG/WebP under 20 MiB, hash-addressed and local-only. It is deliberately not connected to inference until the edit graph is locally tested.

## Verified release evidence

### Application health

The local health endpoint returned:

```json
{
  "comfyui_reachable": true,
  "host": "127.0.0.1",
  "loopback_only": true,
  "port": 7864,
  "queue_depth": 0,
  "share_enabled": false,
  "status": "ok"
}
```

The UI shell loaded successfully and the service reported `Running on http://127.0.0.1:7864`.

### Automated tests

`pytest` result: **6 passed**.

Coverage includes proven-Qwen workflow construction, profile bounds, loopback enforcement, path-traversal rejection, disabled-until-proven reference editing, and archive rejection for an incomplete run.

### Website-originated end-to-end test

- Run ID: `9d7cc74b-27d4-41fa-9d6d-d855bb59176d`
- ComfyUI prompt ID: `51fe3e9f-b49e-48ac-b7d6-0c5fc24373d5`
- Profile: Fast preview
- Parameters: 768×768, 8 steps, Euler/simple, CFG 1.0
- Runtime: 117.866 seconds
- Output: RGBA PNG, 925,601 bytes
- Output SHA-256: `4b25fa8d75c5709d6b9926a24ea43f01687b8f4b55ae926fdb8a95ffaa931832`
- Visual QA: pass. The test output showed the requested single ivory peony, clear glass vase, warm ochre background, and painterly texture. No text, logo, or watermark was visible.

R2 objects from that exact website-generated run were uploaded and verified:

```text
hermes-data/Marvin/Mac Image Lab/runs/9d7cc74b-27d4-41fa-9d6d-d855bb59176d/output.png
hermes-data/Marvin/Mac Image Lab/runs/9d7cc74b-27d4-41fa-9d6d-d855bb59176d/workflow.json
hermes-data/Marvin/Mac Image Lab/runs/9d7cc74b-27d4-41fa-9d6d-d855bb59176d/receipt.json
hermes-data/Marvin/Mac Image Lab/runs/9d7cc74b-27d4-41fa-9d6d-d855bb59176d/comfy-history.json
hermes-data/Marvin/Mac Image Lab/runs/9d7cc74b-27d4-41fa-9d6d-d855bb59176d/comfy-submit.json
hermes-data/Marvin/Mac Image Lab/runs/9d7cc74b-27d4-41fa-9d6d-d855bb59176d/archive.json
```

## Reference/edit status

The current ComfyUI installation exposes the relevant Qwen conditioning/edit node family, including `TextEncodeQwenImage21`, `TextEncodeQwenImageEdit`, `TextEncodeQwenImageEditPlus`, `LoadImage`, and `VAEEncode`.

However, the exact API graph and model requirements for a reference-guided Qwen edit have not yet been exercised in this runtime. The application correctly leaves reference execution disabled rather than claiming a capability that has not passed a local generation, visual QA, receipt, R2 archive, and `head_object` verification.

## Start and stop

Start the lab:

```bash
cd "$HOME/hermes-data/Marvin/Mac Image Lab"
./.venv/bin/python app/app.py
```

Open locally:

```text
http://127.0.0.1:7864
```

Prerequisite: ComfyUI must already be running at `127.0.0.1:8188`.

## Project files

- `app/app.py` — application, queue, workflow builder, archive verifier.
- `app/templates/` and `app/static/` — loopback web UI.
- `tests/test_app.py` — regression tests.
- `requirements.txt` — pinned runtime/test dependencies.
- `runs/<run-id>/` — complete per-run local evidence packages.
- `docs/2026-09-20-build-plan.md` — original staged build specification.

## Honest completion state

Text-to-image, history, receipts, UI downloads, loopback enforcement, and verified R2 archival are built and proven end-to-end.

The remaining explicit technical gate is a verified local Qwen reference/edit graph. It should be enabled only after one actual edit run succeeds, passes visual QA, and has its full artifact package R2-verified.
