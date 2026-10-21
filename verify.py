"""
verify.py - gate every publish.

Checks the PUBLISHED URLs (not local files), because that is what the TV
actually downloads:

  - HTTP 200
  - Content-Type contains "mpegurl" for .m3u (apps reject text/plain)
  - body starts with #EXTM3U
  - channel count >= MIN_PUBLISH
  - every EXTINF line is followed by a URL line
  - no duplicate tvg-id base (a channel must appear once)
  - epg.xml is well-formed XML and non-empty

Exits non-zero on any failure so CI blocks the deploy.
"""

import argparse
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
MIN_PUBLISH = 400
MIN_VOD = 50


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, (resp.headers.get("Content-Type") or "").lower(), resp.read()


def check_m3u(label, url, minimum):
    errors = []
    print("--- %s" % label)
    print("    url: %s" % url)
    try:
        status, ctype, body = fetch(url)
    except Exception as exc:
        print("    FAIL cannot fetch: %s" % exc)
        return ["%s: fetch failed: %s" % (label, exc)], 0
    print("    http %s  content-type %s  bytes %s" % (status, ctype, len(body)))
    if status != 200:
        errors.append("%s: http %s" % (label, status))
    if "mpegurl" not in ctype:
        errors.append("%s: content-type %r is not an M3U type" % (label, ctype))
    text = body.decode("utf-8", "replace")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines or not lines[0].startswith("#EXTM3U"):
        errors.append("%s: missing #EXTM3U header" % label)
    extinf = [l for l in lines if l.startswith("#EXTINF")]
    print("    channels: %s" % len(extinf))
    if len(extinf) < minimum:
        errors.append("%s: %s channels < %s" % (label, len(extinf), minimum))
    # every EXTINF must be followed by a non-# line
    bad = 0
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF"):
            if i + 1 >= len(lines) or lines[i + 1].startswith("#"):
                bad += 1
    if bad:
        errors.append("%s: %s EXTINF lines not followed by a URL" % (label, bad))
    else:
        print("    structure: ok")
    # duplicate channel identity
    bases = []
    for line in extinf:
        m = re.search(r'tvg-id="([^"]*)"', line)
        if m and m.group(1):
            bases.append(m.group(1).split("@")[0].lower())
    dupes = len(bases) - len(set(bases))
    if dupes:
        errors.append("%s: %s duplicate channel ids" % (label, dupes))
    else:
        print("    duplicates: none")
    # group spread
    groups = {}
    for line in extinf:
        m = re.search(r'group-title="([^"]*)"', line)
        if m:
            groups[m.group(1)] = groups.get(m.group(1), 0) + 1
    if groups:
        top = sorted(groups.items(), key=lambda kv: -kv[1])[:8]
        print("    groups: %s" % ", ".join("%s=%s" % (k, v) for k, v in top))
    return errors, len(extinf)


def check_xml(label, url, minimum_bytes=1000):
    errors = []
    print("--- %s" % label)
    print("    url: %s" % url)
    try:
        status, ctype, body = fetch(url)
    except Exception as exc:
        print("    FAIL cannot fetch: %s" % exc)
        return ["%s: fetch failed: %s" % (label, exc)]
    print("    http %s  content-type %s  bytes %s" % (status, ctype, len(body)))
    if status != 200:
        errors.append("%s: http %s" % (label, status))
    if len(body) < minimum_bytes:
        errors.append("%s: only %s bytes" % (label, len(body)))
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        errors.append("%s: not well-formed XML: %s" % (label, exc))
        return errors
    chans = root.findall("channel")
    progs = root.findall("programme")
    print("    xml ok: %s channels, %s programmes" % (len(chans), len(progs)))
    if not chans:
        errors.append("%s: no channels" % label)
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://beexly.github.io/roku-iptv")
    ap.add_argument("--min-channels", type=int, default=MIN_PUBLISH)
    ap.add_argument("--min-vod", type=int, default=MIN_VOD)
    ap.add_argument("--no-vod", action="store_true")
    ap.add_argument("--no-epg", action="store_true")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    errors = []
    counts = {}

    err, n = check_m3u("live playlist", base + "/tv.m3u", args.min_channels)
    errors += err
    counts["tv.m3u"] = n

    if not args.no_vod:
        err, n = check_m3u("vod playlist", base + "/vod.m3u", args.min_vod)
        errors += err
        counts["vod.m3u"] = n

    if not args.no_epg:
        errors += check_xml("epg guide", base + "/epg.xml")

    print()
    if errors:
        print("VERIFY FAILED (%s problems):" % len(errors))
        for e in errors:
            print("  - %s" % e)
        return 1
    print("VERIFY OK: %s" % ", ".join("%s=%s channels" % (k, v) for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
