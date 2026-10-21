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

import categories as cats

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache.json")
TV = os.path.join(ROOT, "tv.m3u")
VERIFIED = os.path.join(ROOT, "verified.m3u")
EPG_OUT = os.path.join(ROOT, "epg.xml")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
WORKERS = int(os.environ.get("IPTV_WORKERS", "8"))
PROBE_TIMEOUT = int(os.environ.get("IPTV_PROBE_TIMEOUT", "12"))
PRECHECK_TIMEOUT = float(os.environ.get("IPTV_PRECHECK_TIMEOUT", "6"))
MIN_PUBLISH = 400          # hard floor, never publish below this
# How long a probe result stays trusted. A daily rebuild must re-check
# yesterday's "live" verdict within a day, otherwise channels that died
# yesterday stay in the playlist for the whole TTL and the list rots.
CACHE_TTL_DAYS = float(os.environ.get("IPTV_CACHE_TTL_DAYS", "1"))
# Failures are retried far sooner than successes. A failed probe is often a
# transient blip (timeout on a busy CDN edge), and a day-long blind spot
# silently removes good channels from the list.
CACHE_RETRY_DAYS = float(os.environ.get("IPTV_CACHE_RETRY_DAYS", "0.25"))
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

# Category order lives in categories.py (CANON) so the playlist order and the
# Xtream API's category order cannot drift apart.


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


# Schemes a Roku IPTV app can actually play. RTMP is the common offender:
# iptv-org carries a few RTMP entries that every player rejects, and they
# would otherwise show up in the list as permanently dead channels.
PLAYABLE_SCHEMES = ("http://", "https://")


# Country suffixes seen in iptv-org tvg-ids. A US-focused list should not
# carry Serbian, Dutch, Indian or Brazilian feeds wearing a "Sports" label.
NON_US_COUNTRIES = {
    "ar", "at", "au", "be", "bg", "br", "ca", "ch", "cl", "cn", "co", "cz",
    "de", "dk", "ee", "eg", "es", "fi", "fr", "gr", "hk", "hr", "hu", "id",
    "ie", "il", "in", "is", "it", "jp", "kr", "lt", "lv", "mx", "my", "nl",
    "no", "nz", "ph", "pl", "pt", "ro", "rs", "ru", "se", "sg", "si", "sk",
    "th", "tr", "tw", "ua", "uk", "vn", "za",
}
# A few of these are legitimately US-facing: keep them.
US_ALLOWED = {"ca"}


def tvg_country(tvg):
    """Extract the country code from an iptv-org tvg-id like 'CNN.us@SD'."""
    if not tvg:
        return ""
    base = tvg.split("@")[0]
    if "." not in base:
        return ""
    code = base.rsplit(".", 1)[-1].lower()
    return code if code.isalpha() and 2 <= len(code) <= 3 else ""


def variant_rank(tvg, info):
    """Prefer the best variant of a channel: US feed, then HD, then larger."""
    score = 0
    suffix = tvg.split("@")[1].lower() if "@" in tvg else ""
    if suffix in ("unitedstates", "us", "east", "west", "national"):
        score += 100
    if suffix in ("hd", "fhd"):
        score += 40
    elif suffix == "sd":
        score += 10
    m = re.search(r"\((\d{3,4})p\)", display_name(info))
    if m:
        score += min(int(m.group(1)), 2160) // 24
    return score


def channel_key(info):
    """Dedup key. The tvg-id base is the channel identity; the @SD/@HD suffix
    is a quality/region variant of the SAME channel, so it must not create
    a second row. Falls back to a normalized name when there is no tvg-id."""
    tvg = (field(info, "tvg-id") or "").strip()
    if tvg:
        return tvg.split("@")[0].lower()
    return "n:" + loose_key(display_name(info))


def rewrite_info(info):
    """Rewrite an EXTINF line onto the canonical category set.

    Delegates to categories.rewrite so the pipeline and the offline
    recategorize.py script cannot drift apart.
    """
    return cats.rewrite(info)


def rank_key(info):
    """Sort by canonical category order, then channel name."""
    return (cats.rank(field(info, "group-title")),
            normalize_name(display_name(info)))


# ---------------------------------------------------------------- probing

# Roku BrightScript codec support (all current models):
#   Video: H.264/AVC (Main/High, up to Level 4.1 for 1080p), H.265/HEVC (4K models)
#   Audio: AAC (LC/HE), AC3 (Dolby Digital), E-AC3, MP3, WMA
# Streams using other codecs play audio but show blank video on Roku.
ROKU_VIDEO_CODECS = {"h264", "avc1", "hev1", "hvc1", "hevc"}
ROKU_AUDIO_CODECS = {"aac", "ac3", "eac3", "mp3", "wma"}


def has_video(payload):
    streams = list(payload.get("streams") or [])
    for prog in payload.get("programs") or []:
        streams.extend(prog.get("streams") or [])
    for s in streams:
        if s.get("codec_type") == "video" or s.get("width"):
            return True
    return False


def roku_compatible(payload):
    """True when the stream uses codecs Roku's BrightScript player can decode.

    A stream with video in an unsupported codec (e.g. MPEG-2, AV1, VP9 on
    older Rokus) or audio in an unsupported codec plays sound but shows a
    blank screen — the #1 cause of "audio plays, video is blank."
    """
    streams = list(payload.get("streams") or [])
    for prog in payload.get("programs") or []:
        streams.extend(prog.get("streams") or [])

    video_ok = False
    audio_ok = False
    for s in streams:
        codec = (s.get("codec_name") or "").lower()
        if s.get("codec_type") == "video":
            if codec in ROKU_VIDEO_CODECS:
                video_ok = True
        elif s.get("codec_type") == "audio":
            if codec in ROKU_AUDIO_CODECS:
                audio_ok = True

    return video_ok and audio_ok


def precheck(url):
    """Cheap liveness filter before the expensive ffprobe.

    A range GET for the first bytes of the stream. Dead hosts, 404s and
    unresolvable DNS fail here in a couple of seconds instead of burning a
    full ffprobe timeout each. Returns False only when the host is clearly
    unreachable; True means "worth an ffprobe".
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Range": "bytes=0-2047"})
        with urllib.request.urlopen(req, timeout=PRECHECK_TIMEOUT) as resp:
            resp.read(2048)
            return True
    except urllib.error.HTTPError as exc:
        # 4xx/5xx on the head of the stream still means the host answered
        return exc.code not in (404, 410)
    except Exception:
        return False


def probe(url):
    """Full verification: does this URL actually carry a video stream?"""
    cmd = [FFPROBE, "-v", "error", "-user_agent", UA, "-rw_timeout", "8000000",
           "-print_format", "json", "-show_streams", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=PROBE_TIMEOUT,
                              check=False)
    except (subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0 and not proc.stdout:
        return False
    try:
        payload = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return False
    return has_video(payload) and roku_compatible(payload)


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
    merged = {}   # key -> dict(info, url, weight, name, tvg, alts)
    for src in SOURCES:
        try:
            text = fetch(src["url"])
        except Exception as exc:
            print("source %s FAILED: %s" % (src["id"], exc), flush=True)
            continue
        rows = parse_m3u(text)
        kept = 0
        dropped_country = 0
        for info, url in rows:
            name = display_name(info)
            group = field(info, "group-title")
            if not is_english(name, group):
                continue
            if not country_ok(info, name, src):
                continue
            if src.get("sports_only") and "sports" not in group.lower():
                continue
            if not url.lower().startswith(PLAYABLE_SCHEMES):
                # RTMP/RTSP/etc: no IPTV app can play these
                continue
            tvg = field(info, "tvg-id").strip()
            # A US-focused list should not carry foreign feeds that merely
            # carry a "Sports" or "Movies" group label.
            ccode = tvg_country(tvg)
            if (ccode and ccode not in US_ALLOWED
                    and ccode in NON_US_COUNTRIES):
                dropped_country += 1
                continue
            key = channel_key(info)
            cand = {"info": info, "url": url,
                    "weight": src["weight"],
                    "name": name, "tvg": tvg, "src": src["id"],
                    "variant": variant_rank(tvg, info)}
            prev = merged.get(key)
            if prev is None:
                merged[key] = cand
                kept += 1
                continue
            # Same channel seen again: keep the better variant.
            if cand["variant"] > prev["variant"]:
                cand["alts"] = prev.get("alts", []) + [prev["url"]]
                cand["alt_info"] = dict(prev.get("alt_info", {}))
                cand["alt_info"][prev["url"]] = prev["info"]
                merged[key] = cand
            else:
                prev.setdefault("alts", []).append(url)
                prev.setdefault("alt_info", {})[url] = info
        extra = " dropped_non_us=%s" % dropped_country if dropped_country else ""
        print("source %-12s rows=%-6s kept=%s%s"
              % (src["id"], len(rows), kept, extra), flush=True)

    print("merged unique channels:", len(merged), flush=True)

    # ---- verify (cache-aware)
    to_probe = []
    for key, rec in merged.items():
        h = url_hash(rec["url"])
        entry = probed.get(h)
        if entry and entry.get("ok") and (now - entry.get("ts", 0)) < CACHE_TTL_DAYS * 86400:
            continue
        if entry and not entry.get("ok") and (now - entry.get("ts", 0)) < CACHE_RETRY_DAYS * 86400:
            continue          # recently failed, don't hammer it
        to_probe.append((key, rec, h))

    print("probing %s channels (%s cached)" % (len(to_probe), len(merged) - len(to_probe)),
          flush=True)
    done = 0
    live = 0

    # Stage 1: cheap precheck. Dead hosts fail here in ~6s instead of costing
    # a full ffprobe timeout, which is the difference between a 4 minute run
    # and a 40 minute one.
    survivors = []
    with ThreadPoolExecutor(max_workers=WORKERS * 2) as pool:
        futs = {pool.submit(precheck, rec["url"]): (key, rec, h)
                for key, rec, h in to_probe}
        for fut in as_completed(futs):
            key, rec, h = futs[fut]
            done += 1
            if fut.result():
                survivors.append((key, rec, h))
            else:
                probed[h] = {"ok": False, "ts": now}
            if done % 100 == 0:
                print("  precheck %s/%s survivors=%s"
                      % (done, len(to_probe), len(survivors)), flush=True)
    print("precheck done: %s/%s reachable, %s dead"
          % (len(survivors), len(to_probe), len(to_probe) - len(survivors)), flush=True)

    # Stage 2: ffprobe the survivors for a real video stream.
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(probe, rec["url"]): (key, rec, h)
                for key, rec, h in survivors}
        for fut in as_completed(futs):
            key, rec, h = futs[fut]
            ok = fut.result()
            probed[h] = {"ok": ok, "ts": now}
            done += 1
            if ok:
                live += 1
            if done % 50 == 0:
                print("  ffprobe %s/%s live=%s" % (done, len(survivors), live),
                      flush=True)

    # ---- failover: a channel whose primary variant died may still have a
    # live alternate URL from another source. Probe those before giving up.
    dead = [(k, r) for k, r in merged.items()
            if not (probed.get(url_hash(r["url"])) or {}).get("ok")]
    alts = [(k, r, a) for k, r in dead for a in (r.get("alts") or [])]
    if alts:
        print("failover: %s dead primaries, %s alternate URLs to try"
              % (len(dead), len(alts)), flush=True)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {pool.submit(probe, a): (k, r, a) for k, r, a in alts}
            for fut in as_completed(futs):
                k, r, a = futs[fut]
                probed[url_hash(a)] = {"ok": fut.result(), "ts": now}
        recovered = 0
        for k, r in dead:
            for a in (r.get("alts") or []):
                if (probed.get(url_hash(a)) or {}).get("ok"):
                    r["url"] = a
                    # keep the alternate's own EXTINF so the tvg-id, logo and
                    # group stay consistent with the URL we are publishing
                    alt_info = r.get("alt_info", {}).get(a)
                    if alt_info:
                        r["info"] = alt_info
                    recovered += 1
                    break
        print("failover recovered %s channels" % recovered, flush=True)

    # ---- assemble
    rows = []
    for key, rec in merged.items():
        h = url_hash(rec["url"])
        entry = probed.get(h)
        if not entry or not entry.get("ok"):
            continue
        rows.append((rewrite_info(rec["info"]), rec["url"]))
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
