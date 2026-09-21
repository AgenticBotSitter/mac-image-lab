"""Verified model registry; unvalidated installations never become selectable."""

from __future__ import annotations

from types import MappingProxyType

from imagelab.models.contracts import GeneratorAdapter, ModelSpec
from imagelab.models.qwen21 import QWEN_SPEC, Qwen21Adapter


class ModelRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ModelSpec] = {}
        self._adapters: dict[str, GeneratorAdapter] = {}

    def register(self, spec: ModelSpec, adapter: GeneratorAdapter) -> None:
        if spec.id in self._specs:
            raise ValueError(f"Model is already registered: {spec.id}")
        if adapter.spec.id != spec.id:
            raise ValueError("Adapter and model specification IDs do not match")
        self._specs[spec.id] = spec
        self._adapters[spec.id] = adapter

    def get(self, model_id: str, *, require_available: bool = True) -> ModelSpec:
        spec = self._specs.get(model_id)
        if spec is None or (require_available and not (spec.installed and spec.validated and spec.available)):
            raise ValueError("Selected image model is not available locally")
        return spec

    def adapter(self, model_id: str) -> GeneratorAdapter:
        self.get(model_id)
        return self._adapters[model_id]

    def available(self) -> list[ModelSpec]:
        return [spec for spec in self._specs.values() if spec.installed and spec.validated and spec.available]

    def specs(self) -> MappingProxyType[str, ModelSpec]:
        return MappingProxyType(self._specs)

    def legacy_view(self) -> dict[str, dict]:
        return {
            spec.id: {
                "label": spec.label,
                "source": spec.source,
                "runtime": "ComfyUI · Apple MPS",
                "status": "available" if spec in self.available() else "unavailable",
                "capabilities": [
                    "Text to image" if capability == "text_to_image" else
                    "Reference transform (experimental)" if capability == "reference_transform" else
                    "RGBA transparency" if capability == "rgba" else capability
                    for capability in sorted(spec.capabilities)
                ],
                "guide": dict(spec.guidance),
                "warnings": list(spec.warnings),
                "version": spec.version,
                "adapter_id": spec.adapter_id,
            }
            for spec in self._specs.values()
        }


registry = ModelRegistry()
registry.register(QWEN_SPEC, Qwen21Adapter())
