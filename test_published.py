"""
End-to-end playability test of the PUBLISHED playlists.

Downloads the published M3U over HTTP exactly as the TV would, then ffprobes
a random sample of the entries it contains. This tests the real delivery
path - not the local build output - so a broken CDN path or a stale file
shows up here.

Usage: python test_published.py [live|vod|both] [sample_size]
"""

import json
import os
import random
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

FFPROBE = r"C:\Users\Garrett\AppData\Local\Microsoft\WinGet\Packages\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-125365-g9a01c1cb6a-win64-gpl\bin\ffprobe.exe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
BASE = "https://beexly.github.io/roku-iptv"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.headers.get("Content-Type", ""), resp.read().decode("utf-8", "replace")


def parse(text):
    rows, pending = [], None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            pending = line
        elif line.startswith("#"):
            continue
        elif pending:
            rows.append((pending, line))
            pending = None
    return rows


def probe(row, timeout):
    info, url = row
    cmd = [FFPROBE, "-v", "error", "-user_agent", UA, "-rw_timeout", "10000000",
           "-print_format", "json", "-show_streams", url]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except Exception:
        return row, False, "timeout"
    if p.returncode != 0 and not p.stdout:
        err = p.stderr.decode("utf-8", "replace")[:70].replace("\n", " ")
        return row, False, err
    try:
        d = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return row, False, "badjson"
    vids = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    if not vids:
        return row, False, "no video"
    s = vids[0]
    return row, True, "%s %sx%s" % (s.get("codec_name"), s.get("width"), s.get("height"))


def test(name, url, size, timeout):
    print("=== %s : %s" % (name, url))
    try:
        ctype, text = fetch(url)
    except Exception as exc:
        print("    FETCH FAILED: %s" % exc)
        return 0, 0, 1
    rows = parse(text)
    print("    content-type %s  entries %s" % (ctype, len(rows)))
    random.seed(11)
    sample = random.sample(rows, min(size, len(rows)))
    ok = 0
    fails = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(probe, r, timeout) for r in sample]
        for f in as_completed(futs):
            row, good, msg = f.result()
            if good:
                ok += 1
            else:
                key = msg.split(":")[0][:40]
                fails[key] = fails.get(key, 0) + 1
    pct = 100.0 * ok / len(sample)
    print("    PLAYABLE %s/%s = %.1f%%" % (ok, len(sample), pct))
    if fails:
        print("    failures: %s" % ", ".join("%s x%s" % (k, v) for k, v in fails.items()))
    return ok, len(sample), 0


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    total_ok = total_n = 0
    bad = 0
    if which in ("live", "both"):
        o, n, e = test("LIVE published", BASE + "/tv.m3u", size, 20)
        total_ok += o
        total_n += n
        bad += e
    if which in ("vod", "both"):
        o, n, e = test("VOD published", BASE + "/vod.m3u", size, 35)
        total_ok += o
        total_n += n
        bad += e
    print()
    print("TOTAL PLAYABLE %s/%s = %.1f%%" % (total_ok, total_n,
                                             100.0 * total_ok / max(1, total_n)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
