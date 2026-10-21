"""
Full local refresh: rebuild -> EPG -> VOD -> setup card -> publish.

Run daily rather than weekly: free stream rot is the dominant failure mode, and
the probe cache makes repeat runs cheap (only changed channels get re-probed).

Order matters:
  pipeline.py   -> writes tv.m3u locally
  build_epg.py  -> remaps the guide onto tv.m3u's tvg-ids
  build_vod.py  -> writes vod.m3u (movies + series) and verifies each entry plays
  build_setup.py -> writes dist/setup.html with the QR code
  publish.py    -> triggers the CI publish and verifies the published URLs

The iptvactivation.com portal is gone: it is a paid, Smarters-only activation
service, and the Roku app is pointed straight at the public Pages URL instead.
There is nothing to repoint, so there is no portal step here.

Every step is checked. A failed step stops the chain so a broken playlist is
never published.
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LOG = os.path.join(ROOT, "refresh.log")

STEPS = [
    ("pipeline", "pipeline.py", 1800),
    ("epg", "build_epg.py", 900),
    ("vod", "build_vod.py", 3600),
    ("setup", "build_setup.py", 300),
    ("publish", "publish.py", 2700),
]


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def run(name, script, timeout):
    script_path = os.path.join(ROOT, script)
    log("START %s (%s)" % (name, script))
    started = time.time()
    try:
        proc = subprocess.run([PY, script_path], cwd=ROOT, capture_output=True,
                              timeout=timeout, text=True, errors="replace")
    except subprocess.TimeoutExpired:
        log("FAIL  %s timed out after %ss" % (name, timeout))
        return False
    took = time.time() - started
    out = (proc.stdout or "").strip().splitlines()
    for line in out[-14:]:
        log("      | %s" % line)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        for line in err[-8:]:
            log("      ! %s" % line)
        log("FAIL  %s exit=%s (%.0fs)" % (name, proc.returncode, took))
        return False
    log("OK    %s (%.0fs)" % (name, took))
    return True


def main():
    for name, script, timeout in STEPS:
        if not run(name, script, timeout):
            log("aborting chain at %s" % name)
            return 1
    log("refresh complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
