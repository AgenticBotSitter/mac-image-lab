# Mac Image Lab — Reference Transform Release

## What changed

Mac Image Lab now has a dedicated **Transform** workflow at `/transform`.

- Upload one PNG, JPEG, or WebP source image (maximum 20 MiB).
- Select a transformation starter: background/scene, hand-painted storybook animation, country-western, space, or a fully custom instruction.
- Use Qwen-Image-2.1's validated reference-conditioned ComfyUI graph.
- Preserve local technical evidence: uploaded reference copy, source hash, workflow, receipt, submission response, history, and output.
- The result starts a new image family; it is deliberately labeled experimental, with **best-effort** subject/composition preservation rather than a promise of identical likeness.
- The primary app navigation now includes Transform.

## Validation basis

The exact official Qwen-Image-2.1 reference-edit graph was previously run locally on Apple MPS with no node errors and a successful completion. The implementation uses that same node shape:

`LoadImage → TextEncodeQwenImage21(images + VAE) → KSampler(latent output) → VAEDecode → SaveImage`

## Verification

- `python -m py_compile app/app.py` passed.
- `python -m pytest -q` passed: 9 tests.
- Flask test client served `/`, `/transform`, `/gallery`, and `/styles` successfully; a missing transform upload is rejected with HTTP 400.
- Live loopback service returned HTTP 200 for `/transform` and healthy ComfyUI connectivity at `/healthz`.

## Intentional limits

- No transform was generated automatically as part of this release.
- Generated material is not automatically archived. The existing explicit archive action must be used, then its R2 objects are `head_object`-verified.
- The service remains loopback-only. Tailnet HTTPS and a separate authenticated LAN proxy remain the next access phase.

## Changed files

- `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab/app/app.py`
- `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab/app/templates/index.html`
- `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab/app/templates/transform.html`
- `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab/tests/test_app.py`
