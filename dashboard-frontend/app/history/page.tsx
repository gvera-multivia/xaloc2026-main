'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { Search, Calendar, CheckCircle2, ChevronLeft, ChevronRight, Download, X } from 'lucide-react';
import { historyApi } from '@/lib/api';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { sileo } from 'sileo';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type HistoryItem = {
  site_id: string;
  resource_id?: number | string;
  protocol?: string;
  started_at?: string;
  ended_at?: string;
  expediente?: string | null;
  fase_procedimiento?: string | null;
  payload?: Record<string, any>;
  result?: Record<string, any>;
};

type FolderResolve = {
  path: string;
  exists: boolean;
  fase_procedimiento?: string | null;
  fase_folder?: string | null;
  ruta_cliente?: string;
};

const DAYS_PER_BLOCK = 35;

export default function HistoryPage() {
  const [days, setDays] = useState<any[]>([]);
  const [daysBlockPage, setDaysBlockPage] = useState(1);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [totalItemsForDay, setTotalItemsForDay] = useState(0);

  const [selectedItem, setSelectedItem] = useState<HistoryItem | null>(null);
  const [folderInfo, setFolderInfo] = useState<FolderResolve | null>(null);
  const [folderLoading, setFolderLoading] = useState(false);

  const getExpediente = (item: HistoryItem): string => {
    return String(
      item.expediente ||
      item.payload?.expediente ||
      item.payload?.expediente_num ||
      item.payload?.denuncia_num ||
      item.payload?.nExp ||
      '-',
    );
  };

  const getFaseProcedimiento = (item: HistoryItem): string => {
    return String(
      item.fase_procedimiento ||
      item.payload?.fase_procedimiento ||
      item.payload?.FaseProcedimiento ||
      item.protocol ||
      '-',
    );
  };

  const toDisplayNetworkPath = (inputPath?: string | null): string => {
    const raw = String(inputPath || '').trim();
    if (!raw) return '-';
    const normalized = raw.replace(/\\/g, '/');
    if (normalized.startsWith('/mnt/clientes')) {
      const tail = normalized.slice('/mnt/clientes'.length).replace(/\//g, '\\');
      return `\\\\SERVER-DOC\\clientes${tail}`;
    }
    if (normalized.startsWith('/mnt/')) {
      const tail = normalized.slice('/mnt/'.length).replace(/\//g, '\\');
      return `\\\\SERVER-DOC\\${tail}`;
    }
    return raw;
  };

  const fetchDays = async () => {
    try {
      const pageSize = 100;
      let currentPage = 1;
      let total = 0;
      const allDays: any[] = [];

      do {
        const res = await historyApi.getDays('success', currentPage, pageSize);
        const chunk = (res.items || []) as any[];
        total = Number(res.total || 0);
        allDays.push(...chunk);
        currentPage += 1;
      } while (allDays.length < total);

      setDays(allDays);
      if (allDays.length > 0 && !selectedDay) {
        const first = typeof allDays[0] === 'string' ? allDays[0] : allDays[0].day;
        setSelectedDay(first);
      }
    } catch {
      sileo.error({ title: 'Error al cargar fechas', description: 'No se pudo obtener el listado de días del historial.' });
    }
  };

  const fetchHistory = async () => {
    if (!selectedDay) { setLoading(false); return; }
    setLoading(true);
    try {
      const pageSize = 500;
      let currentPage = 1;
      let total = 0;
      const allItems: HistoryItem[] = [];
      do {
        const res = await historyApi.getSuccesses(selectedDay, currentPage, pageSize);
        const chunk = (res.items || []) as HistoryItem[];
        total = Number(res.total || 0);
        allItems.push(...chunk);
        currentPage += 1;
      } while (allItems.length < total);
      setItems(allItems);
      setTotalItemsForDay(total || allItems.length);
    } catch {
      sileo.error({ title: 'Error al cargar historial', description: `No se pudo obtener el historial para el día ${selectedDay}.` });
    } finally {
      setLoading(false);
    }
  };

  const openDetail = async (item: HistoryItem) => {
    setSelectedItem(item);
    setFolderInfo(null);
    setFolderLoading(true);
    try {
      const payload = item.payload || {};
      const mergedPayload = {
        ...payload,
        expediente: payload.expediente || item.expediente,
        fase_procedimiento: payload.fase_procedimiento || item.fase_procedimiento || item.protocol,
      };
      const folder = await historyApi.resolveClientFolder(mergedPayload);
      setFolderInfo(folder);
    } catch (err: any) {
      sileo.error({
        title: 'No se pudo reconstruir la ruta',
        description: String(err?.message || 'Error desconocido'),
      });
    } finally {
      setFolderLoading(false);
    }
  };

  useEffect(() => { void fetchDays(); }, []);
  useEffect(() => { void fetchHistory(); }, [selectedDay]);

  const totalDayBlocks = Math.max(1, Math.ceil(days.length / DAYS_PER_BLOCK));
  const safeDayBlockPage = Math.min(daysBlockPage, totalDayBlocks);
  const dayBlockStart = (safeDayBlockPage - 1) * DAYS_PER_BLOCK;
  const visibleDays = days.slice(dayBlockStart, dayBlockStart + DAYS_PER_BLOCK);

  useEffect(() => {
    if (!selectedDay || days.length === 0) return;
    const selectedIndex = days.findIndex((d: any) => {
      const dayStr = typeof d === 'string' ? d : d.day;
      return dayStr === selectedDay;
    });
    if (selectedIndex < 0) return;
    const targetBlock = Math.floor(selectedIndex / DAYS_PER_BLOCK) + 1;
    if (targetBlock !== daysBlockPage) {
      setDaysBlockPage(targetBlock);
    }
  }, [selectedDay, days, daysBlockPage]);

  const filteredItems = items.filter((it) =>
    String(it.resource_id || '').toLowerCase().includes(search.toLowerCase()) ||
    String(it.site_id || '').toLowerCase().includes(search.toLowerCase()) ||
    getExpediente(it).toLowerCase().includes(search.toLowerCase()) ||
    getFaseProcedimiento(it).toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-10 animate-in fade-in duration-700">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tight">Historial de Ejecución</h2>
          <p className="text-xs text-muted-foreground/60 uppercase tracking-widest mt-1">Registro de trámites completados.</p>
          <div className="mt-3 flex items-center gap-2">
            <Link
              href="/history"
              className="px-3 py-1.5 rounded-sm text-[10px] font-black uppercase tracking-[0.15em] border border-[rgba(108,77,255,0.35)] bg-[rgba(108,77,255,0.16)] text-foreground/90"
            >
              Historial
            </Link>
            <Link
              href="/history/top"
              className="px-3 py-1.5 rounded-sm text-[10px] font-black uppercase tracking-[0.15em] border border-border/70 bg-[rgba(17,19,26,0.55)] text-muted-foreground/80 hover:text-foreground hover:border-[rgba(108,77,255,0.22)] transition-all"
            >
              Ranking Usuarios
            </Link>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-2 px-6 py-2 rounded-sm text-[9px] font-black uppercase tracking-[0.2em] bg-[rgba(17,19,26,0.65)] border border-border/70 text-foreground/80 hover:border-[rgba(108,77,255,0.22)] transition-all duration-300">
            <Download size={12} /> Exportar Reporte
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <aside className="lg:col-span-3 space-y-4">
          <div className="flex items-center gap-2 mb-2 px-2">
            <Calendar size={16} className="text-muted-foreground/60" />
            <span className="text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/70">Fechas</span>
          </div>
          <div className="morr-card rounded p-2 space-y-1">
            {visibleDays.map((d: any) => {
              const dayStr = typeof d === 'string' ? d : d.day;
              return (
                <button
                  key={dayStr}
                  onClick={() => { setSelectedDay(dayStr); }}
                  className={cn(
                    'w-full flex items-center justify-between px-4 py-2.5 rounded-sm text-[11px] font-black uppercase tracking-[0.12em] transition-all duration-300 group',
                    selectedDay === dayStr
                      ? 'bg-[color:var(--morr-fate)] text-white/90 shadow-inner'
                      : 'hover:bg-foreground/5 text-muted-foreground/60 hover:text-foreground/90'
                  )}
                >
                  <span>{dayStr}</span>
                  {selectedDay === dayStr && <div className="h-1 w-1 rounded-full bg-white animate-pulse" />}
                </button>
              );
            })}
            <div className="pt-2 mt-2 border-t border-border/60 flex items-center justify-between gap-2">
              <button
                disabled={safeDayBlockPage <= 1}
                onClick={() => setDaysBlockPage((prev) => Math.max(1, prev - 1))}
                className="px-2.5 py-1.5 rounded-sm text-[10px] font-black uppercase tracking-[0.14em] border border-border/70 text-muted-foreground/70 disabled:opacity-30 hover:text-foreground hover:border-[rgba(108,77,255,0.22)] transition-all"
              >
                <ChevronLeft size={13} className="inline mr-1" />
                Bloque
              </button>
              <span className="text-[10px] font-black uppercase tracking-[0.14em] text-muted-foreground/65">
                {safeDayBlockPage}/{totalDayBlocks}
              </span>
              <button
                disabled={safeDayBlockPage >= totalDayBlocks}
                onClick={() => setDaysBlockPage((prev) => Math.min(totalDayBlocks, prev + 1))}
                className="px-2.5 py-1.5 rounded-sm text-[10px] font-black uppercase tracking-[0.14em] border border-border/70 text-muted-foreground/70 disabled:opacity-30 hover:text-foreground hover:border-[rgba(108,77,255,0.22)] transition-all"
              >
                Bloque
                <ChevronRight size={13} className="inline ml-1" />
              </button>
            </div>
          </div>
        </aside>

        <div className="lg:col-span-9 space-y-6">
          <div className="flex flex-col md:flex-row gap-4">
            <div className="flex-1 relative group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/60 group-focus-within:text-[rgba(108,77,255,0.75)] transition-colors" size={16} />
              <input
                type="text"
                placeholder="Filtrar por recurso, expediente, fase o site..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-[rgba(17,19,26,0.55)] border border-border/70 rounded-xl pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:border-[rgba(108,77,255,0.30)] transition-all"
              />
            </div>
          </div>

          <div className="morr-card morr-edge rounded overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[rgba(17,19,26,0.55)] border-b border-border/70">
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Contexto</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">ID Recurso</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Expediente</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Fase Procedimiento</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Fecha / Hora</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Estado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
                  {loading && items.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-12 text-center text-muted-foreground italic text-xs uppercase tracking-widest opacity-50">
                        Consultando registros operativos...
                      </td>
                    </tr>
                  ) : filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-12 text-center text-muted-foreground italic text-xs uppercase tracking-widest opacity-50">
                        No se han encontrado registros para esta búsqueda.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map((item, idx) => (
                      <tr
                        key={idx}
                        className="hover:bg-[rgba(255,255,255,0.03)] transition-colors group cursor-pointer"
                        onClick={() => void openDetail(item)}
                      >
                        <td
                          className="px-6 py-3 text-[11px] font-semibold uppercase tracking-[0.04em] leading-tight max-w-[260px] break-words"
                          title={item.site_id}
                        >
                          {item.site_id}
                        </td>
                        <td className="px-6 py-3 text-[12px] font-mono text-muted-foreground/90">#{item.resource_id || '-'}</td>
                        <td className="px-6 py-3 text-[11px] font-mono text-muted-foreground/80">{getExpediente(item)}</td>
                        <td className="px-6 py-3 text-[11px] font-bold text-muted-foreground/80">{getFaseProcedimiento(item)}</td>
                        <td className="px-6 py-3 text-[11px] font-mono text-muted-foreground/60 uppercase">
                          {new Date(item.ended_at || item.started_at || '').toLocaleString('es-ES')}
                        </td>
                        <td className="px-6 py-3">
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[9px] font-black bg-[rgba(108,77,255,0.08)] text-foreground/90 border border-[rgba(108,77,255,0.22)] uppercase tracking-[0.12em]">
                            <CheckCircle2 size={12} className="opacity-70" /> COMPLETADO
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="p-4 bg-[rgba(17,19,26,0.55)] border-t border-border/70 flex items-center justify-between">
              <span className="text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/60">
                Viendo {filteredItems.length} de {items.length} registros (total día: {totalItemsForDay})
              </span>
            </div>
          </div>
        </div>
      </div>

      {selectedItem && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-3xl rounded-xl border border-border/70 bg-[rgba(17,19,26,0.95)] p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-black uppercase tracking-[0.14em]">Detalle del Registro</h3>
              <button
                onClick={() => { setSelectedItem(null); setFolderInfo(null); }}
                className="rounded-md border border-border/70 p-2 hover:border-foreground/40 transition"
              >
                <X size={14} />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div className="rounded-md border border-border/60 bg-background/20 p-3"><strong>Organismo:</strong> {selectedItem.site_id}</div>
              <div className="rounded-md border border-border/60 bg-background/20 p-3"><strong>ID recurso:</strong> {String(selectedItem.resource_id || '-')}</div>
              <div className="rounded-md border border-border/60 bg-background/20 p-3"><strong>Expediente:</strong> {getExpediente(selectedItem)}</div>
              <div className="rounded-md border border-border/60 bg-background/20 p-3"><strong>Fase procedimiento:</strong> {getFaseProcedimiento(selectedItem)}</div>
            </div>

            <div className="rounded-md border border-border/60 bg-background/20 p-3 text-xs">
              <div className="font-semibold mb-2">Ruta reconstruida del justificante</div>
              {folderLoading ? (
                <div className="text-muted-foreground">Reconstruyendo ruta...</div>
              ) : folderInfo ? (
                <div className="space-y-1">
                  <div><strong>Ruta cliente:</strong> {toDisplayNetworkPath(folderInfo.ruta_cliente)}</div>
                  <div><strong>Subcarpeta fase:</strong> {folderInfo.fase_folder || 'RECURSOS TELEMATICOS'}</div>
                  <div><strong>Ruta final:</strong> {toDisplayNetworkPath(folderInfo.path)}</div>
                  <div><strong>Existe:</strong> {folderInfo.exists ? 'Sí' : 'No'}</div>
                </div>
              ) : (
                <div className="text-muted-foreground">Sin datos de ruta.</div>
              )}
            </div>

            <div className="rounded-md border border-border/60 bg-black/30 p-3 text-[11px]">
              <div className="font-semibold mb-1">Payload técnico</div>
              <pre className="whitespace-pre-wrap">{JSON.stringify(selectedItem.payload || {}, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
