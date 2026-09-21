# Mac Image Lab model adapters

Mac Image Lab exposes only installed generators that have passed a real local run, visual QA, and evidence checks. The registry is an availability boundary, not a list of every model found on disk.

## Current production model

- ID: `qwen-image-2.1-local`
- Adapter: `qwen-image-2.1-comfy`
- Capabilities: text-to-image, experimental reference transform, RGBA output
- Backend: loopback-only ComfyUI on the Mac
- Runtime policy: one heavyweight generation at a time

The exact validated Qwen text and reference graphs live in `imagelab/models/qwen21.py`. Web routes do not construct model-specific ComfyUI nodes.

## Contract

`imagelab/models/contracts.py` defines immutable records for model specifications, generation requests, backend jobs/status, output artifacts, and unsupported operations. A generator adapter owns:

- capability validation;
- workflow construction;
- backend probe/submission/status/collection integration;
- cancellation only when ownership makes it safe;
- unload behavior where the backend supports it.

Queue policy belongs to the worker, not the adapter. Secrets and paid-provider credentials never belong in a model specification, browser form, receipt, or public source.

## Adding a future local model

1. Inventory the exact weights, license, backend requirements, memory demand, and native dimension constraints.
2. Build one adapter under `imagelab/models/` without changing page templates.
3. Define one `ModelSpec` with a stable ID, provenance, capabilities, profiles, guidance, warnings, artifact identities, and runtime-estimate provenance.
4. Keep `installed=False`, `validated=False`, and `available=False` until validation is complete.
5. Add contract tests for capability rejection and exact workflow wiring.
6. Run the model serially on the Mac after unloading/stopping any conflicting heavyweight backend.
7. Verify a real output file and dimensions, visually inspect it, and preserve workflow/history/receipt/model evidence.
8. For reference editing, run a controlled source-versus-result preservation test. Describe identity/composition retention as best effort.
9. Register the adapter only after evidence passes. The registry will then supply model guidance and controls to the UI.
10. Update operations documentation and release evidence. Do not infer API entitlement from a consumer subscription.

## Online providers

An online adapter is a separate source category. It must report connection state without exposing credentials, validate cost/size before submission, maintain session spend controls, and require approval for any operation that could exceed $5. No online provider is connected in the Gold build.

## Deliberately unsupported operations

Adapters return an explicit `UnsupportedOperation` for actions that are not safely implemented. Qwen cancellation currently remains unsupported because ComfyUI interrupt may be global; it must not interrupt unrelated/manual backend work. Runtime submission/status ownership moves into the durable worker in T08.
