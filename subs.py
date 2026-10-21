"""Issue and revoke private playlist URLs for paying subscribers.

Only the public-domain catalogue (vod.m3u: archive.org films and classic TV)
is sold. The live channel list is not part of any paid tier - it carries
public restreams of rights-protected networks, and charging for it would be
commercial infringement, not a business.

How it works:
  subscribers.json  -> {token: {name, plan, active, since}}
  subs/<token>.m3u  -> that subscriber's copy of the catalogue

Tokens are unguessable and a revoked token stops resolving on the next build.
This is obscurity plus revocation, not DRM: a subscriber can always copy a
file they can read. It is sized for family-scale (tens of subscribers), which
is the honest scope. Do not sell it as protection.

Usage:
  python subs.py add "Dana"            # prints the URL to send her
  python subs.py revoke <token>
  python subs.py list
  python subs.py build                 # regenerate subs/ (CI does this)
"""

import hashlib
import json
import os
import secrets
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(ROOT, "subscribers.json")
SUBS_DIR = os.path.join(ROOT, "subs")
VOD = os.path.join(ROOT, "vod.m3u")

BASE = "https://beexly.github.io/roku-iptv/subs/%s.m3u"


def load():
    try:
        with open(REGISTRY, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save(data):
    tmp = REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, REGISTRY)


def add(name, plan="monthly"):
    data = load()
    token = secrets.token_hex(8)
    data[token] = {
        "name": name,
        "plan": plan,
        "active": True,
        "since": time.strftime("%Y-%m-%d"),
    }
    save(data)
    build()
    print("subscriber: %s" % name)
    print("token:      %s" % token)
    print("playlist:   %s" % (BASE % token))
    return token


def revoke(token):
    data = load()
    for key in list(data):
        if key.startswith(token):
            data[key]["active"] = False
            save(data)
            build()
            print("revoked %s (%s)" % (key, data[key]["name"]))
            return
    print("no subscriber matches %s" % token)


def listing():
    data = load()
    if not data:
        print("no subscribers")
        return
    for token, row in sorted(data.items(), key=lambda kv: kv[1]["name"]):
        print("%-20s %-8s %-9s %s  %s"
              % (row["name"], row["plan"],
                 "active" if row["active"] else "revoked",
                 row["since"], BASE % token))


def build():
    """Write one playlist per active subscriber. Called by CI every build."""
    if not os.path.isfile(VOD):
        print("no vod.m3u - nothing to issue")
        return
    with open(VOD, "r", encoding="utf-8", errors="replace") as fh:
        catalogue = fh.read()
    os.makedirs(SUBS_DIR, exist_ok=True)
    data = load()
    written = 0
    for token, row in data.items():
        if not row.get("active"):
            continue
        path = os.path.join(SUBS_DIR, "%s.m3u" % token)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(catalogue)
        # A fingerprint proves the file is the catalogue that was published,
        # so a stale playlist from a previous month is visible, not silent.
        digest = hashlib.sha256(catalogue.encode("utf-8")).hexdigest()[:12]
        with open(path + ".sha", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(digest + "\n")
        written += 1
    # Drop files for tokens that no longer exist or are revoked.
    keep = {"%s.m3u" % t for t, r in data.items() if r.get("active")}
    keep |= {"%s.m3u.sha" % t for t, r in data.items() if r.get("active")}
    for name in os.listdir(SUBS_DIR):
        if name not in keep:
            os.remove(os.path.join(SUBS_DIR, name))
    print("issued %s playlist(s)" % written)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "add":
        if len(argv) < 3:
            raise SystemExit('usage: python subs.py add "Name" [monthly|annual]')
        add(argv[2], argv[3] if len(argv) > 3 else "monthly")
    elif cmd == "revoke":
        if len(argv) < 3:
            raise SystemExit("usage: python subs.py revoke <token>")
        revoke(argv[2])
    elif cmd == "list":
        listing()
    elif cmd == "build":
        build()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
