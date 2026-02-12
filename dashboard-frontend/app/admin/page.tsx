'use client';

import React, { useState, useEffect, useMemo } from 'react';
import {
    Settings,
    ShieldCheck,
    Pause,
    Play,
    Trash2,
    RotateCcw,
    Clock,
    AlertTriangle,
    ChevronRight,
    MoreVertical,
    Check,
    X
} from 'lucide-react';
import { queueApi, authApi, api } from '@/lib/api';
import { QueueItem, PendingAuth, PauseInfo, ItemPauseInfo } from '@/lib/types';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export default function AdminPage() {
    const [selectedDay] = useState(new Date().toISOString().split('T')[0]);
    const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
    const [pauses, setPauses] = useState<PauseInfo[]>([]);
    const [itemPauses, setItemPauses] = useState<ItemPauseInfo[]>([]);
    const [pendingAuth, setPendingAuth] = useState<PendingAuth[]>([]);
    const [globalReason, setGlobalReason] = useState('');
    const [globalMinutes, setGlobalMinutes] = useState('120');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState<string | null>(null);

    const refresh = async () => {
        try {
            const [queueRes, pausesRes, itemPausesRes, authRes] = await Promise.all([
                queueApi.getCurrent(selectedDay, 1, 1000),
                api.get<{ items: PauseInfo[] }>('/queue/pauses?active_only=true'),
                api.get<{ items: ItemPauseInfo[] }>('/queue/item-pauses?active_only=true'),
                authApi.getPending(),
            ]);

            setQueueItems(queueRes.items || []);
            setPauses(pausesRes.items || []);
            setItemPauses(itemPausesRes.items || []);
            setPendingAuth(authRes.items || []);
            setError('');
        } catch (e) {
            setError('Error al cargar datos administrativos.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, 10000);
        return () => clearInterval(id);
    }, [selectedDay]);

    const KNOWN_SITES = ['madrid', 'xaloc_girona', 'base_online'];

    const sites = useMemo(() => {
        const s = new Set(KNOWN_SITES);
        queueItems.forEach(it => s.add(it.site_id));
        pauses.forEach(p => s.add(p.site_id));
        return Array.from(s).filter(Boolean).sort();
    }, [queueItems, pauses]);

    const pauseMap = useMemo(() => {
        const map: Record<string, PauseInfo> = {};
        pauses.forEach(p => { map[p.site_id] = p; });
        return map;
    }, [pauses]);

    const itemPauseMap = useMemo(() => {
        const map: Record<string, ItemPauseInfo> = {};
        itemPauses.forEach(p => { map[`${p.site_id}::${p.resource_id}`] = p; });
        return map;
    }, [itemPauses]);

    const handlePause = async (siteId: string, minutes?: number) => {
        setBusy(`pause-${siteId}`);
        try {
            await queueApi.pauseSite(siteId, minutes, globalReason);
            await refresh();
        } catch (e) {
            setError(`Error al pausar ${siteId}`);
        } finally {
            setBusy(null);
        }
    };

    const handleUnpause = async (siteId: string) => {
        setBusy(`unpause-${siteId}`);
        try {
            await queueApi.unpauseSite(siteId);
            await refresh();
        } catch (e) {
            setError(`Error al reanudar ${siteId}`);
        } finally {
            setBusy(null);
        }
    };

    const handleApproveAuth = async (id: number) => {
        setBusy(`auth-${id}`);
        try {
            await authApi.approve(id);
            await refresh();
        } catch (e) {
            setError('Error al aprobar autorización');
        } finally {
            setBusy(null);
        }
    };

    const handleRejectAuth = async (id: number) => {
        const reason = prompt('Motivo del rechazo:');
        if (!reason) return;
        setBusy(`auth-${id}`);
        try {
            await authApi.reject(id, reason);
            await refresh();
        } catch (e) {
            setError('Error al rechazar autorización');
        } finally {
            setBusy(null);
        }
    };

    const handleDeleteItem = async (siteId: string, resourceId: string | number) => {
        if (!confirm(`¿Eliminar ${resourceId} de ${siteId}?`)) return;
        setBusy(`del-${siteId}-${resourceId}`);
        try {
            await queueApi.deleteItem(siteId, resourceId);
            await refresh();
        } catch (e) {
            setError('Error al eliminar item');
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="space-y-10 animate-in fade-in duration-700">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                    <h2 className="text-3xl font-black tracking-tighter">Panel de Gestión</h2>
                    <p className="text-muted-foreground">Control de sitios, pausas y autorizaciones operativas.</p>
                </div>
            </div>

            {error && (
                <div className="bg-destructive/10 border border-destructive/50 text-destructive px-4 py-3 rounded-xl flex items-center gap-3">
                    <AlertTriangle size={18} />
                    <p className="text-sm font-medium">{error}</p>
                </div>
            )}

            {/* Authorizations */}
            <section className="space-y-4">
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-yellow-400/10 rounded-lg flex items-center justify-center text-yellow-400 shadow-inner">
                        <ShieldCheck size={20} />
                    </div>
                    <h3 className="text-xl font-bold tracking-tight">Autorizaciones Pendientes</h3>
                    <span className={cn(
                        "px-2 py-0.5 rounded-full text-[10px] font-black tracking-widest uppercase border",
                        pendingAuth.length > 0 ? "bg-red-500/10 text-red-500 border-red-500/20 animate-pulse" : "bg-muted text-muted-foreground border-border"
                    )}>
                        {pendingAuth.length} Req.
                    </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {pendingAuth.length === 0 ? (
                        <div className="col-span-full py-8 text-center bg-secondary/10 border border-dashed border-border rounded-3xl text-muted-foreground">
                            <p className="text-sm italic">No hay peticiones de autorización pendientes.</p>
                        </div>
                    ) : (
                        pendingAuth.map((auth) => (
                            <div key={auth.id} className="bg-card border border-border rounded-3xl p-6 shadow-sm hover:shadow-md transition-shadow space-y-4">
                                <div className="flex justify-between items-start">
                                    <div>
                                        <h4 className="font-bold text-lg">{auth.site_id}</h4>
                                        <p className="text-xs text-muted-foreground">Recurso: <span className="text-foreground">#{auth.resource_id}</span></p>
                                    </div>
                                    <span className="text-[10px] bg-secondary px-2 py-1 rounded-md text-muted-foreground font-mono">
                                        {new Date(auth.created_at).toLocaleTimeString()}
                                    </span>
                                </div>

                                <div className="bg-secondary/50 p-3 rounded-2xl border border-border/50">
                                    <p className="text-xs font-bold text-muted-foreground uppercase mb-1">Motivo</p>
                                    <p className="text-sm font-medium leading-relaxed">{auth.reason || 'Requiere intervención manual'}</p>
                                </div>

                                <div className="flex gap-2">
                                    <button
                                        onClick={() => handleApproveAuth(auth.id)}
                                        disabled={busy === `auth-${auth.id}`}
                                        className="flex-1 bg-primary text-primary-foreground py-2.5 rounded-xl text-xs font-bold hover:opacity-90 transition-all flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
                                    >
                                        <Check size={14} /> Autorizar
                                    </button>
                                    <button
                                        onClick={() => handleRejectAuth(auth.id)}
                                        disabled={busy === `auth-${auth.id}`}
                                        className="flex-1 bg-secondary text-foreground py-2.5 rounded-xl text-xs font-bold hover:bg-destructive/10 hover:text-destructive transition-all flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
                                    >
                                        <X size={14} /> Rechazar
                                    </button>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </section>

            {/* Site Control Table */}
            <section className="space-y-4">
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-blue-400/10 rounded-lg flex items-center justify-center text-blue-400 shadow-inner">
                        <Settings size={20} />
                    </div>
                    <h3 className="text-xl font-bold tracking-tight">Control de Sitios Operativos</h3>
                </div>

                <div className="bg-card border border-border rounded-3xl overflow-hidden shadow-sm">
                    <div className="overflow-x-auto">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="bg-secondary/50 border-b border-border">
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">Site / Contexto</th>
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">Estado Actual</th>
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground">Motivo Pausa</th>
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-muted-foreground text-right">Acciones de Control</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {sites.map((site) => {
                                    const isPaused = !!pauseMap[site];
                                    return (
                                        <tr key={site} className="hover:bg-secondary/20 transition-colors group">
                                            <td className="px-6 py-4">
                                                <span className="font-bold text-sm tracking-tight">{site}</span>
                                            </td>
                                            <td className="px-6 py-4">
                                                <span className={cn(
                                                    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold border",
                                                    isPaused
                                                        ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                                        : "bg-green-500/10 text-green-500 border-green-500/20"
                                                )}>
                                                    <span className={cn("w-1.5 h-1.5 rounded-full", isPaused ? "bg-yellow-500" : "bg-green-500 animate-pulse")}></span>
                                                    {isPaused ? 'PAUSADO' : 'ACTIVO'}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4">
                                                <span className="text-xs text-muted-foreground italic">
                                                    {pauseMap[site]?.reason || '-'}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 text-right">
                                                <div className="flex items-center justify-end gap-2">
                                                    {isPaused ? (
                                                        <button
                                                            onClick={() => handleUnpause(site)}
                                                            disabled={!!busy}
                                                            className="px-4 py-2 bg-green-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-green-500/20 hover:scale-105 transition-transform flex items-center gap-2 active:scale-95 disabled:opacity-50"
                                                        >
                                                            <Play size={14} fill="currentColor" /> Reanudar
                                                        </button>
                                                    ) : (
                                                        <>
                                                            <button
                                                                onClick={() => handlePause(site, parseInt(globalMinutes))}
                                                                disabled={!!busy}
                                                                className="px-4 py-2 bg-secondary text-foreground rounded-xl text-xs font-bold hover:bg-yellow-500/10 hover:text-yellow-500 border border-border transition-all flex items-center gap-2 active:scale-95 disabled:opacity-50"
                                                            >
                                                                <Pause size={14} fill="currentColor" /> {globalMinutes}m
                                                            </button>
                                                            <button
                                                                onClick={() => handlePause(site)}
                                                                disabled={!!busy}
                                                                className="px-4 py-2 bg-secondary text-foreground rounded-xl text-xs font-bold hover:bg-yellow-500/10 hover:text-yellow-500 border border-border transition-all flex items-center gap-2 active:scale-95 disabled:opacity-50"
                                                            >
                                                                <Pause size={14} fill="currentColor" /> ∞
                                                            </button>
                                                        </>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            </section>

            {/* Global Config Sidebar or Bottom Bar could go here */}
            <section className="bg-secondary/20 border border-border rounded-3xl p-6 flex flex-col md:flex-row items-center justify-between gap-6">
                <div className="space-y-1">
                    <h4 className="font-bold">Acción Global Rápida</h4>
                    <p className="text-sm text-muted-foreground">Configura los parámetros para las pausas automáticas.</p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                    <div className="flex items-center bg-background border border-border rounded-xl px-3 outline-focus group">
                        <Clock size={16} className="text-muted-foreground" />
                        <input
                            type="number"
                            value={globalMinutes}
                            onChange={(e) => setGlobalMinutes(e.target.value)}
                            className="bg-transparent border-none outline-none py-2 px-2 text-sm w-16 font-mono"
                        />
                        <span className="text-[10px] font-bold text-muted-foreground uppercase">min</span>
                    </div>
                    <input
                        type="text"
                        placeholder="Motivo de la pausa..."
                        value={globalReason}
                        onChange={(e) => setGlobalReason(e.target.value)}
                        className="flex-1 min-w-[200px] bg-background border border-border rounded-xl px-4 py-2 text-sm outline-focus"
                    />
                    <button
                        className="px-6 py-2 bg-yellow-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-yellow-500/20 hover:scale-105 transition-transform active:scale-95"
                    >
                        Pausar Todos
                    </button>
                </div>
            </section>
        </div>
    );
}
