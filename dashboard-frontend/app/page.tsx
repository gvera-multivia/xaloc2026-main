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
} from 'lucide-react';
import { queueApi, historyApi } from '@/lib/api';
import { QueueItem, Incident, EventLog } from '@/lib/types';
import LiveScreencast from '@/components/monitor/LiveScreencast';
import SlaRing from '@/components/monitor/SlaRing';
import QueueCard from '@/components/monitor/QueueCard';

export default function MonitorPage() {
  const [selectedDay] = useState(new Date().toISOString().split('T')[0]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [nowTs, setNowTs] = useState(Date.now());

  const refresh = async () => {
    try {
      const [queueRes, incidentsRes] = await Promise.all([
        queueApi.getCurrent(selectedDay, 1, 14),
        historyApi.getIncidents(selectedDay, 1, 15),
      ]);

      setQueue(queueRes.items || []);
      setIncidents(incidentsRes.items || []);
      setError('');
    } catch (e) {
      setError('No se pudo actualizar el monitor en vivo.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    const clock = setInterval(() => setNowTs(Date.now()), 1000);
    return () => {
      clearInterval(interval);
      clearInterval(clock);
    };
  }, [selectedDay]);

  const liveItem = useMemo(() => queue.find(x => x.state === 'processing'), [queue]);

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
  <div className="space-y-8 animate-in fade-in duration-700">
    {/* Header */}
    <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
      <div>
        <h2 className="text-3xl font-black tracking-tight uppercase">
          Monitor de Operaciones
        </h2>
        <p className="text-muted-foreground">
          Seguimiento técnico de ejecución y flujo de trabajo en tiempo real.
        </p>
      </div>

      {/* Date + refresh */}
      <div className="flex items-center gap-2 rounded-xl border border-border/60 px-2 py-2 morr-card">
        <div className="flex items-center gap-2 px-3 py-1.5 text-[11px] font-black uppercase tracking-[0.22em] text-muted-foreground">
          <Calendar size={14} />
          {selectedDay}
        </div>

        <button
          onClick={refresh}
          className={[
            "flex items-center gap-2 px-4 py-2 rounded-lg",
            "text-[11px] font-black uppercase tracking-[0.18em]",
            "bg-[color:var(--morr-fate)] text-white",
            "border border-transparent",
            "hover:border-[color:rgba(108,77,255,0.35)]",
            "hover:shadow-[0_0_0_1px_rgba(75,46,131,0.25)]",
            "transition active:scale-[0.99]",
          ].join(" ")}
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Actualizar
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
        <LiveScreencast live={!!liveItem} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <SlaRing
            progress={ringProgress}
            elapsed={elapsed}
            label={liveItem ? `${liveItem.site_id} #${liveItem.resource_id}` : "Sistema en Espera"}
          />

          {/* Live metrics card */}
          <div className="morr-card morr-edge rounded-2xl p-7">
            <div className="flex items-center justify-between">
              <h4 className="text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground">
                Métricas en Vivo
              </h4>
              <Activity
                size={16}
                className={liveItem ? "text-[color:var(--morr-fate)]" : "text-muted-foreground/40"}
              />
            </div>

            <div className="mt-5 space-y-3">
              <div className="flex justify-between items-center rounded-xl border border-border/60 bg-[rgba(17,19,26,0.55)] p-4">
                <span className="text-[11px] font-black uppercase tracking-[0.16em] text-muted-foreground">
                  Tarea Activa
                </span>
                <span className="text-sm font-black text-foreground">
                  {liveItem ? `ID ${liveItem.resource_id}` : "NINGUNA"}
                </span>
              </div>

              <div className="flex justify-between items-center rounded-xl border border-border/60 bg-[rgba(17,19,26,0.55)] p-4">
                <span className="text-[11px] font-black uppercase tracking-[0.16em] text-muted-foreground">
                  Sitio Fuente
                </span>
                <span className="text-sm font-black text-foreground uppercase">
                  {liveItem?.site_id || "STANDBY"}
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
        <div className="morr-card morr-edge rounded-2xl overflow-hidden flex flex-col h-[500px]">
          <div className="p-5 border-b border-border/70 sticky top-0 bg-[rgba(11,12,16,0.60)] backdrop-blur-md z-20">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg border border-border/70 bg-[rgba(17,19,26,0.55)] flex items-center justify-center">
                  <BarChart3 size={18} className="text-[color:rgba(108,77,255,0.75)]" />
                </div>
                <span className="font-black text-sm uppercase tracking-tight">
                  Cola de Proceso
                </span>
              </div>

              <span className="text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground px-2 py-1 rounded-md border border-border/70 bg-[rgba(17,19,26,0.55)]">
                {queue.length} items
              </span>
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

        {/* Incidents */}
        <div className="morr-card morr-edge rounded-2xl overflow-hidden">
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
                      {inc.site_id} / #{inc.resource_id}
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
