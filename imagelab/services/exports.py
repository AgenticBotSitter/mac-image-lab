"""Bounded, metadata-stripping image and evidence exports."""
from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageOps


class ExportError(ValueError):
    pass


def _opened(path: Path) -> Image.Image:
    try:
        image = Image.open(path)
        image.load()
        return ImageOps.exif_transpose(image)
    except (OSError, Image.UnidentifiedImageError) as exc:
        raise ExportError("Source image is unreadable") from exc


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)


def convert_image(source: Path, format_name: str, *, background: str | None = None) -> bytes:
    format_name = format_name.lower()
    if format_name == "png":
        return source.read_bytes()
    if format_name not in {"jpeg", "webp"}:
        raise ExportError("Unsupported export format")
    image = _opened(source)
    output = io.BytesIO()
    if format_name == "jpeg":
        if _has_alpha(image):
            if not background:
                raise ExportError("JPEG export requires an explicit alpha background")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
                raise ExportError("JPEG background must be a #RRGGBB color")
            base = Image.new("RGBA", image.size, ImageColor.getrgb(background) + (255,))
            base.alpha_composite(image.convert("RGBA"))
            image = base.convert("RGB")
        else:
            image = image.convert("RGB")
        image.save(output, format="JPEG", quality=95, optimize=True)
    else:
        image.save(output, format="WEBP", quality=95, method=6)
    return output.getvalue()


def resize_to_png(source: Path, destination: Path, *, width: int | None, height: int | None) -> tuple[int, int]:
    image = _opened(source)
    if width is None and height is None:
        raise ExportError("A width or height is required")
    if width is not None and (width < 16 or width > 8192):
        raise ExportError("Width must be between 16 and 8192")
    if height is not None and (height < 16 or height > 8192):
        raise ExportError("Height must be between 16 and 8192")
    if width is None:
        width = max(1, round(image.width * height / image.height))
    if height is None:
        height = max(1, round(image.height * width / image.width))
    assert width is not None and height is not None
    if width * height > 40_000_000:
        raise ExportError("Resized export exceeds the 40 megapixel limit")
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    try:
        resized.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return width, height


def _safe_component(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return value[:80] or "image"


def build_family_zip(runs_root: Path, receipts: list[dict[str, Any]], *, max_bytes: int = 512 * 1024 * 1024) -> bytes:
    if max_bytes < 1:
        raise ExportError("Invalid ZIP size limit")
    if len(receipts) > 100:
        raise ExportError("Family ZIP is limited to 100 runs")
    total = 0
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for receipt in receipts:
            run_id = str(receipt.get("run_id", ""))
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", run_id):
                raise ExportError("Family contains an invalid run ID")
            prefix = f"{_safe_component(str(receipt.get('title', 'image')))}-{run_id[:8]}"
            directory = runs_root / run_id
            receipt_path = directory / "receipt.json"
            output_name = (receipt.get("output") or {}).get("file")
            paths = [(receipt_path, f"{prefix}/receipt.json")]
            for evidence_name in ("workflow.json", "comfy-submit.json", "comfy-history.json", "archive.json", "model-manifest.json", "lineage.json"):
                evidence_path = directory / evidence_name
                if evidence_path.is_file():
                    paths.append((evidence_path, f"{prefix}/{evidence_name}"))
            reference = receipt.get("reference_edit") or {}
            for reference_key in ("source_file", "inference_file"):
                reference_name = reference.get(reference_key)
                if isinstance(reference_name, str) and Path(reference_name).name == reference_name:
                    reference_path = directory / reference_name
                    if reference_path.is_file():
                        paths.append((reference_path, f"{prefix}/{_safe_component(reference_name)}"))
            if isinstance(output_name, str) and Path(output_name).name == output_name:
                output_path = directory / output_name
                expected = (receipt.get("output") or {}).get("sha256")
                if output_path.is_file() and isinstance(expected, str):
                    actual = hashlib.sha256(output_path.read_bytes()).hexdigest()
                    if actual != expected:
                        raise ExportError(f"Output hash mismatch for {run_id}")
                    paths.append((output_path, f"{prefix}/output.png"))
            for path, member_name in paths:
                if not path.is_file():
                    raise ExportError(f"Required evidence is missing for {run_id}")
                size = path.stat().st_size
                total += size
                if total > max_bytes:
                    raise ExportError("Family ZIP exceeds the size limit")
                archive.write(path, member_name)
    data = payload.getvalue()
    if len(data) > max_bytes:
        raise ExportError("Family ZIP exceeds the size limit")
    return data
