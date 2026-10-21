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


# epg.pw appends a region/feed qualifier that our tvg-ids carry instead:
#   epg.pw "Bravo HD"            vs ours "Bravo.us@East"
#   epg.pw "CNN HD"              vs ours "CNN.us@SD"
#   epg.pw "USA Network HD (Pacific)" vs ours "USANetwork.us@SD"
#   epg.pw "ABC National Feed Pacific"  vs ours "ABC.us@SD"
# Dropping these qualifiers lets the two sides meet on the channel name.
# Without it the guide matched only 11% of channels.
QUALIFIER = re.compile(
    r"\b(?:national feed|local feed|feed|pacific|east coast|west coast|"
    r"eastern|western|mountain|central|atlantic|pacific time|eastern time|"
    r"mountain time|central time|latina|español|espanol|english|latam|"
    r"direct kick|uhd|hd|sd|4k|fhd|feeds?)\b", re.I)


def strip_qualifiers(name):
    s = QUALIFIER.sub(" ", name or "")
    s = re.sub(r"[(\[][^)\]]*[)\]]", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())


def loose_stripped(name):
    return "".join(w for w in strip_qualifiers(name).split() if w not in NOISE)


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
    want_strip, want_strip_loose = {}, {}
    for tvg, name in tvgs.items():
        k = norm(name)
        if k:
            want_norm.setdefault(k, tvg)
        lk = loose(name)
        if lk:
            want_loose.setdefault(lk, tvg)
        sk = strip_qualifiers(name)
        if sk:
            want_strip.setdefault(sk, tvg)
        sl = loose_stripped(name)
        if sl:
            want_strip_loose.setdefault(sl, tvg)
        # The tvg-id carries the channel name too ("Bravo.us@East" -> "Bravo"),
        # and epg.pw sometimes labels a channel differently from the playlist
        # ("Bravo HD"). Index both spellings so the guide matches more often.
        base = tvg.split("@")[0].split(".")[0]
        if base and base != name:
            for table, fn in ((want_norm, norm), (want_loose, loose),
                              (want_strip, strip_qualifiers),
                              (want_strip_loose, loose_stripped)):
                bk = fn(base)
                if bk:
                    table.setdefault(bk, tvg)
    print("playlist tvg-ids: %s (norm=%s loose=%s strip=%s)"
          % (len(tvgs), len(want_norm), len(want_loose), len(want_strip)),
          flush=True)

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
    # Four passes, strictest first, so a channel is never stolen by a looser
    # match:
    #   A exact normalized name
    #   B loose name (filler words removed)
    #   C name with region/feed qualifiers stripped ("USA Network HD (Pacific)")
    #   D loose name with qualifiers stripped
    # A tvg-id is claimed by the first pass that matches it.
    id_map = {}
    claimed = set()

    def take(eid, tvg):
        if tvg and tvg not in claimed:
            id_map[eid] = tvg
            claimed.add(tvg)

    for eid, name in epg_name.items():
        take(eid, want_norm.get(norm(name)))
    a = len(id_map)
    for eid, name in epg_name.items():
        if eid not in id_map:
            take(eid, want_loose.get(loose(name)))
    b = len(id_map) - a
    for eid, name in epg_name.items():
        if eid not in id_map:
            take(eid, want_strip.get(strip_qualifiers(name)))
    c = len(id_map) - a - b
    for eid, name in epg_name.items():
        if eid not in id_map:
            take(eid, want_strip_loose.get(loose_stripped(name)))
    d = len(id_map) - a - b - c
    print("matched: %s channels (exact=%s loose=%s stripped=%s stripped-loose=%s)"
          % (len(id_map), a, b, c, d), flush=True)
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
