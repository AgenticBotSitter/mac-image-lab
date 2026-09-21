# Mac Image Lab v2.1 — Guides and controls

## Scope completed

- Added a separate `/styles` route with Qwen-Image-2.1 prompt recipes for photorealistic nature, editorial product photography, painterly botanicals, hand-painted fantasy animation, portrait editorial work, and RGBA transparent assets.
- Added an expandable per-model **Personal notes** field. Notes are saved locally in `model-notes.json`, keyed by model ID, and are not sent to an inference provider.
- Removed the Health link from normal navigation. `/healthz` remains a machine-readable loopback diagnostics endpoint for the service, not user-facing help.
- Simplified the home generation form: **Quality profile** is the default control and defines canvas dimensions plus steps. Manual width, height, steps, and seed are now collapsed under **Advanced controls** with plain-language explanations.
- Added run-detail actions: **Revise prompt / make variation** and **Generate larger**. The latter opens the existing family explorer with the maximum native profile preselected and blank custom overrides, so the profile takes effect.
- Kept image-to-image edit visibly gated. The disabled button says why: an official Qwen edit graph must first pass local MPS generation, visual QA, and evidence verification. The existing supported revision path is text-to-image exploration within the same family.

## Local generator discovery

A second independent ComfyUI installation exists at:

`/Users/alastairfraser/Documents/comfy/ComfyUI/`

It contains a Qwen Image 2512 INT8 model set, including a matching diffusion model, Qwen3-VL text encoder, and VAE. It also contains a MiniMax video model; that is not an image generator.

The Qwen 2512 installation is **discovered, not validated**. It is deliberately not exposed in the Mac Image Lab model selector yet. It needs a loopback runtime check, an official or compatible graph, a real MPS generation, visual QA, receipt, and R2 evidence before it can be marked available for comparison.

## Verification

- `python -m py_compile app/app.py` passed.
- `pytest -q tests` passed: 8 tests.
- Flask test client confirmed HTTP 200 for `/`, `/styles`, `/gallery`, and the larger-variation explorer; it also verified per-model note save/load behavior.
- Live loopback checks confirmed health status `ok`, ComfyUI reachable, queue depth 0, HTTP 200 on `/styles`, updated run actions, and the home-page personal-notes/style-guide/advanced-controls elements.

## Next gate

Validate the discovered Qwen Image 2512 ComfyUI installation as a second local backend before registering it as selectable. Do not load it concurrently with Qwen-Image-2.1 on the 48 GB unified-memory Mac.
