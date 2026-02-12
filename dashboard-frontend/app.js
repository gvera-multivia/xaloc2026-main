
const { useState, useEffect, useMemo, useRef } = React;

const API_BASE = '/api';
const PAGE_SIZE_DEFAULT = 25;
const KNOWN_SITES = ['madrid', 'xaloc_girona', 'base_online'];
const ROUTE_META = {
  '/': { label: 'Estado General' },
  '/control': { label: 'Panel de Control' },
  '/blacklist': { label: 'Listas Negras' },
  '/admin': { label: 'Colas' },
  '/history': { label: 'Historial' },
};

function toIsoDay(date = new Date()) {
  return date.toISOString().split('T')[0];
}

function normalizePath(pathname) {
  const p = (pathname || '/').toLowerCase();
  if (p === '/control' || p === '/control/') return '/control';
  if (p === '/blacklist' || p === '/blacklist/') return '/blacklist';
  if (p === '/queues' || p === '/queues/' || p === '/colas' || p === '/colas/' || p === '/admin' || p === '/admin/') return '/admin';
  if (p === '/history' || p === '/history/' || p === '/historico' || p === '/historico/') return '/history';
  return '/';
}

function fmtDateTime(value) {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('es-ES');
}

function fmtTime(value) {
  if (!value) return '--:--:--';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '--:--:--';
  return d.toLocaleTimeString('es-ES');
}

function toFileUrl(pathValue) {
  const raw = String(pathValue || '').trim();
  if (!raw) return '';
  if (/^file:\/\//i.test(raw)) return raw;
  if (raw.startsWith('\\\\')) {
    const unc = raw.replace(/\\/g, '/').replace(/^\/+/, '');
    return `file:////${unc}`;
  }
  const normalized = raw.replace(/\\/g, '/');
  return `file:///${normalized}`;
}

function elapsedFrom(startedAt, nowTs) {
  if (!startedAt) return '--:--';
  const start = new Date(startedAt).getTime();
  if (!Number.isFinite(start)) return '--:--';
  const diff = Math.max(0, Math.floor((nowTs - start) / 1000));
  const mm = String(Math.floor(diff / 60)).padStart(2, '0');
  const ss = String(diff % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return res.json();
}

function usePathRouting() {
  const [path, setPath] = useState(normalizePath(window.location.pathname));

  useEffect(() => {
    const onPop = () => setPath(normalizePath(window.location.pathname));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const navigate = (nextPath) => {
    const normalized = normalizePath(nextPath);
    if (normalized === path && window.location.pathname === normalized) return;
    window.history.pushState({}, '', normalized);
    setPath(normalized);
  };

  return { path, navigate };
}

function TopNav({ path, onNavigate, workerOnline, workerLabel, quickSearch, setQuickSearch, onQuickSearchSubmit }) {
  return (
    <header className="top-nav-shell">
      <nav className="top-nav">
        <button className="brand" onClick={() => onNavigate('/')}>
          <span className="brand-mark">XA</span>
          <span>
            <strong>Xaloc Console</strong>
            <small>Monitoreo y control</small>
          </span>
        </button>

        <div className="nav-links">
          <button className={path === '/' ? 'nav-link active' : 'nav-link'} onClick={() => onNavigate('/')}>Estado</button>
          <button className={path === '/control' ? 'nav-link active' : 'nav-link'} onClick={() => onNavigate('/control')}>Control</button>
          <button className={path === '/blacklist' ? 'nav-link active' : 'nav-link'} onClick={() => onNavigate('/blacklist')}>Bloqueos</button>
          <button className={path === '/admin' ? 'nav-link active' : 'nav-link'} onClick={() => onNavigate('/admin')}>Colas</button>
          <button className={path === '/history' ? 'nav-link active' : 'nav-link'} onClick={() => onNavigate('/history')}>Historial</button>
        </div>

        <form className="quick-search" onSubmit={onQuickSearchSubmit}>
          <input
            value={quickSearch}
            onChange={(e) => setQuickSearch(e.target.value)}
            placeholder="Buscar tramite, site o protocolo..."
          />
          <button type="submit">Buscar</button>
        </form>

        <div className="nav-utils">
          <div className="worker-pill" title={workerLabel}>
            <span className={workerOnline ? 'led on' : 'led off'}></span>
            Worker {workerOnline ? 'ON' : 'OFF'}
          </div>
          <button className="profile-btn">
            <span className="profile-dot">U</span>
            Perfil
          </button>
        </div>
      </nav>
    </header>
  );
}

function Breadcrumbs({ path, selectedDay }) {
  const label = ROUTE_META[path]?.label || 'Dashboard';
  const items = ['Home', label];
  if (path === '/history' && selectedDay) items.push(selectedDay);
  return (
    <div className="breadcrumbs">
      {items.map((item, idx) => (
        <span key={`${item}-${idx}`} className="crumb">{item}</span>
      ))}
    </div>
  );
}

function MonitorView({ selectedDay, sharedSearch, setWorkerOnline, setWorkerLabel }) {
  const [liveItem, setLiveItem] = useState(null);
  const [queue, setQueue] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [error, setError] = useState('');
  const [eventLog, setEventLog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [nowTs, setNowTs] = useState(Date.now());
  const markerRef = useRef(null);

  useEffect(() => {
    const t = setInterval(() => setNowTs(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const appendLog = (kind, msg) => {
    setEventLog((prev) => {
      const next = [{ ts: new Date().toISOString(), kind, msg }, ...prev];
      return next.slice(0, 60);
    });
  };

  const refresh = async () => {
    try {
      const [queueRes, incidentsRes, markerRes] = await Promise.all([
        apiFetch(`/queue/current?day=${selectedDay}&page=1&page_size=14`),
        apiFetch(`/history/incidents?day=${selectedDay}&page=1&page_size=15`),
        apiFetch(`/queue/completion-marker?day=${selectedDay}`),
      ]);

      setQueue(queueRes.items || []);
      setIncidents(incidentsRes.items || []);

      const processing = (queueRes.items || []).find((x) => (x.state || '').toLowerCase() === 'processing');
      setLiveItem(processing || null);

      if (processing) appendLog('ok', `Procesando ${processing.resource_id} en ${processing.site_id}.`);
      else appendLog('info', 'Worker sin tramite activo en este instante.');

      const marker = markerRes.marker || '0|';
      if (markerRef.current && markerRef.current !== marker) appendLog('ok', 'Nuevo tramite completado detectado.');
      markerRef.current = marker;

      setWorkerOnline(true);
      setWorkerLabel('API conectada y monitor activo');
      setError('');
    } catch (e) {
      setError('No se pudo actualizar el monitor en vivo.');
      setWorkerOnline(false);
      setWorkerLabel('Sin conexion con API');
      appendLog('error', 'Fallo de conexion con API de monitor.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [selectedDay]);

  const filteredQueue = useMemo(() => {
    const term = (sharedSearch || '').trim().toLowerCase();
    if (!term) return queue;
    return queue.filter((item) =>
      String(item.resource_id || '').toLowerCase().includes(term)
      || String(item.site_id || '').toLowerCase().includes(term)
      || String(item.protocol || '').toLowerCase().includes(term)
    );
  }, [queue, sharedSearch]);

  const processingSeconds = liveItem?.started_at ? Math.max(0, (nowTs - new Date(liveItem.started_at).getTime()) / 1000) : 0;
  const ringProgress = Math.min(100, Math.round((processingSeconds / 240) * 100));

  const getPriority = (item, idx) => {
    if ((item.state || '').toLowerCase() === 'processing') return 'high';
    if (idx <= 2) return 'medium';
    return 'low';
  };

  const deleteFromQueue = async (siteId, resourceId) => {
    if (!window.confirm(`Eliminar ${siteId}/${resourceId} de cola y deseleccionar en XVIA?`)) return;
    try {
      await apiFetch(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}`, { method: 'DELETE' });
      appendLog('warn', `Se elimino ${resourceId} de ${siteId} por accion rapida.`);
      refresh();
    } catch (e) {
      appendLog('error', `No se pudo eliminar ${resourceId} de ${siteId}.`);
    }
  };

  return (
    <section className="page-stack">
      <div className="page-title-row">
        <div>
          <h1>Monitor de tramites en vivo</h1>
          <p>Seguimiento tecnico de ejecucion y cola operativa en tiempo real.</p>
        </div>
        <div className="meta-actions">
          <input type="date" value={selectedDay} readOnly />
          <button onClick={refresh}>Actualizar ahora</button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="monitor-grid">
        <article className="panel focus-panel">
          <div className="panel-head">
            <h2>Tramite en curso</h2>
            <span className={liveItem ? 'chip active' : 'chip muted'}>{liveItem ? 'EN CURSO' : 'IDLE'}</span>
          </div>

          <div className="focus-main">
            <div>
              <h3>{liveItem ? `#${liveItem.resource_id}` : 'Sin tramite activo'}</h3>
              <p>{liveItem ? `Site ${liveItem.site_id} | Protocolo ${liveItem.protocol || '-'}` : 'Esperando un item en estado processing.'}</p>
              <div className="sla-row">
                <span>Cronometro SLA</span>
                <strong>{elapsedFrom(liveItem?.started_at, nowTs)}</strong>
              </div>
            </div>
            <div className="ring-wrap" title="Progreso visual estimado">
              <svg viewBox="0 0 120 120" className="ring-svg">
                <circle cx="60" cy="60" r="50" className="ring-track"></circle>
                <circle cx="60" cy="60" r="50" className="ring-fill" style={{ strokeDashoffset: `${314 - ((ringProgress / 100) * 314)}` }}></circle>
              </svg>
              <span>{ringProgress}%</span>
            </div>
          </div>

          {/* Visor en vivo del navegador Playwright (CDP Screencast) */}
          {liveItem && (
            <div className="live-stream-frame">
              <div className="live-stream-label">
                <span className="live-dot"></span> Vista en directo
              </div>
              <img
                src={`/api/queue/live-screenshot?t=${nowTs}`}
                alt="Navegador en vivo"
                onError={(e) => { e.target.style.opacity = '0'; }}
                onLoad={(e) => { e.target.style.opacity = '1'; }}
              />
            </div>
          )}

          <div className="terminal">
            <div className="terminal-title">Consola de eventos</div>
            <ul>
              {eventLog.map((log, idx) => (
                <li key={`${log.ts}-${idx}`} className={`terminal-${log.kind}`}>
                  <code>[{fmtTime(log.ts)}] {log.msg}</code>
                </li>
              ))}
              {eventLog.length === 0 && <li className="terminal-info"><code>Sin eventos todavia...</code></li>}
            </ul>
          </div>
        </article>

        <aside className="panel queue-panel">
          <div className="panel-head">
            <h2>Cola de espera</h2>
            <span className="chip muted">{filteredQueue.length} items</span>
          </div>
          <div className="queue-cards">
            {filteredQueue.map((item, idx) => {
              const priority = getPriority(item, idx);
              return (
                <div key={`${item.site_id}-${item.resource_id}-${idx}`} className="queue-card">
                  <span className={`priority ${priority}`}></span>
                  <div>
                    <strong>#{item.resource_id}</strong>
                    <p>{item.site_id} | {item.protocol || '-'} | {item.state}</p>
                  </div>
                </div>
              );
            })}
            {filteredQueue.length === 0 && !loading && <p className="empty-note">No hay elementos en cola para mostrar.</p>}
          </div>
        </aside>
      </div>

      <section className="panel incidents-panel">
        <div className="panel-head">
          <h2>Centro de incidencias</h2>
          <span className="chip warn">{incidents.length} abiertas</span>
        </div>
        <div className="incident-list">
          {incidents.map((inc, idx) => {
            const severity = (inc.incident_type || '').toLowerCase().includes('critical') ? 'critical' : ((idx % 2) ? 'medium' : 'light');
            return (
              <article key={`${inc.site_id}-${inc.resource_id}-${idx}`} className="incident-item">
                <div>
                  <strong>{inc.site_id} / #{inc.resource_id}</strong>
                  <p>{inc.reason || inc.incident_type || 'Sin detalle'}</p>
                  <small>{fmtDateTime(inc.started_at)}</small>
                </div>
                <div className="incident-actions">
                  <span className={`severity ${severity}`}>{severity.toUpperCase()}</span>
                  <button onClick={() => refresh()}>Reintentar</button>
                  <button className="danger" onClick={() => deleteFromQueue(inc.site_id, inc.resource_id)}>Saltar</button>
                </div>
              </article>
            );
          })}
          {incidents.length === 0 && <p className="empty-note">Sin incidencias hoy.</p>}
        </div>
      </section>
    </section>
  );
}
function AdminView({ selectedDay, setWorkerOnline, setWorkerLabel, sharedSearch }) {
  const [queueItems, setQueueItems] = useState([]);
  const [pauses, setPauses] = useState([]);
  const [itemPauses, setItemPauses] = useState([]);
  const [pendingAuth, setPendingAuth] = useState([]);
  const [globalReason, setGlobalReason] = useState('');
  const [globalMinutes, setGlobalMinutes] = useState('120');
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [busySite, setBusySite] = useState('');
  const [busyItem, setBusyItem] = useState('');
  const [busyAuth, setBusyAuth] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      const [queueRes, pausesRes, itemPausesRes] = await Promise.all([
        apiFetch(`/queue/current?day=${selectedDay}&page=1&page_size=1000`),
        apiFetch('/queue/pauses?active_only=true'),
        apiFetch('/queue/item-pauses?active_only=true'),
      ]);
      setQueueItems(queueRes.items || []);
      setPauses(pausesRes.items || []);
      setItemPauses(itemPausesRes.items || []);
      setError('');
      setWorkerOnline(true);
      setWorkerLabel('API conectada y panel de control operativo');
    } catch (e) {
      setError('No se pudo cargar control de pausas y sites.');
      setWorkerOnline(false);
      setWorkerLabel('Fallo de conexion con API');
    } finally {
      setLoading(false);
    }
    // Fetch pending auth separately so failures don't break the main panel
    try {
      const authRes = await apiFetch('/pending-auth');
      setPendingAuth(authRes.items || []);
    } catch (_) {
      // endpoint may not be available yet (server restart needed)
    }
  };

  const callApproveAuth = async (pendingId) => {
    setBusyAuth(`approve:${pendingId}`);
    try {
      await apiFetch(`/pending-auth/${pendingId}/approve`, { method: 'POST' });
      await refresh();
    } catch (e) {
      setError(`No se pudo aprobar la autorizacion ${pendingId}.`);
    } finally {
      setBusyAuth('');
    }
  };

  const callRejectAuth = async (pendingId) => {
    const reason = prompt('Motivo del rechazo:');
    if (!reason || !reason.trim()) return;
    setBusyAuth(`reject:${pendingId}`);
    try {
      await apiFetch(`/pending-auth/${pendingId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason.trim() }),
      });
      await refresh();
    } catch (e) {
      setError(`No se pudo rechazar la autorizacion ${pendingId}.`);
    } finally {
      setBusyAuth('');
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 6000);
    return () => clearInterval(id);
  }, [selectedDay]);

  const sites = useMemo(() => {
    const setSites = new Set(KNOWN_SITES);
    queueItems.forEach((it) => setSites.add(it.site_id));
    pauses.forEach((p) => setSites.add(p.site_id));
    return Array.from(setSites).filter(Boolean).sort();
  }, [queueItems, pauses]);

  const pauseMap = useMemo(() => {
    const map = {};
    pauses.forEach((p) => { map[p.site_id] = p; });
    return map;
  }, [pauses]);

  const itemPauseMap = useMemo(() => {
    const map = {};
    itemPauses.forEach((p) => { map[`${p.site_id}::${p.resource_id}`] = p; });
    return map;
  }, [itemPauses]);

  const queueBySite = useMemo(() => {
    const out = {};
    for (const site of sites) out[site] = { total: 0, pending: 0, processing: 0 };
    for (const item of queueItems) {
      const site = item.site_id;
      if (!out[site]) out[site] = { total: 0, pending: 0, processing: 0 };
      out[site].total += 1;
      if ((item.state || '').toLowerCase() === 'processing') out[site].processing += 1;
      else out[site].pending += 1;
    }
    return out;
  }, [sites, queueItems]);

  const filteredItems = useMemo(() => {
    const term = (sharedSearch || '').trim().toLowerCase();
    if (!term) return queueItems;
    return queueItems.filter((item) =>
      String(item.resource_id || '').toLowerCase().includes(term)
      || String(item.site_id || '').toLowerCase().includes(term)
      || String(item.protocol || '').toLowerCase().includes(term)
    );
  }, [queueItems, sharedSearch]);

  const callPause = async (siteId, minutesValue) => {
    setBusySite(siteId);
    try {
      const params = new URLSearchParams();
      const n = Number(minutesValue);
      if (Number.isFinite(n) && n > 0) params.set('minutes', String(n));
      if (globalReason.trim()) params.set('reason', globalReason.trim());
      await apiFetch(`/queue/pauses/${encodeURIComponent(siteId)}?${params.toString()}`, { method: 'POST' });
      await refresh();
    } catch (e) {
      setError(`No se pudo pausar ${siteId}.`);
    } finally {
      setBusySite('');
    }
  };

  const callUnpause = async (siteId) => {
    setBusySite(siteId);
    try {
      await apiFetch(`/queue/pauses/${encodeURIComponent(siteId)}`, { method: 'DELETE' });
      await refresh();
    } catch (e) {
      setError(`No se pudo reanudar ${siteId}.`);
    } finally {
      setBusySite('');
    }
  };

  const pauseAllVisibleSites = async () => {
    if (!globalReason.trim()) {
      setError('El motivo es obligatorio para pausa global.');
      setShowConfirmModal(false);
      return;
    }
    setShowConfirmModal(false);
    for (const site of sites) {
      // secuencial para mantener trazabilidad
      // eslint-disable-next-line no-await-in-loop
      await callPause(site, globalMinutes);
    }
    refresh();
  };

  const callPauseItem = async (siteId, resourceId, minutesValue) => {
    const key = `${siteId}::${resourceId}`;
    setBusyItem(key);
    try {
      const params = new URLSearchParams();
      const n = Number(minutesValue);
      if (Number.isFinite(n) && n > 0) params.set('minutes', String(n));
      if (globalReason.trim()) params.set('reason', globalReason.trim());
      await apiFetch(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}/pause?${params.toString()}`, { method: 'POST' });
      await refresh();
    } catch (e) {
      setError(`No se pudo pausar ${siteId}/${resourceId}.`);
    } finally {
      setBusyItem('');
    }
  };

  const callUnpauseItem = async (siteId, resourceId) => {
    const key = `${siteId}::${resourceId}`;
    setBusyItem(key);
    try {
      await apiFetch(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}/pause`, { method: 'DELETE' });
      await refresh();
    } catch (e) {
      setError(`No se pudo reanudar ${siteId}/${resourceId}.`);
    } finally {
      setBusyItem('');
    }
  };

  const callDeleteItem = async (siteId, resourceId) => {
    const key = `${siteId}::${resourceId}`;
    setBusyItem(key);
    try {
      const resp = await apiFetch(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}`, { method: 'DELETE' });
      if (!resp.removed) {
        if (resp.reason === 'status_processing') {
          setError(`No se elimino ${siteId}/${resourceId}: sigue marcado en processing.`);
        } else if (resp.recovery_attempted) {
          setError(`No se elimino ${siteId}/${resourceId}: el owner worker sigue vivo o no requiere recovery.`);
        } else if (resp.reason === 'not_found') {
          setError(`No se encontro ${siteId}/${resourceId} en cola activa.`);
        } else {
          setError(`No se pudo eliminar ${siteId}/${resourceId}. Motivo: ${resp.reason || 'desconocido'}.`);
        }
        await refresh();
        return;
      }
      let nextError = '';
      if (resp.recovered_processing) {
        nextError = `Se recupero un processing atascado antes de eliminar ${siteId}/${resourceId}.`;
      }
      if (!resp.xvia_deselected) {
        nextError = `Eliminado ${siteId}/${resourceId}, pero XVIA no se pudo deseleccionar.`;
      }
      setError(nextError);
      await refresh();
    } catch (e) {
      setError(`No se pudo eliminar ${siteId}/${resourceId}.`);
    } finally {
      setBusyItem('');
    }
  };

  const callRecoverItem = async (siteId, resourceId) => {
    const key = `${siteId}::${resourceId}`;
    setBusyItem(key);
    try {
      const resp = await apiFetch(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}/recover`, { method: 'POST' });
      if (resp.released) setError('');
      else if (resp.reason === 'no_recovery_needed_or_owner_alive') setError(`No recuperado ${siteId}/${resourceId}: worker owner activo o sin recovery necesario.`);
      else setError(`No se pudo recuperar ${siteId}/${resourceId}.`);
      await refresh();
    } catch (e) {
      setError(`No se pudo recuperar ${siteId}/${resourceId}.`);
    } finally {
      setBusyItem('');
    }
  };

  return (
    <section className="page-stack">
      <div className="page-title-row">
        <div>
          <h1>Control administrativo y gestion de sites</h1>
          <p>Pausa global, control por site y microgestion por elemento de cola.</p>
        </div>
        <div className="meta-actions">
          <input type="date" value={selectedDay} readOnly />
          <button onClick={refresh}>Actualizar</button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <article className="panel">
        <div className="panel-head">
          <h2>Autorizaciones pendientes</h2>
          <span className={`chip ${pendingAuth.length > 0 ? 'warn flash' : 'muted'}`}>{pendingAuth.length}</span>
        </div>
        <table>
          <thead>
            <tr><th>ID</th><th>Site</th><th>Recurso</th><th>Tipo</th><th>Motivo</th><th>Fecha</th><th>Acciones</th></tr>
          </thead>
          <tbody>
            {pendingAuth.map((pa) => {
              const resourceId = pa.resource_id || (pa.payload && pa.payload.idRecurso) || '-';
              const isBusy = busyAuth.includes(String(pa.id));
              return (
                <tr key={pa.id}>
                  <td>{pa.id}</td>
                  <td>{pa.site_id}</td>
                  <td>#{resourceId}</td>
                  <td>{pa.authorization_type || '-'}</td>
                  <td>{pa.reason || '-'}</td>
                  <td>{fmtDateTime(pa.created_at)}</td>
                  <td>
                    <div className="action-wrap">
                      <button disabled={isBusy} onClick={() => callApproveAuth(pa.id)}>Autorizar</button>
                      <button className="danger" disabled={isBusy} onClick={() => callRejectAuth(pa.id)}>Rechazar</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {pendingAuth.length === 0 && <tr><td colSpan="7" className="empty">No hay autorizaciones pendientes.</td></tr>}
          </tbody>
        </table>
      </article>

      <div className="admin-row">
        <article className="panel">
          <div className="panel-head"><h2>Pausa global rapida</h2></div>
          <div className="form-inline">
            <input type="number" min="1" value={globalMinutes} onChange={(e) => setGlobalMinutes(e.target.value)} placeholder="Minutos" />
            <input value={globalReason} onChange={(e) => setGlobalReason(e.target.value)} placeholder="Motivo obligatorio" />
            <button className="warn" onClick={() => setShowConfirmModal(true)} disabled={sites.length === 0}>Pausar todos</button>
          </div>
          <p className="help">Antes de pausar globalmente se solicita confirmacion visual para evitar acciones accidentales.</p>
        </article>

        <article className="panel">
          <div className="panel-head">
            <h2>Pausas activas</h2>
            <span className="chip warn">{pauses.length}</span>
          </div>
          <table>
            <thead><tr><th>Site</th><th>Hasta</th><th>Motivo</th></tr></thead>
            <tbody>
              {pauses.map((p) => (
                <tr key={p.site_id}><td>{p.site_id}</td><td>{p.expires_at ? fmtDateTime(p.expires_at) : 'Sin limite'}</td><td>{p.reason || '-'}</td></tr>
              ))}
              {pauses.length === 0 && <tr><td colSpan="3" className="empty">No hay pausas activas.</td></tr>}
            </tbody>
          </table>
        </article>
      </div>

      <article className="panel">
        <div className="panel-head"><h2>Control por site</h2></div>
        <table>
          <thead>
            <tr><th>Site</th><th>Total en cola</th><th>Pendientes</th><th>Procesando</th><th>Estado</th><th>Acciones</th></tr>
          </thead>
          <tbody>
            {sites.map((site) => {
              const paused = !!pauseMap[site];
              const c = queueBySite[site] || { total: 0, pending: 0, processing: 0 };
              return (
                <tr key={site}>
                  <td>{site}</td><td>{c.total}</td><td>{c.pending}</td><td>{c.processing}</td>
                  <td><span className={paused ? 'chip paused' : 'chip active'}>{paused ? 'PAUSADO' : 'ACTIVO'}</span></td>
                  <td>
                    <div className="action-wrap">
                      <button disabled={busySite === site} onClick={() => callPause(site, globalMinutes)}>Pausar</button>
                      <button disabled={busySite === site} onClick={() => callPause(site, null)}>Sin limite</button>
                      <button disabled={busySite === site} onClick={() => callUnpause(site)}>Reanudar</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {sites.length === 0 && !loading && <tr><td colSpan="6" className="empty">Sin sites detectados.</td></tr>}
          </tbody>
        </table>
      </article>

      <article className="panel">
        <div className="panel-head"><h2>Control por elemento de cola</h2><span className="chip muted">{filteredItems.length} visibles</span></div>
        <table>
          <thead><tr><th>Site</th><th>Recurso</th><th>Estado</th><th>Pausa item</th><th>Acciones</th></tr></thead>
          <tbody>
            {filteredItems.map((item) => {
              const key = `${item.site_id}::${item.resource_id}`;
              const pausedItem = itemPauseMap[key];
              const isBusy = busyItem === key;
              return (
                <tr key={`${key}::${item.state || 'x'}`}>
                  <td>{item.site_id}</td><td>#{item.resource_id}</td><td>{item.state || '-'}</td>
                  <td>{pausedItem ? (pausedItem.expires_at ? fmtDateTime(pausedItem.expires_at) : 'Sin limite') : '-'}</td>
                  <td>
                    <div className="action-wrap">
                      <button disabled={isBusy} onClick={() => callPauseItem(item.site_id, item.resource_id, globalMinutes)}>Pausar</button>
                      <button disabled={isBusy} onClick={() => callUnpauseItem(item.site_id, item.resource_id)}>Reanudar</button>
                      <button className="warn" disabled={isBusy || (item.state || '').toLowerCase() !== 'processing'} onClick={() => callRecoverItem(item.site_id, item.resource_id)}>Recuperar</button>
                      <button className="danger" disabled={isBusy} onClick={() => callDeleteItem(item.site_id, item.resource_id)}>Eliminar</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {filteredItems.length === 0 && !loading && <tr><td colSpan="5" className="empty">Sin elementos para este filtro.</td></tr>}
          </tbody>
        </table>
      </article>

      {showConfirmModal && (
        <div className="modal-backdrop" onClick={() => setShowConfirmModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>Confirmar pausa global</h3>
            <p>Se van a pausar {sites.length} sites. Motivo: <strong>{globalReason || '(vacio)'}</strong></p>
            <div className="modal-actions">
              <button onClick={() => setShowConfirmModal(false)}>Cancelar</button>
              <button className="warn" onClick={pauseAllVisibleSites}>Confirmar pausa</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function ControlPanelView({ setWorkerOnline, setWorkerLabel }) {
  const [status, setStatus] = useState({ worker: 'stopped', brain: 'stopped' });
  const [logs, setLogs] = useState({ worker: { stdout: [], stderr: [] }, brain: { stdout: [], stderr: [] } });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const workerLogRef = useRef(null);
  const brainLogRef = useRef(null);

  const refresh = async () => {
    try {
      const [statusRes, workerLogs, brainLogs] = await Promise.all([
        apiFetch('/control/status'),
        apiFetch('/logs/worker?lines=100'),
        apiFetch('/logs/brain?lines=100'),
      ]);
      setStatus(statusRes || {});
      setLogs({
        worker: workerLogs || { stdout: [], stderr: [] },
        brain: brainLogs || { stdout: [], stderr: [] },
      });
      setError('');
      setWorkerOnline(true);
      setWorkerLabel(`Worker: ${(statusRes.worker || 'stopped').toUpperCase()} | Brain: ${(statusRes.brain || 'stopped').toUpperCase()}`);
    } catch (e) {
      setError('No se pudo cargar estado/logs de procesos.');
      setWorkerOnline(false);
      setWorkerLabel('Sin conexion con API de control');
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!autoScroll) return;
    if (workerLogRef.current) workerLogRef.current.scrollTop = workerLogRef.current.scrollHeight;
    if (brainLogRef.current) brainLogRef.current.scrollTop = brainLogRef.current.scrollHeight;
  }, [logs, autoScroll]);

  const callControl = async (name, action) => {
    setBusy(`${name}:${action}`);
    try {
      await apiFetch(`/control/${name}/${action}`, { method: 'POST' });
      await refresh();
    } catch (e) {
      setError(`No se pudo ${action} ${name}.`);
    } finally {
      setBusy('');
    }
  };

  const renderProcessCard = (name) => {
    const current = (status[name] || 'stopped').toLowerCase();
    const isRunning = current === 'running';
    const isError = current === 'error';
    const statusLabel = isRunning ? 'RUNNING' : (isError ? 'ERROR' : 'STOPPED');
    const cardLogs = logs[name] || { stdout: [], stderr: [] };
    const combined = cardLogs.stdout || [];
    const logRef = name === 'worker' ? workerLogRef : brainLogRef;

    const parseLogLine = (line) => {
      // Regex para: 2026-02-12 09:12:04,123 - [WORKER] - INFO - Mensaje
      const logMatch = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\d]*)\s*-\s*\[[^\]]+\]\s*-\s*([A-Z]+)\s*-\s*(.*)$/);
      if (logMatch) {
        return {
          ts: logMatch[1],
          level: logMatch[2],
          msg: logMatch[3],
          type: 'log'
        };
      }

      // Tracebacks: File "...", line 123
      if (line.trim().startsWith('File "') || line.trim().startsWith('Traceback (most recent call last)')) {
        return { msg: line, type: 'traceback' };
      }

      // Otras lineas de error o info generica
      if (line.startsWith('[ERR]')) return { msg: line.replace('[ERR]', '').trim(), level: 'ERROR', type: 'log' };

      return { msg: line, type: 'raw' };
    };

    return (
      <article className="panel process-card" key={name}>
        <div className="panel-head">
          <h2>{name.toUpperCase()}</h2>
          <span className={`chip ${isRunning ? 'active' : (isError ? 'warn' : 'paused')}`}>{statusLabel}</span>
        </div>

        <div className="action-wrap">
          <button disabled={isRunning || busy === `${name}:start`} onClick={() => callControl(name, 'start')}>INICIAR</button>
          <button className="danger" disabled={!isRunning || busy === `${name}:stop`} onClick={() => callControl(name, 'stop')}>DETENER</button>
          <button className="warn" disabled={!isRunning || busy === `${name}:restart`} onClick={() => callControl(name, 'restart')}>REINICIAR</button>
          <button onClick={refresh}>REFRESCAR LOGS</button>
        </div>

        <div className="terminal process-logs" ref={logRef}>
          {combined.length === 0 && <code>Sin logs disponibles.</code>}
          {combined.map((line, idx) => {
            const p = parseLogLine(line);
            let lineClass = 'terminal-line';
            if (p.type === 'traceback') lineClass += ' terminal-line-traceback';
            else if (p.level === 'ERROR') lineClass += ' terminal-line-error';
            else if (p.level === 'WARNING' || p.level === 'WARN') lineClass += ' terminal-line-warn';
            else if (p.level === 'INFO') lineClass += ' terminal-line-info';
            else if (p.msg && p.msg.includes('OK')) lineClass += ' terminal-line-success';

            return (
              <code key={`${name}-line-${idx}`} className={lineClass}>
                {p.ts && <span className="terminal-timestamp">[{p.ts.split(' ')[1]}]</span>}
                {p.level && <span className="terminal-level">{p.level}</span>}
                {p.msg || line}
              </code>
            );
          })}
        </div>
      </article>
    );
  };

  return (
    <section className="page-stack">
      <div className="page-title-row">
        <div>
          <h1>Panel de control de procesos</h1>
          <p>Gestion de worker.py y brain.py sin usar terminal.</p>
        </div>
        <div className="meta-actions">
          <label className="inline-check">
            <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
            Auto-scroll logs
          </label>
          <button onClick={refresh}>Actualizar</button>
        </div>
      </div>
      {error && <div className="alert error">{error}</div>}
      <div className="control-grid">
        {renderProcessCard('worker')}
        {renderProcessCard('brain')}
      </div>
    </section>
  );
}

function BlacklistView({ setWorkerOnline, setWorkerLabel }) {
  const [items, setItems] = useState([]);
  const [configs, setConfigs] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [form, setForm] = useState({ site_id: '', resource_id: '', reason: '' });

  const refresh = async () => {
    try {
      const [blRes, cfgRes] = await Promise.all([
        apiFetch('/blacklist'),
        apiFetch('/config'),
      ]);
      setItems(blRes.items || []);
      setConfigs(cfgRes.items || []);
      setError('');
      setWorkerOnline(true);
      setWorkerLabel('Blacklist y configuracion cargadas');
    } catch (e) {
      setError('No se pudieron cargar bloqueos/configuracion.');
      setWorkerOnline(false);
      setWorkerLabel('Error en API de blacklist/config');
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 6000);
    return () => clearInterval(id);
  }, []);

  const unblock = async (siteId, resourceId) => {
    setBusy(`unblock:${siteId}:${resourceId}`);
    try {
      await apiFetch(`/blacklist/${encodeURIComponent(siteId)}/${resourceId}`, { method: 'DELETE' });
      await refresh();
    } catch (e) {
      setError(`No se pudo desbloquear ${siteId}/${resourceId}.`);
    } finally {
      setBusy('');
    }
  };

  const blockManual = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        site_id: (form.site_id || '').trim(),
        resource_id: Number(form.resource_id),
        reason: (form.reason || '').trim() || null,
        source: 'manual',
      };
      await apiFetch('/blacklist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setForm({ site_id: '', resource_id: '', reason: '' });
      await refresh();
    } catch (err) {
      setError('No se pudo bloquear manualmente el recurso.');
    }
  };

  const toggleConfigActive = async (siteId, currentActive) => {
    setBusy(`cfg:${siteId}`);
    try {
      await apiFetch(`/config/${encodeURIComponent(siteId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !Boolean(currentActive) }),
      });
      await refresh();
    } catch (e) {
      setError(`No se pudo actualizar configuracion para ${siteId}.`);
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="page-stack">
      <div className="page-title-row">
        <div>
          <h1>Listas negras y bloqueos</h1>
          <p>Gestion de recursos bloqueados y estado de organismos.</p>
        </div>
        <div className="meta-actions">
          <button onClick={refresh}>Actualizar</button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <article className="panel">
        <div className="panel-head">
          <h2>Bloqueo manual</h2>
        </div>
        <form className="form-inline long" onSubmit={blockManual}>
          <input value={form.site_id} onChange={(e) => setForm((x) => ({ ...x, site_id: e.target.value }))} placeholder="Site ID" required />
          <input value={form.resource_id} onChange={(e) => setForm((x) => ({ ...x, resource_id: e.target.value }))} placeholder="ID Recurso" type="number" min="1" required />
          <input value={form.reason} onChange={(e) => setForm((x) => ({ ...x, reason: e.target.value }))} placeholder="Motivo" />
          <button type="submit">Bloquear recurso</button>
        </form>
      </article>

      <article className="panel">
        <div className="panel-head">
          <h2>Recursos bloqueados</h2>
          <span className="chip warn">{items.length}</span>
        </div>
        <table>
          <thead>
            <tr><th>ID Recurso</th><th>Site</th><th>Motivo</th><th>Origen</th><th>Fecha</th><th>Acciones</th></tr>
          </thead>
          <tbody>
            {items.map((it) => {
              const key = `${it.site_id}:${it.resource_id}`;
              const isBusy = busy === `unblock:${it.site_id}:${it.resource_id}`;
              return (
                <tr key={key}>
                  <td>{it.resource_id}</td>
                  <td>{it.site_id}</td>
                  <td>{it.reason || '-'}</td>
                  <td>{it.source || '-'}</td>
                  <td>{fmtDateTime(it.created_at)}</td>
                  <td><button disabled={isBusy} onClick={() => unblock(it.site_id, it.resource_id)}>Desbloquear</button></td>
                </tr>
              );
            })}
            {items.length === 0 && <tr><td colSpan="6" className="empty">No hay recursos bloqueados.</td></tr>}
          </tbody>
        </table>
      </article>

      <article className="panel">
        <div className="panel-head">
          <h2>Configuracion de organismos</h2>
        </div>
        <table>
          <thead>
            <tr><th>Site</th><th>Activo</th><th>Login URL</th><th>Regex expediente</th><th>Filtro TExp</th><th>Acciones</th></tr>
          </thead>
          <tbody>
            {configs.map((cfg) => {
              const isBusy = busy === `cfg:${cfg.site_id}`;
              return (
                <tr key={cfg.site_id}>
                  <td>{cfg.site_id}</td>
                  <td><span className={Number(cfg.active) ? 'chip active' : 'chip paused'}>{Number(cfg.active) ? 'ON' : 'OFF'}</span></td>
                  <td>{cfg.login_url || '-'}</td>
                  <td>{cfg.regex_expediente || '-'}</td>
                  <td>{cfg.filtro_texp || '-'}</td>
                  <td><button disabled={isBusy} onClick={() => toggleConfigActive(cfg.site_id, cfg.active)}>{Number(cfg.active) ? 'Desactivar' : 'Activar'}</button></td>
                </tr>
              );
            })}
            {configs.length === 0 && <tr><td colSpan="6" className="empty">No hay configuraciones disponibles.</td></tr>}
          </tbody>
        </table>
      </article>
    </section>
  );
}

function buildPageNumbers(current, totalPages) {
  const pages = [];
  const start = Math.max(1, current - 2);
  const end = Math.min(totalPages, current + 2);
  for (let i = start; i <= end; i += 1) pages.push(i);
  return pages;
}
function HistoryView({ selectedDay, setSelectedDay, sharedSearch, setWorkerOnline, setWorkerLabel }) {
  const [items, setItems] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(PAGE_SIZE_DEFAULT);
  const [total, setTotal] = useState(0);
  const [localSearch, setLocalSearch] = useState('');
  const [selectedRow, setSelectedRow] = useState(null);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const completionMarkerRef = useRef(null);
  const completionReadyRef = useRef(false);

  useEffect(() => {
    setLocalSearch(sharedSearch || '');
  }, [sharedSearch]);

  const refresh = async ({ day = selectedDay, page = historyPage, pageSize = historyPageSize, silent = false } = {}) => {
    try {
      if (!silent) setLoading(true);
      const [successRes, incidentsRes] = await Promise.all([
        apiFetch(`/history/successes?day=${day}&page=${page}&page_size=${pageSize}`),
        apiFetch(`/history/incidents?day=${day}&page=1&page_size=300`),
      ]);
      setItems(successRes.items || []);
      setTotal(successRes.total || 0);
      setIncidents(incidentsRes.items || []);
      setHasLoadedOnce(true);
      setError('');
      setWorkerOnline(true);
      setWorkerLabel('API conectada y auditoria disponible');
    } catch (e) {
      setError('No se pudo cargar historial/auditoria.');
      setWorkerOnline(false);
      setWorkerLabel('Sin conexion al backend');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    completionMarkerRef.current = null;
    completionReadyRef.current = false;

    const checkCompletionMarker = async () => {
      try {
        const markerRes = await apiFetch(`/queue/completion-marker?day=${selectedDay}`);
        const nextMarker = markerRes.marker || '0|';
        if (!completionReadyRef.current) {
          completionMarkerRef.current = nextMarker;
          completionReadyRef.current = true;
          return;
        }
        if (completionMarkerRef.current !== nextMarker) {
          completionMarkerRef.current = nextMarker;
          refresh({ silent: true });
        }
      } catch (_) {
        // Si falla el marcador, no interrumpimos la vista de historial.
      }
    };

    checkCompletionMarker();
    const id = setInterval(checkCompletionMarker, 5000);
    return () => clearInterval(id);
  }, [selectedDay, historyPage, historyPageSize]);

  const incidentMap = useMemo(() => {
    const map = {};
    incidents.forEach((it) => {
      const key = `${it.site_id}::${it.resource_id}`;
      if (!map[key]) map[key] = [];
      map[key].push(it);
    });
    return map;
  }, [incidents]);

  const filtered = useMemo(() => {
    const term = (localSearch || '').trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => {
      return String(item.resource_id || '').toLowerCase().includes(term)
        || String(item.site_id || '').toLowerCase().includes(term)
        || String(item.protocol || '').toLowerCase().includes(term)
        || String(item.job_id || '').toLowerCase().includes(term);
    });
  }, [items, localSearch]);

  const totalPages = Math.max(1, Math.ceil(total / historyPageSize));
  const pageNumbers = buildPageNumbers(historyPage, totalPages);

  return (
    <section className="page-stack">
      <div className="page-title-row">
        <div>
          <h1>Historial de operaciones y auditoria</h1>
          <p>Analisis diario de procesos completados con trazabilidad de errores.</p>
        </div>
        <div className="meta-actions">
          <input
            type="date"
            value={selectedDay}
            onChange={(e) => {
              const nextDay = e.target.value;
              setSelectedDay(nextDay);
              setHistoryPage(1);
              refresh({ day: nextDay, page: 1 });
            }}
          />
          <button onClick={() => refresh()}>Refrescar</button>
        </div>
      </div>

      <div className="history-tools panel">
        <input
          value={localSearch}
          onChange={(e) => setLocalSearch(e.target.value)}
          placeholder="Filtrar por recurso, site, protocolo o usuario..."
        />
        <div className="history-meta">
          <span className="chip active">{total} procesados</span>
          <label>
            Filas
            <select
              value={historyPageSize}
              onChange={(e) => {
                const nextSize = Number(e.target.value);
                setHistoryPageSize(nextSize);
                setHistoryPage(1);
                refresh({ page: 1, pageSize: nextSize });
              }}
            >
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </label>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <article className="panel">
        <table>
          <thead><tr><th>Recurso</th><th>Site</th><th>Protocolo</th><th>Estado final</th><th>Inicio</th><th>Fin</th></tr></thead>
          <tbody>
            {filtered.map((row, idx) => {
              const key = `${row.site_id}::${row.resource_id}`;
              const hasIncident = !!(incidentMap[key] && incidentMap[key].length);
              return (
                <tr key={`${key}-${idx}`} onClick={() => setSelectedRow({ row, incidents: incidentMap[key] || [] })} className="click-row">
                  <td>#{row.resource_id}</td><td>{row.site_id}</td><td>{row.protocol || '-'}</td>
                  <td><span className={hasIncident ? 'chip paused' : 'chip active'}>{hasIncident ? 'Completado con incidencias' : 'Completado'}</span></td>
                  <td>{fmtDateTime(row.started_at)}</td><td>{fmtDateTime(row.ended_at)}</td>
                </tr>
              );
            })}
            {!loading && !hasLoadedOnce && <tr><td colSpan="6" className="empty">Pulsa "Refrescar" para cargar historial.</td></tr>}
            {!loading && hasLoadedOnce && filtered.length === 0 && <tr><td colSpan="6" className="empty">Sin resultados para este filtro.</td></tr>}
            {loading && <tr><td colSpan="6" className="empty">Cargando historial...</td></tr>}
          </tbody>
        </table>

        <div className="pagination-row">
          <button
            disabled={historyPage <= 1}
            onClick={() => {
              const nextPage = Math.max(1, historyPage - 1);
              setHistoryPage(nextPage);
              refresh({ page: nextPage });
            }}
          >
            Anterior
          </button>
          {pageNumbers.map((p) => (
            <button
              key={p}
              className={p === historyPage ? 'active' : ''}
              onClick={() => {
                setHistoryPage(p);
                refresh({ page: p });
              }}
            >
              {p}
            </button>
          ))}
          <button
            disabled={historyPage >= totalPages}
            onClick={() => {
              const nextPage = Math.min(totalPages, historyPage + 1);
              setHistoryPage(nextPage);
              refresh({ page: nextPage });
            }}
          >
            Siguiente
          </button>
        </div>
      </article>

      {selectedRow && (
        <aside className="drawer" onClick={() => setSelectedRow(null)}>
          <div className="drawer-card" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <h3>Auditoria #{selectedRow.row.resource_id}</h3>
              <button onClick={() => setSelectedRow(null)}>Cerrar</button>
            </div>
            <p><strong>Site:</strong> {selectedRow.row.site_id}</p>
            <p><strong>Protocolo:</strong> {selectedRow.row.protocol || '-'}</p>
            <p><strong>Inicio:</strong> {fmtDateTime(selectedRow.row.started_at)}</p>
            <p><strong>Fin:</strong> {fmtDateTime(selectedRow.row.ended_at)}</p>

            <div className="action-wrap" style={{ margin: '10px 0' }}>
              <button onClick={async () => {
                try {
                  const res = await apiFetch('/client-folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      ...(selectedRow.row.payload || {}),
                      open_on_server: false,
                    }),
                  });
                  if (!res.exists) {
                    setError('La carpeta del cliente no existe: ' + (res.path || ''));
                    return;
                  }
                  const fileUrl = toFileUrl(res.path);
                  if (!fileUrl) {
                    setError('No se pudo resolver una ruta valida para abrir la carpeta.');
                    return;
                  }
                  const openedClient = window.open(fileUrl, '_blank');
                  if (openedClient) {
                    setError('');
                  } else {
                    setError(`No se pudo abrir automaticamente. Usa esta ruta: ${res.path || ''}`);
                  }
                } catch (e) {
                  setError('Error al intentar abrir la carpeta del cliente.');
                }
              }}>Abrir carpeta del cliente</button>
            </div>

            <h4>Payload</h4>
            <pre>{JSON.stringify(selectedRow.row.payload || {}, null, 2)}</pre>

            <h4>Resultado</h4>
            <pre>{JSON.stringify(selectedRow.row.result || {}, null, 2)}</pre>

            <h4>Logs/incidencias</h4>
            <pre>{JSON.stringify(selectedRow.incidents || [], null, 2)}</pre>
          </div>
        </aside>
      )}
    </section>
  );
}

function AppRouter() {
  const { path, navigate } = usePathRouting();
  const [selectedDay, setSelectedDay] = useState(toIsoDay());
  const [workerOnline, setWorkerOnline] = useState(false);
  const [workerLabel, setWorkerLabel] = useState('Esperando primer sondeo');
  const [quickSearch, setQuickSearch] = useState('');
  const [sharedSearch, setSharedSearch] = useState('');

  const onQuickSearchSubmit = (e) => {
    e.preventDefault();
    const term = quickSearch.trim();
    setSharedSearch(term);
    if (term) navigate('/history');
  };

  return (
    <div className="shell">
      <TopNav
        path={path}
        onNavigate={navigate}
        workerOnline={workerOnline}
        workerLabel={workerLabel}
        quickSearch={quickSearch}
        setQuickSearch={setQuickSearch}
        onQuickSearchSubmit={onQuickSearchSubmit}
      />

      <main className="page-wrap">
        <Breadcrumbs path={path} selectedDay={selectedDay} />

        {path === '/admin' && (
          <AdminView
            selectedDay={selectedDay}
            setWorkerOnline={setWorkerOnline}
            setWorkerLabel={setWorkerLabel}
            sharedSearch={sharedSearch}
          />
        )}

        {path === '/control' && (
          <ControlPanelView
            setWorkerOnline={setWorkerOnline}
            setWorkerLabel={setWorkerLabel}
          />
        )}

        {path === '/blacklist' && (
          <BlacklistView
            setWorkerOnline={setWorkerOnline}
            setWorkerLabel={setWorkerLabel}
          />
        )}

        {path === '/history' && (
          <HistoryView
            selectedDay={selectedDay}
            setSelectedDay={setSelectedDay}
            sharedSearch={sharedSearch}
            setWorkerOnline={setWorkerOnline}
            setWorkerLabel={setWorkerLabel}
          />
        )}

        {path === '/' && (
          <MonitorView
            selectedDay={selectedDay}
            sharedSearch={sharedSearch}
            setWorkerOnline={setWorkerOnline}
            setWorkerLabel={setWorkerLabel}
          />
        )}
      </main>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<AppRouter />);

