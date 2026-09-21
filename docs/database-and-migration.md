# Local database and legacy migration

Mac Image Lab uses `state/library.sqlite3` as its indexed local source of truth. Run directories under `runs/<run-id>/` remain immutable technical evidence and recovery inputs; Finder-facing copies remain under `~/Documents/Mac Image Lab/Generated Images/`.

## Database properties

- SQLite WAL mode with foreign keys and a 30-second busy timeout.
- Schema version recorded in `schema_migrations`.
- Indexed run, family, queue-state, collection, model-note, recipe, family-choice, and archive-attempt records.
- Full legacy receipt JSON and its SHA-256 remain attached to every imported run.
- Application receipt writes use atomic file replacement and update SQLite in the same application operation.

## Migration

Dry run (default; does not create a database):

```bash
.venv/bin/python scripts/migrate_legacy.py --report state/migration-dry-run.json
```

Apply after inspecting the dry-run counts and errors:

```bash
.venv/bin/python scripts/migrate_legacy.py \
  --apply \
  --report state/migration-report.json \
  --backup backups/library-after-migration.sqlite3
```

The migration is idempotent by run ID. It re-hashes each source receipt, upserts the complete record, imports collection mappings and model notes, and reconciles stored receipt hashes. Malformed records are reported and, on apply, represented by sanitized diagnostic JSON under `state/quarantine/`; source receipts are never moved or rewritten.

Legacy schema-v1 Qwen records without `model_id` are identified only when their recorded model assets explicitly contain the Qwen-Image-2.1 filename. Unknown model provenance remains an error rather than being guessed.

## Backup and restore rehearsal

`imagelab.db.backup_database` uses SQLite's online backup API. Restore testing must use a copied database at an isolated path, run `PRAGMA integrity_check`, and compare run counts before any production replacement. Do not overwrite the active database during a rehearsal.

The Gold T07 migration imported three legacy receipts, reconciled all three receipt hashes, passed `PRAGMA integrity_check`, and restored a three-run backup in an isolated scratch database.
