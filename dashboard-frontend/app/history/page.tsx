'use client';

import React, { useState, useEffect } from 'react';
import {
    History,
    Search,
    Calendar,
    Filter,
    CheckCircle2,
    XCircle,
    ChevronLeft,
    ChevronRight,
    Download
} from 'lucide-react';
import { historyApi } from '@/lib/api';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export default function HistoryPage() {
    const [days, setDays] = useState<any[]>([]);
    const [selectedDay, setSelectedDay] = useState<string | null>(null);
    const [items, setItems] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);

    const fetchDays = async () => {
        try {
            const res = await historyApi.getDays('all', 1, 20);
            setDays(res.items || []);
            if (res.items && res.items.length > 0 && !selectedDay) {
                setSelectedDay(res.items[0].day);
            }
        } catch (e) {
            console.error('Error fetching days', e);
        }
    };

    const fetchHistory = async () => {
        if (!selectedDay) { setLoading(false); return; }
        setLoading(true);
        try {
            const res = await historyApi.getSuccesses(selectedDay, page, 50);
            setItems(res.items || []);
        } catch (e) {
            console.error('Error fetching history', e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchDays(); }, []);
    useEffect(() => { fetchHistory(); }, [selectedDay, page]);

    const filteredItems = items.filter(it =>
        String(it.resource_id).toLowerCase().includes(search.toLowerCase()) ||
        it.site_id.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="space-y-10 animate-in fade-in duration-700">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                    <h2 className="text-3xl font-black uppercase tracking-tight">Historial de Ejecución</h2>
                    <p className="text-muted-foreground">Registro detallado de trámites completados y fallidos.</p>
                </div>
                <div className="flex items-center gap-2">
                    <button className="flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-[0.18em] bg-[rgba(17,19,26,0.55)] border border-border/70 text-foreground/90 hover:border-[rgba(108,77,255,0.22)] transition-all">
                        <Download size={14} /> Exportar CSV
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                {/* Days Sidebar */}
                <aside className="lg:col-span-3 space-y-4">
                    <div className="flex items-center gap-2 mb-2 px-2">
                        <Calendar size={16} className="text-muted-foreground/60" />
                        <span className="text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/70">Fechas</span>
                    </div>
                    <div className="morr-card rounded-2xl p-2 space-y-1">
                        {days.map((d) => (
                            <button
                                key={d.day}
                                onClick={() => { setSelectedDay(d.day); setPage(1); }}
                                className={cn(
                                    "w-full flex items-center justify-between px-4 py-3 rounded-xl text-[12px] font-black uppercase tracking-[0.10em] transition-all group",
                                    selectedDay === d.day
                                        ? "bg-[color:var(--morr-fate)] text-white"
                                        : "hover:bg-[rgba(255,255,255,0.04)] text-muted-foreground/80 hover:text-foreground"
                                )}
                            >
                                <span>{d.day}</span>
                                <span className={cn(
                                    "px-2 py-0.5 rounded text-[10px] font-black border",
                                    selectedDay === d.day ? "bg-white/20 border-white/10" : "bg-[rgba(11,12,16,0.55)] border-border/70"
                                )}>
                                    {d.count}
                                </span>
                            </button>
                        ))}
                    </div>
                </aside>

                {/* Main Content */}
                <div className="lg:col-span-9 space-y-6">
                    <div className="flex flex-col md:flex-row gap-4">
                        <div className="flex-1 relative group">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/60 group-focus-within:text-[rgba(108,77,255,0.75)] transition-colors" size={16} />
                            <input
                                type="text"
                                placeholder="Filtrar por ID de recurso o site..."
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                className="w-full bg-[rgba(17,19,26,0.55)] border border-border/70 rounded-xl pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:border-[rgba(108,77,255,0.30)] transition-all"
                            />
                        </div>
                    </div>

                    <div className="morr-card morr-edge rounded-2xl overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full text-left border-collapse">
                                <thead>
                                    <tr className="bg-[rgba(17,19,26,0.55)] border-b border-border/70">
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Contexto</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">ID Recurso</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Tipo</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Fecha / Hora</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Estado</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
                                    {loading && items.length === 0 ? (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-12 text-center text-muted-foreground italic text-xs uppercase tracking-widest opacity-50">
                                                Consultando registros operativos...
                                            </td>
                                        </tr>
                                    ) : filteredItems.length === 0 ? (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-12 text-center text-muted-foreground italic text-xs uppercase tracking-widest opacity-50">
                                                No se han encontrado registros para esta búsqueda.
                                            </td>
                                        </tr>
                                    ) : (
                                        filteredItems.map((item, idx) => (
                                            <tr key={idx} className="hover:bg-[rgba(255,255,255,0.03)] transition-colors group">
                                                <td className="px-6 py-3 font-black text-[13px] uppercase tracking-tight">{item.site_id}</td>
                                                <td className="px-6 py-3 text-[12px] font-mono text-muted-foreground/90">#{item.resource_id}</td>
                                                <td className="px-6 py-3 text-[11px] font-bold text-muted-foreground/70">{item.protocol || '-'}</td>
                                                <td className="px-6 py-3 text-[11px] font-mono text-muted-foreground/60 uppercase">
                                                    {new Date(item.completed_at || item.started_at).toLocaleString('es-ES')}
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
                            <span className="text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/60">Viendo {filteredItems.length} de {items.length} registros</span>
                            <div className="flex gap-2">
                                <button
                                    disabled={page === 1}
                                    onClick={() => setPage(p => p - 1)}
                                    className="p-2 rounded-xl bg-[rgba(11,12,16,0.55)] border border-border/70 text-muted-foreground/70 hover:text-foreground disabled:opacity-30 transition-all hover:border-[rgba(108,77,255,0.22)]"
                                >
                                    <ChevronLeft size={16} />
                                </button>
                                <button
                                    onClick={() => setPage(p => p + 1)}
                                    className="p-2 rounded-xl bg-[rgba(11,12,16,0.55)] border border-border/70 text-muted-foreground/70 hover:text-foreground transition-all hover:border-[rgba(108,77,255,0.22)]"
                                >
                                    <ChevronRight size={16} />
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
