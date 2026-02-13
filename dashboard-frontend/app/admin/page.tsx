"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Settings,
  ShieldCheck,
  Pause,
  Play,
  Clock,
  AlertTriangle,
  Check,
  X,
} from "lucide-react";
import { queueApi, authApi, api } from "@/lib/api";
import { QueueItem, PendingAuth, PauseInfo, ItemPauseInfo } from "@/lib/types";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * MORRIGAN ADMIN PAGE
 * - Surfaces: raven/obsidian
 * - Violet: transitions/edges only
 * - Fate crimson: active decisions (approve/resume), but never loud
 * - Avoid neon greens/yellows; use restrained “status” colors
 * - Table is matte + terminal-native (clean dividers, minimal hover)
 */
export default function AdminPage() {
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [pauses, setPauses] = useState<PauseInfo[]>([]);
  const [itemPauses, setItemPauses] = useState<ItemPauseInfo[]>([]);
  const [pendingAuth, setPendingAuth] = useState<PendingAuth[]>([]);
  const [globalReason, setGlobalReason] = useState("");
  const [globalMinutes, setGlobalMinutes] = useState("120");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [queueRes, pausesRes, itemPausesRes, authRes] = await Promise.all([
        queueApi.getCurrent(1, 1000),
        api.get<{ items: PauseInfo[] }>("/queue/pauses?active_only=true"),
        api.get<{ items: ItemPauseInfo[] }>("/queue/item-pauses?active_only=true"),
        authApi.getPending(),
      ]);

      setQueueItems(queueRes.items || []);
      setPauses(pausesRes.items || []);
      setItemPauses(itemPausesRes.items || []);
      setPendingAuth(authRes.items || []);
      setError("");
    } catch {
      setError("Error al cargar datos administrativos.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, []);

  const KNOWN_SITES = ["madrid", "xaloc_girona", "base_online", "ayunta_palma"];

  const sites = useMemo(() => {
    const s = new Set(KNOWN_SITES);
    queueItems.forEach((it) => s.add(it.site_id));
    pauses.forEach((p) => s.add(p.site_id));
    return Array.from(s).filter(Boolean).sort();
  }, [queueItems, pauses]);

  const pauseMap = useMemo(() => {
    const map: Record<string, PauseInfo> = {};
    pauses.forEach((p) => {
      map[p.site_id] = p;
    });
    return map;
  }, [pauses]);

  const itemPauseMap = useMemo(() => {
    const map: Record<string, ItemPauseInfo> = {};
    itemPauses.forEach((p) => {
      map[`${p.site_id}::${p.resource_id}`] = p;
    });
    return map;
  }, [itemPauses]);

  const queueBySite = useMemo(() => {
    const out: Record<string, { total: number; pending: number; processing: number }> = {};
    for (const site of sites) out[site] = { total: 0, pending: 0, processing: 0 };
    for (const item of queueItems) {
      const site = item.site_id;
      if (!out[site]) out[site] = { total: 0, pending: 0, processing: 0 };
      out[site].total += 1;
      if ((item.state || '').toLowerCase() === 'processing') out[site].processing += 1;
      else out[site].pending += 1;
    }
    return out;
  }, [sites, queueItems]);

  const handlePause = async (siteId: string, minutes?: number) => {
    setBusy(`pause-${siteId}`);
    try {
      await queueApi.pauseSite(siteId, minutes, globalReason);
      await refresh();
    } catch {
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
    } catch {
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
    } catch {
      setError("Error al aprobar autorización");
    } finally {
      setBusy(null);
    }
  };

  const handleRejectAuth = async (id: number) => {
    const reason = prompt("Motivo del rechazo:");
    if (!reason) return;
    setBusy(`auth-${id}`);
    try {
      await authApi.reject(id, reason);
      await refresh();
    } catch {
      setError("Error al rechazar autorización");
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
    } catch {
      setError("Error al eliminar item");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-10 animate-in fade-in duration-700">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tight">
            Panel de Gestión
          </h2>
          <p className="text-xs text-muted-foreground/60 uppercase tracking-widest mt-1">
            Control de sitios, pausas y autorizaciones operativas.
          </p>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-[rgba(255,60,80,0.35)] bg-[rgba(255,60,80,0.06)] px-4 py-3 flex items-center gap-3">
          <AlertTriangle size={18} className="text-[rgba(255,60,80,0.85)]" />
          <p className="text-sm font-medium text-foreground/90">{error}</p>
        </div>
      )}

      {/* =========================
          Authorizations
         ========================= */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg border border-border/70 bg-[rgba(17,19,26,0.55)] flex items-center justify-center">
            <ShieldCheck size={18} className="text-[rgba(108,77,255,0.75)]" />
          </div>

          <h3 className="text-xl font-black uppercase tracking-tight text-foreground/90">
            Autorizaciones Pendientes
          </h3>

          <span
            className={cn(
              "px-2 py-1 rounded-full text-[10px] font-black uppercase tracking-[0.22em] border",
              pendingAuth.length > 0
                ? "border-[rgba(122,15,30,0.32)] bg-[rgba(122,15,30,0.10)] text-foreground/90"
                : "border-border/70 bg-[rgba(17,19,26,0.55)] text-muted-foreground/80"
            )}
          >
            {pendingAuth.length} Req.
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {pendingAuth.length === 0 ? (
            <div className="col-span-full py-10 text-center morr-card rounded-2xl border border-dashed border-border/70 text-muted-foreground/80">
              <p className="text-sm italic">No hay peticiones de autorización pendientes.</p>
            </div>
          ) : (
            pendingAuth.map((auth) => (
              <div
                key={auth.id}
                className={cn(
                  "morr-card morr-edge rounded p-6 space-y-4",
                  "transition-all duration-500"
                )}
              >
                <div className="flex justify-between items-start gap-4">
                  <div className="min-w-0">
                    <h4 className="font-black text-base uppercase tracking-[0.10em] truncate">
                      {auth.site_id}
                    </h4>
                    <p className="text-xs text-muted-foreground/80 mt-1">
                      Recurso:{" "}
                      <span className="text-foreground/90 font-black">#{auth.resource_id}</span>
                    </p>
                  </div>

                  <span className="text-[10px] px-2 py-1 rounded-md border border-border/70 bg-[rgba(17,19,26,0.55)] text-muted-foreground/80 font-mono">
                    {new Date(auth.created_at).toLocaleTimeString()}
                  </span>
                </div>

                <div className="rounded-xl border border-border/70 bg-[rgba(11,12,16,0.35)] p-4">
                  <p className="text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80 mb-2">
                    Motivo
                  </p>
                  <p className="text-sm leading-relaxed text-foreground/90">
                    {auth.reason || "Requiere intervención manual"}
                  </p>
                </div>

                <div className="flex gap-2 pt-1">
                  {/* Approve = Fate */}
                  <button
                    onClick={() => handleApproveAuth(auth.id)}
                    disabled={busy === `auth-${auth.id}`}
                    className={cn(
                      "morr-focus flex-1 rounded py-2.5",
                      "text-[10px] font-black uppercase tracking-[0.2em]",
                      "bg-[color:var(--morr-fate)] text-white/95",
                      "border border-transparent",
                      "hover:bg-[color:var(--morr-fate-hi)]",
                      "transition-all duration-300 active:scale-[0.98] disabled:opacity-50",
                      "flex items-center justify-center gap-2"
                    )}
                  >
                    <Check size={14} /> Autorizar
                  </button>

                  {/* Reject = quiet destructive */}
                  <button
                    onClick={() => handleRejectAuth(auth.id)}
                    disabled={busy === `auth-${auth.id}`}
                    className={cn(
                      "morr-focus flex-1 rounded-xl py-2.5",
                      "text-[11px] font-black uppercase tracking-[0.18em]",
                      "bg-[rgba(17,19,26,0.55)] text-foreground/90",
                      "border border-border/70",
                      "hover:border-[rgba(255,60,80,0.22)] hover:bg-[rgba(255,60,80,0.06)]",
                      "transition active:scale-[0.99] disabled:opacity-50",
                      "flex items-center justify-center gap-2"
                    )}
                  >
                    <X size={14} /> Rechazar
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      {/* =========================
          Site Control Table
         ========================= */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg border border-border/70 bg-[rgba(17,19,26,0.55)] flex items-center justify-center">
            <Settings size={18} className="text-foreground/75" />
          </div>
          <h3 className="text-xl font-black uppercase tracking-tight text-foreground/90">
            Control de Sitios Operativos
          </h3>
        </div>

        <div className="morr-card rounded overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-[rgba(17,19,26,0.55)] border-b border-border/70">
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">
                    Site / Contexto
                  </th>
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80 text-center">
                    Total Cola
                  </th>
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80 text-center">
                    Pendientes
                  </th>
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80 text-center">
                    Procesando
                  </th>
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">
                    Estado Actual
                  </th>
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">
                    Motivo Pausa
                  </th>
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80 text-right">
                    Acciones de Control
                  </th>
                </tr>
              </thead>

              <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
                {sites.map((site) => {
                  const isPaused = !!pauseMap[site];
                  return (
                    <tr
                      key={site}
                      className="hover:bg-[rgba(255,255,255,0.03)] transition-colors"
                    >
                      <td className="px-6 py-4">
                        <span className="font-black text-sm tracking-tight text-foreground/90">
                          {site}
                        </span>
                      </td>

                      <td className="px-6 py-4 text-center">
                        <span className="font-mono text-sm font-bold text-foreground/90">
                          {(queueBySite[site] || { total: 0 }).total}
                        </span>
                      </td>

                      <td className="px-6 py-4 text-center">
                        <span className="font-mono text-sm text-muted-foreground/80">
                          {(queueBySite[site] || { pending: 0 }).pending}
                        </span>
                      </td>

                      <td className="px-6 py-4 text-center">
                        <span className={cn(
                          "font-mono text-sm font-bold",
                          (queueBySite[site]?.processing || 0) > 0
                            ? "text-[rgba(108,77,255,0.90)]"
                            : "text-muted-foreground/60"
                        )}>
                          {(queueBySite[site] || { processing: 0 }).processing}
                        </span>
                      </td>

                      <td className="px-6 py-4">
                        <span
                          className={cn(
                            "inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-[0.20em] border",
                            isPaused
                              ? "border-[rgba(255,200,80,0.22)] bg-[rgba(255,200,80,0.08)] text-foreground/90"
                              : "border-[rgba(108,77,255,0.22)] bg-[rgba(108,77,255,0.08)] text-foreground/90"
                          )}
                        >
                          <span
                            className="w-1.5 h-1.5 rounded-full"
                            style={{
                              background: isPaused
                                ? "rgba(255,200,80,0.85)"
                                : "rgba(108,77,255,0.85)",
                              boxShadow: isPaused
                                ? "0 0 10px rgba(255,200,80,0.15)"
                                : "0 0 10px rgba(108,77,255,0.15)",
                            }}
                          />
                          {isPaused ? "PAUSADO" : "ACTIVO"}
                        </span>
                      </td>

                      <td className="px-6 py-4">
                        <span className="text-xs text-muted-foreground/80 italic">
                          {pauseMap[site]?.reason || "-"}
                        </span>
                      </td>

                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {isPaused ? (
                            <button
                              onClick={() => handleUnpause(site)}
                              disabled={!!busy}
                              className={cn(
                                "morr-focus px-4 py-2 rounded-xl",
                                "text-[11px] font-black uppercase tracking-[0.18em]",
                                "bg-[color:var(--morr-fate)] text-white",
                                "border border-transparent hover:border-[rgba(108,77,255,0.28)]",
                                "transition active:scale-[0.99] disabled:opacity-50",
                                "inline-flex items-center gap-2"
                              )}
                            >
                              <Play size={14} fill="currentColor" /> Reanudar
                            </button>
                          ) : (
                            <>
                              <button
                                onClick={() => handlePause(site, parseInt(globalMinutes))}
                                disabled={!!busy}
                                className={cn(
                                  "morr-focus px-4 py-2 rounded-xl",
                                  "text-[11px] font-black uppercase tracking-[0.18em]",
                                  "bg-[rgba(17,19,26,0.55)] text-foreground/90",
                                  "border border-border/70",
                                  "hover:border-[rgba(108,77,255,0.22)] hover:bg-[rgba(255,255,255,0.03)]",
                                  "transition active:scale-[0.99] disabled:opacity-50",
                                  "inline-flex items-center gap-2"
                                )}
                              >
                                <Pause size={14} fill="currentColor" /> {globalMinutes}m
                              </button>

                              <button
                                onClick={() => handlePause(site)}
                                disabled={!!busy}
                                className={cn(
                                  "morr-focus px-4 py-2 rounded-xl",
                                  "text-[11px] font-black uppercase tracking-[0.18em]",
                                  "bg-[rgba(17,19,26,0.55)] text-foreground/90",
                                  "border border-border/70",
                                  "hover:border-[rgba(108,77,255,0.22)] hover:bg-[rgba(255,255,255,0.03)]",
                                  "transition active:scale-[0.99] disabled:opacity-50",
                                  "inline-flex items-center gap-2"
                                )}
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

      {/* =========================
          Global Action Bar
         ========================= */}
      <section className="morr-card rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div className="space-y-1">
          <h4 className="font-black uppercase tracking-tight text-foreground/90">
            Acción Global
          </h4>
          <p className="text-sm text-muted-foreground/80">
            Configura los parámetros para pausas automáticas.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Minutes */}
          <div className="flex items-center rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] px-3">
            <Clock size={16} className="text-muted-foreground/80" />
            <input
              type="number"
              value={globalMinutes}
              onChange={(e) => setGlobalMinutes(e.target.value)}
              className="bg-transparent border-none outline-none py-2 px-2 text-sm w-20 font-mono text-foreground/90"
            />
            <span className="text-[10px] font-black text-muted-foreground/80 uppercase tracking-[0.22em]">
              min
            </span>
          </div>

          {/* Reason */}
          <input
            type="text"
            placeholder="Motivo de la pausa…"
            value={globalReason}
            onChange={(e) => setGlobalReason(e.target.value)}
            className={cn(
              "morr-focus flex-1 min-w-[220px] rounded-xl",
              "bg-[rgba(17,19,26,0.55)] text-foreground/90",
              "border border-border/70",
              "focus:border-[rgba(108,77,255,0.30)]",
              "px-4 py-2 text-sm transition"
            )}
          />

          {/* Pause all (FATE) */}
          <button
            className={cn(
              "morr-focus px-6 py-2 rounded-xl",
              "text-[11px] font-black uppercase tracking-[0.18em]",
              "bg-[color:var(--morr-fate)] text-white",
              "border border-transparent hover:border-[rgba(108,77,255,0.28)]",
              "transition active:scale-[0.99]"
            )}
          >
            Pausar Todos
          </button>
        </div>
      </section>

      {/* Optional: show loading quietly if you want */}
      {loading && (
        <div className="text-xs text-muted-foreground/70 uppercase tracking-[0.22em]">
          Actualizando…
        </div>
      )}
    </div>
  );
}
