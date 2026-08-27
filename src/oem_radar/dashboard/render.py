"""Render the dashboard payload into a single self-contained HTML page.
No external assets or CDNs — works fully offline. Data is embedded as JSON
and filtered client-side with vanilla JS, so 'reload' just re-fetches the
page and the server re-queries the DB."""

from __future__ import annotations

import json

_PAGE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>OEM Radar</title>
<style>
  :root{
    --bg:#0d1017; --panel:#161b22; --panel2:#1c232c; --line:#2a323d;
    --fg:#e6edf3; --muted:#8b98a5; --faint:#5f6b78; --accent:#3fb950;
    --s5:#2ecc71; --s4:#e8912d; --s3:#3f8cd6; --s2:#6b7684; --s1:#4a535f;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:var(--bg);color:var(--fg);
    font:14px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    -webkit-font-smoothing:antialiased}
  a{color:var(--s3);text-decoration:none}a:hover{text-decoration:underline}

  header{position:sticky;top:0;z-index:5;background:rgba(13,16,23,.92);
    backdrop-filter:blur(6px);border-bottom:1px solid var(--line);
    padding:14px 24px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
  header h1{margin:0;font-size:17px;font-weight:650;letter-spacing:.4px}
  header h1 .dot{color:var(--accent)}
  .gen{color:var(--muted);font-size:12px}
  .reload{cursor:pointer}

  .wrap{max-width:1080px;margin:0 auto;padding:22px 24px 60px}

  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
    gap:12px;margin-bottom:22px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .stat .n{font-size:23px;font-weight:650;line-height:1}
  .stat .l{color:var(--muted);font-size:12px;margin-top:6px}

  .tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:18px;flex-wrap:wrap}
  .tab{padding:9px 15px;cursor:pointer;color:var(--muted);font-weight:500;
    border-bottom:2px solid transparent;margin-bottom:-1px}
  .tab:hover{color:var(--fg)}
  .tab.active{color:var(--fg);border-bottom-color:var(--accent)}
  .lead{color:var(--muted);font-size:13px;margin:0 2px 14px}

  .filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
  select,input{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
    border-radius:9px;padding:8px 11px;font-size:13px;outline:none}
  select:focus,input:focus{border-color:var(--accent)}
  input.q{flex:1;min-width:200px}

  /* the fix: explicit vertical stack, cards always full width */
  .list{display:flex;flex-direction:column;gap:10px}
  .card{display:grid;grid-template-columns:76px 1fr;gap:14px;width:100%;
    background:var(--panel);border:1px solid var(--line);border-left-width:4px;
    border-radius:12px;padding:13px 16px}
  .card.s5{border-left-color:var(--s5)}.card.s4{border-left-color:var(--s4)}
  .card.s3{border-left-color:var(--s3)}.card.s2{border-left-color:var(--s2)}
  .card.s1{border-left-color:var(--s1)}
  .thumb{width:76px;height:76px;border-radius:9px;background:var(--panel2);
    object-fit:cover;display:block}
  .body{min-width:0;overflow-wrap:anywhere}
  .row1{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
  .title{font-weight:600;font-size:15px}
  .title .man{color:var(--muted);font-weight:400;font-size:13px}
  .when{color:var(--faint);font-size:12px;white-space:nowrap;flex:none}
  .tags{margin:7px 0 2px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .badge{font-size:11px;padding:2px 8px;border-radius:20px;background:var(--panel2);
    border:1px solid var(--line);color:var(--muted);white-space:nowrap}
  .badge.unseen{color:#fff;background:#c0392b;border-color:#c0392b;font-weight:600}
  .badge.hidden{color:#1a1a1a;background:#e0b93c;border-color:#e0b93c;font-weight:600}
  .badge.notified{color:var(--accent);border-color:#2c5c38}
  .badge.type{color:var(--fg)}
  .badge.rev-UNREVIEWED{color:#1a1a1a;background:#e0b93c;border-color:#e0b93c;font-weight:600}
  .badge.rev-HIT{color:#fff;background:#2ecc71;border-color:#27ae60;font-weight:600}
  .badge.rev-INTERESTING{color:#fff;background:#3f8cd6;border-color:#2980b9;font-weight:600}
  .badge.rev-NOISE{color:#fff;background:#6b7684;border-color:#5f6b78;font-weight:600}
  .badge.rev-BUG{color:#fff;background:#c0392b;border-color:#a93226;font-weight:600}
  .alert-id a{font-family:ui-monospace,monospace;font-size:12px}
  .stars{color:var(--s4);letter-spacing:2px;font-size:12px}
  .specs{color:var(--muted);font-size:12.5px;margin-top:5px}
  .specs .warn{color:#e8912d}
  .change{font-size:13px;margin-top:6px;color:var(--fg)}
  .change .old{color:var(--faint)}
  .change .arrow{color:var(--muted);margin:0 5px}
  .change .up{color:#e05c5c}.change .down{color:#4fb36f}
  .listing{display:inline-block;margin-top:8px;font-weight:600;font-size:13px}

  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:13px}
  th{color:var(--muted);font-weight:500}
  tr:hover td{background:var(--panel)}
  .mono{font-variant-numeric:tabular-nums}
  .empty{color:var(--muted);padding:44px;text-align:center;
    border:1px dashed var(--line);border-radius:12px}
  .hide{display:none}
  .count{color:var(--faint);font-size:12px;margin:2px 2px 12px}
  .btn{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
    border-radius:8px;padding:6px 12px;font-size:12.5px;cursor:pointer}
  .btn:hover{border-color:var(--accent);color:var(--accent)}
  .btn.small{padding:3px 10px;font-size:12px}
  .hwbar{display:flex;justify-content:space-between;align-items:center;
    gap:12px;margin-bottom:12px;flex-wrap:wrap}
  td.act{text-align:right;white-space:nowrap}

  nav.crumbs{max-width:1080px;margin:0 auto;padding:10px 24px 0;
    display:flex;gap:8px;flex-wrap:wrap}
  nav.crumbs a{background:var(--panel);border:1px solid var(--line);
    border-radius:20px;padding:6px 14px;font-size:12.5px;color:var(--fg)}
  nav.crumbs a:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
  nav.crumbs a.here{border-color:var(--accent);color:var(--accent)}

  .cta{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:14px 16px;margin-bottom:16px;display:flex;justify-content:space-between;
    align-items:center;gap:14px;flex-wrap:wrap}
  .cta .msg{font-size:13.5px;color:var(--muted)}
  .cta .msg b{color:var(--fg)}

  .health-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
    gap:10px;margin-bottom:16px}
  /* crawl control bar — the dashboard's one write-side control */
  .crawlbar{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:12px 16px;margin-bottom:18px;display:flex;align-items:center;
    gap:12px;flex-wrap:wrap}
  .crawlbar.running{border-color:var(--s3)}
  .crawlbar.stale{border-color:var(--s4)}
  .crawlbar.bad{border-color:#c0392b}
  .crawlbar .cdot{width:9px;height:9px;border-radius:50%;background:var(--faint);flex:none}
  .crawlbar.running .cdot{background:var(--s3);animation:pulse 1.1s ease-in-out infinite}
  .crawlbar.good .cdot{background:var(--accent)}
  .crawlbar.stale .cdot{background:var(--s4)}
  .crawlbar.bad .cdot{background:#c0392b}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
  .crawlbar .ctext{flex:1;min-width:220px}
  .crawlbar .ctitle{font-weight:600}
  .crawlbar .csub{color:var(--muted);font-size:12px;margin-top:2px}
  .crawlbar .cbtns{display:flex;gap:8px;flex-wrap:wrap}
  .crawlbar button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
    border-radius:9px;padding:8px 14px;font-size:13px;font-weight:550;cursor:pointer}
  .crawlbar button:hover:not(:disabled){border-color:var(--accent);color:var(--fg)}
  .crawlbar button:disabled{opacity:.45;cursor:default}
  .crawlbar button.primary{background:var(--accent);border-color:var(--accent);color:#0b1f12}
  .cprog{width:100%;height:4px;background:var(--panel2);border-radius:3px;overflow:hidden}
  .cprog > i{display:block;height:100%;background:var(--s3);transition:width .4s ease}
  /* per-collector list — individual runs, and where the slow ones live
     since they're excluded from the "Run all collectors" sweep above */
  .crawlbar .ctoggle{width:100%;font-size:12px;color:var(--muted);cursor:pointer;
    text-decoration:underline;text-underline-offset:2px;background:none;border:none;
    padding:0;text-align:left}
  .catalog{width:100%;display:flex;flex-direction:column;gap:4px;margin-top:4px}
  .catrow{display:flex;align-items:center;gap:8px;font-size:12.5px;padding:5px 8px;
    border-radius:7px;background:var(--panel2)}
  .catrow .cid{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .catrow .cid b{font-weight:600}
  .catrow .slow{font-size:10.5px;font-weight:700;color:#8a5a00;background:#f5c451;
    border-radius:20px;padding:1px 7px;flex:none}
  .catrow button{background:var(--panel);color:var(--fg);border:1px solid var(--line);
    border-radius:7px;padding:4px 10px;font-size:12px;cursor:pointer;flex:none}
  .catrow button:hover:not(:disabled){border-color:var(--accent)}
  .catrow button:disabled{opacity:.45;cursor:default}

  .health-row{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:10px 12px;display:flex;justify-content:space-between;align-items:center;gap:8px}
  .hstatus{font-size:11px;padding:2px 9px;border-radius:20px;font-weight:650;white-space:nowrap}
  .hstatus.ok{color:#fff;background:#27ae60}
  .hstatus.degraded{color:#1a1a1a;background:#e8912d}
  .hstatus.failed{color:#fff;background:#c0392b}
</style></head>
<body>
<header>
  <h1>OEM&nbsp;<span class="dot">&#9673;</span>&nbsp;Radar</h1>
  <span class="gen">updated <span id="gen"></span> &middot;
    <a class="reload" onclick="location.reload()">reload</a></span>
</header>
<nav class="crumbs">
  <a href="/" class="here">Overview</a>
  <a href="/?tab=events">Alerts</a>
  <a href="/?tab=evidence">Evidence</a>
  <a href="/feedback">Feedback</a>
  <a href="/qc">Recently QCed</a>
</nav>
<div class="wrap">
  <div class="crawlbar" id="crawlbar"></div>
  <div class="cta" id="review-cta"></div>
  <div class="lead" id="baseline-note"></div>
  <div class="stats" id="stats"></div>
  <div class="health-grid" id="health"></div>
  <div class="tabs">
    <div class="tab active" data-tab="stories">Stories</div>
    <div class="tab" data-tab="signals">Signals</div>
    <div class="tab" data-tab="events">All changes</div>
    <div class="tab" data-tab="hardware">Unseen hardware</div>
    <div class="tab" data-tab="oems">Manufacturers</div>
    <div class="tab" data-tab="runs">Runs</div>
    <div class="tab" data-tab="evidence">Evidence</div>
  </div>

    <section id="stories">
    <p class="lead">Cross-OEM stories \u2014 the same unseen silicon or spec jump appearing across multiple makers. Your "before it's news" feed.</p>
    <div id="stories-list" class="list"></div>
  </section>

  <section id="signals" class="hide">
    <p class="lead">High-priority: brand-new products, previously-unseen silicon, and other 4&ndash;5&#9733; changes.</p>
    <div id="signals-list" class="list"></div>
  </section>

  <section id="events" class="hide">
    <p class="lead"><b>Product changes only.</b> New hardware and changes to products this
      radar tracks on a storefront. Evidence records (support artifacts, BIOS, manuals,
      product-database entries) are a different kind of object and live under
      <a href="#" onclick="activateTab('evidence');return false">Evidence</a>.</p>
    <div class="filters">
      <input class="q" id="q" placeholder="Search model, CPU, OEM...">
      <select id="f-man"></select>
      <select id="f-type"></select>
      <select id="f-sev">
        <option value="0">Any severity</option>
        <option value="5">5&#9733; only</option>
        <option value="4">4&#9733; and up</option>
        <option value="3">3&#9733; and up</option>
      </select>
      <select id="f-rev">
        <option value="">Any review status</option>
        <option value="UNREVIEWED">Unreviewed</option>
        <option value="HIT">Hit</option>
        <option value="INTERESTING">Interesting</option>
        <option value="NOISE">Noise</option>
        <option value="BUG">Bug</option>
      </select>
    </div>
    <div class="count" id="events-count"></div>
    <div id="events-list" class="list"></div>
  </section>

  <section id="hardware" class="hide"><div id="hw-list"></div></section>
  <section id="oems" class="hide"><div id="oems-list"></div></section>
  <section id="runs" class="hide"><div id="runs-list"></div></section>
  <section id="evidence" class="hide">
    <p class="lead">Alternate official-source intelligence &mdash; product-database and support
      records found outside a storefront. <b>Evidence supports signal; it is not signal.</b>
      These are deliberately kept out of <i>All changes</i>: an evidence record says an
      official source lists something, not that a tracked product changed. Nothing here
      is reviewed HIT/NOISE, because that workflow rates alerts, and these are not alerts.</p>
    <div class="filters">
      <input class="q" id="ev-q" placeholder="Search evidence model, title, id...">
      <select id="f-ev-man"></select>
      <select id="f-ev-kind"></select>
    </div>
    <div class="count" id="evidence-count"></div>
    <div id="evidence-list"></div>
  </section>
</div>

<script>
const DATA = __DATA__;
const esc = s => (s==null?"":String(s)).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const stars = n => "★".repeat(n)+"☆".repeat(5-n);
const when = s => { if(!s) return ""; const d=new Date(s); return isNaN(d)?esc(s):d.toLocaleString(); };
const short = (v,n=48) => { const s=(v==null?"":String(v)); return s.length>n?esc(s.slice(0,n))+"…":esc(s); };
const TYPE = {new_product:"New product",component_changed:"Component changed",
  spec_changed:"Spec changed",price_changed:"Price changed",availability_changed:"Availability",
  images_changed:"New images",description_changed:"Description",product_renamed:"Renamed",
  regional_variant:"Regional variant",duplicate_listing:"Duplicate listing",
  product_removed:"Removed",support_artifact_added:"Support artifact",source_degraded:"Source degraded"};

function changeLine(e){
  if(e.type==='price_changed' && e.magnitude_pct!=null){
    const dir=e.direction==='up'?'up':'down';
    const cls=e.direction==='up'?'up':'down';
    const arr=e.direction==='up'?'▲':'▼';
    return `<div class="change"><span class="${cls}">${arr} price ${dir} ${esc(e.magnitude_pct)}%</span></div>`;
  }
  if(e.field==='configurations'){
    const parts=[];
    if(e.added&&e.added.length) parts.push('+ '+e.added.map(x=>esc(x)).join(', '));
    if(e.removed&&e.removed.length) parts.push('− '+e.removed.map(x=>esc(x)).join(', '));
    return parts.length?`<div class="change">${parts.join(' &nbsp; ')}</div>`:'';
  }
  if(e.field && e.old!=null && e.type!=='images_changed'){
    return `<div class="change"><b>${esc(e.field)}</b> `+
      `<span class="old">${short(typeof e.old==='object'?JSON.stringify(e.old):e.old)}</span>`+
      `<span class="arrow">→</span>${short(typeof e.new==='object'?JSON.stringify(e.new):e.new)}</div>`;
  }
  return '';
}

function card(e){
  const rev = e.review_status || 'UNREVIEWED';
  const tags=[`<span class="badge type">${esc(TYPE[e.type]||e.type)}</span>`,
    `<span class="stars">${stars(e.severity)}</span>`,
    `<span class="badge rev-${esc(rev)}">${esc(rev)}</span>`,
    `<span class="alert-id"><a href="/alerts/${e.id}">#${e.id}</a></span>`];
  if(e.unseen_component) tags.unshift('<span class="badge unseen">⚠ previously unseen</span>');
  if(e.hidden) tags.unshift('<span class="badge hidden">hidden listing</span>');
  if(e.notified) tags.push('<span class="badge notified">notified</span>');
  if(e.confidence!=null && e.confidence<0.8) tags.push('<span class="badge">low confidence</span>');

  const specs=[e.cpu&&('CPU '+esc(e.cpu)+(e.cpu_unseen?' <span class="warn">⚠</span>':'')),
    e.gpu&&('GPU '+esc(e.gpu)), e.memory&&esc(e.memory), e.storage&&esc(e.storage),
    e.price&&(esc(e.price)+(e.region?(' · '+esc(e.region)):''))].filter(Boolean).join('&nbsp; · &nbsp;');

  const thumb=e.image
    ? `<img class="thumb" src="${esc(e.image)}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb'}))">`
    : `<div class="thumb"></div>`;
  const link=e.url?`<a class="listing" href="${esc(e.url)}" target="_blank" rel="noopener">View listing &rarr;</a>`:'';

  return `<div class="card s${e.severity}">${thumb}<div class="body">
    <div class="row1">
      <div class="title">${esc(e.model||e.product_key)} <span class="man">— ${esc(e.manufacturer||'')}</span></div>
      <div class="when">${when(e.detected_at)}</div>
    </div>
    <div class="tags">${tags.join('')}</div>
    ${specs?`<div class="specs">${specs}</div>`:''}
    ${changeLine(e)}
    ${link}
  </div></div>`;
}

// ---- crawl control ---------------------------------------------------
// The dashboard used to be read-only, which made "reload" meaningless:
// it re-queried a database nothing was updating. This bar is the one
// place that starts a crawl, and the one place that reports on it.
// State lives on the server (core.crawl_service.CrawlController) and is
// polled — never inferred from what this page happens to be showing.
const CSRF = "__CSRF__";
let crawlPollTimer = null, crawlWasRunning = false, catalogOpen = false, lastCrawlState = null;

const ago = s => {
  if(!s) return null;
  const ms = Date.now() - new Date(s).getTime();
  if(isNaN(ms)) return null;
  const m = Math.round(ms/60000);
  if(m < 1) return "just now";
  if(m < 60) return m+"m ago";
  const h = Math.round(m/60);
  if(h < 48) return h+"h ago";
  return Math.round(h/24)+"d ago";
};

function lastCrawlAgeHours(){
  const lr = DATA.summary && DATA.summary.last_run;
  if(!lr) return null;
  const ms = Date.now() - new Date(lr).getTime();
  return isNaN(ms) ? null : ms/3600000;
}

function renderCrawl(st){
  const el = document.getElementById('crawlbar');
  if(!el) return;
  lastCrawlState = st;
  const lr = DATA.summary && DATA.summary.last_run;
  const lastTxt = lr ? ('last successful crawl '+ago(lr)) : 'no successful crawl recorded yet';

  if(!st.enabled){
    el.className = 'crawlbar';
    el.innerHTML = `<span class="cdot"></span><div class="ctext">`+
      `<div class="ctitle">Collectors not controlled from here</div>`+
      `<div class="csub">${esc(st.message||'')} &middot; ${esc(lastTxt)}</div></div>`;
    return;
  }

  if(st.running){
    const done = st.sources_done||0, total = st.sources_total||0;
    const pct = total ? Math.round(done/total*100) : 0;
    el.className = 'crawlbar running';
    el.innerHTML = `<span class="cdot"></span><div class="ctext">`+
      `<div class="ctitle">Crawling&hellip; ${esc(st.message||'')}</div>`+
      `<div class="csub">${done} of ${total} source(s) checked`+
      (st.trigger==='auto'?' &middot; started automatically when you opened the dashboard':'')+
      ` &middot; started ${esc(ago(st.started_at)||'')}</div></div>`+
      `<div class="cbtns"><button disabled>Running&hellip;</button></div>`+
      `<div class="cprog"><i style="width:${pct}%"></i></div>`+
      renderCatalog(st, true);
    return;
  }

  const staleH = st.stale_after_hours || 6;
  const ageH = lastCrawlAgeHours();
  const stale = ageH === null || ageH > staleH;
  let cls = stale ? 'crawlbar stale' : 'crawlbar good';
  let title, sub;

  if(st.status === 'ok' && st.outcome){
    const o = st.outcome;
    cls = 'crawlbar good';
    title = 'Crawl finished';
    sub = `${o.sources} source(s) &middot; ${o.snapshots} snapshot(s) &middot; `+
          `${o.events} change(s)`+(o.errors?` &middot; ${o.errors} error(s)`:'')+
          ` &middot; ${o.duration_s}s`;
  } else if(st.status === 'blocked'){
    cls = 'crawlbar stale';
    title = 'Another crawl already holds the lock';
    sub = esc(st.message||'')+' &mdash; usually the scheduled hourly task. Nothing was skipped; it is running now.';
  } else if(st.status === 'failed'){
    cls = 'crawlbar bad';
    title = 'Crawl failed';
    sub = esc(st.message||'');
  } else {
    title = stale ? 'Data may be stale' : 'Collectors idle';
    sub = lastTxt + (stale && ageH!==null ? ` &mdash; older than the ${staleH}h freshness window` : '');
  }

  const heavyCount = (st.catalog||[]).filter(c=>c.heavy).length;
  const btns = st.allow_manual
    ? `<button class="primary" onclick="startCrawl(false)">Run all collectors</button>`+
      `<button onclick="startCrawl(true)" title="Ignore each source's min_interval and re-crawl every non-slow catalog.">Force re-crawl all</button>`
    : `<button disabled title="dashboard.allow_manual_crawl is false in config/radar.yaml">Manual crawl disabled</button>`;
  if(heavyCount) sub += ` &middot; ${heavyCount} slow collector(s) excluded from "Run all" — run them individually below`;

  el.className = cls;
  el.innerHTML = `<span class="cdot"></span><div class="ctext">`+
    `<div class="ctitle">${title}</div><div class="csub">${sub}</div></div>`+
    `<div class="cbtns">${btns}</div>`+
    renderCatalog(st, false);
}

// One row per enabled collector, individually runnable regardless of the
// `heavy` (>5min normal runtime) flag that excludes it from "Run all
// collectors" above. Collapsed by default so the common case (click Run
// all, walk away) stays a one-line bar.
function renderCatalog(st, running){
  const cat = st.catalog || [];
  if(!cat.length) return '';
  const label = catalogOpen ? 'Hide individual collectors &#9650;' : `Show individual collectors (${cat.length}) &#9660;`;
  let rows = '';
  if(catalogOpen){
    rows = '<div class="catalog">' + cat.map(c => {
      const busy = running && st.current_source === c.id;
      const slow = c.heavy ? `<span class="slow" title="Normal runtime exceeds 5 minutes — excluded from Run all collectors">SLOW${c.runtime_note ? ' &middot; '+esc(c.runtime_note) : ''}</span>` : '';
      const dis = running ? 'disabled' : '';
      const btnLabel = busy ? 'Running&hellip;' : 'Run';
      return `<div class="catrow"><span class="cid"><b>${esc(c.manufacturer)}</b> &middot; ${esc(c.id)}</span>${slow}`+
        `<button ${dis} onclick="startCrawl(true,'${esc(c.id)}')" title="Run only this collector, ignoring its min_interval">${btnLabel}</button></div>`;
    }).join('') + '</div>';
  }
  return `<button class="ctoggle" onclick="toggleCatalog()">${label}</button>${rows}`;
}

function toggleCatalog(){
  catalogOpen = !catalogOpen;
  renderCrawl(lastCrawlState || {enabled:false});
}

function crawlApply(st){
  renderCrawl(st);
  if(st.running){
    crawlWasRunning = true;
    if(!crawlPollTimer) crawlPollTimer = setInterval(crawlPoll, 2000);
    return;
  }
  if(crawlPollTimer){ clearInterval(crawlPollTimer); crawlPollTimer = null; }
  // The whole point of the button is fresh data on the page. Reload only
  // when the crawl actually wrote something — a quiet crawl (every source
  // within its min_interval) should not throw away your scroll position.
  if(crawlWasRunning){
    crawlWasRunning = false;
    const o = st.outcome || {};
    if((o.events||0) > 0 || (o.snapshots||0) > 0){
      const el = document.getElementById('crawlbar');
      if(el) el.insertAdjacentHTML('beforeend',
        '<div class="csub" style="width:100%">New data &mdash; reloading&hellip;</div>');
      setTimeout(()=>location.reload(), 1200);
    }
  }
}

function crawlPoll(){
  fetch('/api/crawl/status').then(r=>r.json()).then(crawlApply).catch(()=>{});
}

function startCrawl(force, source){
  document.querySelectorAll('.crawlbar button').forEach(b=>b.disabled=true);
  const body = {force:!!force};
  if(source) body.source = source;  // per-collector run: bypasses the "Run all" heavy-collector exclusion server-side
  fetch('/api/crawl', {
    method:'POST',
    headers:{'Content-Type':'application/json','X-OEM-Radar-CSRF':CSRF},
    body:JSON.stringify(body),
  }).then(async r=>{
    const d = await r.json().catch(()=>({}));
    if(d.state) crawlApply(d.state); else crawlPoll();
  }).catch(()=>crawlPoll());
}

function renderStats(){
  const s=DATA.summary, fb=DATA.feedback_summary||{};
  const items=[["enabled_sources","Active OEMs"],["events","Alerts total"],
    ["unreviewed_events","Unreviewed"],[null,null],
    ["stories","Stories"],["unseen_components","Unseen parts"]];
  document.getElementById('gen').textContent = when(DATA.generated_at)+
    (s.last_run?(" · last crawl "+when(s.last_run)):"");

  const pct = v => v==null ? '—' : Math.round(v*100)+'%';
  const fbItems = [
    ["HIT", fb.hit_count, fb.hit_rate],
    ["Interesting", fb.interesting_count, fb.interesting_rate],
    ["Noise", fb.noise_count, fb.noise_rate],
    ["Bug", fb.bug_count, fb.bug_rate],
  ];
  const signalRate = fb.reviewed_alerts ? pct((fb.hit_count+fb.interesting_count)/fb.reviewed_alerts) : '—';

  const cells = [
    `<div class="stat"><div class="n mono">${s.enabled_sources??0}</div><div class="l">Active OEMs</div></div>`,
    `<div class="stat"><div class="n mono">${s.events??0}</div><div class="l">Product alerts</div></div>`,
    `<div class="stat"><div class="n mono">${s.evidence_items??0}</div><div class="l">Evidence records</div></div>`,
    `<div class="stat"><div class="n mono">${s.unreviewed_events??0}</div><div class="l">Unreviewed</div></div>`,
    `<div class="stat"><div class="n mono">${(fb.reviewed_alerts??0)}</div><div class="l">Reviewed</div></div>`,
    ...fbItems.map(([l,n,r])=>`<div class="stat"><div class="n mono">${n??0}</div><div class="l">${l} (${pct(r)})</div></div>`),
    `<div class="stat"><div class="n mono">${signalRate}</div><div class="l">Signal rate</div></div>`,
    `<div class="stat"><div class="n mono">${s.degraded_collectors??0}</div><div class="l">Degraded collectors</div></div>`,
    `<div class="stat"><div class="n mono">${s.failed_collectors??0}</div><div class="l">Failed collectors</div></div>`,
    `<div class="stat"><div class="n mono">${s.proposed_suggestions??0}</div><div class="l">Proposed suggestions</div></div>`,
  ];
  document.getElementById('stats').innerHTML = cells.join('');
}

function renderCta(){
  const unrev = DATA.summary.unreviewed_events||0;
  document.getElementById('review-cta').innerHTML =
    `<div class="msg">${unrev
      ? `<b>${unrev}</b> alert${unrev===1?'':'s'} awaiting review.`
      : 'All alerts reviewed.'}</div>`+
    `<a class="btn" href="/?tab=events&amp;review=UNREVIEWED">Review unreviewed alerts &rarr;</a>`+
    `<a class="btn" href="/feedback">Feedback &amp; suggestions &rarr;</a>`;

  // Baseline events (a source's first-ever crawl -- every product is
  // "new" by definition) are excluded from every count and list above by
  // design, not silently: this line is the acknowledgement, and the raw
  // rows stay inspectable at /api/baseline-events for diagnostics.
  const base = DATA.summary.baseline_events||0;
  const note = document.getElementById('baseline-note');
  if(note) note.innerHTML = base
    ? `${base} baseline record${base===1?'':'s'} from initial source crawl(s) — `+
      `excluded from the counts and lists above (not signal). `+
      `<a href="/api/baseline-events" target="_blank" rel="noopener">Inspect raw &rarr;</a>`
    : '';
}

function renderHealth(){
  const rows = DATA.collector_health||[];
  document.getElementById('health').innerHTML = rows.length ? rows.map(c=>
    `<div class="health-row"><span>${esc(c.source)}</span>`+
    `<span class="hstatus ${esc(c.health)}">${esc((c.health||'').toUpperCase())}</span></div>`
  ).join('') : '';
}


function renderStories(){
  const st=DATA.stories||[];
  document.getElementById('stories-list').innerHTML = st.length ? st.map(s=>{
    const ev=(s.evidence||[]).map(e=>{
      const label=`<b>${esc(e.manufacturer)}</b>: ${esc(e.model)}`;
      return e.source_url?`<a href="${esc(e.source_url)}" target="_blank" rel="noopener">${label}</a>`:label;
    }).join(' &nbsp;\u00b7&nbsp; ');
    return `<div class="card s5"><div class="thumb" style="display:flex;align-items:center;justify-content:center;font-size:26px">\uD83D\uDCF0</div>
      <div class="body"><div class="row1"><div class="title">${esc(s.title)}</div>
      <div class="when">${when(s.created_at)}</div></div>
      <div class="tags"><span class="badge" style="background:#5b2c83;border-color:#5b2c83;color:#fff">score ${s.score}/100</span>
        ${(s.manufacturers||[]).map(m=>`<span class="badge">${esc(m)}</span>`).join('')}</div>
      <div class="specs">${(s.reasons||[]).map(esc).join(' \u00b7 ')}</div>
      <div class="change">${ev}</div></div></div>`;
  }).join('') : '<div class="empty">No cross-OEM stories yet. They emerge when the same unseen part shows up across makers.</div>';
}

function renderSignals(){
  const sig=DATA.events.filter(e=>e.severity>=4||e.unseen_component);
  document.getElementById('signals-list').innerHTML = sig.length?sig.map(card).join('')
    :'<div class="empty">No high-priority signals yet. The radar is watching.</div>';
}

function renderEvents(){
  const q=document.getElementById('q').value.toLowerCase().trim();
  const man=document.getElementById('f-man').value, type=document.getElementById('f-type').value;
  const sev=+document.getElementById('f-sev').value;
  const revFilter=(document.getElementById('f-rev')||{}).value||'';
  const rows=DATA.events.filter(e=>{
    if(man && e.manufacturer!==man) return false;
    if(type && e.type!==type) return false;
    if(sev===5 && e.severity!==5) return false;
    if(sev && sev<5 && e.severity<sev) return false;
    if(revFilter){
      const st=e.review_status||'UNREVIEWED';
      if(st!==revFilter) return false;
    }
    if(q){const hay=[e.model,e.manufacturer,e.cpu,e.gpu,TYPE[e.type]].join(' ').toLowerCase();
      if(!hay.includes(q)) return false;}
    return true;
  });
  document.getElementById('events-count').textContent=
    rows.length+" of "+DATA.events.length+" product changes";
  const emptyMsg = (man && DATA.events.length>=300)
    ? `No product changes for ${esc(man)} in the most recent ${DATA.events.length} shown here `+
      `— a larger, more recent crawl elsewhere may have pushed ${esc(man)}'s changes off this page. `+
      `Its products still show under the Manufacturers view.`
    : (man
        ? `No product changes recorded for ${esc(man)} yet. It may be configured but not `+
          `crawled, or its source may be disabled — check the Runs and Manufacturers views.`
        : 'No product changes match these filters.');
  document.getElementById('events-list').innerHTML = rows.length?rows.map(card).join('')
    :`<div class="empty">${emptyMsg}</div>`;
}

function renderHardware(){
  const c=DATA.components;
  const bar=`<div class="hwbar"><div class="lead" style="margin:0">`+
    `Components first seen in the wild and not in the known list. Mark the ones `+
    `you recognise as <b>seen</b> so only genuinely novel silicon stays here.</div>`+
    (c.length?`<button class="btn" onclick="markAllSeen()">Mark all ${c.length} as seen</button>`:'')+
    `</div>`;
  document.getElementById('hw-list').innerHTML = bar + (c.length
    ? '<table><tr><th>Component</th><th>Kind</th><th>First raw string</th><th>First seen</th><th></th></tr>'+
      c.map(x=>`<tr><td><b>${esc(x.canonical_name)}</b></td><td>${esc(x.kind)}</td>`+
        `<td class="muted">${esc(x.first_raw||'')}</td><td class="when">${when(x.first_seen_at)}</td>`+
        `<td class="act"><button class="btn small" onclick="markSeen('${esc(x.canonical_name).replace(/'/g,"\\'")}')">Mark seen</button></td></tr>`).join('')+
      '</table>'
    : '<div class="empty">No previously-unseen hardware. Every component matches the known list. 🎯</div>');
}

async function markSeen(name){
  try{
    const r=await fetch('/api/mark-seen',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({names:[name]})});
    if(!r.ok) throw new Error(await r.text());
    location.reload();
  }catch(e){ alert('Could not mark seen: '+e.message); }
}
async function markAllSeen(){
  if(!confirm('Mark all '+DATA.components.length+' listed components as seen? '+
    'They will stay known (never re-alert) but leave this list.')) return;
  try{
    const r=await fetch('/api/mark-seen',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({all:true})});
    if(!r.ok) throw new Error(await r.text());
    location.reload();
  }catch(e){ alert('Could not mark all seen: '+e.message); }
}

function renderOems(){
  document.getElementById('oems-list').innerHTML =
    '<table><tr><th>Manufacturer</th><th>Products tracked</th></tr>'+
    DATA.manufacturers.map(m=>`<tr><td>${esc(m.name)}</td><td class="mono">${m.products}</td></tr>`).join('')+
    '</table>';
}

function renderRuns(){
  document.getElementById('runs-list').innerHTML = DATA.runs.length
    ? '<table><tr><th>Source</th><th>Started</th><th>Status</th><th>Snapshots</th><th>Changes</th><th>Errors</th></tr>'+
      DATA.runs.map(r=>`<tr><td>${esc(r.source)}</td><td class="when">${when(r.started_at)}</td>`+
        `<td>${esc(r.status)}</td><td class="mono">${r.snapshots??''}</td>`+
        `<td class="mono">${r.events??''}</td><td class="mono">${r.errors??''}</td></tr>`).join('')+
      '</table>'
    : '<div class="empty">No runs recorded yet.</div>';
}

// The ONE source of OEM names in this page. Server-side it is
// dashboard/data.py::collect_oem_registry, which reads the manufacturers
// registry that core.runner.sync_oem_registry keeps in step with
// config/oems/*.yaml. Never derive an OEM list from DATA.events (LIMIT-
// bounded), from filtered rows, from rendered cards, or from evidence —
// any of those silently drops OEMs that are quiet right now.
function oemRegistry(){ return (DATA.manufacturers||[]).map(m=>m.name); }

function initFilters(){
  const mans=oemRegistry();
  const oemOptions='<option value="">All OEMs</option>'+
    mans.map(m=>`<option>${esc(m)}</option>`).join('');
  // Both manufacturer controls are filled from the same call — there is
  // no second, almost-identical implementation to drift out of sync.
  document.getElementById('f-man').innerHTML=oemOptions;
  const evMan=document.getElementById('f-ev-man');
  if(evMan) evMan.innerHTML=oemOptions;
  // Same rule for change types: DATA.change_types is an unbounded DISTINCT
  // over product change_events, not a scan of the visible window.
  const types=DATA.change_types||[];
  document.getElementById('f-type').innerHTML='<option value="">All change types</option>'+
    types.map(t=>`<option value="${esc(t)}">${esc(TYPE[t]||t)}</option>`).join('');
  const ekinds=[...new Set((DATA.evidence_items||[]).map(e=>e.evidence_kind))].sort();
  const ev=document.getElementById('f-ev-kind');
  if(ev) ev.innerHTML='<option value="">All evidence kinds</option>'+
    ekinds.map(k=>`<option>${esc(k)}</option>`).join('');
  ['q','f-man','f-type','f-sev','f-rev'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.addEventListener('input',renderEvents);
  });
  ['ev-q','f-ev-man','f-ev-kind'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.addEventListener('input',renderEvidence);
  });
}

function activateTab(name){
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active', x.dataset.tab===name));
  document.querySelectorAll('.wrap > section').forEach(x=>x.classList.toggle('hide', x.id!==name));
  // Put the tab in the URL so reload — including the automatic one after
  // a crawl finishes — brings you back to the tab you were reading,
  // instead of dumping you on Stories.
  try{
    const u = new URL(location.href);
    u.searchParams.set('tab', name);
    history.replaceState(null, '', u);
  }catch(e){}
}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>activateTab(t.dataset.tab));

function renderEvidence(){
  const all = DATA.evidence_items||[];
  const q=((document.getElementById('ev-q')||{}).value||'').toLowerCase().trim();
  const man=(document.getElementById('f-ev-man')||{}).value||'';
  const kind=(document.getElementById('f-ev-kind')||{}).value||'';
  const items=all.filter(e=>{
    if(man && e.manufacturer!==man) return false;
    if(kind && e.evidence_kind!==kind) return false;
    if(q){const hay=[e.model,e.title,e.family,e.external_id,e.manufacturer].join(' ').toLowerCase();
      if(!hay.includes(q)) return false;}
    return true;
  });
  const cnt=document.getElementById('evidence-count');
  if(cnt) cnt.textContent=items.length+" of "+all.length+" evidence records"+
    (DATA.summary && DATA.summary.evidence_items>all.length
      ? " (most recent "+all.length+" of "+DATA.summary.evidence_items+" stored)" : "");
  // Every row links to /evidence/{id} — no dead cards, no rows that open
  // an alert page they were never going to have facts for.
  document.getElementById('evidence-list').innerHTML = items.length
    ? '<table><tr><th>Manufacturer</th><th>Kind</th><th>Provenance</th><th>Model / Title</th>'+
      '<th>Observed</th><th>Linked product</th><th></th></tr>'+
      items.map(e=>`<tr><td><a href="/evidence/${e.id}">${esc(e.manufacturer)}</a></td>`+
        `<td>${esc(e.evidence_kind)}</td>`+
        `<td class="muted">${esc(e.provenance)}</td>`+
        `<td><a href="/evidence/${e.id}">${esc(e.title||e.model||('#'+e.id))}</a>`+
        (e.description?`<div class="muted small">${esc(e.description)}</div>`:'')+`</td>`+
        `<td class="when">${when(e.observed_at)}</td>`+
        `<td>${e.linked_product_key?esc(e.linked_product_key)+' ('+esc(e.link_method)+')':'<span class="muted">unlinked</span>'}</td>`+
        `<td class="act"><a class="btn small" href="/evidence/${e.id}">Details &rarr;</a></td></tr>`).join('')+
      '</table>'
    : (all.length
        ? '<div class="empty">No evidence records match these filters.</div>'
        : '<div class="empty">No evidence records yet. Evidence sources run separately from collectors.</div>');
}

renderStats();renderCta();renderHealth();renderStories();renderSignals();initFilters();renderEvents();renderHardware();renderOems();renderRuns();renderEvidence();
crawlPoll();

// Deep-link support: /?tab=events&review=UNREVIEWED opens the Alerts tab
// pre-filtered (used by the "Review unreviewed alerts" CTA and nav).
(function(){
  const qs = new URLSearchParams(location.search);
  const tab = qs.get('tab');
  const review = qs.get('review');
  if(review){
    const sel = document.getElementById('f-rev');
    if(sel){ sel.value = review; renderEvents(); }
  }
  if(tab && document.getElementById(tab)) activateTab(tab);
})();
</script>
</body></html>"""


def render(data: dict, *, csrf_token: str = "") -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    # csrf_token is server-generated (secrets.token_urlsafe) so it has no
    # quote characters to escape, but json.dumps it anyway rather than
    # trusting that of a value the caller supplies.
    return (_PAGE.replace("__DATA__", payload)
                 .replace('"__CSRF__"', json.dumps(csrf_token)))



import html as _html


def _esc(s) -> str:
    if s is None:
        return ""
    return _html.escape(str(s), quote=True)


def render_review_page(detail: dict, csrf_token: str = "") -> str:
    """Self-contained review page for one change_event (alert)."""
    from ..core.feedback import reason_taxonomy, OUTCOMES

    d = detail
    review = d.get("review") or {}
    history = d.get("history") or []
    related = d.get("related_events") or []
    current_outcome = review.get("outcome") or ""
    current_reasons = set(review.get("reason_codes") or [])

    outcome_help = {
        "HIT": "Directly useful for an article, scoop, or actionable investigation.",
        "INTERESTING": "Valid signal worth retaining, but not immediately actionable.",
        "NOISE": "Technically correct but not editorially useful.",
        "BUG": "Parser failure, bad extraction, broken matching, or software defect.",
    }
    shortcut = {"HIT": "1", "INTERESTING": "2", "NOISE": "3", "BUG": "4"}

    outcomes_html = []
    for o in OUTCOMES:
        checked = "checked" if o == current_outcome else ""
        outcomes_html.append(
            f'<label class="out"><input type="radio" name="outcome" value="{_esc(o)}" {checked}> '
            f'<strong>{_esc(o)}</strong> <kbd>{shortcut[o]}</kbd>'
            f'<span class="hint">{_esc(outcome_help[o])}</span></label>'
        )

    # Group reasons
    groups: dict[str, list] = {}
    for r in reason_taxonomy():
        groups.setdefault(r["group"], []).append(r)
    reasons_html = []
    for group, items in groups.items():
        rows = []
        for it in items:
            chk = "checked" if it["code"] in current_reasons else ""
            rows.append(
                f'<label class="rc"><input type="checkbox" name="reason" value="{_esc(it["code"])}" {chk}> '
                f'{_esc(it["label"])} <code>{_esc(it["code"])}</code></label>'
            )
        reasons_html.append(f'<div class="rg"><div class="rg-h">{_esc(group)}</div>{"".join(rows)}</div>')

    hist_html = "<p class='muted'>No prior review changes.</p>"
    if history:
        lines = []
        for h in history:
            lines.append(
                f"<li><time>{_esc(h.get('changed_at'))}</time> "
                f"{_esc(h.get('previous_outcome') or '—')} → <strong>{_esc(h.get('new_outcome'))}</strong> "
                f"by {_esc(h.get('changed_by') or 'unknown')}"
                + (f" — {_esc(h.get('change_note'))}" if h.get("change_note") else "")
                + "</li>"
            )
        hist_html = "<ul class='hist'>" + "".join(lines) + "</ul>"

    rel_html = "<p class='muted'>No earlier events for this product key.</p>"
    if related:
        lines = []
        for r in related:
            lines.append(
                f'<li><a href="/alerts/{int(r["id"])}">#{int(r["id"])}</a> '
                f'{_esc(r.get("type"))} · sev { _esc(r.get("severity")) } · {_esc(r.get("detected_at"))}</li>'
            )
        rel_html = "<ul class='hist'>" + "".join(lines) + "</ul>"

    def fmt_val(v):
        if v is None:
            return "—"
        if isinstance(v, (dict, list)):
            import json as _json
            return _esc(_json.dumps(v, ensure_ascii=False)[:800])
        return _esc(str(v)[:800])

    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review alert #{_esc(d.get('id'))} · OEM Radar</title>
<style>
  :root{{--bg:#0d1017;--panel:#161b22;--line:#2a323d;--fg:#e6edf3;--muted:#8b98a5;--accent:#3fb950;}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.5 system-ui,sans-serif}}
  a{{color:#3f8cd6}} header{{padding:14px 24px;border-bottom:1px solid var(--line);
    display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}}
  header h1{{margin:0;font-size:16px}} .wrap{{max-width:960px;margin:0 auto;padding:20px 24px 60px}}
  nav.crumbs{{max-width:960px;margin:0 auto;padding:10px 24px 0;display:flex;
    gap:8px;flex-wrap:wrap;align-items:center}}
  nav.crumbs a{{background:var(--panel);border:1px solid var(--line);
    border-radius:20px;padding:6px 14px;font-size:12.5px;color:var(--fg)}}
  nav.crumbs a:hover{{border-color:var(--accent);color:var(--accent);text-decoration:none}}
  nav.crumbs .sep{{flex:1}}
  .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:16px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 18px}}
  .k{{color:var(--muted);font-size:12px}} .v{{font-weight:500}}
  .out,.rc{{display:block;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin:6px 0;cursor:pointer}}
  .out:has(input:checked),.rc:has(input:checked){{border-color:var(--accent);background:#132019}}
  .hint{{display:block;color:var(--muted);font-size:12px;margin-top:2px}}
  kbd{{background:#222;border:1px solid #444;border-radius:4px;padding:1px 5px;font-size:11px;margin-left:6px}}
  .rg{{margin-bottom:12px}} .rg-h{{color:var(--muted);font-size:12px;margin:8px 0 4px;text-transform:uppercase;letter-spacing:.4px}}
  label.rc code{{color:var(--muted);font-size:11px;margin-left:6px}}
  input[type=text],textarea{{width:100%;background:#1c232c;color:var(--fg);border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;font:inherit}}
  textarea{{min-height:72px}}
  button.save{{background:var(--accent);color:#04120a;border:0;border-radius:8px;padding:10px 18px;
    font-weight:650;cursor:pointer;margin-top:12px}}
  button.save:disabled{{opacity:.5}}
  .muted{{color:var(--muted)}} .hist{{padding-left:18px}} .status{{font-weight:650}}
  .flash{{padding:10px 12px;border-radius:8px;margin-bottom:12px;display:none}}
  .flash.ok{{display:block;background:#132019;border:1px solid var(--accent)}}
  .flash.err{{display:block;background:#2a1515;border:1px solid #c0392b}}
  pre.ev{{white-space:pre-wrap;word-break:break-word;background:#0b0e14;padding:10px;border-radius:8px;font-size:12px}}
</style></head><body>
<header>
  <h1><a href="/">OEM Radar</a> · Review alert #{_esc(d.get('id'))}</h1>
  <span class="status">{_esc(d.get('review_status') or 'UNREVIEWED')}</span>
</header>
<nav class="crumbs">
  <a href="/">&larr; Overview</a>
  <a href="/?tab=events">&larr; Alerts</a>
  <a href="/feedback">Feedback</a>
  <a href="/qc">Recently QCed</a>
  <span class="sep"></span>
  {"<a href='/alerts/"+str(int(d['prev_id']))+"'>&larr; Prev</a>" if d.get('prev_id') else ""}
  {"<a href='/alerts/"+str(int(d['next_id']))+"'>Next &rarr;</a>" if d.get('next_id') else ""}
</nav>
<div class="wrap">
  <div id="flash" class="flash"></div>
  <div class="panel">
    <div class="grid">
      <div><div class="k">Alert ID</div><div class="v">#{_esc(d.get('id'))}</div></div>
      <div><div class="k">Type</div><div class="v">{_esc(d.get('type'))}</div></div>
      <div><div class="k">OEM</div><div class="v">{_esc(d.get('manufacturer'))}</div></div>
      <div><div class="k">Collector</div><div class="v">{_esc(d.get('collector'))}</div></div>
      <div><div class="k">Product</div><div class="v">{_esc(d.get('model'))}</div></div>
      <div><div class="k">Product key</div><div class="v"><code>{_esc(d.get('product_key'))}</code></div></div>
      <div><div class="k">Detected</div><div class="v">{_esc(d.get('detected_at'))}</div></div>
      <div><div class="k">Confidence</div><div class="v">{_esc(d.get('confidence'))}</div></div>
      <div><div class="k">Severity</div><div class="v">{_esc(d.get('severity'))}</div></div>
      <div><div class="k">Listing</div><div class="v">{"<a href='"+_esc(d.get('url'))+"' target='_blank' rel='noopener'>open</a>" if d.get('url') else "—"}</div></div>
    </div>
    <div style="margin-top:12px">
      <div class="k">Change</div>
      <div class="v">field=<code>{_esc(d.get('field'))}</code></div>
      <pre class="ev">old: {fmt_val(d.get('old'))}
new: {fmt_val(d.get('new'))}
meta: {fmt_val(d.get('meta'))}</pre>
    </div>
  </div>

  <div class="panel">
    <h2 style="margin:0 0 8px;font-size:15px">Review</h2>
    <p class="muted" style="margin-top:0">Shortcuts 1–4 select outcome only (disabled while typing). Save explicitly.</p>
    <form id="review-form">
      <input type="hidden" name="csrf_token" value="{_esc(csrf_token)}">
      <div>{''.join(outcomes_html)}</div>
      <h3 style="font-size:13px;margin:16px 0 6px">Reason codes</h3>
      {''.join(reasons_html)}
      <div style="margin-top:12px">
        <label class="k">Reviewer</label>
        <input type="text" name="reviewer" maxlength="64" value="{_esc(review.get('reviewer'))}" autocomplete="username">
      </div>
      <div style="margin-top:10px">
        <label class="k">Reviewer note</label>
        <textarea name="reviewer_note" maxlength="2000">{_esc(review.get('reviewer_note'))}</textarea>
      </div>
      <div style="margin-top:10px">
        <label class="k">Change note (when updating)</label>
        <textarea name="change_note" maxlength="500" placeholder="Why this reclassification?"></textarea>
      </div>
      <button type="submit" class="save" id="save-btn">Save review</button>
    </form>
  </div>

  <div class="panel">
    <h2 style="margin:0 0 8px;font-size:15px">Review history</h2>
    {hist_html}
  </div>
  <div class="panel">
    <h2 style="margin:0 0 8px;font-size:15px">Related previous events</h2>
    {rel_html}
  </div>
</div>
<script>
(function(){{
  const form = document.getElementById('review-form');
  const flash = document.getElementById('flash');
  const alertId = {int(d.get('id') or 0)};
  const csrf = {_esc(csrf_token)!r};

  function isTypingTarget(el){{
    if(!el) return false;
    const tag = (el.tagName||'').toLowerCase();
    if(tag==='input'||tag==='textarea'||tag==='select') return true;
    if(el.isContentEditable) return true;
    return false;
  }}

  document.addEventListener('keydown', function(ev){{
    if(isTypingTarget(ev.target)) return;  // focus guard
    const map = {{'1':'HIT','2':'INTERESTING','3':'NOISE','4':'BUG'}};
    const outcome = map[ev.key];
    if(!outcome) return;
    const radio = form.querySelector('input[name=outcome][value="'+outcome+'"]');
    if(radio){{ radio.checked = true; radio.focus(); }}
    // do not submit
  }});

  form.addEventListener('submit', async function(ev){{
    ev.preventDefault();
    const outcomeEl = form.querySelector('input[name=outcome]:checked');
    if(!outcomeEl){{
      flash.className='flash err'; flash.textContent='Select an outcome.'; return;
    }}
    const reasons = [...form.querySelectorAll('input[name=reason]:checked')].map(x=>x.value);
    const body = {{
      outcome: outcomeEl.value,
      reason_codes: reasons,
      reviewer: form.reviewer.value || null,
      reviewer_note: form.reviewer_note.value || null,
      change_note: form.change_note.value || null,
      csrf_token: csrf,
    }};
    const btn = document.getElementById('save-btn');
    btn.disabled = true;
    try {{
      const resp = await fetch('/api/alerts/'+alertId+'/review', {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-OEM-Radar-CSRF': csrf,
        }},
        body: JSON.stringify(body),
      }});
      const data = await resp.json();
      if(!resp.ok){{
        flash.className='flash err';
        flash.textContent = (data.error && data.error.message) || ('HTTP '+resp.status);
      }} else {{
        flash.className='flash ok';
        flash.textContent = 'Saved as '+data.review.outcome+'. Reloading…';
        setTimeout(()=>location.reload(), 600);
      }}
    }} catch(e){{
      flash.className='flash err'; flash.textContent = String(e);
    }} finally {{
      btn.disabled = false;
    }}
  }});
}})();
</script>
</body></html>"""
    return page


def render_evidence_page(detail: dict) -> str:
    """Detail page for one evidence item.

    Deliberately not `render_review_page` with different labels. There is
    no outcome form here because evidence is not reviewed: HIT/INTERESTING/
    NOISE/BUG rate whether an *alert* was worth the journalist's attention,
    and an evidence record makes no such claim. The page's job is to show
    every fact the record carries, including the raw payload, so a human
    can judge it on the evidence rather than on a score."""
    import json as _json

    d = detail
    links = d.get("links") or []
    history = d.get("history") or []

    def field(k, v, mono=False):
        cls = "v mono" if mono else "v"
        return f'<div><div class="k">{_esc(k)}</div><div class="{cls}">{v or "—"}</div></div>'

    ident = "".join([
        field("Evidence ID", f"#{_esc(d.get('id'))}"),
        field("External ID", f"<code>{_esc(d.get('external_id'))}</code>", mono=True),
        field("Source", f"<code>{_esc(d.get('source_id'))}</code>"),
        field("Manufacturer", _esc(d.get("manufacturer"))),
        field("Evidence kind", _esc(d.get("evidence_kind"))),
        field("Provenance", _esc(d.get("provenance"))),
        field("Model", _esc(d.get("model"))),
        field("Family", _esc(d.get("family"))),
        field("SKU", _esc(d.get("sku")), mono=True),
        field("MPN", _esc(d.get("mpn")), mono=True),
        field("Version", _esc(d.get("version"))),
        field("Filename", _esc(d.get("filename"))),
        field("Region", _esc(d.get("region"))),
        field("Confidence", _esc(d.get("confidence"))),
        field("Published", _esc(d.get("published_at"))),
        field("Observed", _esc(d.get("observed_at"))),
        field("Content hash", f"<code>{_esc((d.get('content_hash') or '')[:32])}</code>", mono=True),
        field("Canonical URL",
              (f"<a href='{_esc(d.get('canonical_url'))}' target='_blank' rel='noopener'>"
               f"open at source &rarr;</a>") if d.get("canonical_url") else ""),
    ])

    if links and any(l.get("product_key") for l in links):
        rows = []
        for l in links:
            if not l.get("product_key"):
                continue
            label = _esc(l.get("model") or l["product_key"])
            rows.append(
                f"<tr><td>{label}</td><td><code>{_esc(l['product_key'])}</code></td>"
                f"<td>{_esc(l.get('method'))}</td><td>{_esc(l.get('confidence'))}</td>"
                f"<td>{_esc(l.get('created_at'))}</td></tr>"
            )
        links_html = ("<table><tr><th>Product</th><th>Product key</th><th>Method</th>"
                      "<th>Confidence</th><th>Linked at</th></tr>" + "".join(rows) + "</table>")
    else:
        method = links[0].get("method") if links else None
        links_html = (
            "<p class='muted'>Not linked to any tracked product"
            + (f" (correlation method attempted: <code>{_esc(method)}</code>)" if method else "")
            + ". This is a deliberate outcome, not a failure — identity linking is exact-match "
              "only (SKU, MPN, exact model string, or explicit alias). A guess here would "
              "attach an official record to the wrong machine.</p>"
        )

    if history:
        hist_html = "<ul class='hist'>" + "".join(
            f"<li><time>{_esc(h.get('detected_at'))}</time> — "
            f"<strong>{_esc(h.get('event_type'))}</strong></li>" for h in history
        ) + "</ul>"
    else:
        hist_html = ("<p class='muted'>No recorded observation events. The item exists but "
                     "predates the evidence event log (schema v7).</p>")

    raw = d.get("raw_data") or {}
    raw_html = _esc(_json.dumps(raw, indent=2, ensure_ascii=False)[:8000]) if raw else "—"

    prev_link = (f"<a href='/evidence/{int(d['prev_id'])}'>&larr; Prev</a>"
                 if d.get("prev_id") else "")
    next_link = (f"<a href='/evidence/{int(d['next_id'])}'>Next &rarr;</a>"
                 if d.get("next_id") else "")

    title = _esc(d.get("title") or d.get("model") or f"Evidence #{d.get('id')}")

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Evidence · OEM Radar</title>
<style>
  :root{{--bg:#0d1017;--panel:#161b22;--line:#2a323d;--fg:#e6edf3;--muted:#8b98a5;--accent:#3fb950;}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.5 system-ui,sans-serif}}
  a{{color:#3f8cd6}} header{{padding:14px 24px;border-bottom:1px solid var(--line);
    display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}}
  header h1{{margin:0;font-size:16px}} .wrap{{max-width:960px;margin:0 auto;padding:20px 24px 60px}}
  nav.crumbs{{max-width:960px;margin:0 auto;padding:10px 24px 0;display:flex;
    gap:8px;flex-wrap:wrap;align-items:center}}
  nav.crumbs a{{background:var(--panel);border:1px solid var(--line);
    border-radius:20px;padding:6px 14px;font-size:12.5px;color:var(--fg)}}
  nav.crumbs a:hover{{border-color:var(--accent);color:var(--accent);text-decoration:none}}
  nav.crumbs .sep{{flex:1}}
  .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:16px 18px;margin-bottom:16px}}
  .panel h2{{margin:0 0 10px;font-size:15px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px 18px}}
  .k{{color:var(--muted);font-size:12px}} .v{{font-weight:500;overflow-wrap:anywhere}}
  .mono{{font-family:ui-monospace,monospace;font-size:12.5px}}
  .muted{{color:var(--muted)}} .hist{{padding-left:18px}}
  .kindtag{{font-size:11px;padding:2px 9px;border-radius:20px;background:#2a1f4d;
    border:1px solid #4a3a7d;color:#c9b6ff;font-weight:650}}
  table{{width:100%;border-collapse:collapse}}
  td,th{{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}}
  th{{color:var(--muted);font-weight:500}}
  pre.raw{{white-space:pre-wrap;word-break:break-word;background:#0b0e14;padding:12px;
    border-radius:8px;font-size:12px;max-height:420px;overflow:auto}}
  .note{{border-left:3px solid var(--accent);padding-left:12px;color:var(--muted);font-size:13px}}
</style></head><body>
<header>
  <h1><a href="/">OEM Radar</a> · Evidence #{_esc(d.get('id'))}</h1>
  <span class="kindtag">{_esc(d.get('evidence_kind'))}</span>
</header>
<nav class="crumbs">
  <a href="/">&larr; Overview</a>
  <a href="/?tab=evidence">&larr; Evidence</a>
  <a href="/?tab=events">Product alerts</a>
  <span class="sep"></span>
  {prev_link}
  {next_link}
</nav>
<div class="wrap">
  <div class="panel">
    <h2>{title}</h2>
    {f'<p class="muted">{_esc(d.get("description"))}</p>' if d.get("description") else ''}
    <div class="grid">{ident}</div>
  </div>

  <div class="panel">
    <h2>Linked products</h2>
    {links_html}
  </div>

  <div class="panel">
    <h2>Observation history</h2>
    {hist_html}
  </div>

  <div class="panel">
    <h2>Raw source payload</h2>
    <pre class="raw">{raw_html}</pre>
  </div>

  <div class="panel">
    <h2>Why there is no review form here</h2>
    <p class="note">HIT / INTERESTING / NOISE / BUG rate whether a <b>product alert</b> earned
      your attention. An evidence record is a statement that an official source lists
      something — it makes no editorial claim to rate. Forcing it through the alert review
      queue would corrupt the signal-rate metrics that queue exists to produce.</p>
  </div>
</div>
</body></html>"""


def render_feedback_page(metrics: dict, suggestions: list, csrf_token: str = "") -> str:
    import html as _html
    import json as _json

    def esc(s):
        return _html.escape(str(s) if s is not None else "", quote=True)

    s = metrics.get("summary") or {}
    rankings = metrics.get("rankings") or {}

    def cards():
        items = [
            ("Total alerts", s.get("total_alerts")),
            ("Reviewed", s.get("reviewed_alerts")),
            ("Unreviewed", s.get("unreviewed_alerts")),
            ("Completion", s.get("review_completion_rate")),
            ("HIT", s.get("hit_count")),
            ("Interesting", s.get("interesting_count")),
            ("Noise", s.get("noise_count")),
            ("Bug", s.get("bug_count")),
            ("Signal", s.get("signal_count")),
            ("S/N", s.get("signal_to_noise_ratio") if not s.get("signal_to_noise_infinite") else "∞"),
        ]
        return "".join(
            f'<div class="stat"><div class="n">{esc(v if not isinstance(v, float) else f"{v:.2f}")}</div>'
            f'<div class="l">{esc(k)}</div></div>'
            for k, v in items
        )

    def rank_table(title, rows, key="key"):
        if not rows:
            return f"<div class='panel'><h3>{esc(title)}</h3><p class='muted'>None</p></div>"
        body = "".join(
            f"<tr><td>{esc(r.get(key))}</td><td>{esc(r.get('noise_rate') or r.get('unreviewed') or r.get('noise') or r.get('hit') or '')}</td></tr>"
            for r in rows[:10]
        )
        return f"<div class='panel'><h3>{esc(title)}</h3><table><tbody>{body}</tbody></table></div>"

    sug_rows = []
    for r in suggestions:
        sug_rows.append(
            f"<tr><td>{esc(r.get('id'))}</td><td>{esc(r.get('status'))}</td>"
            f"<td>{esc(r.get('collector'))}</td><td>{esc(r.get('alert_type'))}</td>"
            f"<td>{esc((r.get('explanation') or r.get('suggested_rule') or '')[:120])}</td>"
            f"<td>{esc(r.get('supporting_alert_count'))}</td>"
            f"<td>{esc(r.get('estimated_noise_reduction'))}</td>"
            f"<td>{esc(r.get('estimated_signal_loss') or r.get('estimated_hit_loss'))}</td></tr>"
        )
    sug_html = (
        "<table><thead><tr><th>ID</th><th>Status</th><th>Collector</th><th>Type</th>"
        "<th>Explanation</th><th>N</th><th>Noise↓</th><th>Signal↓</th></tr></thead>"
        f"<tbody>{''.join(sug_rows) or '<tr><td colspan=8>No suggestions yet. Run: oem-radar feedback analyze</td></tr>'}</tbody></table>"
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Feedback · OEM Radar</title>
<style>
:root{{--bg:#0d1017;--panel:#161b22;--line:#2a323d;--fg:#e6edf3;--muted:#8b98a5;--accent:#3fb950}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
a{{color:#3f8cd6}} header{{padding:14px 24px;border-bottom:1px solid var(--line)}}
.wrap{{max-width:1080px;margin:0 auto;padding:20px 24px}}
nav.crumbs{{max-width:1080px;margin:0 auto;padding:10px 24px 0;display:flex;gap:8px;flex-wrap:wrap}}
nav.crumbs a{{background:var(--panel);border:1px solid var(--line);
  border-radius:20px;padding:6px 14px;font-size:12.5px;color:var(--fg)}}
nav.crumbs a:hover{{border-color:var(--accent);color:var(--accent);text-decoration:none}}
nav.crumbs a.here{{border-color:var(--accent);color:var(--accent)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin-bottom:18px}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}}
.stat .n{{font-size:20px;font-weight:650}} .stat .l{{color:var(--muted);font-size:12px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}}
.muted{{color:var(--muted)}} .warn{{color:#e8912d}}
</style></head><body>
<header><h1><a href="/">OEM Radar</a> · Feedback analytics</h1>
<p class="muted">Signal = HIT + INTERESTING. BUG is not noise. Suggestions never auto-activate.
Status IMPLEMENTED is recordkeeping only — it does not modify collectors.</p>
</header>
<nav class="crumbs">
  <a href="/">&larr; Overview</a>
  <a href="/?tab=events">Alerts</a>
  <a href="/feedback" class="here">Feedback</a>
  <a href="/qc">Recently QCed</a>
</nav>
<div class="wrap">
  <div class="stats">{cards()}</div>
  <h2 style="font-size:14px;margin:18px 0 4px">Analytics <span class="muted" style="font-weight:400">— observed outcomes, no rule changes</span></h2>
  {rank_table("Noisiest collectors", rankings.get("noisiest_collectors") or [])}
  {rank_table("Highest-HIT collectors", rankings.get("highest_hit_rate_collectors") or [])}
  {rank_table("Common NOISE reasons", rankings.get("most_common_noise_reasons") or [])}
  {rank_table("Common BUG reasons", rankings.get("most_common_bug_reasons") or [])}
  {rank_table("Oldest unreviewed", rankings.get("oldest_unreviewed_alerts") or [], key="id")}
  <h2 style="font-size:14px;margin:18px 0 4px">Proposed rules <span class="muted" style="font-weight:400">— deterministic suggestions, never auto-activated</span></h2>
  <div class="panel">
    <h3>Rule suggestions</h3>
    <p class="warn">No Activate control. Accept/Reject is manual approval only.</p>
    {sug_html}
  </div>
</div>
</body></html>"""


def render_qc_page(recent: list, csrf_token: str = "") -> str:
    """"Recently QCed" -- the fleet-wide QC-archive contract's own tab:
    every alert whose reviewer decision (HIT/INTERESTING/NOISE/BUG --
    OEM Radar's domain-appropriate equivalent of Useful/Not useful/False
    positive/Out of stock; see core.qc_archive) has been archived and
    taken out of the active Alerts queue. Read-only: this page has no
    "undo" -- reopening a QC'd alert (if ever needed) is a direct DB
    action, same as every other fleet clank's QC archive."""
    import html as _html

    def esc(s):
        return _html.escape(str(s) if s is not None else "", quote=True)

    _DECISION_CLASS = {"HIT": "hit", "INTERESTING": "interesting",
                       "NOISE": "noise", "BUG": "bug"}

    def row(r):
        cls = _DECISION_CLASS.get(r.get("decision"), "")
        note = esc(r.get("note") or "")
        return (
            f"<tr><td>{esc(r.get('decided_at'))}</td>"
            f"<td><span class='qcdot {cls}'>{esc(r.get('decision'))}</span></td>"
            f"<td><a href='/alerts/{esc(r.get('alert_id'))}'>#{esc(r.get('alert_id'))}</a></td>"
            f"<td>{esc(r.get('source_key'))}</td>"
            f"<td>{esc(r.get('product_key'))}</td>"
            f"<td>{esc(r.get('change_type'))}</td>"
            f"<td>{esc(r.get('decided_by') or '')}</td>"
            f"<td>{note}</td></tr>"
        )

    body = "".join(row(r) for r in recent) or (
        "<tr><td colspan=8 class='muted'>No QC decisions archived yet. "
        "Review an alert to archive its first decision here.</td></tr>"
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Recently QCed &middot; OEM Radar</title>
<style>
:root{{--bg:#0d1017;--panel:#161b22;--line:#2a323d;--fg:#e6edf3;--muted:#8b98a5;--accent:#3fb950}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
a{{color:#3f8cd6}} header{{padding:14px 24px;border-bottom:1px solid var(--line)}}
.wrap{{max-width:1080px;margin:0 auto;padding:20px 24px}}
nav.crumbs{{max-width:1080px;margin:0 auto;padding:10px 24px 0;display:flex;gap:8px;flex-wrap:wrap}}
nav.crumbs a{{background:var(--panel);border:1px solid var(--line);
  border-radius:20px;padding:6px 14px;font-size:12.5px;color:var(--fg)}}
nav.crumbs a:hover{{border-color:var(--accent);color:var(--accent);text-decoration:none}}
nav.crumbs a.here{{border-color:var(--accent);color:var(--accent)}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}}
.muted{{color:var(--muted)}}
.qcdot{{font-size:10.5px;font-weight:700;border-radius:20px;padding:2px 9px;white-space:nowrap}}
.qcdot.hit{{color:#0b1f12;background:#3fb950}} .qcdot.interesting{{color:#0b1f12;background:#6ab0f3}}
.qcdot.noise{{color:var(--muted);background:var(--line)}} .qcdot.bug{{color:#fff;background:#c0392b}}
</style></head><body>
<header><h1><a href="/">OEM Radar</a> &middot; Recently QCed</h1>
<p class="muted">Every alert here has been archived to a separate QC ledger
(oem_radar_qc.db) with a full snapshot and provenance, and has left the
active Alerts queue. No notifications are sent by a QC decision.</p>
</header>
<nav class="crumbs">
  <a href="/">&larr; Overview</a>
  <a href="/?tab=events">Alerts</a>
  <a href="/feedback">Feedback</a>
  <a href="/qc" class="here">Recently QCed</a>
</nav>
<div class="wrap">
  <div class="panel">
    <table><thead><tr><th>Decided</th><th>Decision</th><th>Alert</th>
      <th>Source</th><th>Product</th><th>Change type</th><th>By</th><th>Note</th></tr></thead>
      <tbody>{body}</tbody></table>
  </div>
</div>
</body></html>"""
