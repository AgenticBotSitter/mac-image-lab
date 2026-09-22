#!/usr/bin/env python3
"""Fail-closed verifier for Mac Image Lab release run evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

REQUIRED_EVIDENCE = (
    "receipt.json",
    "workflow.json",
    "comfy-submit.json",
    "comfy-history.json",
    "output.png",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return payload


def validate_run(runs_root: Path, run_id: str) -> dict[str, Any]:
    directory = runs_root / run_id
    errors: list[str] = []
    evidence: dict[str, dict[str, Any]] = {}

    for name in REQUIRED_EVIDENCE:
        path = directory / name
        if not path.is_file():
            errors.append(f"missing evidence: {name}")
            continue
        evidence[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}

    receipt: dict[str, Any] = {}
    if (directory / "receipt.json").is_file():
        try:
            receipt = read_json(directory / "receipt.json")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid receipt.json: {exc}")

    for name in ("workflow.json", "comfy-submit.json", "comfy-history.json"):
        path = directory / name
        if path.is_file():
            try:
                read_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid {name}: {exc}")

    if receipt and receipt.get("run_id") != run_id:
        errors.append("receipt run_id does not match directory")
    if receipt and receipt.get("generation_state") != "succeeded":
        errors.append("generation_state is not succeeded")

    output_report: dict[str, Any] = {"sha256_verified": False, "actual_dimensions": None}
    raw_output = receipt.get("output")
    output_info: dict[str, Any] = raw_output if isinstance(raw_output, dict) else {}
    output_name = str(output_info.get("file") or "output.png")
    output_relative = Path(output_name)
    safe_output_name = not output_relative.is_absolute() and ".." not in output_relative.parts
    if not safe_output_name:
        errors.append("receipt output file must be a safe relative filename")
        output_path = directory / "__invalid_output_path__"
    else:
        output_path = directory / output_relative
    if output_path.is_file():
        actual_hash = sha256(output_path)
        expected_hash = output_info.get("sha256")
        output_report["sha256"] = actual_hash
        output_report["sha256_verified"] = actual_hash == expected_hash
        if not output_report["sha256_verified"]:
            errors.append("output hash does not match receipt")
        expected_width = output_info.get("width")
        expected_height = output_info.get("height")
        if expected_width is None or expected_height is None:
            errors.append("receipt output must record both width and height")
        try:
            with Image.open(output_path) as image:
                image.load()
                actual_dimensions = [image.width, image.height]
            output_report["actual_dimensions"] = actual_dimensions
            if expected_width is not None and expected_height is not None:
                expected_dimensions = [expected_width, expected_height]
                if actual_dimensions != expected_dimensions:
                    errors.append("output dimensions do not match receipt")
        except OSError as exc:
            errors.append(f"output image cannot be decoded: {exc}")
    elif safe_output_name:
        errors.append(f"declared output file is missing: {output_name}")

    parent_id = receipt.get("parent_run_id")
    lineage = {
        "family_id": receipt.get("family_id"),
        "parent_run_id": parent_id,
        "relationship": receipt.get("relationship"),
        "parent_exists": parent_id is None,
        "family_matches_parent": parent_id is None,
    }
    if parent_id:
        parent_receipt_path = runs_root / str(parent_id) / "receipt.json"
        lineage["parent_exists"] = parent_receipt_path.is_file()
        if not lineage["parent_exists"]:
            errors.append("parent receipt is missing")
        else:
            try:
                parent = read_json(parent_receipt_path)
                lineage["family_matches_parent"] = receipt.get("family_id") == parent.get("family_id")
                if not lineage["family_matches_parent"]:
                    errors.append("child family_id does not match parent")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"parent receipt is invalid: {exc}")

    return {
        "run_id": run_id,
        "status": "ok" if not errors else "failed",
        "errors": errors,
        "evidence": evidence,
        "output": output_report,
        "lineage": lineage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_ids", nargs="+", help="Run IDs to verify")
    parser.add_argument("--runs-root", type=Path, default=Path(__file__).parents[1] / "runs")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    reports = [validate_run(args.runs_root, run_id) for run_id in args.run_ids]
    payload = {"status": "ok" if all(item["status"] == "ok" for item in reports) else "failed", "runs": reports}
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")
    print(encoded)
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
