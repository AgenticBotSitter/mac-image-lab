# Mac Image Lab — Tailscale HTTPS Access

## Enabled access boundary

Mac Image Lab is now available to authenticated devices on Alastair's Tailscale network at:

`https://alastairs-mac-mini.tail97e4dc.ts.net/`

Tailscale Serve is the HTTPS proxy. It routes only to the existing local Mac Image Lab listener at `http://127.0.0.1:7864`.

## Security boundary verified

- Mac Image Lab remains loopback-only: `127.0.0.1:7864`.
- ComfyUI remains loopback-only at `127.0.0.1:8188` and is not proxied by Tailscale Serve.
- Tailscale reports the configured endpoint as `tailnet only`.
- A direct HTTPS request through the Tailscale hostname returned the Mac Image Lab `/healthz` response, including `loopback_only: true` and healthy ComfyUI reachability.

## Remaining access work

The separately authenticated LAN endpoint has not been enabled. It requires a secure credential-provisioning decision without placing a reusable password in chat or exposing the app without authentication.
