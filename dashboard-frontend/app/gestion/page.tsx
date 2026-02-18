"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Settings,
  ShieldCheck,
  Pause,
  Play,
  Power,
  Clock,
  AlertTriangle,
  Check,
  X,
  UserPlus,
  Users,
  Edit2,
  Trash2,
  Lock,
  Bell,
} from "lucide-react";
import { queueApi, authApi, configApi, api, usersApi } from "@/lib/api";
import { QueueItem, PendingAuth, PauseInfo, OrganismoConfig, DashboardUser } from "@/lib/types";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { canManagePauses as clientViewCanManagePauses } from "@/lib/permissions";
import { useAuth } from "@/lib/AuthContext";
import { sileo } from "sileo";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const KNOWN_SITES = ["madrid", "xaloc_girona", "base_online", "ayunta_palma"];

/**
 * MORRIGAN ADMIN PAGE
 * - Surfaces: raven/obsidian
 * - Violet: transitions/edges only
 * - Fate crimson: active decisions (approve/resume), but never loud
 * - Avoid neon greens/yellows; use restrained "status" colors
 * - Table is matte + terminal-native (clean dividers, minimal hover)
 *
 * Non-admin users can see queue status and manage authorizations,
 * but pause/unpause/activate buttons are hidden.
 * "Incidencias Recientes" section removed (viewed on separate page).
 */
export default function AdminPage() {
  const { isAdmin } = useAuth();
  const canManagePauses = isAdmin && clientViewCanManagePauses;
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [pauses, setPauses] = useState<PauseInfo[]>([]);
  const [configs, setConfigs] = useState<OrganismoConfig[]>([]);
  const [pendingAuth, setPendingAuth] = useState<PendingAuth[]>([]);
  const [users, setUsers] = useState<DashboardUser[]>([]);
  const [globalReason, setGlobalReason] = useState("");
  const [globalMinutes, setGlobalMinutes] = useState("120");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  // User form state
  const [showUserForm, setShowUserForm] = useState(false);
  const [editingUser, setEditingUser] = useState<DashboardUser | null>(null);
  const [userForm, setUserForm] = useState({
    username: "",
    password: "",
    role: "user" as "admin" | "user",
    active: true,
  });

  const refresh = async () => {
    try {
      const [queueRes, pausesRes, authRes, configRes] = await Promise.all([
        queueApi.getCurrent(1, 1000),
        isAdmin
          ? api.get<{ items: PauseInfo[] }>("/queue/pauses?active_only=true")
          : Promise.resolve({ items: [] as PauseInfo[] }),
        authApi.getPending(),
        isAdmin
          ? configApi.list()
          : Promise.resolve({ items: [] as OrganismoConfig[] }),
      ]);
      const usersRes = isAdmin ? await usersApi.list() : { items: [] };

      setQueueItems(queueRes.items || []);
      setPauses(pausesRes.items || []);
      setPendingAuth(authRes.items || []);
      setConfigs((configRes.items || []) as OrganismoConfig[]);
      setUsers(usersRes.items || []);
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

  const sites = useMemo(() => {
    const s = new Set(KNOWN_SITES);
    configs.forEach((cfg) => s.add(cfg.site_id));
    queueItems.forEach((it) => s.add(it.site_id));
    pauses.forEach((p) => s.add(p.site_id));
    return Array.from(s).filter(Boolean).sort();
  }, [configs, queueItems, pauses]);

  const pauseMap = useMemo(() => {
    const map: Record<string, PauseInfo> = {};
    pauses.forEach((p) => {
      map[p.site_id] = p;
    });
    return map;
  }, [pauses]);

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

  const configActiveMap = useMemo(() => {
    const map: Record<string, boolean> = {};
    configs.forEach((cfg) => {
      map[cfg.site_id] = Number(cfg.active) === 1 || cfg.active === true;
    });
    return map;
  }, [configs]);

  const handlePause = async (siteId: string, minutes?: number) => {
    setBusy(`pause-${siteId}`);
    try {
      await queueApi.pauseSite(siteId, minutes, globalReason);
      sileo.success({ title: `${siteId} pausado`, description: minutes ? `Pausa de ${minutes} minutos` : "Pausa indefinida" });
      await refresh();
    } catch {
      sileo.error({ title: `Error al pausar ${siteId}` });
      setError(`Error al pausar ${siteId}`);
    } finally {
      setBusy(null);
    }
  };

  const handleUnpause = async (siteId: string) => {
    setBusy(`unpause-${siteId}`);
    try {
      await queueApi.unpauseSite(siteId);
      sileo.success({ title: `${siteId} reanudado` });
      await refresh();
    } catch {
      sileo.error({ title: `Error al reanudar ${siteId}` });
      setError(`Error al reanudar ${siteId}`);
    } finally {
      setBusy(null);
    }
  };

  const handleSetSiteActive = async (siteId: string, active: boolean) => {
    setBusy(`active-${siteId}`);
    try {
      await configApi.setSiteActive(siteId, active);
      sileo.success({ title: `${siteId} ${active ? "activado" : "desactivado"}` });
      await refresh();
    } catch {
      sileo.error({ title: `Error al ${active ? "activar" : "desactivar"} ${siteId}` });
      setError(`Error al ${active ? "activar" : "desactivar"} ${siteId}`);
    } finally {
      setBusy(null);
    }
  };

  const handleApproveAuth = async (id: number) => {
    setBusy(`auth-${id}`);
    try {
      await authApi.approve(id);
      sileo.success({ title: "Autorización aprobada", description: `Solicitud #${id} autorizada` });
      await refresh();
    } catch {
      sileo.error({ title: "Error al aprobar autorización" });
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
      sileo.success({ title: "Autorización rechazada", description: `Solicitud #${id} rechazada` });
      await refresh();
    } catch {
      sileo.error({ title: "Error al rechazar autorización" });
      setError("Error al rechazar autorización");
    } finally {
      setBusy(null);
    }
  };

  const handleCreateUser = async () => {
    if (!userForm.username || !userForm.password) {
      sileo.error({ title: "Username y Password requeridos" });
      return;
    }
    setBusy("create-user");
    try {
      await usersApi.create(userForm as any);
      sileo.success({ title: "Usuario creado", description: `Usuario ${userForm.username} añadido.` });
      setUserForm({ username: "", password: "", role: "user", active: true });
      setShowUserForm(false);
      await refresh();
    } catch (err: any) {
      sileo.error({ title: "Error al crear usuario", description: err.message });
    } finally {
      setBusy(null);
    }
  };

  const handleUpdateUser = async (userId: number) => {
    setBusy(`update-user-${userId}`);
    try {
      const payload: any = {
        role: userForm.role,
        active: userForm.active,
      };
      if (userForm.username) payload.username = userForm.username;
      if (userForm.password) payload.password = userForm.password;

      await usersApi.update(userId, payload);
      sileo.success({ title: "Usuario actualizado" });
      setEditingUser(null);
      setUserForm({ username: "", password: "", role: "user", active: true });
      setShowUserForm(false);
      await refresh();
    } catch (err: any) {
      sileo.error({ title: "Error al actualizar", description: err.message });
    } finally {
      setBusy(null);
    }
  };

  const handleDeleteUser = async (userId: number, username: string) => {
    if (!confirm(`¿Estás seguro de eliminar al usuario ${username}?`)) return;
    setBusy(`delete-user-${userId}`);
    try {
      await usersApi.delete(userId);
      sileo.success({ title: "Usuario eliminado" });
      await refresh();
    } catch (err: any) {
      sileo.error({ title: "Error al eliminar", description: err.message });
    } finally {
      setBusy(null);
    }
  };

  const startEditUser = (user: DashboardUser) => {
    setEditingUser(user);
    setUserForm({
      username: user.username,
      password: "",
      role: user.role as "admin" | "user",
      active: !!user.active,
    });
    setShowUserForm(true);
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
            Control de sitios y autorizaciones operativas.
          </p>
        </div>

        <button
          onClick={() => window.dispatchEvent(new CustomEvent('request-browser-notifications'))}
          className={cn(
            "morr-focus px-4 py-2 rounded-xl",
            "text-[10px] font-black uppercase tracking-[0.18em]",
            "bg-[rgba(108,77,255,0.06)] text-foreground/90 border border-border/70",
            "hover:bg-[rgba(108,77,255,0.12)] hover:border-[rgba(108,77,255,0.3)]",
            "transition active:scale-[0.99] flex items-center gap-2"
          )}
        >
          <Bell size={14} className="text-[rgba(108,77,255,0.8)]" />
          Habilitar Notificaciones
        </button>
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
                    Organismo
                  </th>
                  {canManagePauses && (
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">
                      Motivo Pausa
                    </th>
                  )}
                  <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80 text-right">
                    Acciones de Control
                  </th>
                </tr>
              </thead>

              <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
                {sites.map((site) => {
                  const isPaused = !!pauseMap[site];
                  const isActiveConfig = configActiveMap[site] ?? true;
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
                        <span
                          className={cn(
                            "inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-[0.20em] border",
                            isActiveConfig
                              ? "border-[rgba(108,77,255,0.22)] bg-[rgba(108,77,255,0.08)] text-foreground/90"
                              : "border-[rgba(255,60,80,0.30)] bg-[rgba(255,60,80,0.10)] text-foreground/90"
                          )}
                        >
                          <span
                            className="w-1.5 h-1.5 rounded-full"
                            style={{
                              background: isActiveConfig
                                ? "rgba(108,77,255,0.85)"
                                : "rgba(255,60,80,0.85)",
                            }}
                          />
                          {isActiveConfig ? "HABILITADO" : "DESHABILITADO"}
                        </span>
                      </td>

                      {canManagePauses && (
                        <td className="px-6 py-4">
                          <span className="text-xs text-muted-foreground/80 italic">
                            {pauseMap[site]?.reason || "-"}
                          </span>
                        </td>
                      )}

                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {canManagePauses ? (
                            <>
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
                              <button
                                onClick={() => handleSetSiteActive(site, !isActiveConfig)}
                                disabled={!!busy}
                                className={cn(
                                  "morr-focus px-4 py-2 rounded-xl",
                                  "text-[11px] font-black uppercase tracking-[0.18em]",
                                  isActiveConfig
                                    ? "bg-[rgba(255,60,80,0.08)] text-foreground/90 border border-[rgba(255,60,80,0.25)] hover:bg-[rgba(255,60,80,0.14)]"
                                    : "bg-[rgba(108,77,255,0.10)] text-foreground/95 border border-[rgba(108,77,255,0.28)] hover:bg-[rgba(108,77,255,0.16)]",
                                  "transition active:scale-[0.99] disabled:opacity-50",
                                  "inline-flex items-center gap-2"
                                )}
                              >
                                <Power size={14} />
                                {isActiveConfig ? "Desactivar" : "Activar"}
                              </button>
                            </>
                          ) : (
                            <span className="text-[10px] text-muted-foreground/50 border border-border/30 px-2 py-1 rounded uppercase tracking-widest">
                              Read Only
                            </span>
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
      {canManagePauses && (
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
      )}

      {/* =========================
          User Management
         ========================= */}
      {isAdmin && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg border border-border/70 bg-[rgba(17,19,26,0.55)] flex items-center justify-center">
                <Users size={18} className="text-[rgba(108,77,255,0.75)]" />
              </div>
              <h3 className="text-xl font-black uppercase tracking-tight text-foreground/90">
                Gestión de Usuarios
              </h3>
            </div>

            <button
              onClick={() => {
                setEditingUser(null);
                setUserForm({ username: "", password: "", role: "user", active: true });
                setShowUserForm(!showUserForm);
              }}
              className={cn(
                "morr-focus px-4 py-2 rounded-xl",
                "text-[10px] font-black uppercase tracking-[0.18em]",
                "bg-[rgba(108,77,255,0.10)] text-foreground/95 border border-[rgba(108,77,255,0.28)] hover:bg-[rgba(108,77,255,0.16)]",
                "transition active:scale-[0.99] flex items-center gap-2"
              )}
            >
              <UserPlus size={14} />
              Nuevo Usuario
            </button>
          </div>

          {showUserForm && (
            <div className="morr-card rounded-2xl p-6 border border-[rgba(108,77,255,0.2)] bg-[rgba(108,77,255,0.02)] space-y-6 animate-in slide-in-from-top-4 duration-500">
              <div className="flex items-center justify-between">
                <h4 className="font-black uppercase tracking-tight text-foreground/90">
                  {editingUser ? "Editar Usuario" : "Añadir Nuevo Usuario"}
                </h4>
                <button onClick={() => setShowUserForm(false)} className="text-muted-foreground hover:text-foreground">
                  <X size={20} />
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/80">Username</label>
                  <input
                    type="text"
                    value={userForm.username}
                    onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                    className="w-full bg-[rgba(17,19,26,0.55)] border border-border/70 rounded-xl px-4 py-2 text-sm text-foreground/90 focus:border-[rgba(108,77,255,0.3)] outline-none transition"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/80">
                    {editingUser ? "Nueva Password (dejar vacío para no cambiar)" : "Password"}
                  </label>
                  <div className="relative">
                    <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50" />
                    <input
                      type="password"
                      value={userForm.password}
                      onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                      className="w-full bg-[rgba(17,19,26,0.55)] border border-border/70 rounded-xl pl-9 pr-4 py-2 text-sm text-foreground/90 focus:border-[rgba(108,77,255,0.3)] outline-none transition"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/80">Role</label>
                  <select
                    value={userForm.role}
                    onChange={(e) => setUserForm({ ...userForm, role: e.target.value as any })}
                    className="w-full bg-[rgba(17,19,26,0.55)] border border-border/70 rounded-xl px-4 py-2 text-sm text-foreground/90 focus:border-[rgba(108,77,255,0.3)] outline-none transition"
                  >
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/80">Estado</label>
                  <div className="flex items-center gap-4 py-2">
                    <label className="flex items-center gap-2 cursor-pointer group">
                      <input
                        type="radio"
                        checked={userForm.active}
                        onChange={() => setUserForm({ ...userForm, active: true })}
                        className="sr-only"
                      />
                      <div className={cn(
                        "w-4 h-4 rounded-full border border-border flex items-center justify-center transition",
                        userForm.active ? "bg-[rgba(108,77,255,0.8)] border-[rgba(108,77,255,0.8)]" : "bg-transparent"
                      )}>
                        {userForm.active && <div className="w-1.5 h-1.5 bg-white rounded-full" />}
                      </div>
                      <span className="text-sm font-bold uppercase tracking-widest text-foreground/80 hover:text-foreground">Activo</span>
                    </label>

                    <label className="flex items-center gap-2 cursor-pointer group">
                      <input
                        type="radio"
                        checked={!userForm.active}
                        onChange={() => setUserForm({ ...userForm, active: false })}
                        className="sr-only"
                      />
                      <div className={cn(
                        "w-4 h-4 rounded-full border border-border flex items-center justify-center transition",
                        !userForm.active ? "bg-[rgba(255,60,80,0.8)] border-[rgba(255,60,80,0.8)]" : "bg-transparent"
                      )}>
                        {!userForm.active && <div className="w-1.5 h-1.5 bg-white rounded-full" />}
                      </div>
                      <span className="text-sm font-bold uppercase tracking-widest text-foreground/80 hover:text-foreground">Inactivo</span>
                    </label>
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={() => setShowUserForm(false)}
                  className="px-6 py-2 text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground hover:text-foreground transition"
                >
                  Cancelar
                </button>
                <button
                  onClick={() => editingUser ? handleUpdateUser(editingUser.id!) : handleCreateUser()}
                  disabled={!!busy}
                  className={cn(
                    "morr-focus px-8 py-2 rounded-xl",
                    "text-[10px] font-black uppercase tracking-[0.2em]",
                    "bg-[color:var(--morr-fate)] text-white shadow-[0_0_20px_rgba(122,15,30,0.2)]",
                    "hover:shadow-[0_0_25px_rgba(122,15,30,0.3)] hover:scale-[1.02]",
                    "transition-all duration-300 active:scale-[0.98] disabled:opacity-50"
                  )}
                >
                  {editingUser ? "Guardar Cambios" : "Crear Usuario"}
                </button>
              </div>
            </div>
          )}

          <div className="morr-card rounded overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[rgba(17,19,26,0.55)] border-b border-border/70">
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">ID / Usuario</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Role</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Estado</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80">Creado</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-[0.22em] text-muted-foreground/80 text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
                  {users.map((user) => (
                    <tr key={user.id} className="hover:bg-[rgba(255,255,255,0.03)] transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex flex-col">
                          <span className="font-black text-sm tracking-tight text-foreground/90">{user.username}</span>
                          <span className="text-[10px] text-muted-foreground/60 font-mono">UID: #{user.id}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span className={cn(
                          "text-[10px] font-black uppercase tracking-[0.2em] px-2 py-0.5 rounded border",
                          user.role === 'admin'
                            ? "border-[rgba(108,77,255,0.3)] bg-[rgba(108,77,255,0.08)] text-[rgba(108,77,255,0.95)]"
                            : "border-border/50 bg-[rgba(255,255,255,0.03)] text-muted-foreground/80"
                        )}>
                          {user.role}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em]">
                          <div className={cn(
                            "w-1.5 h-1.5 rounded-full",
                            user.active ? "bg-[rgba(108,77,255,0.9)]" : "bg-[rgba(255,60,80,0.8)]"
                          )} />
                          {user.active ? "Activo" : "Inactivo"}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-xs text-muted-foreground/80 font-mono">
                          {user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => startEditUser(user)}
                            disabled={!!busy}
                            className="p-2 rounded-lg border border-border/70 hover:border-[rgba(108,77,255,0.3)] hover:bg-[rgba(108,77,255,0.05)] text-muted-foreground hover:text-[rgba(108,77,255,0.9)] transition"
                            title="Editar"
                          >
                            <Edit2 size={16} />
                          </button>
                          <button
                            onClick={() => handleDeleteUser(user.id!, user.username)}
                            disabled={!!busy || user.username === 'admin'}
                            className="p-2 rounded-lg border border-border/70 hover:border-[rgba(255,60,80,0.3)] hover:bg-[rgba(255,60,80,0.05)] text-muted-foreground hover:text-[rgba(255,60,80,0.9)] transition"
                            title="Eliminar"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {/* Optional: show loading quietly if you want */}
      {loading && (
        <div className="text-xs text-muted-foreground/70 uppercase tracking-[0.22em]">
          Actualizando…
        </div>
      )}
    </div>
  );
}
