from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from dashboard import DashboardService

app = FastAPI(title="Xaloc Realtime Dashboard", version="2.0.0")
service = DashboardService()


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return """
<!doctype html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Xaloc Dashboard</title>
<style>
body{font-family:Segoe UI,Tahoma,sans-serif;background:#f6f8fb;color:#1f2937;margin:0}
.wrap{max-width:980px;margin:40px auto;padding:16px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px}
a.btn{display:inline-block;padding:10px 14px;border:1px solid #d1d5db;border-radius:10px;color:#111827;text-decoration:none;margin-right:10px}
a.btn:hover{background:#f3f4f6}
</style></head>
<body><div class="wrap"><div class="card">
<h2>Dashboard</h2>
<p>Selecciona una pantalla:</p>
<a class="btn" href="/historico">Historico</a>
<a class="btn" href="/colas">Colas actuales</a>
</div></div></body></html>
"""


@app.get("/historico", response_class=HTMLResponse)
async def historico_view() -> str:
    return """
<!doctype html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Historico</title>
<style>
body{font-family:Segoe UI,Tahoma,sans-serif;background:#f6f8fb;color:#1f2937;margin:0}
.wrap{max-width:1400px;margin:0 auto;padding:16px}
.top{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid #eef2f7;text-align:left;vertical-align:top}
th{background:#f9fafb;position:sticky;top:0}
.tbl-wrap{max-height:72vh;overflow:auto}
.pill{display:inline-block;border:1px solid #d1d5db;border-radius:999px;padding:2px 8px;font-size:12px;cursor:pointer;background:#fff}
.pill.active{background:#111827;color:#fff;border-color:#111827}
.muted{color:#6b7280;font-size:12px}
button{border:1px solid #d1d5db;border-radius:8px;background:#fff;padding:6px 10px;cursor:pointer}
</style></head>
<body>
<div class="wrap">
  <div class="top card">
    <a href="/">Inicio</a>
    <strong>Historico</strong>
    <span class="muted">Dia:</span>
    <div id="days"></div>
    <button id="prevDays">Dias previos</button>
    <button id="nextDays">Dias siguientes</button>
    <button id="refresh">Refresh</button>
    <span class="muted" id="lastUpdate"></span>
  </div>
  <div class="grid">
    <div class="card">
      <h3>Incidencias</h3>
      <div class="muted" id="inc-meta"></div>
      <div class="tbl-wrap"><table id="inc-table"><thead><tr><th>Site</th><th>Recurso</th><th>Tipo</th><th>Motivo</th><th>Inicio</th><th>Fin</th></tr></thead><tbody></tbody></table></div>
    </div>
    <div class="card">
      <h3>Exitos</h3>
      <div class="muted" id="ok-meta"></div>
      <div class="tbl-wrap"><table id="ok-table"><thead><tr><th>Site</th><th>Recurso</th><th>Job</th><th>Protocol</th><th>Inicio</th><th>Fin</th></tr></thead><tbody></tbody></table></div>
    </div>
  </div>
</div>
<script>
let daysPage=1; let selectedDay=null;
async function fetchJson(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}
function fmt(v){if(!v)return ''; const d=new Date(v); return Number.isNaN(d.getTime())?v:d.toLocaleString();}
function renderRows(tableId,rows,mapFn){const tb=document.querySelector(`#${tableId} tbody`);tb.innerHTML='';rows.forEach(r=>{const tr=document.createElement('tr');tr.innerHTML=mapFn(r);tb.appendChild(tr);});}
async function loadDays(){const d=await fetchJson(`/api/history/days?source=all&page=${daysPage}&page_size=10`);const c=document.getElementById('days');c.innerHTML='';if(!d.items.length){selectedDay=new Date().toISOString().slice(0,10);const s=document.createElement('span');s.className='muted';s.textContent='Sin datos';c.appendChild(s);return;}if(!selectedDay||!d.items.includes(selectedDay))selectedDay=d.items[0];d.items.forEach(day=>{const e=document.createElement('span');e.className='pill'+(day===selectedDay?' active':'');e.textContent=day;e.onclick=()=>{selectedDay=day;loadAll();};c.appendChild(e);});}
async function loadAll(){await loadDays();const day=selectedDay||new Date().toISOString().slice(0,10);const [inc,ok]=await Promise.all([fetchJson(`/api/history/incidents?day=${day}&page=1&page_size=200`),fetchJson(`/api/history/successes?day=${day}&page=1&page_size=200`)]);document.getElementById('inc-meta').textContent=`Dia ${day} - total ${inc.total}`;document.getElementById('ok-meta').textContent=`Dia ${day} - total ${ok.total}`;renderRows('inc-table',inc.items,r=>`<td>${r.site_id||''}</td><td>${r.resource_id??''}</td><td>${r.incident_type||''}</td><td>${(r.reason||'').slice(0,160)}</td><td>${fmt(r.started_at)}</td><td>${fmt(r.ended_at)}</td>`);renderRows('ok-table',ok.items,r=>`<td>${r.site_id||''}</td><td>${r.resource_id??''}</td><td>${r.job_id||''}</td><td>${r.protocol||''}</td><td>${fmt(r.started_at)}</td><td>${fmt(r.ended_at)}</td>`);document.getElementById('lastUpdate').textContent='Actualizado: '+new Date().toLocaleTimeString();}
document.getElementById('prevDays').onclick=async()=>{daysPage+=1;await loadAll();};
document.getElementById('nextDays').onclick=async()=>{daysPage=Math.max(1,daysPage-1);await loadAll();};
document.getElementById('refresh').onclick=loadAll;
setInterval(loadAll,5000); loadAll();
</script></body></html>
"""


@app.get("/colas", response_class=HTMLResponse)
async def colas_view() -> str:
    return """
<!doctype html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Colas actuales</title>
<style>
body{font-family:Segoe UI,Tahoma,sans-serif;background:#f6f8fb;color:#1f2937;margin:0}
.wrap{max-width:1200px;margin:0 auto;padding:16px}
.top{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid #eef2f7;text-align:left;vertical-align:top}
th{background:#f9fafb;position:sticky;top:0}
.tbl-wrap{max-height:76vh;overflow:auto}
.pill{display:inline-block;border:1px solid #d1d5db;border-radius:999px;padding:2px 8px;font-size:12px;cursor:pointer;background:#fff}
.pill.active{background:#111827;color:#fff;border-color:#111827}
.muted{color:#6b7280;font-size:12px}
button{border:1px solid #d1d5db;border-radius:8px;background:#fff;padding:6px 10px;cursor:pointer}
</style></head>
<body>
<div class="wrap">
  <div class="top card">
    <a href="/">Inicio</a>
    <strong>Colas actuales</strong>
    <span class="muted">Dia:</span><div id="days"></div>
    <button id="prevDays">Dias previos</button>
    <button id="nextDays">Dias siguientes</button>
    <button id="refresh">Refresh</button>
    <span class="muted" id="lastUpdate"></span>
  </div>
  <div class="card" style="margin-top:12px">
    <div class="muted" id="queue-meta"></div>
    <div class="tbl-wrap"><table id="queue-table"><thead><tr><th>Site</th><th>Recurso</th><th>Estado</th><th>Protocol</th><th>Inicio</th><th>Fin</th></tr></thead><tbody></tbody></table></div>
  </div>
</div>
<script>
let daysPage=1; let selectedDay=null;
async function fetchJson(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}
function fmt(v){if(!v)return ''; const d=new Date(v); return Number.isNaN(d.getTime())?v:d.toLocaleString();}
function renderRows(rows){const tb=document.querySelector('#queue-table tbody');tb.innerHTML='';rows.forEach(r=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${r.site_id||''}</td><td>${r.resource_id??''}</td><td>${r.state||''}</td><td>${r.protocol||''}</td><td>${fmt(r.started_at)}</td><td>${fmt(r.ended_at)}</td>`;tb.appendChild(tr);});}
async function loadDays(){const d=await fetchJson(`/api/queue/days?page=${daysPage}&page_size=10`);const c=document.getElementById('days');c.innerHTML='';if(!d.items.length){selectedDay=new Date().toISOString().slice(0,10);const s=document.createElement('span');s.className='muted';s.textContent='Sin datos';c.appendChild(s);return;}if(!selectedDay||!d.items.includes(selectedDay))selectedDay=d.items[0];d.items.forEach(day=>{const e=document.createElement('span');e.className='pill'+(day===selectedDay?' active':'');e.textContent=day;e.onclick=()=>{selectedDay=day;loadAll();};c.appendChild(e);});}
async function loadAll(){await loadDays();const day=selectedDay||new Date().toISOString().slice(0,10);const q=await fetchJson(`/api/queue/current?day=${day}&page=1&page_size=300`);document.getElementById('queue-meta').textContent=`Dia ${day} - total ${q.total}`;renderRows(q.items);document.getElementById('lastUpdate').textContent='Actualizado: '+new Date().toLocaleTimeString();}
document.getElementById('prevDays').onclick=async()=>{daysPage+=1;await loadAll();};
document.getElementById('nextDays').onclick=async()=>{daysPage=Math.max(1,daysPage-1);await loadAll();};
document.getElementById('refresh').onclick=loadAll;
setInterval(loadAll,5000); loadAll();
</script></body></html>
"""


@app.get("/api/history/days")
async def api_history_days(
    source: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> dict:
    return service.list_history_days(source=source, page=page, page_size=page_size)


@app.get("/api/history/incidents")
async def api_history_incidents(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return service.list_history_incidents(day=day, page=page, page_size=page_size)


@app.get("/api/history/successes")
async def api_history_successes(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return service.list_history_successes(day=day, page=page, page_size=page_size)


@app.get("/api/queue/days")
async def api_queue_days(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> dict:
    return service.list_queue_days(page=page, page_size=page_size)


@app.get("/api/queue/current")
async def api_queue_current(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return service.list_queue_current(day=day, page=page, page_size=page_size)
