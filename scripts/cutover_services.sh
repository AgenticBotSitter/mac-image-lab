#!/bin/bash
# One-time approval-gated cutover from manual processes to launchd.
set -euo pipefail

ROOT="/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab"
DOMAIN="gui/$(id -u)"
AGENTS="$HOME/Library/LaunchAgents"
SECRET="$HOME/.config/mac-image-lab/session-key"
cd "$ROOT"

fail() { printf 'CUTOVER FAILED: %s\n' "$*" >&2; exit 1; }
loaded() { launchctl print "$DOMAIN/$1" >/dev/null 2>&1; }
wait_url() {
  local url="$1" attempts="$2"
  for ((i=1; i<=attempts; i++)); do
    curl -fsS --max-time 5 "$url" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}
stop_listener() {
  local port="$1" expected="$2" pid command
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN | head -n 1 || true)"
  [ -n "$pid" ] || return 0
  command="$(ps -p "$pid" -o command=)"
  [[ "$command" == *"$expected"* ]] || fail "port $port belongs to unexpected process: $command"
  kill -TERM "$pid"
  for _ in {1..30}; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done
  fail "PID $pid on port $port did not stop"
}

echo '[1/7] Checking queues'
active="$(sqlite3 state/library.sqlite3 "SELECT COUNT(*) FROM jobs WHERE state IN ('submitting','running','needs_attention');")"
[ "$active" = 0 ] || fail "$active active Image Lab job(s) remain"
if queue="$(curl -fsS --max-time 10 http://127.0.0.1:8188/queue 2>/dev/null)"; then
  python3 - "$queue" <<'PY'
import json, sys
q = json.loads(sys.argv[1])
if q.get("queue_running") or q.get("queue_pending"):
    raise SystemExit("CUTOVER FAILED: ComfyUI queue is not drained")
PY
else
  echo 'ComfyUI is stopped; database confirms no active jobs, so cutover can continue.'
fi

for label in comfyui worker web; do
  loaded "com.alastairfraser.mac-image-lab.$label" && fail "$label LaunchAgent is already loaded; ask Hermes to verify the partial cutover"
done

echo '[2/7] Backing up SQLite state'
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="backups/cutover-$stamp/library.sqlite3"
mkdir -p "$(dirname "$backup")" logs
.venv/bin/python - "$backup" <<'PY'
from pathlib import Path
import sys
from imagelab.db import backup_database
backup_database(Path("state/library.sqlite3"), Path(sys.argv[1]))
PY
[ "$(sqlite3 "$backup" 'PRAGMA integrity_check;')" = ok ] || fail 'database backup integrity check failed'

echo '[3/7] Provisioning private session key'
install -d -m 700 "$HOME/.config/mac-image-lab"
if [ ! -f "$SECRET" ]; then
  (umask 077; openssl rand -hex 32 > "$SECRET")
fi
chmod 600 "$SECRET"
.venv/bin/python scripts/run_web.py --secret-file "$SECRET" --check >/dev/null

echo '[4/7] Installing LaunchAgents'
mkdir -p "$AGENTS"
cp deploy/launchd/com.alastairfraser.mac-image-lab.*.plist "$AGENTS/"
plutil -lint "$AGENTS"/com.alastairfraser.mac-image-lab.*.plist >/dev/null

echo '[5/7] Switching ComfyUI and starting worker'
stop_listener 8188 'Qwen-Image-2.1/ComfyUI'
launchctl bootstrap "$DOMAIN" "$AGENTS/com.alastairfraser.mac-image-lab.comfyui.plist"
wait_url http://127.0.0.1:8188/object_info 90 || fail 'supervised ComfyUI did not become ready; inspect logs/comfyui.err.log'
launchctl bootstrap "$DOMAIN" "$AGENTS/com.alastairfraser.mac-image-lab.worker.plist"
sleep 2
loaded com.alastairfraser.mac-image-lab.worker || fail 'worker LaunchAgent did not remain loaded'

echo '[6/7] Switching web service to Waitress'
stop_listener 7864 'Mac Image Lab'
launchctl bootstrap "$DOMAIN" "$AGENTS/com.alastairfraser.mac-image-lab.web.plist"
wait_url http://127.0.0.1:7864/healthz 60 || fail 'Waitress did not become healthy; inspect logs/web.err.log'

echo '[7/7] Verifying local and Tailscale health'
for label in comfyui worker web; do
  loaded "com.alastairfraser.mac-image-lab.$label" || fail "$label LaunchAgent is not loaded"
done
curl -fsS http://127.0.0.1:7864/healthz >/dev/null
curl -fsS https://alastairs-mac-mini.tail97e4dc.ts.net/healthz >/dev/null
lsof -nP -iTCP:7864 -iTCP:8188 -sTCP:LISTEN
printf '\nCUTOVER COMPLETE\nBackup: %s\n' "$backup"
