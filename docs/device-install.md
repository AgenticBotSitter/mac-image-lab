# Install Mac Image Lab on trusted devices

Use the same private URL on every enrolled device:

`https://alastairs-mac-mini.tail97e4dc.ts.net/`

There is no LAN fallback. Tailscale must be connected, and the host Mac must be awake with `alastairfraser` logged in after a reboot/FileVault unlock.

## Mac or another computer

1. Connect Tailscale and open the URL in Chrome, Edge, or Safari.
2. Chrome/Edge: use the install icon in the address bar or **Menu → Cast, save and share → Install page as app**.
3. Safari on current macOS: **File → Add to Dock**.
4. Reopen the installed app and confirm Library loads from the same HTTPS URL.

## iPhone or iPad

1. Connect Tailscale and open the URL in Safari.
2. Tap **Share → Add to Home Screen → Add**.
3. Launch **Image Lab** from the Home Screen.
4. On an image page, tap **Save to Photos**. In the iOS share sheet, choose **Save Image**. Use **Download to Files** only when a copy in Files/Downloads is intended.

## Android

1. Connect Tailscale and open the URL in Chrome.
2. Tap **Menu → Install app** or **Add to Home screen**.
3. Launch **Image Lab** from the installed icon.

## Offline and privacy behavior

- The app shell may be cached so an unreachable message can render.
- Generated images, thumbnails, run pages, API responses, downloads, and technical evidence are never stored by the service worker.
- Unsubmitted text controls are stored only in that browser's local storage and restored after an interruption. Selected source-image files are not persisted and must be reselected.
- An unreachable banner means no submission was sent. Reconnect Tailscale or wake/log into the host Mac, then reload before submitting.
- **Save in Mac library** writes to Finder on the host Mac. **Download** saves to the device currently using the browser.

## Cross-device acceptance

Record the device/browser and verify:

- Library and thumbnails load.
- Create controls retain unsent text after a reload.
- Queue state matches the Mac.
- A controlled single submission appears in the same queue; do not submit again while reconnecting.
- A completed image can be added to iPhone Photos through **Save to Photos → Save Image**; **Download to Files** remains available for Files/Downloads.
- **Open on host Mac** is visibly labeled and understood as a host-only action.
- Repeat on a phone first over Wi-Fi, then with Wi-Fi disabled while Tailscale remains connected.
