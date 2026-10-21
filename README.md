# Roku IPTV

Verified free-TV playlist for a Roku TV, rebuilt automatically in cloud CI.

- Playlist: https://beexly.github.io/roku-iptv/tv.m3u
- Guide:    https://beexly.github.io/roku-iptv/epg.xml

## How it works

`pipeline.py` merges several public IPTV sources, filters to English-language
US channels, removes duplicates, and keeps only streams that an `ffprobe`
video check confirms are live. `build_epg.py` remaps the epg.pw XMLTV guide
onto the surviving `tvg-id`s. A GitHub Actions workflow runs daily and commits
the results, which GitHub Pages publishes with the `audio/x-mpegurl` content
type that IPTV apps require.

Sources: iptv-org/iptv, Free-TV/IPTV, HerbertHe/iptv-sources.
