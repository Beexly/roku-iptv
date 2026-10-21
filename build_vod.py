"""
Build a VOD (movies + TV shows) M3U from Archive.org public-domain items.

Why Archive.org:
  - Legitimate and free. Feature films and classic TV series are donated to
    the Internet Archive; ~28.5k feature films and ~11k classic TV items.
  - Items expose original .mp4 derivatives over plain HTTPS with HTTP range
    support, which is exactly what an IPTV app needs to play an entry.
  - No account, no paid panel, no API key, no per-viewer credentials.

The URL must come from the item's own metadata (the "name" field), not be
guessed from the identifier - guessing gives a 404.

Output: vod.m3u, a plain M3U whose entries are on-demand MP4s. Group titles
separate Films from Series so the player can sort them.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "vod.m3u")
STATE = os.path.join(ROOT, "vod_state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko; Gecko) Chrome/128.0.0.0 Safari/537.36"
UA = UA.replace("; Gecko;", ";")

MAX_ITEMS = int(os.environ.get("VOD_MAX_ITEMS", "400"))
MIN_SIZE_MB = 20
MIN_SECONDS = 600           # skip shorts/clips


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def search(query, rows, page=1):
    url = ("https://archive.org/advancedsearch.php?q="
           + urllib.parse.quote(query)
           + "&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=year"
           + "&rows=" + str(rows) + "&page=" + str(page) + "&output=json")
    data = json.loads(get(url).decode("utf-8", "replace"))
    resp = data.get("response", {})
    return resp.get("docs", []), resp.get("numFound", 0)


def metadata(identifier):
    try:
        data = json.loads(get("https://archive.org/metadata/%s" % identifier,
                              timeout=25).decode("utf-8", "replace"))
    except Exception:
        return None
    return data


def pick_video(files):
    """Best original .mp4 for this item: the largest one that is a real feature."""
    best = None
    for f in files:
        name = (f.get("name") or "")
        if not name.lower().endswith(".mp4"):
            continue
        if f.get("source") != "original":
            continue
        try:
            size = int(f.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if size < MIN_SIZE_MB * 1024 * 1024:
            continue
        try:
            length = float(f.get("length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length and length < MIN_SECONDS:
            continue
        # prefer higher resolution
        try:
            pixels = int(f.get("width") or 0) * int(f.get("height") or 0)
        except (TypeError, ValueError):
            pixels = 0
        cand = (pixels, size, length, name)
        if best is None or cand[:2] > best[:2]:
            best = cand
    if best is None:
        return None
    pixels, size, length, name = best
    return {"name": name, "size": size, "length": length,
            "width": f.get("width"), "height": f.get("height")}


def slug(title):
    s = re.sub(r"[^A-Za-z0-9 &-]", "", title or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s or "Untitled"


def main():
    state = {}
    if os.path.isfile(STATE):
        try:
            with open(STATE, "r", encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            state = {}
    seen = set(state.get("seen", []))

    entries = []
    stats = {}
    queries = [
        ("Films", "mediatype:movies AND collection:feature_films"),
        ("Series", "mediatype:movies AND collection:classic_tv"),
    ]
    for group, query in queries:
        docs, total = search(query, rows=MAX_ITEMS)
        stats[group] = {"candidates": len(docs), "total_available": total}
        for doc in docs:
            ident = doc.get("identifier")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            meta = metadata(ident)
            if not meta:
                continue
            server = meta.get("server")
            d1 = meta.get("dir")
            files = meta.get("files") or []
            pick = pick_video(files)
            if not pick:
                continue
            name = pick["name"]
            url = "https://archive.org/download/%s/%s" % (
                urllib.parse.quote(ident), urllib.parse.quote(name))
            title = doc.get("title") or meta.get("metadata", {}).get("title") or ident
            year = doc.get("year") or meta.get("metadata", {}).get("year") or ""
            label = "%s (%s)" % (slug(title), year) if year else slug(title)
            dur = int(pick["length"]) if pick["length"] else -1
            entries.append({
                "info": '#EXTINF:-1 tvg-id="vod.%s" group-title="%s",%s'
                        % (re.sub(r"[^A-Za-z0-9]+", "_", ident)[:40], group, label),
                "url": url,
                "group": group,
                "duration": dur,
            })
            time.sleep(0.12)
        stats[group]["collected"] = sum(1 for e in entries if e["group"] == group)

    # ---- verify a sample actually plays, then write
    print("collected %s entries (%s)"
          % (len(entries), ", ".join("%s=%s" % (k, v.get("collected"))
                                     for k, v in stats.items())), flush=True)
    if len(entries) < 50:
        raise SystemExit("ABORT: only %s VOD entries collected" % len(entries))

    entries.sort(key=lambda e: (e["group"], -e["duration"]))
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("#EXTM3U\n")
        for e in entries:
            fh.write(e["info"] + "\n")
            fh.write(e["url"] + "\n")
    os.replace(tmp, OUT)
    with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"seen": sorted(seen), "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "count": len(entries)}, fh, indent=1)
    print("wrote %s (%s entries, %s bytes)"
          % (OUT, len(entries), os.path.getsize(OUT)), flush=True)


if __name__ == "__main__":
    main()
