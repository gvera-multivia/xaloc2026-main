'use client';

import React, { useState, useEffect } from 'react';
import {
    ShieldAlert,
    Plus,
    Search,
    AlertCircle,
    FileText,
    Clock,
    Unlock,
    Trash2,
    RefreshCw
} from 'lucide-react';
import { blacklistApi, queueApi } from '@/lib/api';
import { sileo } from 'sileo';

interface BlacklistItem {
    site_id: string;
    resource_id: number;
    reason?: string;
    source?: string;
    screenshot_url?: string;
    created_at: string;
}

export default function BlacklistPage() {
    const [items, setItems] = useState<BlacklistItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState<string | null>(null);
    const [showAddForm, setShowAddForm] = useState(false);

    const [newResourceId, setNewResourceId] = useState('');
    const [newReason, setNewReason] = useState('');

    const fetchBlacklist = async () => {
        setLoading(true);
        try {
            const res = await blacklistApi.list();
            setItems(res.items || []);
        } catch {
            setError('Error al cargar la lista negra.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchBlacklist(); }, []);
    const knownSites = ['madrid', 'xaloc_girona', 'base_online', 'ayunta_palma', 'redsara', 'terrassa', 'valencia', 'atc'];

    // Action 1 & 2: Delete/Unblock (Functionally the same for now)
    const handleUnblock = async (siteId: string, resourceId: number) => {
        setBusy(`unblock-${siteId}-${resourceId}`);
        try {
            await blacklistApi.unblock(siteId, resourceId);
            sileo.success({ title: 'Recurso desbloqueado', description: `${siteId} #${resourceId}` });
            await fetchBlacklist();
        } catch {
            sileo.error({ title: 'Error al desbloquear recurso' });
            setError('Error al desbloquear recurso.');
        } finally {
            setBusy(null);
        }
    };

    // Action 3: Retry (Delete + Recover)
    const handleRetry = async (siteId: string, resourceId: number) => {
        setBusy(`retry-${siteId}-${resourceId}`);
        try {
            // First, remove from blacklist
            await blacklistApi.unblock(siteId, resourceId);
            // Then, trigger recovery
            await queueApi.recoverItem(siteId, resourceId);
            sileo.success({ title: 'Reintento lanzado', description: `${siteId} #${resourceId} — Desbloqueado y en cola de recuperación` });
            await fetchBlacklist();
        } catch {
            sileo.error({ title: 'Error al reintentar recurso' });
            setError('Error al reintentar recurso.');
        } finally {
            setBusy(null);
        }
    };

    const handleBlock = async () => {
        const resourceId = Number(newResourceId);
        if (!Number.isInteger(resourceId) || resourceId <= 0) {
            setError('El ID de recurso debe ser un número entero positivo.');
            return;
        }

        setBusy(`new-global-${resourceId}`);
        try {
            const res = await blacklistApi.block(
                'global',
                resourceId,
                newReason.trim() || 'Bloqueo manual desde dashboard',
                'manual'
            );
            const extraMsg = res.queue_removed ? " y eliminado de la cola" : "";
            sileo.success({ title: 'Bloqueo creado', description: `#${resourceId}${extraMsg}` });
            setShowAddForm(false);
            setNewResourceId('');
            setNewReason('');
            setError('');
            await fetchBlacklist();
        } catch {
            sileo.error({ title: 'Error al crear el bloqueo manual' });
            setError('Error al crear el bloqueo manual.');
        } finally {
            setBusy(null);
        }
    };

    const filteredItems = items.filter(it =>
        String(it.resource_id).toLowerCase().includes(search.toLowerCase()) ||
        it.site_id.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="space-y-8 animate-in zoom-in-95 duration-700">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                    <h2 className="text-3xl font-black tracking-tighter">Recursos Bloqueados</h2>
                    <p className="text-muted-foreground">Gestión de la lista negra operativa (Blacklist).</p>
                </div>
                <button
                    onClick={() => setShowAddForm(prev => !prev)}
                    className="flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-xl text-sm font-bold shadow-lg shadow-primary/20 hover:scale-105 transition-transform active:scale-95"
                >
                    <Plus size={18} /> Añadir Bloqueo Manual
                </button>
            </div>

            {showAddForm && (
                <div className="bg-card border border-border rounded-2xl p-5 space-y-4">
                    <h3 className="text-sm font-black uppercase tracking-wider">Nuevo bloqueo manual</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">

                        <label className="text-xs text-muted-foreground space-y-1">
                            <span>ID Recurso</span>
                            <input
                                type="number"
                                min={1}
                                value={newResourceId}
                                onChange={(e) => setNewResourceId(e.target.value)}
                                className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm"
                                placeholder="Ej: 12345"
                            />
                        </label>
                        <label className="text-xs text-muted-foreground space-y-1">
                            <span>Motivo</span>
                            <input
                                type="text"
                                value={newReason}
                                onChange={(e) => setNewReason(e.target.value)}
                                className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm"
                                placeholder="Opcional"
                            />
                        </label>
                    </div>
                    <div className="flex items-center justify-end gap-2">
                        <button
                            onClick={() => setShowAddForm(false)}
                            className="px-4 py-2 border border-border rounded-xl text-xs font-bold"
                        >
                            Cancelar
                        </button>
                        <button
                            onClick={handleBlock}
                            disabled={busy === `new-global-${Number(newResourceId)}`}
                            className="px-4 py-2 bg-primary text-primary-foreground rounded-xl text-xs font-bold disabled:opacity-50"
                        >
                            Guardar Bloqueo
                        </button>
                    </div>
                </div>
            )}

            {error && (
                <div className="bg-destructive/10 border border-destructive/50 text-destructive px-4 py-3 rounded-xl flex items-center gap-3">
                    <AlertCircle size={18} />
                    <p className="text-sm font-medium">{error}</p>
                </div>
            )}

            <div className="bg-card border border-border rounded-3xl overflow-hidden shadow-sm">
                <div className="p-6 border-b border-border bg-secondary/20">
                    <div className="relative group max-w-md">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-primary transition-colors" size={16} />
                        <input
                            type="text"
                            placeholder="Buscar por ID o site..."
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            className="w-full bg-background border border-border rounded-2xl pl-10 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                        />
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-0 divide-x divide-y divide-border">
                    {loading ? (
                        <div className="col-span-full py-20 text-center text-muted-foreground italic">
                            Consultando base de datos de bloqueos...
                        </div>
                    ) : filteredItems.length === 0 ? (
                        <div className="col-span-full py-20 text-center text-muted-foreground flex flex-col items-center gap-4">
                            <ShieldAlert size={48} className="opacity-10" />
                            <p className="text-sm italic">No hay recursos bloqueados actualmente.</p>
                        </div>
                    ) : (
                        filteredItems.map((item, idx) => (
                            <div key={idx} className="p-6 bg-card hover:bg-secondary/10 transition-colors group flex flex-col justify-between gap-6">
                                <div className="space-y-4">
                                    <div className="flex items-start justify-between">
                                        <div className="w-12 h-12 rounded-2xl bg-destructive/10 flex items-center justify-center text-destructive">
                                            <ShieldAlert size={24} />
                                        </div>
                                        <div className="text-right">
                                            <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">Source: {item.source || 'system'}</span>
                                            <p className="text-[10px] text-muted-foreground flex items-center justify-end gap-1">
                                                <Clock size={10} /> {new Date(item.created_at).toLocaleDateString()}
                                            </p>
                                        </div>
                                    </div>

                                    <div>
                                        <h4 className="font-bold text-lg leading-tight uppercase tracking-tight">{item.site_id}</h4>
                                        <p className="text-xl font-mono font-bold text-primary">#{item.resource_id}</p>
                                    </div>

                                    <div className="bg-secondary/50 p-4 rounded-2xl border border-border/50 text-xs leading-relaxed italic">
                                        <FileText size={12} className="inline mr-2 opacity-50" />
                                        {item.reason || 'Sin motivo documentado'}
                                    </div>

                                    {item.screenshot_url && (
                                        <div className="mt-4 rounded-xl overflow-hidden border border-border bg-black/5 aspect-video relative group/img">
                                            <img 
                                                src={`/api/blacklist/${item.site_id}/${item.resource_id}/screenshot`} 
                                                alt="Captura del error"
                                                className="w-full h-full object-cover cursor-zoom-in hover:scale-110 transition-transform duration-500"
                                                onClick={() => window.open(`/api/blacklist/${item.site_id}/${item.resource_id}/screenshot`, '_blank')}
                                            />
                                            <div className="absolute inset-0 bg-black/40 opacity-0 group-hover/img:opacity-100 transition-opacity flex items-center justify-center pointer-events-none">
                                                <span className="text-[10px] font-bold text-white uppercase tracking-widest">Click para ampliar</span>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                <div className="flex flex-col gap-2">
                                    {/* Opción 1: Eliminar (Olvido) */}
                                    <button
                                        onClick={() => handleUnblock(item.site_id, item.resource_id)}
                                        disabled={busy === `unblock-${item.site_id}-${item.resource_id}`}
                                        className="w-full py-2 bg-secondary/80 text-foreground border border-border rounded-xl text-xs font-bold hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                                        title="Eliminar de la lista negra (Olvido)"
                                    >
                                        <Trash2 size={14} /> Eliminar
                                    </button>

                                    <div className="flex gap-2">
                                        {/* Opción 2: Desbloquear (Standard) */}
                                        <button
                                            onClick={() => handleUnblock(item.site_id, item.resource_id)}
                                            disabled={busy === `unblock-${item.site_id}-${item.resource_id}`}
                                            className="flex-1 py-2 bg-secondary text-foreground rounded-xl text-xs font-bold hover:bg-primary hover:text-primary-foreground transition-all flex items-center justify-center gap-2 group-hover:shadow-lg disabled:opacity-50"
                                            title="Desbloquear para que continúe la ejecución normal"
                                        >
                                            <Unlock size={14} /> Desbloquear
                                        </button>

                                        {/* Opción 3: Reintentar (Desbloquear + Recover) */}
                                        <button
                                            onClick={() => handleRetry(item.site_id, item.resource_id)}
                                            disabled={busy === `retry-${item.site_id}-${item.resource_id}`}
                                            className="flex-1 py-2 bg-primary text-primary-foreground rounded-xl text-xs font-bold hover:brightness-110 transition-all flex items-center justify-center gap-2 group-hover:shadow-lg disabled:opacity-50"
                                            title="Desbloquear y forzar reintento inmediato"
                                        >
                                            <RefreshCw size={14} /> Reintentar
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}
