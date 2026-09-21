#!/usr/bin/env python3
"""Dry-run or apply the legacy receipt-to-SQLite migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from imagelab.db import backup_database
from imagelab.migration import migrate_legacy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "runs")
    parser.add_argument("--database", type=Path, default=ROOT / "state" / "library.sqlite3")
    parser.add_argument("--model-notes", type=Path, default=ROOT / "state" / "model-notes.json")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true", help="write the database; default is read-only dry-run")
    parser.add_argument("--backup", type=Path, help="online-backup the resulting database after apply")
    args = parser.parse_args()

    report = migrate_legacy(
        args.runs,
        args.database,
        dry_run=not args.apply,
        model_notes_path=args.model_notes,
    )
    if args.apply and args.backup:
        backup_database(args.database, args.backup)
        report["backup_path"] = str(args.backup.resolve())
    body = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(body)
    print(body, end="")
    return 1 if report["hash_mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
