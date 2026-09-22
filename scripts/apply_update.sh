#!/usr/bin/env bash
set -euo pipefail
ROOT="/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab"
cd "$ROOT"

printf '%s\n' '[1/4] Checking for active work'
PYTHONPATH=. .venv/bin/python - <<'PY'
from imagelab.db import initialize_database
from imagelab.repositories.jobs import JobRepository
from pathlib import Path
connection = initialize_database(Path("state/library.sqlite3"))
try:
    active = JobRepository(connection).active()
    if active is not None:
        raise SystemExit(f"UPDATE STOPPED: job {active['id']} is {active['state']}")
finally:
    connection.close()
PY
queue="$(curl -fsS --max-time 10 http://127.0.0.1:8188/queue)"
python3 - "$queue" <<'PY'
import json, sys
value = json.loads(sys.argv[1])
if value.get("queue_running") or value.get("queue_pending"):
    raise SystemExit("UPDATE STOPPED: ComfyUI queue is not drained")
PY

printf '%s\n' '[2/4] Validating committed update'
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_runtime.py tests/browser/test_devices.py

printf '%s\n' '[3/4] Reloading worker and web services'
launchctl kickstart -k "gui/$(id -u)/com.alastairfraser.mac-image-lab.worker"
launchctl kickstart -k "gui/$(id -u)/com.alastairfraser.mac-image-lab.web"

printf '%s\n' '[4/4] Verifying production update'
for attempt in {1..30}; do
  if curl -fsS --max-time 5 http://127.0.0.1:7864/healthz >/dev/null; then break; fi
  sleep 1
done
curl -fsS --max-time 10 http://127.0.0.1:7864/healthz
curl -fsS --max-time 10 https://alastairs-mac-mini.tail97e4dc.ts.net/healthz
curl -fsS --max-time 10 https://alastairs-mac-mini.tail97e4dc.ts.net/static/manifest.webmanifest >/dev/null
curl -fsSI --max-time 10 https://alastairs-mac-mini.tail97e4dc.ts.net/service-worker.js | grep -qi '^service-worker-allowed: /'
launchctl print "gui/$(id -u)/com.alastairfraser.mac-image-lab.worker" | grep -E '^\s*(state|pid) ='
launchctl print "gui/$(id -u)/com.alastairfraser.mac-image-lab.web" | grep -E '^\s*(state|pid) ='
printf '%s\n' 'UPDATE COMPLETE'
