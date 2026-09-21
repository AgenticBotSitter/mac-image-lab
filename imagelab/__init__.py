"""Mac Image Lab application factory."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from flask import Flask

from imagelab.config import default_config, validate_config
from imagelab.security import init_security


def create_app(
    import_name: str = __name__,
    *,
    config: Mapping[str, Any] | None = None,
    template_folder: str | Path | None = None,
    static_folder: str | Path | None = None,
) -> Flask:
    app = Flask(
        import_name,
        template_folder=str(template_folder) if template_folder else None,
        static_folder=str(static_folder) if static_folder else None,
    )
    values = default_config()
    if config:
        values.update(config)
    validate_config(values)
    app.config.update(values)
    init_security(app)
    return app
