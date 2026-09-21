"""Validated Qwen-Image-2.1 ComfyUI adapter."""

from __future__ import annotations

from typing import Any, Mapping

from imagelab.models.contracts import (
    BackendJob,
    BackendStatus,
    ModelSpec,
    OutputArtifact,
    UnsupportedOperation,
)
from imagelab.validation import GenerationRequest

PROFILES = {
    "fast": {"label": "Fast preview", "width": 768, "height": 768, "steps": 8, "resolution": 768, "expected": "about 2 minutes after warm-up"},
    "standard": {"label": "Standard", "width": 1024, "height": 1024, "steps": 20, "resolution": 1024, "expected": "about 6 minutes after warm-up"},
    "maximum": {"label": "Maximum native 2K", "width": 1696, "height": 2528, "steps": 25, "resolution": 2048, "expected": "about 35 minutes on MPS; submit intentionally"},
}

QWEN_SPEC = ModelSpec(
    id="qwen-image-2.1-local",
    label="Qwen-Image-2.1",
    version="2.1-int8-convrot",
    source="Local",
    adapter_id="qwen-image-2.1-comfy",
    installed=True,
    validated=True,
    available=True,
    capabilities=frozenset({"text_to_image", "reference_transform", "rgba"}),
    profiles=PROFILES,
    guidance={
        "summary": "Describe the finished frame: medium, subject, placement, background, materials, lighting, palette, and composition.",
        "strengths": ("Detailed materials, lighting, composition, and refined texture", "Literal visible text when quoted exactly", "Native transparent RGBA output"),
        "avoid": ("Vague keyword piles such as ‘masterpiece, 8K’", "Conflicting styles or lighting", "Dense tiny text without exact quoted wording"),
        "template": "A [orientation] [medium/style] of [subject], [placement/framing], against [specific background]. [Materials and details]. [Light]. The composition is [mood/palette/layout].",
        "docs": "https://github.com/QwenLM/Qwen-Image-2.1",
    },
    warnings=("Reference transformations preserve identity, objects, and composition on a best effort basis.",),
    artifacts={
        "unet": "qwen_image_2.1_int8_convrot.safetensors",
        "text_encoder": "qwen3vl_8b_int8_convrot.safetensors",
        "vae": "qwen_image_2.1_vae_bf16.safetensors",
    },
    runtime_estimate_provenance="Measured on this Apple M4 Pro Mac mini; estimates vary by warm state and image size.",
)


class Qwen21Adapter:
    spec = QWEN_SPEC

    def probe(self) -> Mapping[str, Any]:
        return {"configured": True, "installed": self.spec.installed, "validated": self.spec.validated}

    def validate(self, request: GenerationRequest) -> GenerationRequest:
        if request.model_id != self.spec.id:
            raise ValueError("Request model does not match the Qwen adapter")
        capability = "reference_transform" if request.action == "reference_transform" else "text_to_image"
        if capability not in self.spec.capabilities:
            raise ValueError(f"Qwen adapter does not support {capability}")
        return request

    def build_workflow(
        self,
        request: GenerationRequest,
        *,
        prefix: str,
        input_name: str | None = None,
    ) -> dict[str, Any]:
        self.validate(request)
        if request.action == "reference_transform":
            if not input_name:
                raise ValueError("Reference transform requires a source image name")
            return self._reference_workflow(request, prefix, input_name)
        if input_name is not None:
            raise ValueError("Text-to-image workflow does not accept a source image")
        return self._text_workflow(request, prefix)

    def _loaders(self) -> dict[str, Any]:
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": self.spec.artifacts["unet"], "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": self.spec.artifacts["text_encoder"], "type": "qwen_image", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": self.spec.artifacts["vae"]}},
        }

    def _text_workflow(self, request: GenerationRequest, prefix: str) -> dict[str, Any]:
        return {
            **self._loaders(),
            "4": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "prompt": request.prompt, "negative_prompt": "", "resolution": request.resolution}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": request.width, "height": request.height, "batch_size": 1}},
            "6": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["4", 1], "latent_image": ["5", 0], "seed": request.seed, "steps": request.steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
            "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
            "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
        }

    def _reference_workflow(self, request: GenerationRequest, prefix: str, input_name: str) -> dict[str, Any]:
        return {
            **self._loaders(),
            "4": {"class_type": "LoadImage", "inputs": {"image": input_name}},
            "5": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "prompt": request.prompt, "negative_prompt": "", "resolution": request.resolution, "images": {"image_1": ["4", 0]}, "vae": ["3", 0]}},
            "6": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["5", 1], "latent_image": ["5", 2], "seed": request.seed, "steps": request.steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
            "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
            "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
        }

    def submit(self, request: GenerationRequest, correlation_id: str) -> BackendJob | UnsupportedOperation:
        return UnsupportedOperation("submit", "Backend transport moves to the durable worker in T08")

    def inspect(self, job: BackendJob) -> BackendStatus | UnsupportedOperation:
        return UnsupportedOperation("inspect", "Backend transport moves to the durable worker in T08")

    def collect(self, job: BackendJob) -> tuple[OutputArtifact, ...] | UnsupportedOperation:
        return UnsupportedOperation("collect", "Backend transport moves to the durable worker in T08")

    def cancel(self, job: Mapping[str, Any] | BackendJob) -> Mapping[str, Any] | UnsupportedOperation:
        return UnsupportedOperation("cancel", "ComfyUI global interrupt is unsafe without exclusive ownership proof")

    def unload(self) -> Mapping[str, Any] | UnsupportedOperation:
        return UnsupportedOperation("unload", "No validated per-model unload operation is configured")
