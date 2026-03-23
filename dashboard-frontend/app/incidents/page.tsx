'use client';

import React, { useState, useEffect } from 'react';
import { Lock, Unlock, RefreshCw, ChevronDown, ChevronUp, AlertCircle } from 'lucide-react';
import { useWebSocket } from '@/lib/WebSocketContext';
import { incidentsApi } from '@/lib/api';
import { sileo } from 'sileo';

type Incident = {
    site_id: string;
    resource_id: number | string | null;
    expediente?: string;
    incident_type: string;
    reason: string;
    day: string;
    started_at: string;
    ended_at: string;
    payload: any;
    locked?: boolean;
    lock_user_id?: string | null;
    lock_username?: string | null;
    lock_expires_at?: string | null;
};

export default function IncidentsPage() {
    const { lastMessage } = useWebSocket();
    const [incidents, setIncidents] = useState<Incident[]>([]);
    const [loading, setLoading] = useState(true);
    const [locks, setLocks] = useState<Record<string, string>>({}); // incident_id -> user_id/username
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
    const fmtRid = (rid: number | string | null | undefined) => (rid === null || rid === undefined || rid === '' ? 'N/A' : String(rid));
    const idRid = (rid: number | string | null | undefined) => (rid === null || rid === undefined || rid === '' ? 'none' : String(rid));

    const fetchIncidents = async () => {
        setLoading(true);
        try {
            const res = await incidentsApi.getPending();
            const rawItems = res.items || [];
            
            // Sort by resource_id (numerically), then by numclient
            const nextItems = [...rawItems].sort((a, b) => {
                const ridA = parseInt(String(a.resource_id)) || 0;
                const ridB = parseInt(String(b.resource_id)) || 0;
                if (ridA !== ridB) return ridB - ridA;
                
                const clientA = parseInt(String(a.numclient || 0)) || 0;
                const clientB = parseInt(String(b.numclient || 0)) || 0;
                if (clientA !== clientB) return clientA - clientB;

                const dateA = new Date(a.started_at || 0).getTime();
                const dateB = new Date(b.started_at || 0).getTime();
                return dateB - dateA;
            });

            setIncidents(nextItems);
            const nextLocks: Record<string, string> = {};
            for (const item of nextItems) {
                const incidentId = `${item.site_id}:${idRid(item.resource_id)}`;
                const locked = Boolean(item.locked);
                if (locked) {
                    const lockedBy = item.lock_username || item.lock_user_id || 'unknown';
                    nextLocks[incidentId] = String(lockedBy);
                }
            }
            setLocks(nextLocks);
        } catch (e) {
            sileo.error({ title: 'Error al cargar incidencias' });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchIncidents();
        const timer = setInterval(fetchIncidents, 5000);
        return () => clearInterval(timer);
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
        const id = `${incident.site_id}:${idRid(incident.resource_id)}`;
        try {
            await incidentsApi.claim(id);
            sileo.success({ title: 'Incidencia capturada', description: 'Has tomado el control de la incidencia.' });
        } catch (e: any) {
            sileo.error({ title: 'Error al capturar', description: e.message });
        }
    };

    const handleRelease = async (incident: Incident) => {
        const id = `${incident.site_id}:${idRid(incident.resource_id)}`;
        try {
            await incidentsApi.release(id);
            sileo.success({ title: 'Incidencia liberada', description: 'La incidencia vuelve a estar disponible.' });
        } catch (e: any) {
            sileo.error({ title: 'Error al liberar', description: e.message });
        }
    };

    const toggleExpand = (id: string) => {
        setExpandedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const isCritical = (inc: Incident) => {
        const text = `${inc.reason} ${inc.incident_type}`.toLowerCase();
        return (
            text.includes('folder missing') ||
            text.includes('carpeta') ||
            text.includes('missing') ||
            text.includes('autorizacion missing') ||
            text.includes('authorization missing') ||
            text.includes('cliente') ||
            text.includes('cliete') ||
            text.includes('no encontrar')
        );
    };

    const getClientId = (inc: any) => {
        if (inc.numclient) return String(inc.numclient);
        const p = inc.payload;
        return p?.numclient || p?.idCliente || p?.client_id || p?.id_cliente || p?.client || 'N/A';
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
                            const id = `${inc.site_id}:${idRid(inc.resource_id)}`;
                            const lockedBy = locks[id];
                            const isExpanded = expandedIds.has(id);
                            const critical = isCritical(inc);
                            const clientId = getClientId(inc);
                            
                            return (
                                <React.Fragment key={id}>
                                    <tr className={`transition-colors ${critical ? 'bg-red-500/5 hover:bg-red-500/10' : 'hover:bg-[rgba(255,255,255,0.03)]'}`}>
                                        <td className="px-6 py-4 border-l-2 border-transparent data-[critical=true]:border-red-500" data-critical={critical}>
                                            <div className="flex items-center gap-3">
                                                <button
                                                    onClick={() => toggleExpand(id)}
                                                    className="w-6 h-6 rounded border border-border/70 flex items-center justify-center hover:bg-foreground/5 transition-transform"
                                                >
                                                    {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                                </button>
                                                <div className="flex flex-col">
                                                    <span className={`text-xs font-black uppercase ${critical ? 'text-red-400' : ''}`}>{inc.site_id}</span>
                                                    <span className="text-[10px] font-mono text-muted-foreground">#{fmtRid(inc.resource_id)}</span>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="flex flex-col gap-1">
                                                <div className="flex items-center gap-2">
                                                    <span className={`text-[10px] font-black uppercase ${critical ? 'text-red-500/60' : 'text-muted-foreground/50'}`}>{inc.incident_type}</span>
                                                    {critical && (
                                                        <span className="bg-red-500/20 text-red-500 text-[9px] px-1.5 py-0.5 rounded font-black uppercase tracking-tighter">
                                                            Cliente: {clientId}
                                                        </span>
                                                    )}
                                                </div>
                                                <span className={`text-xs max-w-md truncate ${critical ? 'text-red-500 font-bold' : 'text-muted-foreground/90'}`} title={inc.reason}>
                                                    {inc.reason}
                                                </span>
                                            </div>
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
                                                    className={`px-3 py-1 border rounded text-[10px] font-bold uppercase transition-colors ${
                                                        critical 
                                                        ? "bg-red-500/10 border-red-500/30 text-red-500 hover:bg-red-500/20 font-black"
                                                        : "bg-emerald-500/10 border-emerald-500/20 text-emerald-500 hover:bg-emerald-500/20"
                                                    }`}
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
                                    {isExpanded && (
                                        <tr className="bg-[rgba(255,255,255,0.015)]">
                                            <td colSpan={4} className="px-6 py-4 border-l border-r border-border/20">
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                                                    <div className="space-y-4">
                                                        <div className="flex flex-col">
                                                            <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/50">Detalles Temporales</span>
                                                            <div className="mt-2 grid grid-cols-2 gap-4">
                                                                <div>
                                                                    <span className="text-[9px] uppercase font-bold text-muted-foreground/40 block">Iniciado</span>
                                                                    <span className="text-xs font-mono">{inc.started_at || 'N/A'}</span>
                                                                </div>
                                                                <div>
                                                                    <span className="text-[9px] uppercase font-bold text-muted-foreground/40 block">Finalizado</span>
                                                                    <span className="text-xs font-mono">{inc.ended_at || 'N/A'}</span>
                                                                </div>
                                                            </div>
                                                        </div>
                                                        <div className="flex flex-col">
                                                            <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/50">Expediente / Ref</span>
                                                            <span className="text-xs mt-1">{inc.expediente || 'No especificado'}</span>
                                                        </div>
                                                        {critical && (
                                                            <div className="p-3 bg-red-500/5 border border-red-500/20 rounded">
                                                                <span className="text-[10px] font-black uppercase text-red-500/60 block mb-1 tracking-widest">Identificación Cliente</span>
                                                                <span className="text-sm font-black text-red-500">{clientId}</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                    <div className="space-y-2">
                                                        <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/50">Payload (Data)</span>
                                                        <div className="bg-black/40 rounded p-4 font-mono text-[11px] overflow-x-auto max-h-60 scrollbar-thin">
                                                            <pre className={critical ? "text-red-400/80" : "text-emerald-500/80"}>
                                                                {JSON.stringify(inc.payload, null, 2)}
                                                            </pre>
                                                        </div>
                                                    </div>
                                                </div>
                                            </td>
                                        </tr>
                                    )}
                                </React.Fragment>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
