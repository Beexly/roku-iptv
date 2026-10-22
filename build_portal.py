"""
Build the Apollo TV-style streaming portal (dist/portal.html).

One self-contained HTML page that reads tv.m3u + vod.m3u from GitHub Pages
and renders a Netflix/Apollo-TV-style interface:
  - Live TV grid with channel logos and category filters
  - Movies & Series grid with search
  - HLS video player (hls.js) with fullscreen
  - Works in any browser; cast to Roku via screen mirroring
  - No build dependencies at runtime — pure HTML/JS, CDN for hls.js
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
PLAYER = BASE + "/portal.html"

HLS_JS = "https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js"

# ---------------------------------------------------------------------------
# M3U -> JS data embedding
# ---------------------------------------------------------------------------

def parse_m3u(text):
    items = []
    cur = None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            name = line[line.rfind(",") + 1:].strip() if "," in line else line
            g = re.search(r'group-title="([^"]*)"', line)
            logo = re.search(r'tvg-logo="([^"]*)"', line)
            tvg = re.search(r'tvg-id="([^"]*)"', line)
            cur = {
                "name": name,
                "group": g.group(1) if g else "Other",
                "logo": logo.group(1) if logo else "",
                "tvg": tvg.group(1) if tvg else "",
            }
        elif line.startswith("#"):
            continue
        elif cur is not None:
            if re.match(r"^https?://", line, re.I):
                cur["url"] = line
                items.append(cur)
            cur = None
    return items


def m3u_js():
    """Fetch both M3Us and return JS data blocks."""
    import urllib.request

    def fetch(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace")

    live = parse_m3u(fetch(M3U))
    vod = parse_m3u(fetch(VOD))

    # Tag VOD entries as movies/series by name heuristics + group
    for item in vod:
        item["type"] = "vod"
    for item in live:
        item["type"] = "live"

    return live, vod


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Home Stream — Movies, Shows & Live TV</title>
<style>
  :root {
    --bg:#0a0b0f; --panel:#12141a; --line:#232730;
    --fg:#e8ecf1; --dim:#9aa3b1; --acc:#ff4d4f; --acc2:#2f88ff;
    --card:#171a22; --hover:#1f232d;
  }
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; background:var(--bg); color:var(--fg);
               font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
               overflow-x:hidden; }
  header { position:sticky; top:0; z-index:50; background:rgba(10,11,15,.92);
           backdrop-filter: blur(8px); border-bottom:1px solid var(--line);
           padding:14px 18px; display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .brand { font-weight:800; font-size:1.25rem; letter-spacing:.5px;
           background:linear-gradient(90deg,var(--acc),var(--acc2));
           -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
  .sub { color:var(--dim); font-size:.85rem; margin-top:2px; }
  input[type=search] { flex:1; min-width:200px; background:#0c0d12;
     border:1px solid var(--line); border-radius:999px; padding:10px 16px;
     color:var(--fg); font:inherit; }
  button { font:inherit; background:var(--panel); color:var(--fg);
           border:1px solid var(--line); border-radius:10px;
           padding:9px 16px; cursor:pointer; }
  button.primary { background:var(--acc); border-color:var(--acc); color:#fff; font-weight:700; }
  button.secondary { background:transparent; color:var(--dim); }
  button.secondary.active { background:var(--acc2); border-color:var(--acc2); color:#fff; }
  .tagline { color:var(--dim); font-size:.9rem; margin-left:auto; white-space:nowrap; }
  .hero { padding:26px 18px 6px; }
  .hero h2 { font-size:1.5rem; margin:0 0 6px; }
  .hero p { color:var(--dim); margin:0 0 14px; }
  .stats { display:flex; gap:16px; color:var(--dim); font-size:.85rem; }
  .stats b { color:var(--fg); }
  .section { padding:0 18px 24px; }
  .sec-head { display:flex; align-items:center; justify-content:space-between;
              margin-bottom:12px; }
  .sec-head h3 { margin:0; font-size:1.1rem; }
  .chips { display:flex; gap:8px; overflow-x:auto; padding-bottom:6px; margin-bottom:12px;
           scrollbar-width:none; }
  .chips::-webkit-scrollbar { display:none; }
  .chip { background:var(--panel); border:1px solid var(--line); color:var(--dim);
          border-radius:999px; padding:6px 12px; font-size:.85rem; white-space:nowrap;
          cursor:pointer; }
  .chip.active { border-color:var(--acc2); color:var(--acc2); }
  .grid { display:grid; gap:12px;
          grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          overflow:hidden; cursor:pointer; transition:transform .15s,border-color .15s;
          display:flex; flex-direction:column; }
  .card:hover { border-color:var(--acc2); transform:translateY(-3px); }
  .card art { position:relative; display:block; aspect-ratio:16/9; background:#050608;
              overflow:hidden; }
  .card art img { width:100%; height:100%; object-fit:cover; display:block; }
  .card art .play { position:absolute; inset:0; background:rgba(0,0,0,.45);
                    display:flex; align-items:center; justify-content:center;
                    opacity:0; transition:opacity .2s; }
  .card:hover art .play { opacity:1; }
  .card art .play::before { content:"▶"; font-size:2rem; color:#fff; filter:drop-shadow(0 2px 4px #000); }
  .card .info { padding:10px 12px 12px; }
  .card .name { font-size:.9rem; font-weight:600; margin:0 0 4px; white-space:nowrap;
                overflow:hidden; text-overflow:ellipsis; }
  .card .meta { font-size:.75rem; color:var(--dim); }
  .live-badge { position:absolute; top:8px; left:8px; background:var(--acc);
                color:#fff; font-size:.7rem; font-weight:800; padding:2px 8px;
                border-radius:4px; box-shadow:0 2px 6px rgba(255,77,79,.4); }
  .vod-badge { position:absolute; top:8px; right:8px; background:rgba(0,0,0,.5);
               color:#fff; font-size:.7rem; padding:2px 8px; border-radius:4px; }
  #stage { display:none; position:fixed; inset:0; background:#000; z-index:100;
           flex-direction:column; }
  #stage video { width:100%; height:100%; background:#000; display:block; }
  #ctrl { position:absolute; inset:0; display:none; align-items:center;
          justify-content:center; z-index:101; }
  #ctrl .big { width:64px; height:64px; border-radius:50%; background:rgba(0,0,0,.7);
               display:flex; align-items:center; justify-content:center;
               font-size:2rem; color:#fff; cursor:pointer; backdrop-filter:blur(4px); }
  #topbar { position:absolute; top:14px; left:14px; right:14px; z-index:102;
            display:flex; align-items:center; justify-content:space-between; }
  #cur-title { font-weight:700; font-size:1rem; color:#fff; text-shadow:0 1px 4px #000; }
  #cur-meta { color:rgba(255,255,255,.8); font-size:.85rem; text-shadow:0 1px 4px #000; }
  #close { background:rgba(255,255,255,.15); border-color:rgba(255,255,255,.3); color:#fff; }
  .empty { grid-column:1/-1; text-align:center; color:var(--dim); padding:40px; }
  .note { color:var(--dim); font-size:.8rem; margin-top:8px; }
  footer { padding:30px 18px; border-top:1px solid var(--line); color:var(--dim);
           font-size:.8rem; text-align:center; }
  a { color:var(--acc2); }
  .hidden { display:none !important; }
</style>
</head>
<body>

<header>
  <div class="brand">Home Stream</div>
  <div class="sub" style="font-size:.75rem;">Live TV · Movies · Series</div>
  <input type="search" id="q" placeholder="Search movies, shows, channels…">
  <button class="secondary" id="btn-live" onclick="setView('live')">Live TV</button>
  <button class="secondary" id="btn-vod" onclick="setView('vod')">Movies &amp; Series</button>
  <div class="tagline" id="tagline"></div>
</header>

<div class="hero">
  <h2 id="hero-title">Browse</h2>
  <p id="hero-desc">Pick something to watch.</p>
  <div class="stats" id="stats"></div>
</div>

<div class="section">
  <div class="sec-head">
    <h3 id="sec-title">Live Channels</h3>
    <div class="chips" id="chips"></div>
  </div>
  <div id="grid" class="grid"></div>
</div>

<div id="stage">
  <div id="ctrl"><div class="big" id="btn-play">▶</div></div>
  <div id="topbar">
    <div>
      <div id="cur-title"></div>
      <div id="cur-meta"></div>
    </div>
    <button id="close" onclick="stop()">✕ Close</button>
  </div>
  <video id="video" controls playsinline></video>
</div>

<div class="note hidden" id="empty">No results.</div>

<footer>
  Home Stream · Live channels and movies refresh automatically. No account, no subscription.
  <br>Cast from your phone to the Roku, or watch right in the browser.
</footer>

<script src="__HLS_JS__"></script>
<script>
const M3U_URL = __M3U__;
const VOD_URL = __VOD__;

const state = {
  live: [], vod: [], view: 'live',
  filter: '', group: 'All', item: null, hls: null
};

function esc(t){return t.replace(/[&<>"']/g,c=>({['&']:'&amp;',['<']:'&lt;',['>']:'&gt;',['"']:'&quot;',["'"]:'&#39;'}[c]));}

function el(tag, attrs, ...kids){
  const n=document.createElement(tag);
  for(const [k,v] of Object.entries(attrs||{})){
    if(k==='class') n.className=v;
    else if(k==='text') n.textContent=v;
    else if(k==='html') n.innerHTML=v;
    else if(k.startsWith('on')) n.addEventListener(k.slice(2),v);
    else n.setAttribute(k,v);
  }
  for(const k of kids) n.append(k);
  return n;
}

function groupList(items){
  const m=new Map();
  for(const it of items) m.set(it.group,(m.get(it.group)||0)+1);
  return [...m.entries()].sort((a,b)=>b[1]-a[1]);
}

function render(){
  const items = state.view==='live' ? state.live : state.vod;
  const groups = groupList(items);
  const chipBox=document.getElementById('chips');
  chipBox.innerHTML='';
  const allChip=el('button',{class:'chip'+(state.group==='All'?' active':''),text:'All ('+items.length+')',onclick:()=>{state.group='All';render();}});
  chipBox.append(allChip);
  for(const [g,n] of groups){
    chipBox.append(el('button',{class:'chip'+(state.group===g?' active':''),text:g+' ('+n+')',onclick:()=>{state.group=g;render();}}));
  }
  const grid=document.getElementById('grid');
  grid.innerHTML='';
  const filtered=items.filter(it=>
    (state.group==='All'||it.group===state.group)&&
    (!state.filter||it.name.toLowerCase().includes(state.filter)));
  if(filtered.length===0){
    grid.append(el('div',{class:'empty',text:'No results. Try a different search or category.'}));
  } else {
    for(const it of filtered){
      const card=el('div',{class:'card',onclick:()=>play(it)},
        el('art',
          it.logo?el('img',{src:it.logo,loading:'lazy',alt:''}):null,
          el('div',{class:'play'}),
          state.view==='live'?el('div',{class:'live-badge',text:'LIVE'}):el('div',{class:'vod-badge',text:'VOD'})
        ),
        el('div',{class:'info'},
          el('div',{class:'name',text:it.name}),
          el('div',{class:'meta',text:it.group})
        )
      );
      grid.append(card);
    }
  }
  document.getElementById('stats').textContent = filtered.length+' of '+items.length+((state.view==='live')?' live channels':' movies & series');
  document.getElementById('sec-title').textContent = state.view==='live'?'Live Channels':'Movies & Series';
  document.getElementById('tagline').textContent = state.view==='live'?'1,000+ live channels':'1,000+ movies & series';
}

function setView(v){
  state.view=v; state.group='All'; state.filter='';
  document.getElementById('q').value='';
  document.getElementById('btn-live').className='secondary'+(v==='live'?' active':'');
  document.getElementById('btn-vod').className='secondary'+(v==='vod'?' active':'');
  document.getElementById('hero-title').textContent = v==='live'?'Live TV':'Movies & Series';
  document.getElementById('hero-desc').textContent = v==='live'?'Watch live channels from around the US.':'Movies, series, and public-domain classics.';
  render();
}

function onSearch(t){state.filter=t.toLowerCase();render();}

async function load(){
  try{
    const [liveResp,vodResp]=await Promise.all([fetch(M3U_URL,{cache:'no-store'}),fetch(VOD_URL,{cache:'no-store'})]);
    const liveText=await liveResp.text();
    const vodText=await vodResp.text();
    state.live=parseM3U(liveText);
    state.vod=parseM3U(vodText);
    setView('live');
  }catch(e){
    document.getElementById('stats').textContent='Failed to load: '+e.message;
  }
}

function parseM3U(text){
  const items=[]; let cur=null;
  for(const raw of text.split('\n')){
    const line=raw.trim();
    if(!line||line.startsWith('#EXTM3U')) continue;
    if(line.startsWith('#EXTINF')){
      const name=line.includes(',')?line.slice(line.lastIndexOf(',')+1).trim():line;
      const g=/group-title="([^"]*)"/.exec(line);
      const logo=/tvg-logo="([^"]*)"/.exec(line);
      cur={name,group:g?g[1]:'Other',logo:logo?logo[1]:'',tvg:''};
    } else if(line.startsWith('#')){ continue; }
    else if(cur){
      if(/^https?:\/\//i.test(line)){cur.url=line;items.push(cur);}
      cur=null;
    }
  }
  return items;
}

function play(item){
  state.item=item;
  const v=document.getElementById('video');
  document.getElementById('cur-title').textContent=item.name;
  document.getElementById('cur-meta').textContent=item.group+(item.tvg?'  ·  '+item.tvg:'');
  document.getElementById('stage').style.display='flex';
  v.style.display='block';
  document.getElementById('ctrl').style.display='none';
  if(v.hls){v.hls.destroy();v.hls=null;}
  v.removeAttribute('src');
  if(item.url.indexOf('.m3u8')>-1){
    if(window.Hls&&window.Hls.isSupported()){
      const hls=new window.Hls({enableWorker:true,lowLatencyMode:true});
      hls.loadSource(item.url);
      hls.attachMedia(v);
      v.hls=hls;
    } else { v.src=item.url; }
  } else {
    v.src=item.url;
    v.onerror=()=>{document.getElementById('cur-meta').textContent='This host blocks browser playback (CORS). Try the Roku app.';};
  }
  v.play().catch(()=>{document.getElementById('ctrl').style.display='flex';});
}

function stop(){
  const v=document.getElementById('video');
  if(v.hls){v.hls.destroy();v.hls=null;}
  v.pause();v.removeAttribute('src');
  document.getElementById('stage').style.display='none';
  document.getElementById('ctrl').style.display='none';
  state.item=null;
}

document.getElementById('q').addEventListener('input',e=>onSearch(e.target.value));
document.getElementById('btn-play').addEventListener('click',()=>{const v=document.getElementById('video');if(v.paused)v.play();else v.pause();});
document.getElementById('video').addEventListener('play',()=>{document.getElementById('ctrl').style.display='none';});
document.getElementById('video').addEventListener('pause',()=>{document.getElementById('ctrl').style.display='flex';});
document.getElementById('video').addEventListener('ended',stop);
window.addEventListener('keydown',e=>{if(e.key==='Escape')stop();});

load();
</script>
</body>
</html>"""


def build():
    live, vod = m3u_js()
    live_js = "const LIVE_DATA = " + json.dumps(live, ensure_ascii=False) + ";"
    vod_js = "const VOD_DATA = " + json.dumps(vod, ensure_ascii=False) + ";"

    # Replace the load() function to use embedded data instead of fetching
    page = PAGE_TEMPLATE.replace("__HLS_JS__", HLS_JS)
    page = page.replace("__M3U__", json.dumps(M3U))
    page = page.replace("__VOD__", json.dumps(VOD))

    # Inject embedded data before load()
    data_block = "<script>\n" + live_js + "\n" + vod_js + "\n</script>\n"
    page = page.replace("<script>\nconst M3U_URL", data_block + "<script>\nconst M3U_URL")

    # Replace the load() async fetch with embedded data usage
    old_load = """async function load(){
  try{
    const [liveResp,vodResp]=await Promise.all([fetch(M3U_URL,{cache:'no-store'}),fetch(VOD_URL,{cache:'no-store'})]);
    const liveText=await liveResp.text();
    const vodText=await vodResp.text();
    state.live=parseM3U(liveText);
    state.vod=parseM3U(vodText);
    setView('live');
  }catch(e){
    document.getElementById('stats').textContent='Failed to load: '+e.message;
  }
}"""
    new_load = """function load(){
  state.live = window.LIVE_DATA || [];
  state.vod = window.VOD_DATA || [];
  setView('live');
}"""
    page = page.replace(old_load, new_load)

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "portal.html")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print("wrote", out, os.path.getsize(out), "bytes")
    print("live channels:", len(live), "| vod entries:", len(vod))
    return out


if __name__ == "__main__":
    build()
