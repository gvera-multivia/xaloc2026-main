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
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-1000">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-3xl font-black tracking-tighter">Monitor de Operaciones</h2>
          <p className="text-muted-foreground">Seguimiento técnico de ejecución y flujo de trabajo en tiempo real.</p>
        </div>
        <div className="flex items-center gap-2 bg-secondary/30 p-1.5 rounded-xl border border-border/50">
          <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-muted-foreground">
            <Calendar size={14} />
            {selectedDay}
          </div>
          <button
            onClick={refresh}
            className="flex items-center gap-2 px-4 py-1.5 bg-primary text-primary-foreground rounded-lg text-xs font-bold hover:opacity-90 transition-all shadow-lg active:scale-95"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Actualizar
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/50 text-destructive px-4 py-3 rounded-xl flex items-center gap-3 animate-pulse">
          <AlertCircle size={20} />
          <p className="text-sm font-medium">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Visual Monitor & SLA */}
        <div className="lg:col-span-8 space-y-8">
          <LiveScreencast live={!!liveItem} />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <SlaRing
              progress={ringProgress}
              elapsed={elapsed}
              label={liveItem ? `${liveItem.site_id} #${liveItem.resource_id}` : 'Sistema en Espera'}
            />

            <div className="bg-card border border-border rounded-3xl p-8 shadow-xl flex flex-col justify-center space-y-6">
              <div className="flex items-center justify-between">
                <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground">Métricas en Vivo</h4>
                <Activity size={16} className={liveItem ? "text-primary animate-pulse" : "text-muted-foreground/30"} />
              </div>

              <div className="space-y-4">
                <div className="flex justify-between items-center bg-secondary/20 p-4 rounded-2xl border border-border/50">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Tarea Activa</span>
                  <span className="text-sm font-black text-foreground">{liveItem ? `ID ${liveItem.resource_id}` : 'NINGUNA'}</span>
                </div>
                <div className="flex justify-between items-center bg-secondary/20 p-4 rounded-2xl border border-border/50">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Sitio Fuente</span>
                  <span className="text-sm font-black text-foreground uppercase">{liveItem?.site_id || 'STANDBY'}</span>
                </div>
              </div>

              <div className="pt-4 border-t border-border flex items-center justify-between">
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase font-black text-muted-foreground tracking-tighter">Tiempo de Ejecución</span>
                  <span className="text-2xl font-black font-mono text-primary">{elapsed}</span>
                </div>
                <div className="flex flex-col items-end text-right">
                  <span className="text-[10px] uppercase font-black text-muted-foreground tracking-tighter">Carga SLA</span>
                  <span className="text-2xl font-black font-mono">{ringProgress}%</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Queue & Incidents */}
        <div className="lg:col-span-4 space-y-8">
          {/* Queue Section */}
          <div className="bg-card border border-border rounded-3xl overflow-hidden shadow-xl flex flex-col h-[500px]">
            <div className="p-5 border-b border-border flex items-center justify-between sticky top-0 bg-card/80 backdrop-blur-md z-20">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <BarChart3 size={18} />
                </div>
                <span className="font-black text-sm tracking-tight">Cola de Proceso</span>
              </div>
              <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground bg-secondary px-2 py-1 rounded-md border border-border">
                {queue.length} items
              </span>
            </div>
            <div className="p-4 overflow-y-auto flex-1 space-y-3 z-10 scrollbar-thin scrollbar-thumb-muted-foreground/20">
              {queue.length === 0 && !loading ? (
                <div className="h-full flex flex-col items-center justify-center text-center p-8">
                  <CheckCircle2 size={40} className="mb-4 opacity-10 text-green-400" />
                  <p className="text-sm text-muted-foreground font-medium italic">Todos los trámites han sido procesados.</p>
                </div>
              ) : (
                queue.map((item, idx) => (
                  <QueueCard key={`${item.site_id}-${item.resource_id}`} item={item} index={idx} />
                ))
              )}
            </div>
          </div>

          {/* Incidents Section */}
          <div className="bg-card border border-border rounded-3xl overflow-hidden shadow-xl">
            <div className="p-5 border-b border-border flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center text-red-500">
                <AlertCircle size={18} />
              </div>
              <span className="font-black text-sm tracking-tight">Incidencias Recientes</span>
            </div>
            <div className="p-4 space-y-3">
              {incidents.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6 italic">Sin registros de fallo hoy.</p>
              ) : (
                incidents.slice(0, 3).map((inc, i) => (
                  <div key={i} className="p-4 bg-red-500/5 border border-red-500/10 rounded-2xl flex items-start gap-4 group hover:bg-red-500/10 transition-colors">
                    <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center text-red-500 shrink-0 shadow-inner">
                      <AlertCircle size={18} />
                    </div>
                    <div className="min-w-0">
                      <h5 className="text-xs font-black truncate text-foreground/90 uppercase">{inc.site_id} / #{inc.resource_id}</h5>
                      <p className="text-[10px] text-muted-foreground mt-1 line-clamp-2 leading-relaxed">{inc.reason || 'Error en flujo de automatización'}</p>
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
