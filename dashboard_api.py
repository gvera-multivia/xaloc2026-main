from __future__ import annotations

import os
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from core.dashboard_data import DashboardDataSource

app = FastAPI(title="Xaloc Realtime Dashboard", version="1.0.0")

data_source = DashboardDataSource(
    sqlite_db_path=os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db"),
    pg_dsn=os.getenv("REPORT_PG_DSN"),
    queue_backend=os.getenv("QUEUE_BACKEND", "sqlite"),
)


@app.get("/", response_class=HTMLResponse)
async def dashboard_home() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Xaloc Dashboard</title>
  <style>
    body { font-family: "Segoe UI", Tahoma, sans-serif; margin: 0; background: #f7fafc; color: #1f2937; }
    .wrap { max-width: 1400px; margin: 0 auto; padding: 16px; }
    .top { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px; }
    .grid { display: grid; grid-template-columns: 1fr; gap: 12px; margin-top: 12px; }
    @media (min-width: 1200px) { .grid { grid-template-columns: 1fr 1fr 1fr; } }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 6px 8px; border-bottom: 1px solid #eef2f7; text-align: left; vertical-align: top; }
    th { background: #f9fafb; position: sticky; top: 0; }
    .tbl-wrap { max-height: 65vh; overflow: auto; }
    .pill { display: inline-block; border: 1px solid #d1d5db; border-radius: 999px; padding: 2px 8px; font-size: 12px; cursor: pointer; background: #fff; }
    .pill.active { background: #111827; color: #fff; border-color: #111827; }
    .muted { color: #6b7280; font-size: 12px; }
    button { border: 1px solid #d1d5db; border-radius: 8px; background: #fff; padding: 6px 10px; cursor: pointer; }
    button:hover { background: #f3f4f6; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top card">
      <strong>Realtime Dashboard</strong>
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
        <h3>Encolados (actual)</h3>
        <div class="muted" id="queue-meta"></div>
        <div class="tbl-wrap"><table id="queue-table"><thead><tr><th>Site</th><th>Recurso</th><th>Estado</th><th>Protocol</th><th>Inicio</th></tr></thead><tbody></tbody></table></div>
      </div>
      <div class="card">
        <h3>Exitos</h3>
        <div class="muted" id="ok-meta"></div>
        <div class="tbl-wrap"><table id="ok-table"><thead><tr><th>Site</th><th>Recurso</th><th>Job</th><th>Protocol</th><th>Inicio</th><th>Fin</th></tr></thead><tbody></tbody></table></div>
      </div>
    </div>
  </div>

  <script>
    let daysPage = 1;
    let selectedDay = null;

    async function fetchJson(url) {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      return await res.json();
    }

    function formatTs(v) {
      if (!v) return "";
      const d = new Date(v);
      if (Number.isNaN(d.getTime())) return v;
      return d.toLocaleString();
    }

    function renderRows(tableId, rows, mapFn) {
      const tbody = document.querySelector(`#${tableId} tbody`);
      tbody.innerHTML = "";
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = mapFn(row);
        tbody.appendChild(tr);
      });
    }

    async function loadDays() {
      const data = await fetchJson(`/api/days?source=all&page=${daysPage}&page_size=10`);
      const container = document.getElementById("days");
      container.innerHTML = "";
      if (!data.items.length) {
        selectedDay = new Date().toISOString().slice(0, 10);
        const span = document.createElement("span");
        span.className = "muted";
        span.textContent = "Sin datos historicos";
        container.appendChild(span);
        return;
      }
      if (!selectedDay || !data.items.includes(selectedDay)) selectedDay = data.items[0];
      data.items.forEach((day) => {
        const el = document.createElement("span");
        el.className = "pill" + (day === selectedDay ? " active" : "");
        el.textContent = day;
        el.onclick = () => { selectedDay = day; loadAll(); };
        container.appendChild(el);
      });
    }

    async function loadAll() {
      await loadDays();
      const day = selectedDay || new Date().toISOString().slice(0, 10);
      const [inc, queue, ok] = await Promise.all([
        fetchJson(`/api/incidents?day=${day}&page=1&page_size=200`),
        fetchJson(`/api/queue?day=${day}&page=1&page_size=200`),
        fetchJson(`/api/successes?day=${day}&page=1&page_size=200`),
      ]);

      document.getElementById("inc-meta").textContent = `Dia ${day} - total ${inc.total}`;
      document.getElementById("queue-meta").textContent = `Dia ${day} - total ${queue.total}`;
      document.getElementById("ok-meta").textContent = `Dia ${day} - total ${ok.total}`;

      renderRows("inc-table", inc.items, (r) =>
        `<td>${r.site_id || ""}</td><td>${r.resource_id ?? ""}</td><td>${r.incident_type || ""}</td><td>${(r.reason || "").slice(0, 160)}</td><td>${formatTs(r.started_at)}</td><td>${formatTs(r.ended_at)}</td>`
      );
      renderRows("queue-table", queue.items, (r) =>
        `<td>${r.site_id || ""}</td><td>${r.resource_id ?? ""}</td><td>${r.state || ""}</td><td>${r.protocol || ""}</td><td>${formatTs(r.started_at)}</td>`
      );
      renderRows("ok-table", ok.items, (r) =>
        `<td>${r.site_id || ""}</td><td>${r.resource_id ?? ""}</td><td>${r.job_id || ""}</td><td>${r.protocol || ""}</td><td>${formatTs(r.started_at)}</td><td>${formatTs(r.ended_at)}</td>`
      );

      document.getElementById("lastUpdate").textContent = "Actualizado: " + new Date().toLocaleTimeString();
    }

    document.getElementById("prevDays").onclick = async () => {
      daysPage += 1;
      await loadAll();
    };
    document.getElementById("nextDays").onclick = async () => {
      daysPage = Math.max(1, daysPage - 1);
      await loadAll();
    };
    document.getElementById("refresh").onclick = loadAll;

    setInterval(loadAll, 5000);
    loadAll();
  </script>
</body>
</html>
    """


@app.get("/api/days")
async def api_days(
    source: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> dict:
    return data_source.list_days(source=source, page=page, page_size=page_size)


@app.get("/api/incidents")
async def api_incidents(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return data_source.list_incidents(day=day, page=page, page_size=page_size)


@app.get("/api/successes")
async def api_successes(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return data_source.list_successes(day=day, page=page, page_size=page_size)


@app.get("/api/queue")
async def api_queue(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return data_source.list_queue(day=day, page=page, page_size=page_size)
