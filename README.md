# Mac Image Lab

A private, loopback-only image-generation workstation for macOS and Apple Silicon. It provides a small operator UI over a local [ComfyUI](https://github.com/Comfy-Org/ComfyUI) Qwen-Image-2.1 runtime: curated generation profiles, serial jobs, reproducible receipts, run history, downloads, and an explicit R2 archival action with per-object verification.

> **Research/evaluation only.** The Qwen-Image-2.1 model has its own license. Read and comply with the model license before downloading or using weights. No weights, credentials, reference assets, or generated image outputs are included here.

## Credit

Mac Image Lab was inspired by [Spark Image Lab](https://github.com/joeynyc/spark-image-lab) by Joey Rodriguez—an excellent local Qwen-Image-2.1 generation and editing lab for NVIDIA DGX Spark. Spark Image Lab is MIT licensed; see [`NOTICE`](NOTICE) for attribution and license information.

This is an independent, macOS/Apple-MPS implementation. It does **not** reuse Spark’s NVIDIA/CUDA Docker runtime, and it does not claim Spark Image Lab compatibility or endorsement.

## What it does

- Binds only to `127.0.0.1`; no public share mode, tunnel, social publishing, store actions, or payments.
- Calls an existing local ComfyUI endpoint (default: `http://127.0.0.1:8188`).
- Offers Fast (768² / 8 steps), Standard (1024² / 20 steps), and Maximum Native (1696×2528 / 25 steps) profiles, plus validated custom dimensions and seed.
- Uses a model registry: the selector currently exposes the verified local Qwen-Image-2.1 adapter and its model-specific prompting guidance; future adapters must pass their own validation before they become selectable.
- Uses one worker queue to protect unified memory on Apple Silicon.
- Creates image families for controlled variations and prompt revisions, preserving the parent/source run and selected model.
- Provides an image-first full gallery with responsive density controls, search, model filtering, and family grouping.
- Files completed images beneath `~/Documents/Mac Image Lab/Generated Images/` using safe nested subfolders, while retaining canonical technical evidence separately.
- Records prompt, exact API workflow, model filenames, parameters, prompt ID, timings, output hash, dimensions, ComfyUI history, and status for every run.
- Provides history plus output, receipt, workflow, and ComfyUI-history downloads.
- Archives a completed run only when explicitly requested, and marks it complete only after every R2 object passes `head_object` verification.
- Stages local reference uploads for future use. Reference/edit generation remains disabled until a Qwen edit graph has passed an actual macOS/MPS validation run.

## Requirements

- macOS on Apple Silicon.
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/).
- A working local ComfyUI/Qwen-Image-2.1 installation at `127.0.0.1:8188`.
- For the optional archive action: R2/S3 credentials supplied through your normal local environment. Do not commit them.

## Quick start

```bash
git clone https://github.com/AgenticBotSitter/mac-image-lab.git
cd mac-image-lab
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python app/app.py
```

Open `http://127.0.0.1:7864` on the same Mac.

Before starting the UI, start ComfyUI separately and keep it loopback-bound:

```bash
cd /path/to/ComfyUI
.venv/bin/python main.py --listen 127.0.0.1 --port 8188
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAC_IMAGE_LAB_COMFY_URL` | `http://127.0.0.1:8188` | Local ComfyUI API base URL. |
| `MAC_IMAGE_LAB_PORT` | `7864` | Local UI port. The host is intentionally fixed to `127.0.0.1`. |

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

The test suite covers the proven text-to-image workflow, dimensions, loopback restriction, path validation, explicit reference/edit gate, and archival refusal for incomplete runs.

## Data and privacy

Generated files, receipts, history, local logs, virtual environments, local ComfyUI schema dumps, and environment files are intentionally excluded from Git. The app is a trusted single-owner local tool, not a multi-user or authenticated service.

## Scope and current gate

Text-to-image, receipts, local history, downloads, and verified explicit R2 archiving are implemented. Reference/image editing is visible as a planned capability but is not enabled until an official Qwen editing workflow has been successfully tested on Apple MPS with visual QA and evidence verification.

## License

Mac Image Lab application code is released under the [MIT License](LICENSE). This does not grant rights to Qwen weights or any other third-party models.
