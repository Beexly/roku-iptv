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
PLAYER = BASE + "/player.html"

APP_NAME = "Xtream IPTV Player"
APP_ID = "814924"
# The app's own listing says it plays "streaming URLs and Xtream Codes API
# credentials". Its "scan to add a playlist" QR opens the vendor's website
# (which is account-gated), so the URL field is the path that needs no
# account and no purchase.
APP_NOTE = ("Channel Store id %s. It is free and its listing says it plays "
            "streaming URLs. In the app go to Settings, add a playlist, and "
            "choose the M3U URL option - do NOT use the scan QR, that opens "
            "the vendor's account page." % APP_ID)


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
    qr_player = qr_svg(PLAYER)
    # strip the XML declaration so the SVG can be inlined in HTML
    qr = qr.replace('<?xml version="1.0" standalone="yes"?>', "")
    qr = qr.replace("<svg ", '<svg role="img" aria-label="QR code for the playlist URL" ', 1)
    qr_player = qr_player.replace('<?xml version="1.0" standalone="yes"?>', "")
    qr_player = qr_player.replace(
        "<svg ", '<svg role="img" aria-label="QR code for the web player" ', 1)
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

<h2>1. The playlist URL</h2>
<p class="url" id="m3u">{m3u}</p>
<button onclick="navigator.clipboard.writeText(document.getElementById('m3u').textContent)">Copy playlist URL</button>
<p class="note">This is the one thing you have to type into the TV. Everything else refreshes on its own. The code below carries the same URL if you would rather scan it with a phone.</p>
<div class="qr">{qr}</div>

<h2>2. The guide URL (optional)</h2>
<p class="note">Add this in the player's EPG / XMLTV setting if it has one. It is a separate field - not all players take a guide URL at all.</p>
<p class="url" id="epg">{epg}</p>
<button onclick="navigator.clipboard.writeText(document.getElementById('epg').textContent)">Copy guide URL</button>

<h2>3. In the app</h2>
<p>Use <strong>{app_name}</strong> (Roku Channel Store). {app_note}</p>
<ol>
  <li>Install {app_name} from the Roku Channel Store if it is not already there.</li>
  <li>Open it and go to <strong>Settings</strong> -&gt; add a playlist -&gt; choose the <strong>M3U URL</strong> option.</li>
  <li>Paste the playlist URL above and save.</li>
  <li>Pick the live-TV categories you want. That is it.</li>
</ol>

<h2>4. Or play it right here, with no app at all</h2>
<p>This site also hosts a <strong>web player</strong> that reads the same playlist. Open it on a phone or tablet and cast it to the Roku, or just watch it in the browser. Nothing to buy, nothing to sign up for, and it works even if the TV has no IPTV app installed.</p>
<p><a href="{player}" style="font-size:1.05rem">{player}</a></p>
<div class="qr">{qr_player}</div>
<p class="note">Scan that code with a phone to open the web player, then use the Roku's screen mirroring or cast to send it to the TV.</p>

{extra}
<footer>
  The playlist is rebuilt every day and published automatically, so the URL never changes and the
  channels keep refreshing on their own. Publicly-posted stream URLs and public-domain media;
  availability varies by broadcaster.
</footer>
</body>
</html>
""".format(qr=qr, qr_player=qr_player, m3u=html.escape(m3u_url),
           epg=html.escape(epg_url), player=html.escape(PLAYER),
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
