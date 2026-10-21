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

## Architecture

```
sources            probe-once            render            deploy         verify
-------            ----------            ------            ------         ------
iptv-org/iptv  ┐
Free-TV/IPTV     ├──> ffprobe ──> cache.json ──> tv.m3u  ──┐
HerbertHe        │   (one probe       (probed    vod.m3u    ├──> GitHub  ──> verify.py
Archive.org      ┘    per stream)      once)     epg.xml    │    Pages      (gates the
                                     ▲                                  │     deploy)
                                     └────────── daily CI ──────────────┘
```

**Probe once, publish many.** Every stream is probed exactly once per build and
the verdict is cached in `cache.json`, which is committed to the repo. The cache
is the expensive part; regenerating a playlist from it is free. That is what
makes adding a second viewer cheap.

## How it works

`pipeline.py` merges four public sources, filters to English-language US
channels, drops duplicate variants of the same channel, and keeps only streams
that an `ffprobe` check confirms carry a real video stream. `build_epg.py`
remaps the epg.pw XMLTV guide onto the surviving `tvg-id`s. `build_vod.py`
collects feature films and classic TV series from Archive.org, whose
public-domain items expose original `.mp4` files over plain HTTPS with range
support — real on-demand video, not a live stream in a trenchcoat.

`verify.py` then checks the **published** URLs, not the local files: HTTP 200,
correct content type, `#EXTM3U` header, minimum channel count, every `EXTINF`
followed by a URL, and no duplicate channel identities. It exits non-zero on
any failure, which fails the CI job before anything is published.

### Source playlists (free, legal, community-maintained)

- `https://iptv-org.github.io/iptv/countries/us.m3u` — US channels (primary)
- `https://iptv-org.github.io/iptv/categories/sports.m3u` — sports (US-filtered)
- `https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_usa.m3u8`
- `https://raw.githubusercontent.com/HerbertHe/iptv-sources/gh-pages/all.m3u`
- Archive.org (`feature_films`, `classic_tv` collections) — VOD

## On the Roku: the one manual step

**You have to paste the URL into the app once.** This cannot be automated.

Roku's ECP control API is LAN-only and its app set is not scriptable from
outside; the app's own text entry cannot be driven remotely, and this TV
exposes no `screencap` endpoint at all, so there is no way to verify what is
on screen programmatically. ECP can launch a channel and query state, and
nothing more.

So: install the app, open it, paste the URL, done. After that the app refreshes
on its own schedule and the daily CI keeps the content fresh underneath it.

## Choosing a player

Verify against the **current** Roku Channel Store listing before assuming an
app accepts an M3U URL — app capabilities change, and this repo deliberately
does not hard-code a recommendation that may have gone stale.

The playlist is a plain M3U over HTTPS. Any player that accepts a **Playlist /
M3U URL** will work. Players that only accept **Xtream Codes**
(server / port / username / password) will not — that is a different protocol
and needs a middleware panel, not a static file.

**Backup option:** if the preferred app turns out to be Xtream-Codes-only, the
upgrade path is to run a middleware panel that speaks Xtream Codes and outputs
M3U *and* Xtream from the same sources. See below.

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
python publish.py       # push to GitHub Pages
python verify.py        # check the published URLs
```

Tunables: `IPTV_WORKERS`, `IPTV_PROBE_TIMEOUT`, `IPTV_PRECHECK_TIMEOUT`,
`IPTV_CACHE_TTL_DAYS`, `IPTV_CACHE_RETRY_DAYS`, `VOD_MAX_ITEMS`.
