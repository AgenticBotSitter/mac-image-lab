import json

import pytest

from imagelab.db import initialize_database
from imagelab.repositories.preferences import PreferenceConflict, PreferenceRepository


def test_named_recipe_round_trips_validated_versioned_request(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    repository = PreferenceRepository(connection)
    saved = repository.save_recipe(
        recipe_id="recipe-one",
        name="Quiet product portrait",
        description="Neutral studio starting point",
        request={
            "schema_version": 1,
            "mode": "text",
            "model_id": "qwen-image-2.1-local",
            "prompt": "A quiet product portrait on warm stone.",
            "profile": "fast",
            "aspect": "portrait",
        },
    )

    assert saved["request"]["schema_version"] == 1
    assert repository.list_recipes()[0]["name"] == "Quiet product portrait"
    assert json.loads(connection.execute("SELECT request_json FROM recipes").fetchone()[0])["aspect"] == "portrait"


def test_recipe_validation_rejects_unknown_shape_without_writing(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    repository = PreferenceRepository(connection)

    with pytest.raises(ValueError, match="Recipe mode"):
        repository.save_recipe(
            recipe_id="bad",
            name="Bad recipe",
            description="",
            request={"schema_version": 1, "mode": "automatic", "model_id": "qwen-image-2.1-local", "prompt": "test", "profile": "fast", "aspect": "square"},
        )

    assert repository.list_recipes() == []


def test_model_note_revision_prevents_silent_overwrite(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    repository = PreferenceRepository(connection)
    first = repository.save_model_note("qwen-image-2.1-local", "Use literal material names.", expected_revision=0)
    second = repository.save_model_note("qwen-image-2.1-local", "Prefer restrained lighting.", expected_revision=1)

    assert first["revision"] == 1
    assert second["revision"] == 2
    with pytest.raises(PreferenceConflict):
        repository.save_model_note("qwen-image-2.1-local", "Stale edit", expected_revision=1)
    assert repository.get_model_note("qwen-image-2.1-local")["note"] == "Prefer restrained lighting."
