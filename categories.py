"""Canonical channel categories for the published playlists.

The upstream feeds (iptv-org, Free-TV, HerbertHe) label channels with ~70
overlapping groups — "General", "Legislative", "Classic", and compound labels
like "Education;Kids". That is fine as machine metadata and awful as an app
menu: a viewer opening the playlist sees 68 categories, most holding under 10
channels, with the biggest one called "General".

This module collapses every source label into the fourteen published
categories, in the owner's display order, and reclassifies the catch-all
buckets by channel name and tvg-id country — so "ESPN 8" does not sit in "Other"
just because its feed said "Undefined", and a Bahraini feed does not sit in
"Sports" just because it carries a Sports label.

Rules, in order:
  1. A non-US tvg-id country code wins: that channel is International.
  2. Take the FIRST token of a compound group ("Education;Kids" -> "Education").
  3. Explicit group map wins ("Sports" -> Sports, "Legislative" -> News).
  4. Placeholder groups (General/Undefined/Other/empty) fall through to a
     call-sign test, then a name-keyword pass.
  5. Anything still unmatched lands in "Other" — never dropped.
"""

import re

# Display order, exactly as published. The app renders categories in first-seen
# order, so this list is the order a viewer scrolls through.
CANON = (
    "News",
    "Sports",
    "Movies",
    "Kids",
    "Entertainment",
    "Documentary",
    "Music",
    "Lifestyle",
    "Shopping",
    "Weather",
    "International",
    "Local",
    "Religious",
    "Other",
)

# Source label (lowercase, first token only) -> canonical category.
# A value of None means "placeholder, classify by channel name instead".
GROUP_MAP = {
    "news": "News",
    "legislative": "News",
    "politics": "News",
    "business": "News",
    "sports": "Sports",
    "outdoor": "Sports",
    "movies": "Movies",
    "films": "Movies",
    "film": "Movies",
    "vod": "Movies",
    "classic": "Movies",
    # The live playlist has no Series shelf - a live "Series" feed is a rerun
    # channel, not a TV series. The VOD list is different: there, Films and
    # Series are genuinely different shelves (a film vs an episode), and the
    # player offers a separate tab for each. canonical() is told which list
    # it is classifying via the `series_shelf` flag, so the same map serves
    # both without flattening the VOD library.
    "series": "Movies",
    "kids": "Kids",
    "animation": "Kids",
    "family": "Kids",
    "entertainment": "Entertainment",
    "comedy": "Entertainment",
    "documentary": "Documentary",
    "culture": "Documentary",
    # No Education shelf: informational channels sit with documentary.
    "education": "Documentary",
    "music": "Music",
    "relax": "Music",
    "lifestyle": "Lifestyle",
    "cooking": "Lifestyle",
    "travel": "Lifestyle",
    "auto": "Lifestyle",
    "shop": "Shopping",
    "weather": "Weather",
    "religious": "Religious",
    "faith": "Religious",
    "religion": "Religious",
    "local": "Local",
    "government": "Local",
    # placeholders -> classify by name
    "general": None,
    "undefined": None,
    "generic": None,
    "other": None,
    "x_other": None,
    "": None,
}

# (regex, category). First match wins, so specific brands sit above generic
# words: "Fox Sports" must land in Sports, not News.
KEYWORDS = [
    (re.compile(r"\b(espn|nfl|nba|mlb|nhl|ncaa|ufc|wwe|golf|tennis|soccer|"
                r"football|baseball|hockey|basketball|motogp|nascar|indycar|"
                r"racing|boxing|poker|sports?|athletic|kickboxing|snooker|"
                r"lacrosse|strongman|bowling|sec|big.?ten|acc|pac.?12|"
                r"conference)\b"), "Sports"),
    (re.compile(r"\b(news|newschannel|cnn|msnbc|newsmax|c.?span|"
                r"senate|congress|legislat|briefing|headlines)\b"), "News"),
    (re.compile(r"\b(weathernation|weatherspy|weather|meteorolog)\b"), "Weather"),
    (re.compile(r"\b(qvc|hsn|shop|shopping|jewelry|jewellery|auction|"
                r"gem|telemarket|infomercial)\b"), "Shopping"),
    (re.compile(r"\b(cartoon|toon|nick|nickelodeon|disney.?jr|baby|"
                r"kids?|children|junior|pbs.?kids)\b"), "Kids"),
    (re.compile(r"\b(documentary|docu|explore|discovery|history|nature|"
                r"wildlife|science|smithsonian)\b"), "Documentary"),
    (re.compile(r"\b(music|mtv|vevo|hits|radio|rock|jazz|classical)\b"),
     "Music"),
    (re.compile(r"\b(church|god|jesus|christ|gospel|faith|islam|quran|"
                r"ministr|worship|bible|saint|catholic|buddhist|jewish)\b"),
     "Religious"),
    # Local affiliates and public-access channels arrive labelled "General" and
    # would otherwise swamp the catch-all bucket.
    (re.compile(r"\b(access|public.?access|community|peg|city|county|"
                r"school.?district|municipal|civic|gov)\b"), "Local"),
    (re.compile(r"\bchannel.?[0-9]{1,3}\b"), "Local"),
    (re.compile(r"\b(cook|food|kitchen|travel|home|garden|auto|car|motor|"
                r"diy|fashion|beauty|real.?estate|design)\b"), "Lifestyle"),
    (re.compile(r"\b(internacional|international|worldwide|world|global|"
                r"africa|asia|europe|europa|arab|india|china|korea|japan|"
                r"latino|hispanic|mexico|filipino|vietnam|persian|turkish)\b"),
     "International"),
    (re.compile(r"\b(movie|film|cinema|theater|theatre)\b"), "Movies"),
    (re.compile(r"\b(series|sitcom|episodes?)\b"), "Movies"),
    (re.compile(r"\b(comedy|funny|prank|stand.?up)\b"), "Entertainment"),
]

# US broadcast call signs: "KAAL", "KIIO-LD", "WATC-DT". Case-sensitive on
# purpose — lowercasing turns ordinary words into false matches. Only consulted
# for channels whose feed label is a placeholder, which keeps "KTV Sport" (a
# real Sports channel) out of Local.
_CALLSIGN = re.compile(r"\b(?:K|W)[A-Z]{3}[A-Z]?(?:-(?:LD|CD|DT|TV))?\b")

# Country code embedded in an iptv-org tvg-id: "ESPN.us@SD", "Arryadia.ma".
_COUNTRY = re.compile(r"\.([a-z]{2})(?:@|$)")

PLACEHOLDERS = {"general", "undefined", "generic", "other", "x_other", ""}

US_ALIASES = {"us", "usa"}


def first_group(group):
    """Compound labels are joined with ';' — keep only the first token."""
    return (group or "").split(";")[0].strip()


def country_code(tvg_id):
    """Return the country code from a tvg-id, or '' when it carries none."""
    match = _COUNTRY.search((tvg_id or "").strip().lower())
    return match.group(1) if match else ""


def canonical(group, name="", tvg_id="", series_shelf=False):
    """Map a source group label + channel name + tvg-id to one category.

    `series_shelf=True` keeps "Series" as its own category. Use it for the
    VOD list, where a film and an episode are genuinely different things.
    The live playlist leaves it off, so a live "Series" rerun channel folds
    into Movies with the rest of the movie channels.
    """
    code = country_code(tvg_id)
    if code and code not in US_ALIASES:
        return "International"

    key = first_group(group).lower()
    if series_shelf and key in ("series", "films", "film", "movies", "movie"):
        return {"series": "Series", "films": "Films", "film": "Films",
                "movies": "Films", "movie": "Films"}[key]
    mapped = GROUP_MAP.get(key)
    if mapped:
        return mapped

    label = name or ""
    if _CALLSIGN.search(label):
        return "Local"
    haystack = ("%s %s" % (label, key)).lower()
    for pattern, category in KEYWORDS:
        if pattern.search(haystack):
            return category

    # A channel the feed simply labelled "General" is general entertainment;
    # only genuinely unlabelled material stays in the catch-all bucket.
    if key in PLACEHOLDERS and key != "":
        return "Entertainment"
    return "Other"


def rank(category):
    """Sort key so the playlist is written in CANON order."""
    try:
        return CANON.index(category)
    except ValueError:
        return len(CANON)


# Channels a viewer is most likely to look for first. Within a category these
# are listed before everything else, so "Sports" opens with ESPN rather than
# with 30A Golf Kingdom. Matched as whole words against the display name.
BRANDS = (
    "espn", "espn2", "espnu", "fox sports", "fs1", "fs2", "cbs sports",
    "nfl network", "nba tv", "mlb network", "nhl network", "golf channel",
    "tennis channel", "big ten", "sec network", "acc network",
    "cnn", "fox news", "msnbc", "nbc news", "abc news", "cbs news",
    "weather channel", "fox weather", "weathernation",
    "discovery", "history", "national geographic", "animal planet",
    "food network", "hgtv", "travel channel", "tlc",
    "cartoon network", "nickelodeon", "disney", "pbs kids", "boomerang",
    "mtv", "vh1", "cmt", "bet",
    "a&e", "usa network", "tnt", "tbs", "amc", "fx", "syfy", "bravo",
    "comedy central", "paramount", "freeform", "hallmark",
    "qvc", "hsn",
)


def prominence(name):
    """0 for a well-known network, 1 for everything else."""
    low = (name or "").lower()
    for brand in BRANDS:
        if brand in low:
            return 0
    return 1


def sort_key(info):
    """Playlist order: category, then big brands, then alphabetical.

    The app lists entries in file order, so this is the order a viewer sees.
    """
    group = _attr(info, "group-title")
    label = _label(info)
    return (rank(group), prominence(label), label.lower())


# Order for the VOD list. "Series" and "Films" are not in CANON (a live
# playlist has no Series shelf), so they are ranked explicitly here.
VOD_CANON = ("Films", "Series")


def vod_rank(category):
    """Sort key for the VOD playlist: Films first, then Series."""
    try:
        return VOD_CANON.index(category)
    except ValueError:
        return len(VOD_CANON)


# Upstream names carry quality tags and provenance warnings:
# "A&E (1080p)", "Adult Swim [Not 24/7;Geo-blocked]". They are noise in a
# channel list a viewer scrolls, and the EPG match normalizes them away anyway.
_NOISE = re.compile(
    r"\s*(?:\((?:[0-9]{3,4}[pi]|hd|sd|uhd|4k)\)|\[[^\]]*\])",
    re.IGNORECASE,
)

# The published list is US-only, so "ACTV (United States)" is redundant noise.
_COUNTRY_SUFFIX = re.compile(
    r"\s*\((?:United States|USA|US)\)(?=\s*(?:[0-9]{3,4}[pi]|HD|SD|UHD|4K)?\s*$)",
    re.IGNORECASE)


def clean_name(name):
    """Strip resolution tags and provenance brackets from a display name."""
    out = _NOISE.sub("", name or "")
    out = _COUNTRY_SUFFIX.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" -\u2013|")
    return out or (name or "").strip()


def _attr(info, name):
    match = re.search(r'%s="([^"]*)"' % name, info)
    return match.group(1) if match else ""


def _label(info):
    return info.rsplit(",", 1)[-1].strip()


def rewrite(info):
    """Rewrite one EXTINF line onto the canonical category set.

    Replaces the upstream group label with its canonical category and strips
    quality/provenance noise from the display name. tvg-id, tvg-logo and every
    other attribute are preserved verbatim so EPG matching and artwork keep
    working. Shared by pipeline.py and recategorize.py so there is exactly one
    implementation.
    """
    group = _attr(info, "group-title")
    name = _label(info)
    category = canonical(group, name, _attr(info, "tvg-id"))
    clean = clean_name(name)
    head = info.rsplit(",", 1)[0]
    head = re.sub(r'\s*group-title="[^"]*"', "", head).rstrip()
    return '%s group-title="%s",%s' % (head, category, clean)
