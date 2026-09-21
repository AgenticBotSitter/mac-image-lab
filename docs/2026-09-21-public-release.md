# Public Release Record — Mac Image Lab

**Released:** 2026-09-21T05:43:24Z
**Repository:** https://github.com/AgenticBotSitter/mac-image-lab
**Visibility:** public
**Default branch:** `main`
**Initial public commit:** `4fa6a11efb8c30bdf9584a8e69babdcd58791d09`
**Repository license:** MIT

## Release contents

The public repository contains the Mac Image Lab application source, loopback web UI, regression tests, documentation, dependency pins, MIT license, and third-party notices.

It deliberately excludes local virtual environments, logs, generated runs, ComfyUI schema captures, R2 credentials, model weights, source reference assets, and generated images.

## Verification

- Local test suite: `6 passed`.
- `git diff --cached --check`: passed before the initial commit.
- Secret scan: passed for committed source candidates; no credential assignments or GitHub token-like values found.
- GitHub repository readback: public, default branch `main`, MIT license.
- GitHub content readback: `README.md` and `NOTICE` both present at the public remote.
- GitHub remote commit readback matched the initial public commit above.

## Attribution

The repository credits [Spark Image Lab](https://github.com/joeynyc/spark-image-lab) by Joey Rodriguez in both `README.md` and `NOTICE`.

Spark Image Lab is an MIT-licensed local Qwen-Image-2.1 lab targeting NVIDIA DGX Spark. Mac Image Lab is an independent macOS/Apple-MPS implementation and does not bundle Spark Image Lab code, the NVIDIA/CUDA Docker runtime, or Qwen model weights.

## Canonical evidence

This release record is retained locally and uploaded to the Mac Image Lab canonical R2 prefix after write-time `head_object` verification.
