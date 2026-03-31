'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Lock, RefreshCw, Unlock } from 'lucide-react';
import { incidentsApi } from '@/lib/api';
import { useAuth } from '@/lib/AuthContext';
import { useWebSocket } from '@/lib/WebSocketContext';
import { sileo } from 'sileo';

type Incident = {
    incident_id?: string;
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
    numclient?: number | string | null;
    cliente_tipo?: number | string | null;
    client_folder_exists?: boolean;
    gesdoc_missing_auth_candidate?: boolean;
    gesdoc_ui_variant?: 'purple' | 'default';
};

type GesdocStatus = {
    ok: boolean;
    incident_id?: string;
    numclient?: number | string;
    cliente_tipo?: number | null;
    client_folder_exists: boolean;
    client_folder_path?: string | null;
    has_sent_request: boolean;
    sent_request_entries: string[];
    available_actions: string[];
    locked_required: boolean;
};

type GesdocState = {
    loading: boolean;
    data?: GesdocStatus | null;
    error?: string | null;
};

export default function IncidentsPage() {
    const { lastMessage } = useWebSocket();
    const { user } = useAuth();
    const [incidents, setIncidents] = useState<Incident[]>([]);
    const [loading, setLoading] = useState(true);
    const [locks, setLocks] = useState<Record<string, string>>({});
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
    const [gesdocStates, setGesdocStates] = useState<Record<string, GesdocState>>({});
    const [gesdocActionBusy, setGesdocActionBusy] = useState<Record<string, 'generate' | 'send' | undefined>>({});

    const fmtRid = (rid: number | string | null | undefined) => (rid === null || rid === undefined || rid === '' ? 'N/A' : String(rid));
    const idRid = (rid: number | string | null | undefined) => (rid === null || rid === undefined || rid === '' ? 'none' : String(rid));
    const incidentIdOf = (inc: Incident) =>
        String(
            inc.incident_id ||
                `${inc.site_id}:${idRid(inc.resource_id)}:${String(inc.incident_type || '').trim().toUpperCase() || 'UNKNOWN'}:${
                    String(inc.expediente || '').trim().toUpperCase() || 'none'
                }`,
        );

    const normalize = (value: string | null | undefined) => String(value || '').trim().toLowerCase();
    const currentLockTokens = useMemo(
        () => new Set([user?.sub, user?.username, user?.xvia_username].map((value) => normalize(value)).filter(Boolean)),
        [user],
    );

    const isLockedByCurrentUser = (inc: Incident) =>
        !!inc.locked && [inc.lock_user_id, inc.lock_username].some((value) => currentLockTokens.has(normalize(value)));

    const fetchIncidents = async () => {
        setLoading(true);
        try {
            const res = await incidentsApi.getPending();
            const rawItems = res.items || [];
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
                const incidentId = incidentIdOf(item);
                if (item.locked) {
                    nextLocks[incidentId] = String(item.lock_username || item.lock_user_id || 'unknown');
                }
            }
            setLocks(nextLocks);
        } catch {
            sileo.error({ title: 'Error al cargar incidencias' });
        } finally {
            setLoading(false);
        }
    };

    const loadGesdocStatus = async (incident: Incident, force = false) => {
        const id = incidentIdOf(incident);
        const current = gesdocStates[id];
        if (!force && (current?.loading || current?.data)) return;
        setGesdocStates((prev) => ({ ...prev, [id]: { loading: true, error: null, data: force ? null : prev[id]?.data } }));
        try {
            const data = await incidentsApi.getIncidentGesdocStatus(incident.site_id, incident.resource_id || 0);
            setGesdocStates((prev) => ({ ...prev, [id]: { loading: false, error: null, data } }));
        } catch (error: any) {
            setGesdocStates((prev) => ({
                ...prev,
                [id]: { loading: false, data: null, error: String(error?.message || 'No se pudo consultar GESDOC.') },
            }));
        }
    };

    const handleGesdocAction = async (incident: Incident, action: 'generate' | 'send') => {
        const id = incidentIdOf(incident);
        if (action === 'send') {
            const confirmed = window.confirm(
                'Esto enviara una solicitud real en GESDOC y luego intentara copiar la autorizacion a la documentacion del cliente. Deseas continuar?',
            );
            if (!confirmed) return;
        }

        setGesdocActionBusy((prev) => ({ ...prev, [id]: action }));
        try {
            const result = await incidentsApi.runIncidentGesdocAction(incident.site_id, incident.resource_id || 0, action);
            if (result.ok) {
                sileo.success({ title: 'Autorizacion copiada', description: result.message || 'Autorizacion copiada a la documentacion del cliente.' });
            } else {
                sileo.warning({
                    title: action === 'send' ? 'Solicitud ejecutada sin PDF copiado' : 'Generacion sin PDF copiado',
                    description: result.message || 'GESDOC respondio, pero no aparecio el PDF en la carpeta temporal.',
                });
            }
            await fetchIncidents();
            await loadGesdocStatus(incident, true);
        } catch (error: any) {
            sileo.error({
                title: action === 'send' ? 'Error al enviar solicitud' : 'Error al generar autorizacion',
                description: String(error?.message || 'No se pudo completar la accion GESDOC.'),
            });
        } finally {
            setGesdocActionBusy((prev) => ({ ...prev, [id]: undefined }));
        }
    };

    const handleClaim = async (incident: Incident) => {
        const id = incidentIdOf(incident);
        try {
            await incidentsApi.claim(id);
            sileo.success({ title: 'Incidencia capturada', description: 'Has tomado el control de la incidencia.' });
            await fetchIncidents();
        } catch (error: any) {
            sileo.error({ title: 'Error al capturar', description: String(error?.message || 'No se pudo bloquear la incidencia.') });
        }
    };

    const handleRelease = async (incident: Incident) => {
        const id = incidentIdOf(incident);
        try {
            await incidentsApi.release(id);
            sileo.success({ title: 'Incidencia liberada', description: 'La incidencia vuelve a estar disponible.' });
            setGesdocStates((prev) => {
                const copy = { ...prev };
                delete copy[id];
                return copy;
            });
            await fetchIncidents();
        } catch (error: any) {
            sileo.error({ title: 'Error al liberar', description: String(error?.message || 'No se pudo liberar la incidencia.') });
        }
    };

    const toggleExpand = (id: string) => {
        setExpandedIds((prev) => {
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

    const getClientId = (inc: Incident) => {
        if (inc.numclient) return String(inc.numclient);
        const payload = inc.payload || {};
        return payload?.numclient || payload?.idCliente || payload?.client_id || payload?.id_cliente || payload?.client || 'N/A';
    };

    const getGenerateLabel = (clienteTipo: number | string | null | undefined) =>
        Number(clienteTipo) === 2 ? 'Generar autorizacion empresa' : 'Generar autorizacion particular';

    useEffect(() => {
        void fetchIncidents();
        const timer = setInterval(() => {
            void fetchIncidents();
        }, 5000);
        return () => clearInterval(timer);
    }, []);

    useEffect(() => {
        if (!lastMessage) return;
        const { event, data } = lastMessage;
        if (event === 'INCIDENT_LOCKED') {
            setLocks((prev) => ({ ...prev, [data.incident_id]: data.username || data.user_id }));
        } else if (event === 'INCIDENT_UNLOCKED') {
            setLocks((prev) => {
                const copy = { ...prev };
                delete copy[data.incident_id];
                return copy;
            });
        }
    }, [lastMessage]);

    useEffect(() => {
        for (const incident of incidents) {
            const id = incidentIdOf(incident);
            if (!expandedIds.has(id)) continue;
            if (incident.gesdoc_ui_variant !== 'purple') continue;
            if (!isLockedByCurrentUser(incident)) continue;
            const state = gesdocStates[id];
            if (state?.loading || state?.data || state?.error) continue;
            void loadGesdocStatus(incident);
        }
    }, [expandedIds, gesdocStates, incidents, user]);

    return (
        <div className="space-y-10 animate-in fade-in duration-700">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-black uppercase tracking-tight">Incidencias Pendientes</h2>
                    <p className="text-xs text-muted-foreground/60 uppercase tracking-widest mt-1">
                        Gestion y resolucion manual de excepciones.
                    </p>
                </div>
                <button
                    onClick={() => void fetchIncidents()}
                    className="flex items-center gap-2 px-6 py-2 rounded-sm text-[9px] font-black uppercase tracking-[0.2em] bg-[var(--morr-fate)] text-white/90 border border-transparent hover:bg-[var(--morr-fate-hi)] transition-all"
                >
                    <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
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
                        {incidents.map((inc) => {
                            const id = incidentIdOf(inc);
                            const lockedBy = locks[id];
                            const isExpanded = expandedIds.has(id);
                            const critical = isCritical(inc);
                            const isPurpleGesdoc = inc.gesdoc_ui_variant === 'purple';
                            const clientId = getClientId(inc);
                            const ownedByCurrentUser = isLockedByCurrentUser(inc);
                            const gesdocState = gesdocStates[id];
                            const gesdocBusyAction = gesdocActionBusy[id];
                            const generateLabel = getGenerateLabel(gesdocState?.data?.cliente_tipo ?? inc.cliente_tipo);

                            const rowClass = isPurpleGesdoc
                                ? 'bg-violet-500/5 hover:bg-violet-500/10'
                                : critical
                                  ? 'bg-red-500/5 hover:bg-red-500/10'
                                  : 'hover:bg-[rgba(255,255,255,0.03)]';
                            const siteClass = isPurpleGesdoc ? 'text-violet-300' : critical ? 'text-red-400' : '';
                            const typeClass = isPurpleGesdoc
                                ? 'text-violet-400/70'
                                : critical
                                  ? 'text-red-500/60'
                                  : 'text-muted-foreground/50';
                            const badgeClass = isPurpleGesdoc ? 'bg-violet-500/20 text-violet-200' : 'bg-red-500/20 text-red-500';
                            const reasonClass = isPurpleGesdoc
                                ? 'text-violet-200 font-bold'
                                : critical
                                  ? 'text-red-500 font-bold'
                                  : 'text-muted-foreground/90';
                            const identifyBoxClass = isPurpleGesdoc
                                ? 'p-3 bg-violet-500/5 border border-violet-500/20 rounded'
                                : 'p-3 bg-red-500/5 border border-red-500/20 rounded';
                            const identifyTextClass = isPurpleGesdoc ? 'text-violet-200' : 'text-red-500';

                            return (
                                <React.Fragment key={id}>
                                    <tr className={`transition-colors ${rowClass}`}>
                                        <td
                                            className={`px-6 py-4 border-l-2 ${isPurpleGesdoc ? 'border-violet-400/50' : critical ? 'border-red-500/60' : 'border-transparent'}`}
                                        >
                                            <div className="flex items-center gap-3">
                                                <button
                                                    onClick={() => toggleExpand(id)}
                                                    className="w-6 h-6 rounded border border-border/70 flex items-center justify-center hover:bg-foreground/5 transition-transform"
                                                >
                                                    {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                                </button>
                                                <div className="flex flex-col">
                                                    <span className={`text-xs font-black uppercase ${siteClass}`}>{inc.site_id}</span>
                                                    <span className="text-[10px] font-mono text-muted-foreground">#{fmtRid(inc.resource_id)}</span>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="flex flex-col gap-1">
                                                <div className="flex items-center gap-2">
                                                    <span className={`text-[10px] font-black uppercase ${typeClass}`}>{inc.incident_type}</span>
                                                    {(critical || isPurpleGesdoc) && (
                                                        <span className={`${badgeClass} text-[9px] px-1.5 py-0.5 rounded font-black uppercase tracking-tighter`}>
                                                            Cliente: {clientId}
                                                        </span>
                                                    )}
                                                </div>
                                                <span className={`text-xs max-w-md truncate ${reasonClass}`} title={inc.reason}>
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
                                                    onClick={() => void handleClaim(inc)}
                                                    className={`px-3 py-1 border rounded text-[10px] font-bold uppercase transition-colors ${
                                                        isPurpleGesdoc
                                                            ? 'bg-violet-500/10 border-violet-500/30 text-violet-200 hover:bg-violet-500/20'
                                                            : critical
                                                              ? 'bg-red-500/10 border-red-500/30 text-red-500 hover:bg-red-500/20 font-black'
                                                              : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-500 hover:bg-emerald-500/20'
                                                    }`}
                                                >
                                                    Atender
                                                </button>
                                            )}
                                            {lockedBy && (
                                                <button
                                                    onClick={() => void handleRelease(inc)}
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
                                                            <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/50">
                                                                Detalles Temporales
                                                            </span>
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
                                                        {(critical || isPurpleGesdoc) && (
                                                            <div className={identifyBoxClass}>
                                                                <span className={`text-[10px] font-black uppercase block mb-1 tracking-widest ${isPurpleGesdoc ? 'text-violet-300/70' : 'text-red-500/60'}`}>
                                                                    Identificacion Cliente
                                                                </span>
                                                                <span className={`text-sm font-black ${identifyTextClass}`}>{clientId}</span>
                                                            </div>
                                                        )}
                                                        {isPurpleGesdoc && (
                                                            <div className="p-4 bg-violet-500/5 border border-violet-500/20 rounded space-y-3">
                                                                <div className="flex items-center justify-between gap-3">
                                                                    <span className="text-[10px] font-black uppercase tracking-widest text-violet-300/80">
                                                                        Operativa GESDOC
                                                                    </span>
                                                                    <span className="text-[10px] font-mono text-violet-200/80">Cliente {clientId}</span>
                                                                </div>

                                                                {!ownedByCurrentUser && (
                                                                    <p className="text-xs text-violet-100/80">
                                                                        Bloquea esta incidencia para consultar GESDOC y ejecutar acciones.
                                                                    </p>
                                                                )}

                                                                {ownedByCurrentUser && gesdocState?.loading && (
                                                                    <div className="flex items-center gap-2 text-xs text-violet-100/80">
                                                                        <RefreshCw size={12} className="animate-spin" />
                                                                        <span>Consultando GESDOC...</span>
                                                                    </div>
                                                                )}

                                                                {ownedByCurrentUser && !gesdocState?.loading && gesdocState?.error && (
                                                                    <div className="text-xs text-red-300">{gesdocState.error}</div>
                                                                )}

                                                                {ownedByCurrentUser && !gesdocState?.loading && gesdocState?.data && (
                                                                    <>
                                                                        <div className="space-y-1 text-xs text-violet-100/85">
                                                                            <div>
                                                                                Estado GESDOC:{' '}
                                                                                <span className="font-bold">
                                                                                    {gesdocState.data.has_sent_request ? 'Solicitud ya enviada' : 'Solicitud no enviada'}
                                                                                </span>
                                                                            </div>
                                                                            {gesdocState.data.sent_request_entries.length > 0 && (
                                                                                <div>
                                                                                    Solicitudes detectadas:{' '}
                                                                                    <span className="font-mono">{gesdocState.data.sent_request_entries.join(', ')}</span>
                                                                                </div>
                                                                            )}
                                                                            {gesdocState.data.client_folder_path && (
                                                                                <div className="break-all text-violet-100/65">
                                                                                    Carpeta cliente: {gesdocState.data.client_folder_path}
                                                                                </div>
                                                                            )}
                                                                        </div>

                                                                        <div className="flex flex-wrap gap-2">
                                                                            {gesdocState.data.available_actions.includes('generate') && (
                                                                                <button
                                                                                    onClick={() => void handleGesdocAction(inc, 'generate')}
                                                                                    disabled={!!gesdocBusyAction}
                                                                                    className="px-3 py-1 rounded text-[10px] font-black uppercase tracking-wide bg-violet-500/15 border border-violet-400/30 text-violet-100 hover:bg-violet-500/25 disabled:opacity-50"
                                                                                >
                                                                                    {gesdocBusyAction === 'generate' ? 'Generando...' : generateLabel}
                                                                                </button>
                                                                            )}
                                                                            {gesdocState.data.available_actions.includes('send') && (
                                                                                <button
                                                                                    onClick={() => void handleGesdocAction(inc, 'send')}
                                                                                    disabled={!!gesdocBusyAction}
                                                                                    className="px-3 py-1 rounded text-[10px] font-black uppercase tracking-wide bg-amber-500/15 border border-amber-400/30 text-amber-100 hover:bg-amber-500/25 disabled:opacity-50"
                                                                                >
                                                                                    {gesdocBusyAction === 'send' ? 'Enviando...' : 'Enviar solicitud'}
                                                                                </button>
                                                                            )}
                                                                        </div>
                                                                    </>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <div className="space-y-2">
                                                        <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/50">Payload (Data)</span>
                                                        <div className="bg-black/40 rounded p-4 font-mono text-[11px] overflow-x-auto max-h-60 scrollbar-thin">
                                                            <pre className={isPurpleGesdoc ? 'text-violet-200/80' : critical ? 'text-red-400/80' : 'text-emerald-500/80'}>
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
