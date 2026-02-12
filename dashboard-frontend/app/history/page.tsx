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
        if (!selectedDay) return;
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
        <div className="space-y-8 animate-in slide-in-from-left-4 duration-700">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                    <h2 className="text-3xl font-black tracking-tighter">Historial de Ejecución</h2>
                    <p className="text-muted-foreground">Registro detallado de trámites completados y fallidos.</p>
                </div>
                <div className="flex items-center gap-2">
                    <button className="flex items-center gap-2 px-4 py-2 bg-secondary text-foreground rounded-xl text-xs font-bold border border-border hover:bg-secondary/80 transition-all">
                        <Download size={14} /> Exportar CSV
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                {/* Days Sidebar */}
                <aside className="lg:col-span-3 space-y-4">
                    <div className="flex items-center gap-2 mb-2 px-2">
                        <Calendar size={16} className="text-primary" />
                        <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">Fechas</span>
                    </div>
                    <div className="bg-card border border-border rounded-3xl p-2 space-y-1 shadow-sm">
                        {days.map((d) => (
                            <button
                                key={d.day}
                                onClick={() => { setSelectedDay(d.day); setPage(1); }}
                                className={cn(
                                    "w-full flex items-center justify-between px-4 py-3 rounded-2xl text-sm font-medium transition-all group",
                                    selectedDay === d.day ? "bg-primary text-primary-foreground shadow-lg" : "hover:bg-secondary text-muted-foreground hover:text-foreground"
                                )}
                            >
                                <span>{d.day}</span>
                                <span className={cn(
                                    "px-2 py-0.5 rounded text-[10px] font-bold border",
                                    selectedDay === d.day ? "bg-white/20 border-white/10" : "bg-card border-border"
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
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-primary transition-colors" size={16} />
                            <input
                                type="text"
                                placeholder="Filtrar por ID de recurso o site..."
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                className="w-full bg-card border border-border rounded-2xl pl-10 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <button className="p-2.5 bg-card border border-border rounded-xl text-muted-foreground hover:text-foreground transition-colors">
                                <Filter size={18} />
                            </button>
                        </div>
                    </div>

                    <div className="bg-card border border-border rounded-3xl overflow-hidden shadow-sm">
                        <div className="overflow-x-auto">
                            <table className="w-full text-left border-collapse">
                                <thead>
                                    <tr className="bg-secondary/50 border-b border-border">
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">Contexto</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">ID Recurso</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">Tipo</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">Fecha / Hora</th>
                                        <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">Estado</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-border">
                                    {loading && items.length === 0 ? (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-12 text-center text-muted-foreground italic">
                                                Cargando historial operativo...
                                            </td>
                                        </tr>
                                    ) : filteredItems.length === 0 ? (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-12 text-center text-muted-foreground italic">
                                                No se han encontrado registros para esta búsqueda.
                                            </td>
                                        </tr>
                                    ) : (
                                        filteredItems.map((item, idx) => (
                                            <tr key={idx} className="hover:bg-secondary/20 transition-colors group">
                                                <td className="px-6 py-3 font-bold text-sm">{item.site_id}</td>
                                                <td className="px-6 py-3 text-sm font-mono text-muted-foreground">#{item.resource_id}</td>
                                                <td className="px-6 py-3 text-xs">{item.protocol || '-'}</td>
                                                <td className="px-6 py-3 text-xs text-muted-foreground">
                                                    {new Date(item.completed_at || item.started_at).toLocaleString()}
                                                </td>
                                                <td className="px-6 py-3">
                                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-green-500/10 text-green-500 border border-green-500/20 uppercase">
                                                        <CheckCircle2 size={12} /> Exitoso
                                                    </span>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>

                        <div className="p-4 bg-secondary/30 border-t border-border flex items-center justify-between">
                            <span className="text-xs text-muted-foreground">Viendo {filteredItems.length} de {items.length} registros</span>
                            <div className="flex gap-2">
                                <button
                                    disabled={page === 1}
                                    onClick={() => setPage(p => p - 1)}
                                    className="p-2 bg-card border border-border rounded-xl text-muted-foreground hover:text-foreground disabled:opacity-30 transition-all"
                                >
                                    <ChevronLeft size={16} />
                                </button>
                                <button
                                    onClick={() => setPage(p => p + 1)}
                                    className="p-2 bg-card border border-border rounded-xl text-muted-foreground hover:text-foreground transition-all"
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
