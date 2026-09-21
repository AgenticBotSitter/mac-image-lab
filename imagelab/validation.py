"""Pure validation and normalization for image generation requests."""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from typing import Any, Mapping

MIN_DIMENSION = 512
MAX_DIMENSION = 2752
DIMENSION_STEP = 32
MAX_STEPS = 80
MAX_SEED = 2**63 - 1
# Qwen's validated maximum-native profile is the current memory budget ceiling.
MAX_PIXEL_AREA = 1696 * 2528
ACTIONS = {"original", "variation", "repeat", "regenerate_larger", "reference_transform"}
PARENT_INHERITING_ACTIONS = {"variation", "repeat", "regenerate_larger"}


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    model_id: str
    profile: str
    width: int
    height: int
    steps: int
    seed: int
    resolution: int
    action: str


def _present(form: Mapping[str, Any], key: str) -> bool:
    value = form.get(key)
    return value is not None and str(value).strip() != ""


def _integer(value: Any, label: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc


def _larger_dimensions(width: int, height: int, target_area: int) -> tuple[int, int]:
    current_area = width * height
    if current_area >= target_area:
        raise ValueError("Image is already at the maximum selected profile size")
    scale = math.sqrt(target_area / current_area)
    candidate_width = min(MAX_DIMENSION, int(width * scale) // DIMENSION_STEP * DIMENSION_STEP)
    candidate_height = min(MAX_DIMENSION, int(height * scale) // DIMENSION_STEP * DIMENSION_STEP)
    while candidate_width * candidate_height > target_area:
        if candidate_width / width >= candidate_height / height:
            candidate_width -= DIMENSION_STEP
        else:
            candidate_height -= DIMENSION_STEP
    if candidate_width * candidate_height <= current_area:
        raise ValueError("No larger validated size is available for this aspect ratio")
    return candidate_width, candidate_height


def normalize_generation_request(
    form: Mapping[str, Any],
    *,
    profiles: Mapping[str, Mapping[str, Any]],
    available_models: set[str],
    parent: Mapping[str, Any] | None = None,
) -> GenerationRequest:
    action = str(form.get("action") or ("variation" if parent else "original")).strip()
    if action not in ACTIONS:
        raise ValueError("Unknown generation action")

    raw_prompt = str(form.get("prompt") or "").strip()
    if not raw_prompt and parent and action in PARENT_INHERITING_ACTIONS:
        raw_prompt = str(parent.get("prompt") or "").strip()
    if not raw_prompt or len(raw_prompt) > 4000:
        raise ValueError("Prompt must be 1–4000 characters")

    model_id = str(form.get("model_id") or (parent.get("model_id") if parent else "qwen-image-2.1-local"))
    if model_id not in available_models:
        raise ValueError("Selected image model is not available locally")

    explicit_profile = _present(form, "profile")
    profile = str(form.get("profile") if explicit_profile else (parent.get("profile") if parent and action in PARENT_INHERITING_ACTIONS else "fast"))
    if profile not in profiles:
        raise ValueError("Unknown profile")
    selected = profiles[profile]

    parent_parameters = parent.get("parameters", {}) if parent and action in PARENT_INHERITING_ACTIONS else {}
    if explicit_profile:
        base_width = _integer(selected["width"], "Width")
        base_height = _integer(selected["height"], "Height")
        base_steps = _integer(selected["steps"], "Steps")
    else:
        base_width = _integer(parent_parameters.get("width", selected["width"]), "Width")
        base_height = _integer(parent_parameters.get("height", selected["height"]), "Height")
        base_steps = _integer(parent_parameters.get("steps", selected["steps"]), "Steps")

    has_custom_size = _present(form, "width") or _present(form, "height")
    if action == "regenerate_larger" and parent and not has_custom_size:
        old_width = _integer(parent_parameters.get("width"), "Width")
        old_height = _integer(parent_parameters.get("height"), "Height")
        width, height = _larger_dimensions(old_width, old_height, _integer(selected["width"], "Width") * _integer(selected["height"], "Height"))
    else:
        width = _integer(form["width"], "Width") if _present(form, "width") else base_width
        height = _integer(form["height"], "Height") if _present(form, "height") else base_height

    steps = _integer(form["steps"], "Steps") if _present(form, "steps") else base_steps
    if _present(form, "seed"):
        seed = _integer(form["seed"], "Seed")
    elif action == "repeat" and parent:
        seed = _integer(parent_parameters.get("seed"), "Seed")
    else:
        seed = secrets.randbelow(MAX_SEED + 1)

    if (
        width < MIN_DIMENSION
        or height < MIN_DIMENSION
        or width > MAX_DIMENSION
        or height > MAX_DIMENSION
        or width % DIMENSION_STEP
        or height % DIMENSION_STEP
    ):
        raise ValueError("Dimensions must be 512–2752 and multiples of 32")
    if width * height > MAX_PIXEL_AREA:
        raise ValueError(f"Requested pixel area exceeds the validated limit of {MAX_PIXEL_AREA}")
    if not 1 <= steps <= MAX_STEPS:
        raise ValueError("Steps must be 1–80")
    if not 0 <= seed <= MAX_SEED:
        raise ValueError("Seed out of range")

    return GenerationRequest(
        prompt=raw_prompt,
        model_id=model_id,
        profile=profile,
        width=width,
        height=height,
        steps=steps,
        seed=seed,
        resolution=_integer(selected["resolution"], "Resolution"),
        action=action,
    )
