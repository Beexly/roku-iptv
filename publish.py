"""
Publish the verified playlist.

Publishing is done by GitHub Actions: the CI job builds the playlists, uploads
them as a Pages artifact and deploys from the artifact. Build output is never
committed to the branch - committing it caused rebase conflicts in generated
files and raced with the CI run.

This script is the local convenience entry point. It:
  1. checks the local build output is sane
  2. dispatches the refresh workflow
  3. waits for it to finish
  4. verifies the published URLs

The laptop is not required for publishing - the scheduled CI run does the same
thing on its own.

Usage:
  python publish.py            # trigger CI and wait, then verify
  python publish.py --local    # just verify the current published URLs
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
TV = os.path.join(ROOT, "tv.m3u")
VOD = os.path.join(ROOT, "vod.m3u")
STATE = os.path.join(ROOT, "publish_state.json")

OWNER = "Beexly"
REPO = "roku-iptv"
# GitHub Pages is the published URL. jsDelivr is a fallback only: it also
# serves the right MIME but caches branch refs for 12 hours (s-maxage=43200)
# and served a stale playlist right after a publish.
PAGES = "https://%s.github.io/%s" % (OWNER, REPO)
JSDELIVR = "https://cdn.jsdelivr.net/gh/%s/%s@main" % (OWNER, REPO)
MIN_PUBLISH = 400
MIN_VOD = 50


def count_channels(path):
    if not os.path.isfile(path):
        return 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if line.startswith("#EXTINF"))


def gh(args):
    proc = subprocess.run(["gh"] + args, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("gh %s failed: %s"
                           % (args[1] if len(args) > 1 else args[0],
                              proc.stderr.decode("utf-8", "replace")[:300]))
    return proc.stdout.decode("utf-8", "replace")


def latest_run_id():
    out = gh(["run", "list", "--repo", "%s/%s" % (OWNER, REPO), "--workflow",
              "refresh.yml", "--limit", "1", "--json", "databaseId"])
    try:
        return json.loads(out)[0]["databaseId"]
    except (ValueError, KeyError, IndexError):
        return None


def wait_for_run(run_id, timeout=3000):
    """Poll until the run finishes. Returns (status, conclusion)."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        out = gh(["run", "view", str(run_id), "--repo", "%s/%s" % (OWNER, REPO),
                  "--json", "status,conclusion"])
        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            time.sleep(10)
            continue
        state = "%s/%s" % (d.get("status"), d.get("conclusion"))
        if state != last:
            print("  run %s: %s" % (run_id, state), flush=True)
            last = state
        if d.get("status") == "completed":
            return d.get("status"), d.get("conclusion")
        time.sleep(15)
    return "timeout", None


def fetch(url, limit=None):
    """Fetch a URL. `limit` caps the body for playlist files; the EPG is
    several MB, so it must be fetched whole or the XML will not parse."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        if limit:
            return resp.status, (resp.headers.get("Content-Type") or ""), resp.read(limit)
        return resp.status, (resp.headers.get("Content-Type") or ""), resp.read()


def verify_published():
    """Check the published URLs. Returns True when everything passes."""
    ok = True
    for url, minimum in ((PAGES + "/tv.m3u", MIN_PUBLISH),
                         (PAGES + "/vod.m3u", MIN_VOD)):
        try:
            code, ctype, body = fetch(url, limit=400000)
        except Exception as exc:
            print("  %s -> FETCH FAILED %s" % (url, exc))
            ok = False
            continue
        n = body.count(b"#EXTINF")
        good = code == 200 and "mpegurl" in ctype.lower() and n >= minimum
        print("  %s -> http %s %s channels=%s %s"
              % (url, code, ctype, n, "OK" if good else "FAIL"))
        if not good:
            ok = False
    try:
        code, ctype, body = fetch(PAGES + "/epg.xml")
        import xml.etree.ElementTree as ET
        root = ET.fromstring(body)
        nch = len(root.findall("channel"))
        npr = len(root.findall("programme"))
        good = code == 200 and nch > 0
        print("  %s/epg.xml -> http %s %s channels=%s programmes=%s %s"
              % (PAGES, code, ctype, nch, npr, "OK" if good else "FAIL"))
        if not good:
            ok = False
    except Exception as exc:
        print("  epg.xml -> FAILED %s" % exc)
        ok = False
    try:
        code, _, body = fetch(PAGES + "/setup.html")
        has = b"<svg" in body and b'id="m3u"' in body
        good = code == 200 and has
        print("  %s/setup.html -> http %s qr=%s %s"
              % (PAGES, code, has, "OK" if good else "FAIL"))
        if not good:
            ok = False
    except Exception as exc:
        print("  setup.html -> FAILED %s" % exc)
        ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true",
                    help="verify the published URLs without triggering CI")
    ap.add_argument("--no-wait", action="store_true",
                    help="trigger CI but do not wait for it")
    args = ap.parse_args()

    if args.local:
        print("verifying published URLs")
        return 0 if verify_published() else 1

    n = count_channels(TV)
    v = count_channels(VOD)
    print("local build: tv.m3u=%s vod.m3u=%s" % (n, v))
    if n < MIN_PUBLISH:
        raise SystemExit("ABORT: local tv.m3u has %s channels (< %s). "
                         "Build locally first." % (n, MIN_PUBLISH))

    print("dispatching refresh workflow")
    gh(["workflow", "run", "refresh.yml", "--repo", "%s/%s" % (OWNER, REPO)])
    time.sleep(5)
    run_id = latest_run_id()
    print("run id:", run_id)
    if args.no_wait or not run_id:
        return 0

    status, conclusion = wait_for_run(run_id)
    print("ci: %s %s" % (status, conclusion))
    if conclusion != "success":
        print("CI did not succeed - nothing was published.")
        return 1

    print("verifying published URLs")
    if not verify_published():
        return 1

    state = {
        "public_url": PAGES + "/tv.m3u",
        "backup_url": JSDELIVR + "/tv.m3u",
        "pages_url": PAGES + "/tv.m3u",
        "channels": n,
        "vod_entries": v,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    print("\npublished:", state["public_url"])
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
