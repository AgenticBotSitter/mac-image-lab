import pytest

from imagelab import validation

PROFILES = {
    "fast": {"width": 768, "height": 768, "steps": 8, "resolution": 768},
    "standard": {"width": 1024, "height": 1024, "steps": 20, "resolution": 1024},
    "maximum": {"width": 1696, "height": 2528, "steps": 25, "resolution": 2048},
}
PARENT = {
    "model_id": "qwen-image-2.1-local",
    "profile": "fast",
    "prompt": "parent prompt",
    "parameters": {"width": 1024, "height": 768, "steps": 12, "seed": 99},
}


def normalize(form, parent=None):
    return validation.normalize_generation_request(
        form,
        profiles=PROFILES,
        available_models={"qwen-image-2.1-local"},
        parent=parent,
    )


def test_explicit_profile_wins_over_parent_settings():
    request = normalize({"prompt": "larger", "profile": "maximum"}, parent=PARENT)
    assert (request.width, request.height, request.steps) == (1696, 2528, 25)


def test_variation_without_profile_inherits_parent_settings():
    request = normalize({"prompt": "variation", "action": "variation"}, parent=PARENT)
    assert (request.width, request.height, request.steps) == (1024, 768, 12)
    assert request.seed != 99


def test_repeat_inherits_parent_seed_but_explicit_zero_is_preserved():
    repeated = normalize({"prompt": "repeat", "action": "repeat"}, parent=PARENT)
    explicit = normalize({"prompt": "repeat", "action": "repeat", "seed": "0"}, parent=PARENT)
    assert repeated.seed == 99
    assert explicit.seed == 0


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="Unknown profile"):
        normalize({"prompt": "test", "profile": "missing"})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("steps", "0", "Steps"), ("seed", "-1", "Seed"), ("width", "513", "Dimensions")],
)
def test_parameter_bounds_are_rejected(field, value, message):
    with pytest.raises(ValueError, match=message):
        normalize({"prompt": "test", field: value})


def test_pixel_area_budget_is_enforced():
    with pytest.raises(ValueError, match="pixel area"):
        normalize({"prompt": "test", "width": "2752", "height": "2752"})


@pytest.mark.parametrize("old_width,old_height", [(1024, 768), (768, 1024), (768, 768)])
def test_regenerate_larger_preserves_aspect_and_increases_area(old_width, old_height):
    parent = {**PARENT, "parameters": {**PARENT["parameters"], "width": old_width, "height": old_height}}
    request = normalize({"prompt": "larger", "profile": "maximum", "action": "regenerate_larger"}, parent=parent)
    old_ratio = old_width / old_height
    new_ratio = request.width / request.height
    assert request.width * request.height > old_width * old_height
    assert abs(new_ratio - old_ratio) < 0.05
    assert request.width % 32 == request.height % 32 == 0
    assert request.width * request.height <= validation.MAX_PIXEL_AREA


def test_regenerate_larger_at_maximum_is_rejected():
    max_parent = {**PARENT, "profile": "maximum", "parameters": {"width": 1696, "height": 2528, "steps": 25, "seed": 1}}
    with pytest.raises(ValueError, match="already at the maximum"):
        normalize({"prompt": "larger", "profile": "maximum", "action": "regenerate_larger"}, parent=max_parent)
