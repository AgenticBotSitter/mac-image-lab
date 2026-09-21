# Mac Image Lab v2 — Image Workspace Release Record

**Date:** 2026-09-21
**Status:** operational local-only image workspace
**Local URL:** `http://127.0.0.1:7864`
**Canonical project prefix:** `hermes-data/Marvin/Mac Image Lab/`

## Delivered

### Model-aware foundation

- A model registry now drives the local generator selector, capability metadata, and selected-model prompt guidance.
- The only selectable generator is the installed and verified `Qwen-Image-2.1` local ComfyUI/Apple-MPS adapter.
- There are no fake local model choices and no online provider connection, key form, or paid API action.
- The selected guide states Qwen prompting structure, strengths, exclusions, and links to official Qwen documentation.

### Image library and provenance

- The app creates and uses `~/Documents/Mac Image Lab/Generated Images/` as the Finder-friendly image library.
- Default folders include `Inbox`, `Favorites`, `Collections`, `Exports/Upscaled`, and `Exports/Print Size`.
- Safe nested subfolders can be created beneath the Generated Images root.
- Every new run receives a model ID, model label/source at display time, title, family ID, optional parent run ID, library folder, and copy record.
- A completed image is copied to the selected Finder folder while the canonical generation evidence stays under the Mac Image Lab run directory.
- Folder traversal outside the library root is rejected.

### Gallery and image families

- Home now shows the latest 40 run records with image, model, dimensions/profile, and prompt excerpt.
- `/gallery` is a separate image-first gallery with large, medium, and compact grid density controls.
- Gallery has client-side prompt/model/folder search, model filter, and one-image-per-family view.
- `/families/<family-id>` presents related images together.
- A run detail page presents the image, complete prompt, model, parameters, Finder folder, downloads, archive action, and related family members.

### Controlled exploration

- `Explore this image` starts a new, explicitly submitted child run in the same family.
- The user may revise the prompt, select an installed model, choose a profile/resolution, request a new seed, and choose the destination folder.
- No alternate model, prompt rewrite, or generation occurs automatically.

## Verification

- Automated suite: **8 passed**.
- Python compilation: passed.
- Health endpoint: passed; loopback-only app and ComfyUI reachable.
- Live routes verified: home, gallery, run explorer.
- Safe folder creation and completed-image filing verified against `Collections/V2 Verification`.
- No online model provider was activated and no paid generation was requested.

## Known boundary

Reference/image-edit execution remains disabled until the official Qwen edit graph completes a real MPS run with visual QA and verified evidence. Online-provider adapters remain future work; they must use secure local credential storage, display provider/model/cost before generation, and obey the spend approval gate.
