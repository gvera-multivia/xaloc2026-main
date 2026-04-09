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
  ExternalLink,
  Lock,
  Unlock,
} from 'lucide-react';
import Link from 'next/link';
import { queueApi, historyApi, incidentsApi } from '@/lib/api';
import { QueueItem } from '@/lib/types';
import LiveScreencast from '@/components/monitor/LiveScreencast';
import SlaRing from '@/components/monitor/SlaRing';
import QueueCard from '@/components/monitor/QueueCard';
import { sileo } from 'sileo';

export default function MonitorPage() {
  const QUEUE_REFRESH_MS = 3000;
  const INCIDENT_MARKER_POLL_MS = 10000;
  const LIVE_STREAM_GRACE_MS = 8000;

  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [nowTs, setNowTs] = useState(Date.now());
  const [lastLiveSeenTs, setLastLiveSeenTs] = useState(0);
  const completionMarkerRef = useRef<string>('');
  const successCountRef = useRef<number>(-1);
  const monitorFailStreakRef = useRef<number>(0);
  const incidentsFailStreakRef = useRef<number>(0);
  const queueRequestRef = useRef(false);
  const markerRequestRef = useRef(false);
  const incidentsRequestRef = useRef(false);
  const [recovering, setRecovering] = useState(false);

  const showTransientError = (message: string, ms = 5000) => {
    setError(message);
    if (errorTimerRef.current) {
      clearTimeout(errorTimerRef.current);
    }
    errorTimerRef.current = setTimeout(() => setError(''), ms);
  };

  const today = useMemo(() => new Date().toISOString().split('T')[0], []);

  const refreshQueue = async () => {
    if (queueRequestRef.current) return;
    queueRequestRef.current = true;
    try {
      const queueRes = await queueApi.getCurrent(1, 1000);
      setQueue(queueRes.items || []);
    } finally {
      queueRequestRef.current = false;
    }
  };

  const refreshIncidents = async () => {
    if (incidentsRequestRef.current) return;
    incidentsRequestRef.current = true;
    try {
      const incidentsRes = await incidentsApi.getPending(1, 10);
      setIncidents(incidentsRes.items || []);
      incidentsFailStreakRef.current = 0;
    } finally {
      incidentsRequestRef.current = false;
    }
  };

  const refreshMarker = async () => {
    if (markerRequestRef.current) return null;
    markerRequestRef.current = true;
    try {
      return await queueApi.getCompletionMarker(today);
    } finally {
      markerRequestRef.current = false;
    }
  };

  const refresh = async () => {
    const [markerRes, queueRes, incidentsRes] = await Promise.allSettled([
      refreshMarker(),
      refreshQueue(),
      refreshIncidents(),
    ]);

    if (markerRes.status === 'fulfilled' && markerRes.value) {
      completionMarkerRef.current = markerRes.value.marker || '';
      monitorFailStreakRef.current = 0;
      // Seed success count on first load (no notification on initial load)
      if (successCountRef.current < 0) {
        successCountRef.current = Number((markerRes.value as any).success_count || 0);
      }
    }

    const hardFail = markerRes.status === 'rejected' || queueRes.status === 'rejected';
    if (hardFail) {
      monitorFailStreakRef.current += 1;
      if (monitorFailStreakRef.current >= 3) {
        sileo.error({ title: 'Error de sincronización', description: 'No se pudo actualizar el monitor en vivo.' });
        showTransientError('No se pudo actualizar el monitor en vivo.');
      }
    } else if (incidentsRes.status === 'rejected') {
      incidentsFailStreakRef.current += 1;
      if (incidentsFailStreakRef.current >= 3) {
        // Evitar banner permanente por ruido de polling de incidencias.
        showTransientError('No se pudo actualizar el panel de incidencias.', 3000);
      }
    } else {
      incidentsFailStreakRef.current = 0;
      setError('');
    }
    setLoading(false);
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
        monitorFailStreakRef.current = 0;
      } catch (e) {
        monitorFailStreakRef.current += 1;
        // Silencioso en polling; evitar banner permanente por ruido de red.
      }
    }, QUEUE_REFRESH_MS);

    const markerPoll = setInterval(async () => {
      try {
        const markerRes = await refreshMarker() as any;
        if (!markerRes) return;
        const marker = markerRes.marker || '';
        monitorFailStreakRef.current = 0;
        if (completionMarkerRef.current && completionMarkerRef.current !== marker) {
          void refreshIncidents().catch(() => {
            incidentsFailStreakRef.current += 1;
          });
        }
        completionMarkerRef.current = marker;

        // Detect new successful completions
        const newSuccessCount = Number(markerRes.success_count || 0);
        if (successCountRef.current >= 0 && newSuccessCount > successCountRef.current) {
          const lastSuccess = markerRes.last_success;
          const siteLabel = lastSuccess?.site_id?.replace(/_/g, ' ')?.toUpperCase() || '';
          const resId = lastSuccess?.resource_id ?? '';
          sileo.success({
            title: 'Tramite completado',
            description: siteLabel && resId
              ? `${siteLabel} #${resId} completado y marcado en XVIA.`
              : `${newSuccessCount - successCountRef.current} tramite(s) completado(s) correctamente.`,
          });
          if (typeof window !== 'undefined' && 'Notification' in window && window.Notification.permission === 'granted') {
            new window.Notification('Tramite completado', {
              body: siteLabel && resId
                ? `${siteLabel} #${resId} completado y marcado en XVIA.`
                : `${newSuccessCount - successCountRef.current} tramite(s) completado(s).`,
              icon: '/favicon.ico',
            });
          }
        }
        successCountRef.current = newSuccessCount;
      } catch (e) {
        monitorFailStreakRef.current += 1;
      }
    }, INCIDENT_MARKER_POLL_MS);

    const clock = setInterval(() => setNowTs(Date.now()), 1000);
    return () => {
      clearInterval(interval);
      clearInterval(markerPoll);
      clearInterval(clock);
      if (errorTimerRef.current) {
        clearTimeout(errorTimerRef.current);
      }
    };
  }, [today]);

  const liveItem = useMemo(() => queue.find(x => (x.state || '').toLowerCase() === 'processing') || null, [queue]);
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
          <LiveScreencast live={liveStreamEnabled} />

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
                queue.map((item, idx) => (
                  <QueueCard key={`${item.site_id}-${item.resource_id}`} item={item} index={idx} />
                ))
              )}
            </div>
          </div>

          {/* Incidencias Pendientes (Preview) */}
          <div className="morr-card morr-edge rounded overflow-hidden">
            <div className="p-5 border-b border-border/70 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg border border-[color:rgba(255,60,80,0.25)] bg-[rgba(255,60,80,0.08)] flex items-center justify-center">
                  <AlertCircle size={18} className="text-[color:rgba(255,60,80,0.85)]" />
                </div>
                <span className="font-black text-sm uppercase tracking-tight">Incidencias Pendientes</span>
              </div>
              
              <Link
                href="/incidents"
                className="flex items-center gap-1 text-[9px] font-black uppercase tracking-[0.2em] text-muted-foreground/60 hover:text-[color:var(--morr-fate)] transition-colors group"
              >
                <span>Ver todas</span>
                <ExternalLink size={10} className="group-hover:translate-x-0.5 transition-transform" />
              </Link>
            </div>

            <div className="p-4 space-y-3">
              {incidents.length === 0 ? (
                <div className="py-12 flex flex-col items-center justify-center text-center">
                  <CheckCircle2 size={32} className="mb-3 opacity-10 text-emerald-500" />
                  <p className="text-[10px] text-muted-foreground font-black uppercase tracking-widest">
                    Sin incidencias pendientes
                  </p>
                </div>
              ) : (
                incidents.slice(0, 4).map((inc, i) => (
                  <div
                    key={inc.incident_id || i}
                    className={[
                      "p-4 rounded-xl border",
                      "bg-[rgba(255,255,255,0.02)] border-border/40",
                      "hover:border-[color:var(--morr-fate-low)] hover:bg-[rgba(255,255,255,0.04)]",
                      "transition-all duration-300",
                      "flex items-start gap-4",
                    ].join(" ")}
                  >
                    <div className="w-10 h-10 rounded-xl border border-border/60 bg-black/20 flex items-center justify-center shrink-0">
                      {inc.locked ? (
                        <Lock size={16} className="text-amber-500/80" />
                      ) : (
                        <AlertCircle size={16} className="text-red-500/80" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between">
                        <h5 className="text-[10px] font-black truncate text-foreground/90 uppercase tracking-wider">
                          {inc.site_id} / #{formatResource(inc.resource_id)}
                        </h5>
                        {inc.locked && (
                          <span className="text-[8px] font-black uppercase tracking-tighter text-amber-500/60 ml-2 truncate max-w-[80px]">
                            {inc.lock_username || "BLOQUEADO"}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground/70 mt-1 line-clamp-1 leading-relaxed italic">
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
