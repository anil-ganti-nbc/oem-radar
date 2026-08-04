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
</style></head>
<body>
<header>
  <h1>OEM&nbsp;<span class="dot">&#9673;</span>&nbsp;Radar</h1>
  <span class="gen">updated <span id="gen"></span> &middot;
    <a class="reload" onclick="location.reload()">reload</a></span>
</header>
<div class="wrap">
  <div class="stats" id="stats"></div>
  <div class="tabs">
    <div class="tab active" data-tab="stories">Stories</div>
    <div class="tab" data-tab="signals">Signals</div>
    <div class="tab" data-tab="events">All changes</div>
    <div class="tab" data-tab="hardware">Unseen hardware</div>
    <div class="tab" data-tab="oems">Manufacturers</div>
    <div class="tab" data-tab="runs">Runs</div>
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
    </div>
    <div class="count" id="events-count"></div>
    <div id="events-list" class="list"></div>
  </section>

  <section id="hardware" class="hide"><div id="hw-list"></div></section>
  <section id="oems" class="hide"><div id="oems-list"></div></section>
  <section id="runs" class="hide"><div id="runs-list"></div></section>
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
  const tags=[`<span class="badge type">${esc(TYPE[e.type]||e.type)}</span>`,
    `<span class="stars">${stars(e.severity)}</span>`];
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

function renderStats(){
  const s=DATA.summary;
  const items=[["products","Products"],["snapshots","Snapshots"],["events","Changes seen"],
    ["stories","Stories"],["unseen_components","Unseen parts"],["manufacturers","OEMs"],["pending_notifications","Queued"]];
  document.getElementById('gen').textContent = when(DATA.generated_at)+
    (s.last_run?(" · last crawl "+when(s.last_run)):"");
  document.getElementById('stats').innerHTML = items.map(([k,l])=>
    `<div class="stat"><div class="n mono">${s[k]??0}</div><div class="l">${l}</div></div>`).join('');
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
  const rows=DATA.events.filter(e=>{
    if(man && e.manufacturer!==man) return false;
    if(type && e.type!==type) return false;
    if(sev===5 && e.severity!==5) return false;
    if(sev && sev<5 && e.severity<sev) return false;
    if(q){const hay=[e.model,e.manufacturer,e.cpu,e.gpu,TYPE[e.type]].join(' ').toLowerCase();
      if(!hay.includes(q)) return false;}
    return true;
  });
  document.getElementById('events-count').textContent=
    rows.length+" of "+DATA.events.length+" changes";
  document.getElementById('events-list').innerHTML = rows.length?rows.map(card).join('')
    :'<div class="empty">No changes match these filters.</div>';
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

function initFilters(){
  const mans=[...new Set(DATA.events.map(e=>e.manufacturer).filter(Boolean))].sort();
  document.getElementById('f-man').innerHTML='<option value="">All OEMs</option>'+
    mans.map(m=>`<option>${esc(m)}</option>`).join('');
  const types=[...new Set(DATA.events.map(e=>e.type))].sort();
  document.getElementById('f-type').innerHTML='<option value="">All change types</option>'+
    types.map(t=>`<option value="${esc(t)}">${esc(TYPE[t]||t)}</option>`).join('');
  ['q','f-man','f-type','f-sev'].forEach(id=>
    document.getElementById(id).addEventListener('input',renderEvents));
}

document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.wrap > section').forEach(x=>x.classList.add('hide'));
  t.classList.add('active');
  document.getElementById(t.dataset.tab).classList.remove('hide');
});

renderStats();renderStories();renderSignals();initFilters();renderEvents();renderHardware();renderOems();renderRuns();
</script>
</body></html>"""


def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _PAGE.replace("__DATA__", payload)
