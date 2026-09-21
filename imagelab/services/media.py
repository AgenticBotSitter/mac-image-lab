"""Hash-keyed, private thumbnail derivation."""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

_ALLOWED_SIZES = {320, 640, 960}


@dataclass(frozen=True)
class Thumbnail:
    path: Path
    width: int
    height: int
    etag: str


class ThumbnailService:
    def __init__(self, cache_root: Path):
        self.cache_root = Path(cache_root)

    @staticmethod
    def _digest(path: Path) -> str:
        value = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                value.update(block)
        return value.hexdigest()

    def get_or_create(self, source: Path, source_sha256: str, size: int) -> Thumbnail:
        if size not in _ALLOWED_SIZES:
            raise ValueError("Unsupported thumbnail size")
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        if self._digest(source) != source_sha256:
            raise ValueError("Source image hash does not match indexed evidence")
        directory = self.cache_root / source_sha256
        target = directory / f"{size}.webp"
        directory.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with Image.open(source) as opened:
                opened.load()
                derived = ImageOps.exif_transpose(opened).convert("RGB")
                derived.thumbnail((size, size), Image.Resampling.LANCZOS)
                descriptor, temporary_name = tempfile.mkstemp(prefix=f".{size}-", suffix=".tmp", dir=directory)
                os.close(descriptor)
                temporary = Path(temporary_name)
                try:
                    derived.save(temporary, format="WEBP", quality=84, method=6)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        with Image.open(target) as thumbnail:
            width, height = thumbnail.size
        return Thumbnail(target, width, height, f'"{source_sha256}-{size}"')
