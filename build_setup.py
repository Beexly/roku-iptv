"""
Build the viewer setup card: dist/setup.html

One page the user opens on a phone (or scans from the TV) that carries:
  - the M3U URL as a copy-able line
  - the EPG URL as a separate copy-able line
  - a QR code of the M3U URL, inline SVG (no external assets, no CDN)
  - the app to install and the exact steps

The QR is the fast path: the TV's player has a "scan to add a playlist"
option, so scanning this from a phone that can see the screen is one step
instead of typing a long URL with a remote.

Also writes dist/u/<token>/setup.html equivalents when a token is supplied,
so per-viewer URLs are self-contained.
"""

import html
import os
import sys

import qrcode
import qrcode.image.svg

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BASE = os.environ.get("SITE_BASE", "https://beexly.github.io/roku-iptv")
M3U = BASE + "/tv.m3u"
VOD = BASE + "/vod.m3u"
EPG = BASE + "/epg.xml"

APP_NAME = "Xtream IPTV Player"
APP_ID = "814924"
APP_NOTE = ("Channel Store id %s. It is free. In its setup screen choose "
            "\"Add playlist\" and either scan the QR code or paste the URL."
            % APP_ID)


def qr_svg(data, box=10, border=2):
    """Inline SVG QR. Purely local - no image host, no tracking."""
    qr = qrcode.QRCode(box_size=box, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    import io
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def page(m3u_url, epg_url, extra_blocks=""):
    qr = qr_svg(m3u_url)
    # strip the XML declaration so the SVG can be inlined in HTML
    qr = qr.replace('<?xml version="1.0" standalone="yes"?>', "")
    qr = qr.replace("<svg ", '<svg role="img" aria-label="QR code for the playlist URL" ', 1)
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Roku IPTV - setup</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; padding: 24px 16px 48px; max-width: 720px; margin-inline: auto; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .sub {{ opacity: .75; margin: 0 0 28px; font-size: .95rem; }}
  h2 {{ font-size: 1.05rem; margin: 32px 0 10px; }}
  .url {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: .82rem; word-break: break-all; background: #8883;
          border: 1px solid #8885; border-radius: 8px; padding: 10px 12px; margin: 0 0 10px; }}
  .qr {{ display: block; width: min(320px, 80vw); height: auto; margin: 16px auto 8px;
         background: #fff; padding: 12px; border-radius: 12px; }}
  ol, ul {{ padding-left: 22px; }}
  li {{ margin: 6px 0; }}
  button {{ font: inherit; padding: 8px 14px; border-radius: 8px; border: 1px solid #8886;
            background: #8882; cursor: pointer; }}
  .note {{ opacity: .8; font-size: .88rem; }}
  footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #8884; opacity: .7; font-size: .85rem; }}
</style>
</head>
<body>
<h1>Your Roku IPTV playlist</h1>
<p class="sub">One playlist, rebuilt daily. No account, no subscription, no setup on a computer.</p>

<h2>1. Scan this on the TV</h2>
<p>The TV's player has a <strong>scan to add a playlist</strong> option. Point your phone's camera at the code and hand the phone the link, or type the URL by hand from the line below.</p>
<div class="qr">{qr}</div>
<p class="note">If the TV's scanner is on-screen, scan with any phone camera app first, then paste the link it opens into the TV.</p>

<h2>2. The playlist URL</h2>
<p class="url" id="m3u">{m3u}</p>
<button onclick="navigator.clipboard.writeText(document.getElementById('m3u').textContent)">Copy playlist URL</button>

<h2>3. The guide URL (optional)</h2>
<p class="note">Add this in the player's EPG / XMLTV setting if it has one. It is a separate field - not all players take a guide URL at all.</p>
<p class="url" id="epg">{epg}</p>
<button onclick="navigator.clipboard.writeText(document.getElementById('epg').textContent)">Copy guide URL</button>

<h2>4. The app</h2>
<p>Use <strong>{app_name}</strong> (Roku Channel Store). {app_note}</p>
<ol>
  <li>Install {app_name} from the Roku Channel Store.</li>
  <li>Open it and choose <strong>Add playlist</strong>.</li>
  <li>Scan the code above, or paste the playlist URL.</li>
  <li>Pick the live-TV categories you want and save. That is it.</li>
</ol>

{extra}
<footer>
  The playlist is rebuilt every day and published automatically, so the URL never changes and the
  channels keep refreshing on their own. Publicly-posted stream URLs and public-domain media;
  availability varies by broadcaster.
</footer>
</body>
</html>
""".format(qr=qr, m3u=html.escape(m3u_url), epg=html.escape(epg_url),
           app_name=html.escape(APP_NAME), app_note=html.escape(APP_NOTE),
           extra=extra_blocks)


def main():
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "setup.html")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page(M3U, EPG))
    print("wrote", out, os.path.getsize(out), "bytes")

    # a per-viewer card, if a token was supplied
    token = os.environ.get("VIEWER_TOKEN")
    if token:
        vdir = os.path.join(DIST, "u", token)
        os.makedirs(vdir, exist_ok=True)
        vout = os.path.join(vdir, "setup.html")
        with open(vout, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(page(BASE + "/u/%s/tv.m3u" % token, BASE + "/u/%s/epg.xml" % token))
        print("wrote", vout, os.path.getsize(vout), "bytes")

    # robots: this is a personal setup page, not a site to index
    with open(os.path.join(DIST, "robots.txt"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write("User-agent: *\nDisallow: /\n")
    print("wrote", os.path.join(DIST, "robots.txt"))


if __name__ == "__main__":
    main()
