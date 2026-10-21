# Roku IPTV — verified free-TV + VOD playlist

Two playlists for a Roku TV, rebuilt every day in cloud CI and published on
GitHub Pages with the `audio/x-mpegurl` content type that Roku IPTV apps
require. **Nothing depends on the user's laptop** — the laptop is not in the
build loop and not in the delivery path.

| What | URL |
|---|---|
| Live TV playlist | `https://beexly.github.io/roku-iptv/tv.m3u` |
| Movies + TV series (VOD) | `https://beexly.github.io/roku-iptv/vod.m3u` |
| EPG guide (XMLTV) | `https://beexly.github.io/roku-iptv/epg.xml` |
| Setup card (QR + copy-able URLs) | `https://beexly.github.io/roku-iptv/setup.html` |
| Web player (no app needed) | `https://beexly.github.io/roku-iptv/player.html` |

## Architecture

```
sources            probe-once            render            deploy         verify
-------            ----------            ------            ------         ------
iptv-org/iptv  ┐
Free-TV/IPTV     ├──> ffprobe ──> cache.json ──> tv.m3u  ──┐
HerbertHe        │   (one probe       (actions/ vod.m3u    ├──> Pages  ──> verify.py
Archive.org      ┘    per stream)      cache)     epg.xml    │    artifact     (gates the
                                     ▲              setup.html│    deploy)      deploy)
                                     │              player.html
                                     └────────── daily CI ──────────────┘
```

**Probe once, publish many.** Every stream is probed exactly once per build and
the verdict is cached, so regenerating a playlist from the cache is free. The
cache lives in `actions/cache`, not in the repo.

**Build output is never committed.** The CI job uploads `dist/` as a Pages
artifact and deploys from the artifact. Committing build output back to the
branch caused rebase conflicts in generated files and raced with the CI run.

### CI job graph

```
probe  ──>  deploy  ──>  verify  ──>  summary
(build, EPG,  (Pages      (checks the
 VOD, QR)      artifact)   published URLs)
```

`verify.py` checks the **published** URLs, not the local files: HTTP 200,
correct content type, `#EXTM3U` header, minimum channel count, every `EXTINF`
followed by a URL, and no duplicate channel identities. It exits non-zero on
any failure, which fails the job. `verify_qr.py` additionally decodes the
setup card's QR codes with OpenCV and checks each payload is its own URL.

## How it works

`pipeline.py` merges four public sources, filters to English-language US
channels, drops duplicate variants of the same channel, drops non-`http(s)`
streams that no player can open, and keeps only streams that an `ffprobe`
check confirms carry a real video stream. `build_epg.py` remaps the epg.pw
XMLTV guide onto the surviving `tvg-id`s. `build_vod.py` collects feature
films and classic TV series from Archive.org, whose public-domain items expose
original `.mp4` files over plain HTTPS with range support — real on-demand
video, not a live stream in a trenchcoat. `build_player.py` writes a
self-hosted web player that reads the same two playlists.

### Source playlists (free, legal, community-maintained)

- `https://iptv-org.github.io/iptv/countries/us.m3u` — US channels (primary)
- `https://iptv-org.github.io/iptv/categories/sports.m3u` — sports (US-filtered)
- `https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_usa.m3u8`
- `https://raw.githubusercontent.com/HerbertHe/iptv-sources/gh-pages/all.m3u`
- Archive.org (`feature_films`, `classic_tv` collections) — VOD

## On the Roku: the one manual step

**You have to paste the URL into the app once.** This cannot be automated.

Roku's ECP control API is LAN-only; it can launch a channel and query state,
and that is all. The app's own text entry cannot be driven remotely, and this
TV exposes no `screencap` endpoint, so there is no way to verify what is on
screen programmatically. Blind keypress sequences are not used — without
visual feedback there is no way to know where they landed.

So: install the app, open it, add the playlist, done. After that the app
refreshes on its own schedule and the daily CI keeps the content fresh
underneath it.

### Which app

**Xtream IPTV Player** (Roku Channel Store id `814924`) — free. Its Channel
Store listing says it plays "streaming URLs and Xtream Codes API credentials
provided by your IPTV service provider", so a plain playlist URL is the
supported input. **Use the M3U URL field in its settings, not the "scan to
add a playlist" QR** — that QR opens the vendor's website
(`xtreamtvplayer.pro`), which is account-gated and paid for playlist syncing.

**If that app misbehaves:** *IPTV Smart Player Lite* — 18 ratings, listing
states "M3U/M3U8 playlist URL support", "EPG integration" and "no hidden fees
or subscriptions". *M3U IPTV Pro* and *Smart IPTV Player* are other options,
but M3U IPTV Pro's privacy policy points at the paid portal we removed, and
Smart IPTV Player has 0 ratings.

Verify against the current Channel Store listing before installing — app
capabilities change, and this repo deliberately does not hard-code a
recommendation that may have gone stale.

### Free TV shows and movies with zero setup

The Roku already has **Tubi, Fawesome, Pure Flix, Sling Freestream, The Roku
Channel, STARZ and Backdrops** installed. Those are ad-supported and need no
playlist at all. Our `vod.m3u` adds a separate library of public-domain films
and classic series on top.

## The web player

`player.html` is a self-hosted player that reads the same `tv.m3u` and
`vod.m3u`. It needs no app purchase, no account and no service, so it is the
path that works even if no IPTV app is installed on the TV. Open it on a
phone or tablet and cast it to the Roku, or just watch it in a browser.

**Known limitation:** archive.org's CDN does not send CORS headers on its
redirect target, so the **VOD entries will not play in a browser** — they
work in the Roku app, which is not CORS-bound. Live TV plays in the browser
because those hosts send `Access-Control-Allow-Origin: *`. The player says so
explicitly rather than showing a black rectangle.

## Optional upgrade path: Dispatcharr on a small VPS

If a viewer needs Xtream Codes (three short fields instead of a long URL), or
if real per-viewer access control matters, run
[Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) (open source, Docker)
on a ~$5/mo VPS. It aggregates the same upstream sources, proxies the streams,
and exposes both an M3U endpoint and an Xtream Codes API per user. That
replaces GitHub Pages as the customer-facing endpoint — Pages is fine for a
handful of viewers on a home network, not for concurrent streams.

Not built here. It is a deliberate upgrade, not a default.

## What was removed and why

See [LEGACY.md](LEGACY.md).

## Legal note

This project aggregates publicly-posted stream URLs and public-domain media
donated to the Internet Archive. It hosts no content of its own and no
credentials. Legality of any particular stream varies by jurisdiction — the
user is responsible for what they watch and where.

## Local development

```bash
python pipeline.py      # rebuild tv.m3u from sources (slow: probes every stream)
python build_epg.py     # remap the guide onto tv.m3u
python build_vod.py     # rebuild vod.m3u from Archive.org
python build_setup.py   # rebuild dist/setup.html with the QR codes
python build_player.py  # rebuild dist/player.html
python publish.py       # trigger the CI publish and verify the result
python verify.py        # check the published URLs
python test_published.py both 40   # end-to-end playability of what is live
```

Tunables: `IPTV_WORKERS`, `IPTV_PROBE_TIMEOUT`, `IPTV_PRECHECK_TIMEOUT`,
`IPTV_CACHE_TTL_DAYS`, `IPTV_CACHE_RETRY_DAYS`, `VOD_MAX_ITEMS`,
`VOD_VERIFY_WORKERS`.
