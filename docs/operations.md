# Mac Image Lab operations

## Service boundaries

- Web: Waitress on `127.0.0.1:7864`; exposed only through Tailscale Serve.
- Generation worker: one leader using `state/worker.lock`.
- ComfyUI: `127.0.0.1:8188`; never exposed directly.
- Session key: owner-only file at `~/.config/mac-image-lab/session-key`; never place its value in a plist, log, Git, or R2.

## Approval checkpoint

Do not install, bootstrap, boot out, kick, or replace the live services until Alastair explicitly approves the T20 production cutover. Preparing and validating the repository templates is safe; changing `~/Library/LaunchAgents` or the processes on ports 7864/8188 is the cutover.

## One-time secret provisioning

After approval, create the private directory and generate a strong key without printing it:

```bash
install -d -m 700 ~/.config/mac-image-lab
umask 077
openssl rand -hex 32 > ~/.config/mac-image-lab/session-key
chmod 600 ~/.config/mac-image-lab/session-key
```

Validate without revealing the value:

```bash
.venv/bin/python scripts/run_web.py \
  --secret-file ~/.config/mac-image-lab/session-key --check
```

## Pre-cutover drain and backup

1. Open `/queue` and wait until there are no `submitting`, `running`, or `needs_attention` jobs. Cancel queued jobs only when they are not wanted.
2. Confirm ComfyUI history has no active generation.
3. Run the database backup command from `docs/restore.md`.
4. Record current listeners with `lsof -nP -iTCP:7864 -iTCP:8188 -sTCP:LISTEN`.
5. Create `logs/` and confirm the three repository plist templates pass `plutil -lint`.

## Cutover

After explicit approval and a clean drain, the preferred path is the checked one-command cutover script. Run it from Terminal.app outside the Hermes gateway:

```bash
cd "/Users/alastairfraser/hermes-data/Marvin/Mac Image Lab"
bash scripts/cutover_services.sh
```

The script checks both queues, creates and verifies a SQLite backup, provisions the owner-only key when absent, installs the validated plists, replaces only the expected manual listeners, starts all three services, and verifies local plus Tailscale health. If it reports `CUTOVER FAILED`, do not rerun it blindly; inspect the named failure or ask Hermes to verify whether the cutover is partial.

Manual equivalent, retained for recovery/reference:

```bash
mkdir -p logs ~/Library/LaunchAgents
cp deploy/launchd/com.alastairfraser.mac-image-lab.*.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/com.alastairfraser.mac-image-lab.*.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alastairfraser.mac-image-lab.comfyui.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alastairfraser.mac-image-lab.worker.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alastairfraser.mac-image-lab.web.plist
```

Stop the old manual processes only at the point each replacement is ready to take its port. Never terminate an active generation. If a label is already registered, inspect it before using `launchctl kickstart -k gui/$(id -u)/<label>`.

## Verification

```bash
launchctl print gui/$(id -u)/com.alastairfraser.mac-image-lab.web
launchctl print gui/$(id -u)/com.alastairfraser.mac-image-lab.worker
launchctl print gui/$(id -u)/com.alastairfraser.mac-image-lab.comfyui
lsof -nP -iTCP:7864 -iTCP:8188 -sTCP:LISTEN
curl -fsS http://127.0.0.1:7864/healthz
curl -fsS http://127.0.0.1:8188/object_info >/dev/null
curl -fsS https://alastairs-mac-mini.tail97e4dc.ts.net/healthz
```

Expect one loopback listener per port, all three service labels with real PIDs, a healthy web response, and no direct public ComfyUI route. Perform one crash-recovery exercise only when no generation is active. Verify the replacement PID and health before continuing.

## Rollback

If production verification fails:

1. Preserve logs and record the failing service state.
2. Boot out only the failed new labels.
3. Restore the previous manual loopback commands:
   - web: `.venv/bin/python -m app.app`
   - worker: `.venv/bin/python -m imagelab.worker`
   - ComfyUI: its pinned Python plus `main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch`
4. Re-run loopback and Tailscale health checks.
5. Restore the database only if integrity checks fail; process rollback alone must not replace data.

Example boot-out command (human-gated):

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.alastairfraser.mac-image-lab.web.plist
```

## Logs and release evidence

Logs live under `logs/` and are excluded from release source. The Gold release archive must contain allowlisted source and documentation only. Upload it under the approved Mac Image Lab R2 prefix and verify every object with `boto3.head_object` before reporting completion.
