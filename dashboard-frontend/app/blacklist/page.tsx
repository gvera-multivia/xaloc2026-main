'use client';

import React, { useState, useEffect } from 'react';
import {
    ShieldAlert,
    Trash2,
    Plus,
    Search,
    AlertCircle,
    FileText,
    Clock,
    Unlock
} from 'lucide-react';
import { api } from '@/lib/api';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export default function BlacklistPage() {
    const [items, setItems] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState<string | null>(null);

    const fetchBlacklist = async () => {
        setLoading(true);
        try {
            const res = await api.get<any>('/blacklist');
            setItems(res.items || []);
        } catch (e) {
            setError('Error al cargar la lista negra.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchBlacklist(); }, []);

    const handleUnblock = async (siteId: string, resourceId: number) => {
        setBusy(`${siteId}-${resourceId}`);
        try {
            await api.delete<any>(`/blacklist/${encodeURIComponent(siteId)}/${resourceId}`);
            await fetchBlacklist();
        } catch (e) {
            setError('Error al desbloquear recurso.');
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
                <button className="flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-xl text-sm font-bold shadow-lg shadow-primary/20 hover:scale-105 transition-transform active:scale-95">
                    <Plus size={18} /> Añadir Bloqueo Manual
                </button>
            </div>

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
                                </div>

                                <button
                                    onClick={() => handleUnblock(item.site_id, item.resource_id)}
                                    disabled={busy === `${item.site_id}-${item.resource_id}`}
                                    className="w-full py-3 bg-secondary text-foreground rounded-2xl text-xs font-bold hover:bg-primary hover:text-primary-foreground transition-all flex items-center justify-center gap-2 group-hover:shadow-lg disabled:opacity-50"
                                >
                                    <Unlock size={14} /> Desbloquear Recurso
                                </button>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}
