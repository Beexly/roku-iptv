"""Rewrite existing .m3u files onto the canonical category set, in place.

The pipeline applies categories.py during a full rebuild. This script applies
the same rewrite to files that already exist, so a playlist can be fixed
without re-fetching and re-probing 1,400 streams. Backs up to <file>.bak once.

Usage:
    python recategorize.py tv.m3u verified.m3u vod.m3u
"""

import os
import re
import sys

import categories as cats

EXTINF = "#EXTINF"
_GROUP = re.compile(r'group-title="([^"]*)"')


def group_of(info):
    """Return the group-title attribute of an EXTINF line."""
    match = _GROUP.search(info)
    return match.group(1) if match else ""


def split_entries(lines):
    """Yield (extinf_line, [following non-EXTINF lines]) preserving order."""
    pending = None
    trailing = []
    for raw in lines:
        if raw.startswith(EXTINF):
            if pending is not None:
                yield pending, trailing
            pending = raw
            trailing = []
        elif pending is None:
            continue          # #EXTM3U and stray comments before the first entry
        elif raw.strip():
            trailing.append(raw)
    if pending is not None:
        yield pending, trailing


def rewrite(path):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        lines = fh.read().split("\n")
    if lines and lines[0].startswith("#EXTM3U"):
        header, body = lines[0], lines[1:]
    else:
        header, body = "#EXTM3U", lines

    entries = []
    changed = 0
    for info, trailing in split_entries(body):
        new_info = cats.rewrite(info)
        if new_info != info:
            changed += 1
        entries.append((new_info, trailing))
    total = len(entries)

    # The app lists categories in first-seen order, so the file order IS the
    # menu order. Sort by the canonical rank, then by name within a category.
    entries.sort(key=lambda e: (cats.rank(group_of(e[0])), e[0].lower()))

    out = [header]
    for info, trailing in entries:
        out.append(info)
        out.extend(trailing)
    text = "\n".join(line for line in out if line is not None)
    text = text.rstrip("\n") + "\n"

    backup = path + ".bak"
    if not os.path.exists(backup):
        with open(backup, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return total, changed


def main(argv):
    targets = argv[1:] or ["tv.m3u"]
    for target in targets:
        if not os.path.isfile(target):
            print("skip %s (missing)" % target)
            continue
        total, changed = rewrite(target)
        print("%s: %s entries, %s rewritten" % (target, total, changed))


if __name__ == "__main__":
    main(sys.argv)
