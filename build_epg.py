"""
Remap the epg.pw US XMLTV guide onto the tvg-ids of the live playlist.

epg.pw uses numeric channel ids with zero overlap with iptv-org tvg-ids, so the
guide must be matched by normalized display name and re-emitted with playlist ids.

Single streaming pass: every <channel> block and every <programme> element is
rewritten with the matched tvg-id. Unmatched content is dropped, so the guide
stays small. XMLTV lines are indented, so every line is stripped before matching.
"""

import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
TV = os.path.join(ROOT, "tv.m3u")
EPG_IN = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\Users\Garrett\AppData\Local\hermes\cache\scratch\epg_US.xml"
EPG_OUT = os.path.join(ROOT, "epg.xml")

NOISE = {"the", "tv", "channel", "network", "us", "usa", "uk", "hd", "of", "sd"}
CH_RE = re.compile(r'<channel\s+id="([^"]+)"')
PROG_RE = re.compile(r'<programme\b[^>]*\bchannel="([^"]+)"')


def strip_accents(text):
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def norm(name):
    s = strip_accents(name).lower()
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\((?:[^)]*\b(?:p|hd|sd|uhd|4k|fhd)\b[^)]*)\)", " ", s)
    s = re.sub(r"\b(?:uhd|fhd|hd|sd|4k|8k|1080p|720p|480p|360p|hdtv)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def loose(name):
    return "".join(w for w in norm(name).split() if w not in NOISE)


def playlist_tvgs():
    """tvg-id -> display name, from the live playlist."""
    rows, pending = [], None
    with open(TV, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#EXTINF"):
                pending = line
            elif line.startswith("#"):
                continue
            elif pending:
                rows.append(pending)
                pending = None
    out = {}
    for info in rows:
        m = re.search(r'tvg-id="([^"]*)"', info)
        if not m:
            continue
        tvg = m.group(1).strip()
        if tvg:
            out.setdefault(tvg, info.rsplit(",", 1)[-1].strip())
    return out


def main():
    tvgs = playlist_tvgs()
    want_norm, want_loose = {}, {}
    for tvg, name in tvgs.items():
        k = norm(name)
        if k:
            want_norm.setdefault(k, tvg)
        lk = loose(name)
        if lk:
            want_loose.setdefault(lk, tvg)
        # The tvg-id carries the channel name too ("Bravo.us@East" -> "Bravo"),
        # and epg.pw sometimes labels a channel differently from the playlist
        # ("Bravo HD"). Index both spellings so the guide matches more often.
        base = tvg.split("@")[0].split(".")[0]
        if base and base != name:
            bk = norm(base)
            if bk:
                want_norm.setdefault(bk, tvg)
            bl = loose(base)
            if bl:
                want_loose.setdefault(bl, tvg)
    print("playlist tvg-ids: %s (norm=%s loose=%s)"
          % (len(tvgs), len(want_norm), len(want_loose)), flush=True)

    # ---- pass 1: read EPG channel id -> display name
    epg_name = {}
    cur = None
    with open(EPG_IN, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            m = CH_RE.match(line)
            if m:
                cur = m.group(1)
                continue
            if cur and line.startswith("<display-name"):
                dn = re.search(r">([^<]+)<", line)
                if dn:
                    epg_name.setdefault(cur, dn.group(1).strip())
                cur = None
                continue
            if line.startswith("</channel"):
                cur = None
    print("epg channels: %s" % len(epg_name), flush=True)

    # ---- match: epg numeric id -> playlist tvg-id
    #
    # Two passes. Pass A takes only exact normalized-name matches, so a
    # channel never gets stolen by a looser match. Pass B then fills the
    # remaining channels with loose matches, and skips any tvg-id that a
    # pass-A match already claimed.
    id_map = {}
    claimed = set()
    for eid, name in epg_name.items():
        tvg = want_norm.get(norm(name))
        if tvg and tvg not in claimed:
            id_map[eid] = tvg
            claimed.add(tvg)
    exact = len(id_map)
    for eid, name in epg_name.items():
        if eid in id_map:
            continue
        tvg = want_loose.get(loose(name))
        if tvg and tvg not in claimed:
            id_map[eid] = tvg
            claimed.add(tvg)
    print("matched: %s channels (%s exact, %s loose)"
          % (len(id_map), exact, len(id_map) - exact), flush=True)
    if not id_map:
        raise SystemExit("no matches - refusing to write an empty guide")

    # ---- pass 2: emit remapped XMLTV
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<tv>"]
    kept_ch = 0
    kept_prog = 0
    in_channel = False
    in_prog = False
    with open(EPG_IN, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line == "</tv>":
                continue
            m = CH_RE.match(line)
            if m:
                tvg = id_map.get(m.group(1))
                in_channel = tvg is not None
                if in_channel:
                    out.append('  <channel id="%s">' % tvg)
                    kept_ch += 1
                continue
            if line.startswith("</channel>"):
                if in_channel:
                    out.append("  </channel>")
                in_channel = False
                continue
            if in_channel:
                out.append(line)
                continue
            m = PROG_RE.search(line)
            if m:
                eid = m.group(1)
                tvg = id_map.get(eid)
                if tvg:
                    out.append(line.replace('channel="%s"' % eid,
                                            'channel="%s"' % tvg, 1))
                    kept_prog += 1
                    in_prog = True
                else:
                    in_prog = False
                continue
            if in_prog:
                out.append(line)
                if line.startswith("</programme>"):
                    in_prog = False
    out.append("</tv>")

    tmp = EPG_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    os.replace(tmp, EPG_OUT)
    print("emitted channels=%s programmes=%s -> %s (%s bytes)"
          % (kept_ch, kept_prog, EPG_OUT, os.path.getsize(EPG_OUT)), flush=True)


if __name__ == "__main__":
    main()
