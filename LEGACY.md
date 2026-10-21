# Removed: what was dropped and why

This file records the pieces that existed during setup and are no longer part
of the system, so a future reader does not "restore" them by accident.

## The iptvactivation.com portal

**Removed.** It was a device-activation and playlist-storage service for the
Smarters Pro *app*. Three reasons it is gone:

1. **It is paid.** The activation it provides is a paid service, and the user
   does not want to pay for it. All the channels come from the M3U sources
   anyway — the portal served zero channels of its own.
2. **It is Smarters-only.** It is an activation layer for one app, not a
   general playlist host. A viewer on a different app cannot use it.
3. **It added a rate limit and a failure mode.** The API answers `429` with a
   `Retry-After` of ~12 minutes after a handful of calls, and it silently
   expires device activations (`expire_date` in the past, `is_trial: 0`).

The portal was never needed: the player points straight at the public GitHub
Pages URL.

## LAN serving (`http://192.168.x.x:8971/tv.m3u`)

**Removed from all committed artifacts.** A LAN URL only works while that
machine is awake, on that network, with that IP. The user explicitly asked for
a setup that does not depend on their laptop. The local server may still run
for debugging, but no published URL, setup card or config file points at it.

## Device MACs and device keys

**Removed.** `device.json` and every other file that carried an app MAC or
device key has been deleted. Those are personal identifiers for a specific
viewer, they are not needed once the portal is gone, and they do not belong in
a public repository.

The Roku's own NIC MAC is also not written anywhere in the repo. It is needed
only for LAN diagnostics, and it identifies the user's hardware.

## The dev-mode key sequence

**Removed.** The attempt to put the Roku TV into developer mode
(Home×3, Up×2, Right/Left×3) to enable `screencap` does not work on this
model — `developer-enabled` stays `false` and `query/screencap` returns 404
permanently. It was also a bad idea: it may have left a dialog on the TV, and
it is not needed now that no UI automation is attempted.

The consequence is accepted and documented: **there is no way to see the TV
screen**, so playback must be confirmed by the user.

## Blind UI automation over ECP

**Removed.** ECP keypresses were used to try to reach an app's playlist entry
field. This is abandoned for two reasons: it is blind (no screen feedback, so
there is no way to know what the keypresses landed on), and typing a URL with
`Lit_` keypresses is fragile enough to leave the app in a broken state.

The playlist URL is now pasted by the user, once.

## The `publish_url.py` / `repoint.py` / `watcher.py` local chain

**Removed.** These existed only to keep the portal's playlist rows in sync with
a LAN URL that changes when the host gets a new DHCP lease. With the portal
gone and Pages as the fixed public URL, there is nothing to keep in sync.

## `mime_test.m3u`

**Removed.** A placeholder used to prove that GitHub Pages serves `.m3u` with
`Content-Type: audio/x-mpegurl`. It proved its point; keeping it in the repo
only meant serving a dead channel to the TV.

## Kept, and why

- **`build_verified.py` → replaced by `pipeline.py`.** The old script verified
  a single source. The new one merges several, dedupes, and caches probe
  results. The old file was deleted rather than kept around.
- **`state.json`, `watcher_state.json`** — deleted. They tracked the LAN
  address and the portal's copy of it.
- **The local `server.py` and the "IPTV Playlist Server" scheduled task** —
  kept, but debug-only. It serves the playlist on the LAN for testing. Nothing
  published depends on it.
