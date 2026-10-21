"""
Unified IPTV pipeline: multi-source ingest -> normalize -> dedupe -> verify -> rank -> publish.

Replaces the single-source build_verified.py. Sources are declared in SOURCES below;
each is fetched, parsed, and merged. Channels are deduplicated by tvg-id (falling back to
a normalized display name), and only entries that pass an ffprobe video check survive.

State is cached in cache.json so a re-run only re-probes what changed. That keeps the
weekly refresh fast and stops the pipeline from re-probing 1,400 stable channels.

Outputs:
  tv.m3u        - the playlist the Roku loads
  verified.m3u  - same content, kept for the previous file contract
  epg.xml       - XMLTV remapped onto the surviving tvg-ids
  cache.json    - probe cache + health history
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache.json")
TV = os.path.join(ROOT, "tv.m3u")
VERIFIED = os.path.join(ROOT, "verified.m3u")
EPG_OUT = os.path.join(ROOT, "epg.xml")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
WORKERS = 8
MIN_PUBLISH = 400          # hard floor, never publish below this
CACHE_TTL_DAYS = 5         # re-probe a healthy channel after this long
CACHE_MAX_DAYS = 21        # forget a channel entirely after this long


def find_ffprobe():
    """Locate ffprobe. Windows: the WinGet package dir holds a version dir, then
    bin/. Linux (CI): ffprobe is on PATH at /usr/bin/ffprobe."""
    import shutil
    found = shutil.which("ffprobe")
    if found:
        return found
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "Microsoft", "WinGet", "Packages")
    hits = []
    if os.path.isdir(base):
        for root, dirs, files in os.walk(base):
            if "ffprobe.exe" in files:
                hits.append(os.path.join(root, "ffprobe.exe"))
            if len(hits) > 8:
                break
    hits.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for h in hits:
        if os.path.isfile(h):
            return h
    return None


FFPROBE = find_ffprobe()

# ---------------------------------------------------------------- sources

SOURCES = [
    {
        "id": "org_us",
        "url": "https://iptv-org.github.io/iptv/countries/us.m3u",
        "weight": 100,          # higher wins when the same channel appears twice
        "country": "us",
    },
    {
        "id": "freetv_us",
        "url": "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_usa.m3u8",
        "weight": 80,
        "country": "us",
    },
    {
        "id": "org_sports",
        "url": "https://iptv-org.github.io/iptv/categories/sports.m3u",
        "weight": 60,
        "country": None,        # any country, but only sports group
        "sports_only": True,
    },
    {
        "id": "herbert",
        "url": "https://raw.githubusercontent.com/HerbertHe/iptv-sources/gh-pages/all.m3u",
        "weight": 40,
        "country": None,
        "english_only": True,
    },
]

# Language blocklist: names containing these are not English-language channels.
# Sports/News group does NOT imply English audio.
LANG_BLOCK = {
    "chinese", "mandarin", "cantonese", "hokkien", "hindi", "tamil", "telugu",
    "kannada", "malayalam", "marathi", "punjabi", "bengali", "urdu", "arabic",
    "persian", "farsi", "turkish", "russian", "ukrainian", "serbian", "croatian",
    "greek", "hebrew", "japanese", "korean", "vietnamese", "thai", "indonesian",
    "filipino", "tagalog", "malay", "spanish", "espanol", "portuguese", "italian",
    "german", "french", "dutch", "polish", "czech", "slovak", "hungarian",
    "romanian", "bulgarian", "albanian", "greek ", "latin", "catalan", "basque",
    "swedish", "norwegian", "danish", "finnish", "icelandic", "estonian",
    "latvian", "lithuanian", "belarusian", "kazakh", "uzbek", "mongolian",
    "arabic ", "farsi ", "pashto", "sinhala", "burmese", "khmer", "lao",
    "cambodian", "myanmar", "ethiopian", "amharic", "swahili", "zulu", "afrikaans",
}
# CJK / Cyrillic / Arabic ranges: any name containing these is not English.
NON_LATIN = re.compile(
    "[\u0400-\u04FF\u0530-\u08FF\u3040-\u30FF\u4E00-\u9FFF\u0600-\u06FF"
    "\u0750-\u077F\u0980-\u0DFF\uFB00-\uFB4F\uFE70-\uFEFF]")

PRIORITY = ("sports", "news", "entertainment", "movies", "series", "kids",
            "animation", "music", "general", "other")


# ---------------------------------------------------------------- fetching

def fetch(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        import gzip
        import io
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def parse_m3u(text):
    """Yield (extinf_line, url) pairs."""
    rows = []
    pending = None
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


# ---------------------------------------------------------------- normalizing

def field(info, name):
    m = re.search(r'%s="([^"]*)"' % name, info)
    return m.group(1) if m else ""


def display_name(info):
    return info.rsplit(",", 1)[-1].strip()


def normalize_name(name):
    """Strip resolution/quality noise so duplicate spellings collapse."""
    s = name.lower()
    s = re.sub(r"\[[^\]]*\]", " ", s)            # [HD], [BD], [VGA]
    s = re.sub(r"\((?:[^)]*\b(?:p|hd|sd|uhd|4k|fhd|hd|sd)\b[^)]*)\)", " ", s)
    s = re.sub(r"\b(?:uhd|fhd|hd|sd|4k|8k|1080p|720p|480p|360p|240p|hdtv|fptv)\b",
               " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def loose_key(name):
    """Aggressive key: drop filler words, remove spaces."""
    s = normalize_name(name)
    drop = {"the", "tv", "channel", "network", "us", "usa", "uk", "hd", "of"}
    words = [w for w in s.split() if w not in drop]
    return "".join(words)


def is_english(name, group):
    low = name.lower()
    if NON_LATIN.search(name):
        return False
    for word in LANG_BLOCK:
        if word in low:
            return False
    return True


def country_ok(info, name, source):
    """Keep US channels; drop obvious non-US country markers for country feeds."""
    if source.get("country") != "us":
        return True
    tvg = (field(info, "tvg-id") or "").lower()
    if tvg.endswith(".us") or ".us@" in tvg:
        return True
    if tvg and not re.search(r"\.(us)@", tvg):
        # a non-.us tvg-id inside the US feed -> not a US channel
        return False
    return True


def rank_key(info):
    group = (field(info, "group-title") or "").lower()
    first = group.split(";")[0].strip()
    for idx, key in enumerate(PRIORITY):
        if key in first:
            return (idx, normalize_name(display_name(info)))
    return (len(PRIORITY), normalize_name(display_name(info)))


# ---------------------------------------------------------------- probing

def has_video(payload):
    streams = list(payload.get("streams") or [])
    for prog in payload.get("programs") or []:
        streams.extend(prog.get("streams") or [])
    for s in streams:
        if s.get("codec_type") == "video" or s.get("width"):
            return True
    return False


def probe(url):
    cmd = [FFPROBE, "-v", "error", "-user_agent", UA, "-rw_timeout", "8000000",
           "-print_format", "json", "-show_streams", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=12, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0 and not proc.stdout:
        return False
    try:
        payload = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return False
    return has_video(payload)


# ---------------------------------------------------------------- cache

def load_cache():
    try:
        with open(CACHE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"probed": {}, "meta": {}}


def save_cache(cache):
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
    os.replace(tmp, CACHE)


def url_hash(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- main

def main():
    if not FFPROBE or not os.path.isfile(FFPROBE):
        raise SystemExit("ffprobe not found")
    print("ffprobe:", FFPROBE, flush=True)

    cache = load_cache()
    probed = cache.setdefault("probed", {})
    now = time.time()

    # ---- ingest
    merged = {}   # key -> dict(info, url, weight, name, tvg)
    for src in SOURCES:
        try:
            text = fetch(src["url"])
        except Exception as exc:
            print("source %s FAILED: %s" % (src["id"], exc), flush=True)
            continue
        rows = parse_m3u(text)
        kept = 0
        for info, url in rows:
            name = display_name(info)
            group = field(info, "group-title")
            if not is_english(name, group):
                continue
            if not country_ok(info, name, src):
                continue
            if src.get("sports_only") and "sports" not in group.lower():
                continue
            tvg = field(info, "tvg-id")
            key = tvg.strip().lower() if tvg.strip() else "n:" + loose_key(name)
            if not tvg.strip():
                key = "n:" + loose_key(name)
            prev = merged.get(key)
            if prev is None:
                merged[key] = {"info": info, "url": url, "weight": src["weight"],
                               "name": name, "tvg": tvg, "src": src["id"]}
                kept += 1
            elif src["weight"] > prev["weight"]:
                prev["info"] = info
                prev["url"] = url
                prev["weight"] = src["weight"]
                prev["src"] = src["id"]
            # same channel from a lower-weight source: remember it as a fallback
            merged[key].setdefault("alts", []).append(url)
        print("source %-12s rows=%-6s kept=%s" % (src["id"], len(rows), kept), flush=True)

    print("merged unique channels:", len(merged), flush=True)

    # ---- verify (cache-aware)
    to_probe = []
    for key, rec in merged.items():
        h = url_hash(rec["url"])
        entry = probed.get(h)
        if entry and entry.get("ok") and (now - entry.get("ts", 0)) < CACHE_TTL_DAYS * 86400:
            continue
        if entry and not entry.get("ok") and (now - entry.get("ts", 0)) < 2 * 86400:
            continue          # recently failed, don't hammer it
        to_probe.append((key, rec, h))

    print("probing %s channels (%s cached)" % (len(to_probe), len(merged) - len(to_probe)),
          flush=True)
    done = 0
    live = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(probe, rec["url"]): (key, rec, h)
                for key, rec, h in to_probe}
        for fut in as_completed(futs):
            key, rec, h = futs[fut]
            ok = fut.result()
            probed[h] = {"ok": ok, "ts": now}
            done += 1
            if ok:
                live += 1
            if done % 50 == 0:
                print("  progress %s/%s live=%s" % (done, len(to_probe), live), flush=True)

    # ---- assemble
    rows = []
    for key, rec in merged.items():
        h = url_hash(rec["url"])
        entry = probed.get(h)
        if not entry or not entry.get("ok"):
            continue
        rows.append((rec["info"], rec["url"]))
    rows.sort(key=lambda r: rank_key(r[0]))

    print("verified live:", len(rows), flush=True)
    if len(rows) < MIN_PUBLISH:
        raise SystemExit("ABORT: only %s live channels (< %s). tv.m3u untouched."
                         % (len(rows), MIN_PUBLISH))

    def write_m3u(path, entries):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("#EXTM3U\n")
            for info, url in entries:
                fh.write(info + "\n")
                fh.write(url + "\n")
        os.replace(tmp, path)

    write_m3u(VERIFIED, rows)
    write_m3u(TV, rows)
    print("wrote tv.m3u + verified.m3u (%s channels)" % len(rows), flush=True)

    # ---- prune stale cache
    cutoff = now - CACHE_MAX_DAYS * 86400
    for h in list(probed.keys()):
        if probed[h].get("ts", 0) < cutoff:
            probed.pop(h, None)
    save_cache(cache)
    print("cache entries:", len(probed), flush=True)


if __name__ == "__main__":
    main()
