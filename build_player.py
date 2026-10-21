"""
Build a self-hosted IPTV web player (dist/player.html).

Why a web player instead of a Roku channel-store app:

  - Every IPTV app in the Roku Channel Store either needs a paid
    subscription (TiviMate), an account wall (the Xtream app's "scan to add"
    QR goes to a login-gated vendor site), or a third-party service
    (M3U IPTV Pro -> iptvactivation.com, which is the paid portal we
    removed).
  - A web player hosted on our own Pages site needs no purchase, no account
    and no service. The Roku has "Mirror Screen to Roku" and Chromecast
    support, so the phone or laptop browser can cast a channel to the TV.
  - It also means the TV is not a special case: the same URL works in any
    browser, and the same playlist can be pasted into any IPTV app that
    accepts a playlist URL.

The player is one HTML file with no build step and no external asset
requirements beyond hls.js, which is loaded from a CDN and pinned to a
version. If the CDN is unreachable the page still works for .mp4 and
progressive sources.

It reads the same tv.m3u / vod.m3u that the Roku apps read, so there is
one source of truth.
"""

import html
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BASE = os.environ.get("SITE_BASE", "https://beexly.github.io/roku-iptv")
M3U = BASE + "/tv.m3u"
VOD = BASE + "/vod.m3u"
EPG = BASE + "/epg.xml"

HLS_JS = "https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js"


def build():
    m3u_js = """
const M3U_URL = %s;
const VOD_URL = %s;

async function loadM3U(url) {
  const res = await fetch(url, {cache: 'no-store'});
  if (!res.ok) throw new Error('HTTP ' + res.status + ' for ' + url);
  const text = await res.text();
  const items = [];
  let cur = null;
  for (const raw of text.split('\\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('#EXTINF')) {
      const name = line.slice(line.lastIndexOf(',') + 1).trim();
      const g = /group-title="([^"]*)"/.exec(line);
      const logo = /tvg-logo="([^"]*)"/.exec(line);
      const tvg = /tvg-id="([^"]*)"/.exec(line);
      cur = {name, group: g ? g[1] : 'Other', logo: logo ? logo[1] : '',
             tvg: tvg ? tvg[1] : ''};
    } else if (line.startsWith('#')) {
      continue;
    } else if (cur) {
      // Only http(s): browsers and IPTV apps cannot play rtmp/rtsp/etc.
      if (!/^https?:\/\//i.test(line)) { cur = null; continue; }
      cur.url = line;
      items.push(cur);
      cur = null;
    }
  }
  return items;
}

const state = {live: [], vod: [], view: 'live', filter: '', group: 'All', item: null};

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k);
  return n;
}

function groupList(items) {
  const counts = new Map();
  for (const it of items) counts.set(it.group, (counts.get(it.group) || 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function render() {
  const items = state.view === 'live' ? state.live : state.vod;
  const groups = groupList(items);
  if (!groups.some(g => g[0] === state.group)) state.group = 'All';
  const filtered = items.filter(it =>
    (state.group === 'All' || it.group === state.group) &&
    (!state.filter || it.name.toLowerCase().includes(state.filter)));

  const bar = document.getElementById('groups');
  bar.innerHTML = '';
  const mk = (label, val) => {
    const b = el('button', {class: 'gbtn' + (state.group === val ? ' on' : ''),
                             text: label, onclick: () => {state.group = val; render();}});
    bar.append(b);
  };
  mk('All', 'All');
  for (const [g, n] of groups) mk(g + ' (' + n + ')', g);

  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  for (const it of filtered.slice(0, 800)) {
    const card = el('div', {class: 'card', onclick: () => play(it)},
      it.logo ? el('img', {class: 'logo', src: it.logo, loading: 'lazy',
                            onerror: 'this.style.visibility="hidden"'}) : null,
      el('div', {class: 'nm', text: it.name}));
    grid.append(card);
  }
  document.getElementById('count').textContent =
    filtered.length + ' of ' + items.length + ' channels';
}

function play(item) {
  state.item = item;
  const v = document.getElementById('video');
  document.getElementById('title').textContent = item.name;
  document.getElementById('meta').textContent = item.group +
    (item.tvg ? '  -  ' + item.tvg : '');
  const holder = document.getElementById('stage');
  holder.style.display = 'block';
  v.style.display = 'block';
  if (v.hls) { v.hls.destroy(); v.hls = null; }
  v.removeAttribute('src');
  if (item.url.indexOf('.m3u8') > -1) {
    if (window.Hls && window.Hls.isSupported()) {
      const hls = new window.Hls({enableWorker: true, lowLatencyMode: true});
      hls.loadSource(item.url);
      hls.attachMedia(v);
      hls.on(Hls.Events.ERROR, (e, d) => {
        if (d.fatal) document.getElementById('meta').textContent =
          'Stream error: ' + d.details;
      });
      v.hls = hls;
    } else {
      v.src = item.url;
    }
  } else {
    v.src = item.url;
  }
  v.play().catch(() => {
    document.getElementById('meta').textContent =
      'Press play - the browser blocked autoplay';
  });
}

function stop() {
  const v = document.getElementById('video');
  if (v.hls) { v.hls.destroy(); v.hls = null; }
  v.pause();
  v.removeAttribute('src');
  document.getElementById('stage').style.display = 'none';
  state.item = null;
}

async function boot() {
  try {
    const [live, vod] = await Promise.all([loadM3U(M3U_URL), loadM3U(VOD_URL)]);
    state.live = live;
    state.vod = vod;
    render();
    document.getElementById('status').textContent =
      live.length + ' live channels, ' + vod.length + ' movies & series';
  } catch (e) {
    document.getElementById('status').textContent = 'Failed: ' + e.message;
  }
}
""" % (json.dumps(M3U), json.dumps(VOD))

    page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>IPTV Player</title>
<style>
  :root { color-scheme: dark; --bg:#0d0f12; --panel:#161a20; --line:#262c35;
          --fg:#e8ecf1; --dim:#98a3b3; --acc:#4da3ff; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
  header { position:sticky; top:0; z-index:10; background:var(--panel);
           border-bottom:1px solid var(--line); padding:12px 16px; }
  h1 { font-size:1.05rem; margin:0 0 2px; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .sub { color:var(--dim); font-size:.85rem; }
  input[type=search] { flex:1; min-width:180px; background:#0f1216; color:var(--fg);
      border:1px solid var(--line); border-radius:8px; padding:9px 12px; font:inherit; }
  button { font:inherit; background:#1e242c; color:var(--fg); border:1px solid var(--line);
           border-radius:8px; padding:9px 14px; cursor:pointer; }
  button.on { background:var(--acc); color:#06121f; border-color:var(--acc); font-weight:600; }
  #groups { display:flex; gap:8px; overflow-x:auto; padding:10px 16px;
            border-bottom:1px solid var(--line); background:#111419; }
  .gbtn { white-space:nowrap; font-size:.85rem; padding:6px 11px; }
  #grid { display:grid; gap:10px; padding:16px;
          grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px;
          padding:10px; cursor:pointer; transition:border-color .12s,transform .12s; }
  .card:hover { border-color:var(--acc); transform:translateY(-2px); }
  .logo { width:100%; height:52px; object-fit:contain; background:#0b0d10;
          border-radius:6px; margin-bottom:8px; }
  .nm { font-size:.82rem; line-height:1.3; }
  #stage { display:none; position:fixed; inset:0; background:#000; z-index:50;
           flex-direction:column; }
  #stage video { width:100%; height:100%; background:#000; }
  #bar { display:flex; gap:10px; align-items:center; padding:10px 14px;
         background:rgba(0,0,0,.75); }
  #title { font-weight:600; }
  #meta { color:var(--dim); font-size:.8rem; }
  #count { color:var(--dim); font-size:.8rem; padding:0 16px 8px; }
  a { color:var(--acc); }
</style>
</head>
<body>
<header>
  <div class="row">
    <h1>IPTV Player</h1>
    <button id="tablive" class="on" onclick="setView('live')">Live TV</button>
    <button id="tabvod" onclick="setView('vod')">Movies &amp; Series</button>
    <input type="search" id="q" placeholder="Search channels" oninput="onSearch(this.value)">
  </div>
  <div class="sub" id="status">loading...</div>
</header>
<div id="groups"></div>
<div id="count"></div>
<div id="grid"></div>

<div id="stage">
  <video id="video" controls playsinline></video>
  <div id="bar">
    <button onclick="stop()">Close</button>
    <span id="title"></span>
    <span id="meta"></span>
  </div>
</div>

<script src="__HLS_JS__"></script>
<script>
__M3U_JS__
function setView(v) {
  state.view = v;
  document.getElementById('tablive').className = v === 'live' ? 'on' : '';
  document.getElementById('tabvod').className = v === 'vod' ? 'on' : '';
  state.group = 'All';
  render();
}
function onSearch(t) { state.filter = t.toLowerCase(); render(); }
window.addEventListener('keydown', e => {
  if (e.key === 'Escape') stop();
});
boot();
</script>
</body>
</html>
"""
    page = page.replace("__HLS_JS__", HLS_JS).replace("__M3U_JS__", m3u_js)

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "player.html")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print("wrote", out, os.path.getsize(out), "bytes")
    return out


if __name__ == "__main__":
    build()
