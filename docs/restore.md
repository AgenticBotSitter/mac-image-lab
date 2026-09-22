# Mac Image Lab backup and restore

## Scope

This restores the operational SQLite index and verifies immutable run evidence. It does not restore model weights, credentials, generated Finder copies, or the session key.

**Never replace the live database while the worker owns an active job.** First confirm there are no `queued`, `submitting`, `running`, or `needs_attention` jobs that must be preserved.

## Create a consistent backup

From `/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab`:

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PYTHONPATH=. .venv/bin/python - <<PY
from pathlib import Path
from imagelab.db import backup_database
backup_database(Path("state/library.sqlite3"), Path("backups/manual-$STAMP/library.sqlite3"))
PY
sqlite3 "backups/manual-$STAMP/library.sqlite3" 'PRAGMA integrity_check;'
```

Expected result: `ok`.

## Rehearse in isolation

Never test restoration against `state/library.sqlite3`.

```bash
mkdir -p validation/restore-rehearsal
cp "backups/manual-$STAMP/library.sqlite3" validation/restore-rehearsal/restored.sqlite3
sqlite3 validation/restore-rehearsal/restored.sqlite3 'PRAGMA integrity_check;'
PYTHONPATH=. .venv/bin/python scripts/migrate_legacy.py \
  --runs runs \
  --database validation/restore-rehearsal/migrated.sqlite3 \
  --apply \
  --report validation/restore-rehearsal/migration.json
```

Compare the `runs` count in the backup, restored copy, and isolated migration. The isolated migration reconstructs run metadata from receipts; it intentionally does not reconstruct job/event history.

## Restore production

1. Drain work and inspect both queues.
2. Preserve the current database before replacing it.
3. Stop both the worker and web LaunchAgents so no process can retain an old WAL connection.
4. Checkpoint the current database, preserve it, and remove its now-unused WAL/SHM sidecars.
5. Copy the verified backup into place atomically.
6. Start both services and verify integrity, queue state, and health.

```bash
cd "/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab"
sqlite3 state/library.sqlite3 "select state,count(*) from jobs group by state;"
curl -fsS http://127.0.0.1:8188/queue

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
launchctl bootout "gui/$(id -u)/com.alastairfraser.mac-image-lab.worker"
launchctl bootout "gui/$(id -u)/com.alastairfraser.mac-image-lab.web"
sqlite3 state/library.sqlite3 'PRAGMA wal_checkpoint(TRUNCATE);'
cp state/library.sqlite3 "backups/pre-restore-$STAMP.sqlite3"
rm -f state/library.sqlite3-wal state/library.sqlite3-shm
cp /absolute/path/to/verified/library.sqlite3 state/library.sqlite3.restore
sqlite3 state/library.sqlite3.restore 'PRAGMA integrity_check;'
mv state/library.sqlite3.restore state/library.sqlite3
rm -f state/library.sqlite3-wal state/library.sqlite3-shm
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.alastairfraser.mac-image-lab.worker.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.alastairfraser.mac-image-lab.web.plist"
```

Then run:

```bash
.venv/bin/python scripts/verify_install.py
curl -fsS https://alastairs-mac-mini.tail97e4dc.ts.net/healthz
```

## Rollback a failed restore

If the replacement fails integrity or service checks:

1. Stop only the worker.
2. Move the failed database aside; do not delete it.
3. Restore `backups/pre-restore-<stamp>.sqlite3`.
4. Restart the worker and rerun diagnostics.

Do not restore an older database over newly completed production runs without first preserving their run directories and reconciling them with `scripts/migrate_legacy.py` in an isolated database.

## Verified Gold rehearsal

The Gold release rehearsal used an online backup, restored copy, isolated receipt migration, and rollback copy under `validation/t24-restore/`.

- Source backup: integrity `ok`; 8 runs, 5 jobs, 785 job events.
- Restored copy: identical integrity and row counts.
- Isolated migration: integrity `ok`; all 8 run receipts imported.
- Rollback copy: identical to the source backup.
- All 8 receipt/output SHA-256 relationships verified.
