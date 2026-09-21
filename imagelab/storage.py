"""Safe reference-image decoding and atomic local writes."""

from __future__ import annotations

import hashlib
import io
import os
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_DECODED_PIXELS = 50_000_000
MIME_FORMATS = {
    "image/png": ("PNG", ".png"),
    "image/jpeg": ("JPEG", ".jpg"),
    "image/webp": ("WEBP", ".webp"),
}


@dataclass(frozen=True)
class IngestedReference:
    original_bytes: bytes
    derivative_bytes: bytes
    original_suffix: str
    derivative_suffix: str
    original_sha256: str
    derivative_sha256: str
    source_format: str
    width: int
    height: int
    mode: str
    exif_transposed: bool


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_reference(data: bytes, declared_mime: str) -> IngestedReference:
    """Verify, fully decode, orient, and metadata-strip a supported still image."""
    if declared_mime not in MIME_FORMATS:
        raise ValueError("Upload a PNG, JPEG, or WebP image; HEIC is not supported yet")
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Image must be non-empty and 20 MiB or smaller")

    expected_format, source_suffix = MIME_FORMATS[declared_mime]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != expected_format:
                    raise ValueError("Declared image type does not match decoded image format")
                if probe.width * probe.height > MAX_DECODED_PIXELS:
                    raise ValueError(f"Image exceeds the decoded pixel limit of {MAX_DECODED_PIXELS}")
                probe.verify()
            with Image.open(io.BytesIO(data)) as source:
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported")
                if source.width * source.height > MAX_DECODED_PIXELS:
                    raise ValueError(f"Image exceeds the decoded pixel limit of {MAX_DECODED_PIXELS}")
                orientation = source.getexif().get(274)
                source.load()
                normalized = ImageOps.exif_transpose(source)
                if normalized.mode in {"RGBA", "LA"} or "transparency" in normalized.info:
                    normalized = normalized.convert("RGBA")
                else:
                    normalized = normalized.convert("RGB")
                derivative_buffer = io.BytesIO()
                normalized.save(derivative_buffer, format="PNG", optimize=True)
                derivative = derivative_buffer.getvalue()
                return IngestedReference(
                    original_bytes=data,
                    derivative_bytes=derivative,
                    original_suffix=source_suffix,
                    derivative_suffix=".png",
                    original_sha256=_digest(data),
                    derivative_sha256=_digest(derivative),
                    source_format=expected_format,
                    width=normalized.width,
                    height=normalized.height,
                    mode=normalized.mode,
                    exif_transposed=orientation not in (None, 1),
                )
    except ValueError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError(f"Image exceeds the decoded pixel limit of {MAX_DECODED_PIXELS}") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Upload a valid image that can be fully decoded") from exc


def atomic_write_beneath(root: Path, relative: str, data: bytes) -> Path:
    """Atomically replace a file below root while rejecting traversal and symlink escapes."""
    root = root.resolve()
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("Destination escapes the approved storage root")
    target = (root / raw).resolve()
    if root not in target.parents:
        raise ValueError("Destination escapes the approved storage root")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
