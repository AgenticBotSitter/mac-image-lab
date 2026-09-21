# Mac Image Lab

- **WHAT:** A private, local-only web control plane for Qwen-Image-2.1 and future local image workflows on the M4 Pro Mac mini.
- **WHY:** Make repeatable local image testing, reference-guided iteration, run history, and R2-backed evidence accessible without exposing ComfyUI’s node graph.
- **OWNER:** Marvin (Mac mini).
- **R2 HOME:** `hermes-data/Marvin/Mac Image Lab/`
- **LOCAL MIRROR:** `~/hermes-data/Marvin/Mac Image Lab/`
- **BUCKET:** `hermes-data`
- **STARTED:** 2026-09-20
- **STATUS:** public code release; text-to-image and verified archive flow operational; reference/edit execution gated pending a separately validated MPS graph.
- **STORES AFFECTED:** none — research/evaluation only.

## Documentation points

- `docs/2026-09-20-kickoff.md`
- `docs/2026-09-20-build-plan.md`
- `docs/YYYY-MM-DD-progress-<milestone>.md`
- `docs/YYYY-MM-DD-wrap-up.md`

## Decisions

- The requested R2 location is used literally: `Marvin/Mac Image Lab/`.
- The lab will call the already-proven loopback ComfyUI API at `127.0.0.1:8188`; it will not port or run the NVIDIA/CUDA-only Spark Image Lab repository.
- The lab itself binds only to loopback and has no public share mode, authentication bypass, social posting, store publishing, or payment controls.
- Every retained generation must have a local output, deterministic generation receipt, R2 upload, and exact-key `head_object` verification.
- Current Qwen-Image-2.1 use is research/evaluation only. No commercial listing or sale workflow is in scope.

## Anti-patterns to avoid

- Do not run two model-serving processes for the same Qwen weights.
- Do not expose the lab or ComfyUI to LAN/public interfaces.
- Do not treat local output as complete before R2 verification.
- Do not add social, Etsy, Printify, purchase, or publish actions to the lab.
- Do not preserve credentials, raw secrets, or reference assets outside their approved local/R2 storage paths.
