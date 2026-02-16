'use client';

import React, { useState, useEffect } from 'react';
import {
    AlertCircle,
    CheckCircle2,
    Lock,
    Unlock,
    RefreshCw,
    Play
} from 'lucide-react';
import { useWebSocket } from '@/lib/WebSocketContext';
import { incidentsApi } from '@/lib/api';

type Incident = {
    site_id: string;
    resource_id: number;
    expediente?: string;
    incident_type: string;
    reason: string;
    day: string;
    started_at: string;
    ended_at: string;
    payload: any;
};

export default function IncidentsPage() {
    const { lastMessage } = useWebSocket();
    const [incidents, setIncidents] = useState<Incident[]>([]);
    const [loading, setLoading] = useState(true);
    const [locks, setLocks] = useState<Record<string, string>>({}); // incident_id -> user_id/username

    const fetchIncidents = async () => {
        setLoading(true);
        try {
            const res = await incidentsApi.getPending();
            setIncidents(res.items || []);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchIncidents();
    }, []);

    useEffect(() => {
        if (!lastMessage) return;
        const { event, data } = lastMessage;
        if (event === 'INCIDENT_LOCKED') {
            setLocks(prev => ({ ...prev, [data.incident_id]: data.username || data.user_id }));
        } else if (event === 'INCIDENT_UNLOCKED') {
            setLocks(prev => {
                const copy = { ...prev };
                delete copy[data.incident_id];
                return copy;
            });
        }
    }, [lastMessage]);

    const handleClaim = async (incident: Incident) => {
        const id = `${incident.site_id}:${incident.resource_id}`;
        try {
             await incidentsApi.claim(id);
        } catch (e) {
             alert("Error claiming: " + e);
        }
    };

    const handleRelease = async (incident: Incident) => {
        const id = `${incident.site_id}:${incident.resource_id}`;
        try {
             await incidentsApi.release(id);
        } catch (e) {
             alert("Error releasing: " + e);
        }
    };

    return (
        <div className="space-y-10 animate-in fade-in duration-700">
             <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-black uppercase tracking-tight">
                        Incidencias Pendientes
                    </h2>
                    <p className="text-xs text-muted-foreground/60 uppercase tracking-widest mt-1">
                        Gestión y resolución manual de excepciones.
                    </p>
                </div>
                <button
                    onClick={fetchIncidents}
                    className="flex items-center gap-2 px-6 py-2 rounded-sm text-[9px] font-black uppercase tracking-[0.2em] bg-[var(--morr-fate)] text-white/90 border border-transparent hover:bg-[var(--morr-fate-hi)] transition-all"
                >
                    <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
                    Refrescar
                </button>
            </div>

            <div className="morr-card morr-edge rounded overflow-hidden">
                <table className="w-full text-left border-collapse">
                    <thead>
                        <tr className="bg-[rgba(17,19,26,0.55)] border-b border-border/70">
                            <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Recurso</th>
                            <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Motivo</th>
                            <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Estado</th>
                            <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Acciones</th>
                        </tr>
                    </thead>
                     <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
                        {incidents.map((inc, i) => {
                            const id = `${inc.site_id}:${inc.resource_id}`;
                            const lockedBy = locks[id];
                            return (
                                <tr key={i} className="hover:bg-[rgba(255,255,255,0.03)] transition-colors">
                                    <td className="px-6 py-4">
                                        <div className="flex flex-col">
                                            <span className="text-xs font-black uppercase">{inc.site_id}</span>
                                            <span className="text-[10px] font-mono text-muted-foreground">#{inc.resource_id}</span>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 text-xs text-muted-foreground/90 max-w-md truncate" title={inc.reason}>
                                        {inc.reason}
                                    </td>
                                    <td className="px-6 py-4">
                                        {lockedBy ? (
                                            <div className="flex items-center gap-1 text-[10px] font-bold text-amber-500 uppercase tracking-wider">
                                                <Lock size={10} />
                                                <span>En uso ({lockedBy})</span>
                                            </div>
                                        ) : (
                                            <div className="flex items-center gap-1 text-[10px] font-bold text-emerald-500 uppercase tracking-wider">
                                                <Unlock size={10} />
                                                <span>Disponible</span>
                                            </div>
                                        )}
                                    </td>
                                    <td className="px-6 py-4 flex gap-2">
                                        {!lockedBy && (
                                            <button
                                                onClick={() => handleClaim(inc)}
                                                className="px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 rounded text-[10px] font-bold uppercase hover:bg-emerald-500/20 transition-colors"
                                            >
                                                Atender
                                            </button>
                                        )}
                                        {lockedBy && (
                                             <button
                                                onClick={() => handleRelease(inc)}
                                                className="px-3 py-1 bg-amber-500/10 border border-amber-500/20 text-amber-500 rounded text-[10px] font-bold uppercase hover:bg-amber-500/20 transition-colors"
                                            >
                                                Liberar
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            );
                        })}
                     </tbody>
                </table>
            </div>
        </div>
    );
}
