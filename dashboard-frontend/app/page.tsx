'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Activity,
  Clock,
  AlertCircle,
  CheckCircle2,
  BarChart3,
  Calendar,
  RefreshCw,
  ZapOff,
} from 'lucide-react';
import { queueApi, historyApi } from '@/lib/api';
import { QueueItem, Incident } from '@/lib/types';
import LiveScreencast from '@/components/monitor/LiveScreencast';
import SlaRing from '@/components/monitor/SlaRing';
import QueueCard from '@/components/monitor/QueueCard';
import { sileo } from 'sileo';

export default function MonitorPage() {
  const UI_REFRESH_MS = 1000;
  const INCIDENT_MARKER_POLL_MS = 1000;
  const LIVE_STREAM_GRACE_MS = 8000;

  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [nowTs, setNowTs] = useState(Date.now());
  const [lastLiveSeenTs, setLastLiveSeenTs] = useState(0);
  const completionMarkerRef = useRef<string>('');
  const [recovering, setRecovering] = useState(false);

  const today = useMemo(() => new Date().toISOString().split('T')[0], []);

  const refreshQueue = async () => {
    const queueRes = await queueApi.getCurrent(1, 1000);
    setQueue(queueRes.items || []);
  };

  const refreshIncidents = async () => {
    const incidentsRes = await historyApi.getIncidents(undefined, 1, 15);
    setIncidents(incidentsRes.items || []);
  };

  const refresh = async () => {
    try {
      const [markerRes] = await Promise.all([
        queueApi.getCompletionMarker(today),
        refreshQueue(),
        refreshIncidents(),
      ]);
      completionMarkerRef.current = markerRes.marker || '';
      setError('');
    } catch (e) {
      sileo.error({ title: 'Error de sincronización', description: 'No se pudo actualizar el monitor en vivo.' });
      setError('No se pudo actualizar el monitor en vivo.');
    } finally {
      setLoading(false);
    }
  };

  const handleRecoverStuck = async () => {
    setRecovering(true);
    try {
      const result = await queueApi.recoverStuck();
      const recovered = Number(result?.recovered || 0);
      const alive = Number(result?.alive_workers || 0);
      const scanned = Number(result?.scanned || 0);

      const msg = recovered > 0
        ? `Recuperados ${recovered} items huérfanos (explorados ${scanned}, workers vivos=${alive}).`
        : `Sin items huérfanos detectados (explorados ${scanned}, workers vivos=${alive}).`;

      sileo.success({ title: 'Reconciliación UUID', description: msg });
      await refreshQueue();
    } catch (err) {
      sileo.error({ title: 'Error en reconciliación', description: 'Error validando UUID-workers; revisa los logs.' });
    } finally {
      setRecovering(false);
    }
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(async () => {
      try {
        await refreshQueue();
      } catch (e) {
        setError('No se pudo actualizar el monitor en vivo.');
      }
    }, UI_REFRESH_MS);

    const markerPoll = setInterval(async () => {
      try {
        const markerRes = await queueApi.getCompletionMarker(today);
        const marker = markerRes.marker || '';
        if (completionMarkerRef.current && completionMarkerRef.current !== marker) {
          refreshIncidents().catch(() => setError('No se pudo actualizar el panel de incidencias.'));
        }
        completionMarkerRef.current = marker;
      } catch (e) {
        setError('No se pudo actualizar el panel de incidencias.');
      }
    }, INCIDENT_MARKER_POLL_MS);

    const clock = setInterval(() => setNowTs(Date.now()), 1000);
    return () => {
      clearInterval(interval);
      clearInterval(markerPoll);
      clearInterval(clock);
    };
  }, [today]);

  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);

  const liveItem = useMemo(() => {
    if (selectedWorkerId) {
      // Intentar buscar el item que está procesando el worker seleccionado
      // (Asumiendo que el worker_id se guarda en el item o que podemos deducirlo)
      // Por ahora, si hay varios en processing, mostramos el primero o el que coincida si tuviéramos esa info.
      // Optimización: si no hay un item específico ligado al worker en el payload de la cola,
      // mostramos cualquier item en 'processing' que coincida con el site del worker si lo supiéramos.
      return queue.find(x => (x.state || '').toLowerCase() === 'processing') || null;
    }
    return queue.find(x => (x.state || '').toLowerCase() === 'processing') || null;
  }, [queue, selectedWorkerId]);

  useEffect(() => {
    if (liveItem) {
      setLastLiveSeenTs(Date.now());
    }
  }, [liveItem]);
  const liveStreamEnabled = !!liveItem || (lastLiveSeenTs > 0 && nowTs - lastLiveSeenTs <= LIVE_STREAM_GRACE_MS);
  const formatResource = (resourceId: unknown) => (resourceId === null || resourceId === undefined || resourceId === '' ? 'N/A' : String(resourceId));

  const ringProgress = useMemo(() => {
    if (!liveItem?.started_at) return 0;
    const start = new Date(liveItem.started_at).getTime();
    const seconds = Math.max(0, (nowTs - start) / 1000);
    return Math.min(100, Math.round((seconds / 240) * 100)); // 4 minutes SLA
  }, [liveItem, nowTs]);

  const elapsed = useMemo(() => {
    if (!liveItem?.started_at) return '--:--';
    const start = new Date(liveItem.started_at).getTime();
    const diff = Math.max(0, Math.floor((nowTs - start) / 1000));
    const mm = String(Math.floor(diff / 60)).padStart(2, '0');
    const ss = String(diff % 60).padStart(2, '0');
    return `${mm}:${ss}`;
  }, [liveItem, nowTs]);

  return (
    <div className="space-y-10 animate-in fade-in duration-700">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black tracking-tight uppercase">
            Monitor de Operaciones
          </h2>
          <p className="text-xs text-muted-foreground/60 uppercase tracking-widest mt-1">
            Seguimiento técnico de ejecución y flujo de trabajo.
          </p>
        </div>

        {/* Date + refresh */}
        <div className="flex items-center gap-2 rounded border border-border/70 px-2 py-1.5 bg-[rgba(17,19,26,0.65)]">
          <div className="flex items-center gap-2 px-3 py-1.5 text-[9px] font-black uppercase tracking-[0.25em] text-muted-foreground/60">
            <Calendar size={12} />
            {today}
          </div>

          <button
            onClick={refresh}
            className={[
              "flex items-center gap-2 px-6 py-2 rounded-sm",
              "text-[9px] font-black uppercase tracking-[0.2em]",
              "bg-[color:var(--morr-fate)] text-white/90",
              "border border-transparent",
              "hover:bg-[color:var(--morr-fate-hi)] transition-all duration-300 active:scale-[0.98]",
            ].join(" ")}
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Sincronizar
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-[color:rgba(255,60,80,0.35)] bg-[rgba(255,60,80,0.06)] px-4 py-3 flex items-center gap-3">
          <AlertCircle size={18} className="text-[color:rgba(255,60,80,0.85)]" />
          <p className="text-sm font-medium text-[color:rgba(255,255,255,0.90)]">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left */}
        <div className="lg:col-span-8 space-y-8">
          <LiveScreencast
            live={liveStreamEnabled}
            onWorkerSelect={(id) => setSelectedWorkerId(id)}
          />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <SlaRing
              progress={ringProgress}
              elapsed={elapsed}
              label={liveItem ? `${liveItem.site_id} #${formatResource(liveItem.resource_id)}` : "Sistema en Espera"}
            />

            {/* Live metrics card */}
            <div className="morr-card morr-edge rounded p-7">
              <div className="flex items-center justify-between">
                <h4 className="text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground">
                  Métricas en Vivo
                </h4>
                <Activity
                  size={16}
                  className={liveItem ? "text-[color:var(--morr-fate)]" : "text-muted-foreground/40"}
                />
              </div>

              <div className="mt-5 space-y-3 font-mono">
                <div className="flex justify-between items-center rounded border border-border/60 bg-[rgba(17,19,26,0.65)] p-4">
                  <span className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/50">
                    ID_RECURSO
                  </span>
                  <span className="text-sm font-black text-foreground">
                    {liveItem ? `#${formatResource(liveItem.resource_id)}` : "VOID"}
                  </span>
                </div>

                <div className="flex justify-between items-center rounded border border-border/60 bg-[rgba(17,19,26,0.65)] p-4">
                  <span className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/50">
                    ID_SITIO
                  </span>
                  <span className="text-sm font-black text-foreground uppercase">
                    {liveItem?.site_id || "OBSERVING"}
                  </span>
                </div>
              </div>

              <div className="mt-6 pt-5 border-t border-border/70 flex items-center justify-between">
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase font-black text-muted-foreground tracking-[0.16em]">
                    Tiempo de Ejecución
                  </span>
                  <span className="text-2xl font-black font-mono text-[color:var(--morr-fate)]">
                    {elapsed}
                  </span>
                </div>
                <div className="flex flex-col items-end text-right">
                  <span className="text-[10px] uppercase font-black text-muted-foreground tracking-[0.16em]">
                    Carga SLA
                  </span>
                  <span className="text-2xl font-black font-mono text-foreground">
                    {ringProgress}%
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right */}
        <div className="lg:col-span-4 space-y-8">
          {/* Queue */}
          <div className="morr-card morr-edge rounded overflow-hidden flex flex-col h-[500px]">
            <div className="p-5 border-b border-border/70 sticky top-0 bg-[rgba(11,12,16,0.60)] backdrop-blur-md z-20">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg border border-border/70 bg-[rgba(17,19,26,0.55)] flex items-center justify-center">
                    <BarChart3 size={18} className="text-[color:rgba(108,77,255,0.75)]" />
                  </div>
                  <span className="font-black text-sm uppercase tracking-tight">
                    Cola de Proceso
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground px-2 py-1 rounded-md border border-border/70 bg-[rgba(17,19,26,0.55)]">
                    {queue.length} items
                  </span>
                  <button
                    onClick={handleRecoverStuck}
                    disabled={recovering}
                    className="flex items-center gap-1 rounded-full border border-border/80 bg-[rgba(255,255,255,0.04)] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.2em] transition hover:border-[rgba(108,77,255,0.45)] hover:bg-[rgba(108,77,255,0.08)] disabled:opacity-50"
                  >
                    <ZapOff size={14} className={recovering ? "animate-spin" : ""} />
                    <span>{recovering ? "Revisando..." : "Reconcilia UUID"}</span>
                  </button>
                </div>
              </div>
            </div>

            <div className="p-4 overflow-y-auto flex-1 space-y-3 scrollbar-thin scrollbar-thumb-muted-foreground/20">
              {queue.length === 0 && !loading ? (
                <div className="h-full flex flex-col items-center justify-center text-center p-8">
                  <CheckCircle2 size={40} className="mb-4 opacity-10 text-[rgba(255,255,255,0.55)]" />
                  <p className="text-sm text-muted-foreground font-medium italic">
                    Todos los trámites han sido procesados.
                  </p>
                </div>
              ) : (
                queue.slice(0, 14).map((item, idx) => (
                  <QueueCard key={`${item.site_id}-${item.resource_id}`} item={item} index={idx} />
                ))
              )}
            </div>
          </div>

          {/* Incidents */}
          <div className="morr-card morr-edge rounded overflow-hidden">
            <div className="p-5 border-b border-border/70 flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg border border-[color:rgba(255,60,80,0.25)] bg-[rgba(255,60,80,0.08)] flex items-center justify-center">
                <AlertCircle size={18} className="text-[color:rgba(255,60,80,0.85)]" />
              </div>
              <span className="font-black text-sm uppercase tracking-tight">Incidencias Recientes</span>
            </div>

            <div className="p-4 space-y-3">
              {incidents.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6 italic">
                  Sin registros de fallo hoy.
                </p>
              ) : (
                incidents.slice(0, 3).map((inc, i) => (
                  <div
                    key={i}
                    className={[
                      "p-4 rounded-xl border",
                      "bg-[rgba(255,60,80,0.05)] border-[rgba(255,60,80,0.12)]",
                      "hover:border-[rgba(108,77,255,0.22)] hover:bg-[rgba(255,60,80,0.07)]",
                      "transition-colors",
                      "flex items-start gap-4",
                    ].join(" ")}
                  >
                    <div className="w-10 h-10 rounded-xl border border-[rgba(255,60,80,0.18)] bg-[rgba(255,60,80,0.08)] flex items-center justify-center shrink-0">
                      <AlertCircle size={18} className="text-[color:rgba(255,60,80,0.85)]" />
                    </div>
                    <div className="min-w-0">
                      <h5 className="text-xs font-black truncate text-foreground/90 uppercase">
                        {inc.site_id} / #{formatResource(inc.resource_id)}
                      </h5>
                      <p className="text-[11px] text-muted-foreground mt-1 line-clamp-2 leading-relaxed">
                        {inc.reason || "Error en flujo de automatización"}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
