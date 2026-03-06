import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useAuthStore } from '@/core/auth/auth.store'
import { morriganWs } from '@/core/api/ws'
import { incidentsApi } from '@/modules/incidents/incidents.api'
import type { IncidentItem, WsEvent } from '@/core/api/schemas'
import { releaseApi, type ReleaseStatusResponse } from '@/modules/release/release.api'
import '@/styles/globals.css'

const SITE_LABELS: Record<string, string> = {
    madrid: 'Madrid',
    xaloc_girona: 'Xaloc Girona',
    ayunta_palma: 'Palma',
    base_online: 'Base Online',
}

const INCIDENT_NOTIFY_DEDUPE_MS = 60_000

function siteLabel(siteId: string | undefined): string {
    const key = String(siteId || '').trim().toLowerCase()
    return SITE_LABELS[key] || (siteId ? siteId.replace(/_/g, ' ') : 'Sistema')
}

function incidentEventKey(ev: WsEvent): string {
    const data = (ev.data || {}) as Record<string, unknown>
    const parts = [
        String(data.site_id || ''),
        String(data.incident_type || data.error_code || ''),
        String(data.resource_id || ''),
        String(data.expediente || ''),
    ]
    return parts.join('|')
}

export function DashboardView() {
    const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
    const userRole = String(useAuthStore((s) => s.user?.role || '')).toLowerCase()
    const isAdmin = userRole === 'admin'
    const [incidents, setIncidents] = useState<IncidentItem[]>([])
    const [loading, setLoading] = useState(true)
    const [updaterState, setUpdaterState] = useState<
        Awaited<ReturnType<typeof window.morrigan.updater.getState>> | null
    >(null)
    const [updaterBusy, setUpdaterBusy] = useState(false)
    const [releaseVersion, setReleaseVersion] = useState('')
    const [releaseBusy, setReleaseBusy] = useState(false)
    const [releaseStatus, setReleaseStatus] = useState<ReleaseStatusResponse | null>(null)
    const lastIncidentNotifyAtRef = useRef<Map<string, number>>(new Map())

    const fetchIncidents = async () => {
        try {
            setLoading(true)
            const data = await incidentsApi.getIncidents()
            setIncidents(data)
        } catch (err) {
            console.error('Error fetching incidents:', err)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        if (isAuthenticated) {
            void fetchIncidents()
        }
    }, [isAuthenticated])

    useEffect(() => {
        let mounted = true

        const loadUpdaterState = async () => {
            try {
                const state = await window.morrigan.updater.getState()
                if (mounted) {
                    setUpdaterState(state)
                }
            } catch (err) {
                console.error('Error loading updater state:', err)
            }
        }

        void loadUpdaterState()
        const unsubscribe = window.morrigan.updater.onStatusChange((status) => {
            if (mounted) {
                setUpdaterState(status)
            }
        })

        return () => {
            mounted = false
            unsubscribe()
        }
    }, [])

    useEffect(() => {
        if (!isAuthenticated) return

        const token = useAuthStore.getState().token
        morriganWs.connectWithToken(token ?? null)

        const unsubscribe = morriganWs.subscribe((ev) => {
            const type = String(ev.type || '').toLowerCase()
            const isIncident = type.includes('incident') || type.includes('error') || ev.type === 'job.failed'
            const isAdminAlert = ev.type === 'admin.alert'

            if (isIncident) {
                const key = incidentEventKey(ev)
                const now = Date.now()
                const last = lastIncidentNotifyAtRef.current.get(key) || 0
                if (now - last < INCIDENT_NOTIFY_DEDUPE_MS) {
                    return
                }
                lastIncidentNotifyAtRef.current.set(key, now)

                void fetchIncidents()
                const data = (ev.data || {}) as Record<string, unknown>
                const site = siteLabel(String(data.site_id || ''))
                const rid = data.resource_id ? ` (recurso ${String(data.resource_id)})` : ''
                const title = `ATENCION: INCIDENCIA EN ${site.toUpperCase()}${rid}`
                const body = String(
                    data.reason ||
                    data.error_code ||
                    data.incident_type ||
                    'Se ha detectado una nueva incidencia.'
                )

                const reasonLower = body.toLowerCase()
                const typeLower = String(data.incident_type || '').toLowerCase()

                let notifType = 'default'
                if (reasonLower.includes('aut') || reasonLower.includes('carpeta') || typeLower.includes('aut') || typeLower.includes('carpeta')) {
                    notifType = 'red-large'
                } else if (reasonLower.includes('recurso') || reasonLower.includes('hacer') || typeLower.includes('recurso')) {
                    notifType = 'green'
                } else if (reasonLower.includes('bloqueo') || typeLower.includes('bloqueo')) {
                    notifType = 'purple'
                }

                window.morrigan.auth.notify(title, body, notifType)
            }

            if (isAdminAlert) {
                const data = (ev.data || {}) as { title?: string; body?: string; level?: string; design_code?: string }
                const title = data.title || 'Aviso de Administracion'
                const body = data.body || 'Nuevo mensaje broadcast recibido.'
                const level = (data.level || 'info').toLowerCase()
                const designCode = data.design_code
                const iconPrefix = level === 'critical' ? '[CRITICAL] ' : level === 'warning' ? '[WARN] ' : '[INFO] '

                let adminNotifType = 'default'
                if (level === 'critical') adminNotifType = 'red-large'
                else if (level === 'info') adminNotifType = 'green'

                window.morrigan.auth.notify(`${iconPrefix}${title}`, body, { type: adminNotifType, design_code: designCode } as any)
            }
        })

        return () => {
            unsubscribe()
        }
    }, [isAuthenticated])

    useEffect(() => {
        if (!isAuthenticated || !isAdmin) return
        let timer: ReturnType<typeof setInterval> | null = null
        let mounted = true

        const refresh = async () => {
            try {
                const status = await releaseApi.status()
                if (!mounted) return
                setReleaseStatus(status)
                if (status.running && !timer) {
                    timer = setInterval(() => {
                        void refresh()
                    }, 2000)
                }
                if (!status.running && timer) {
                    clearInterval(timer)
                    timer = null
                }
            } catch {
                // noop
            }
        }

        void refresh()
        return () => {
            mounted = false
            if (timer) clearInterval(timer)
        }
    }, [isAuthenticated, isAdmin])

    if (!isAuthenticated) return null

    const runCheckNow = async () => {
        try {
            setUpdaterBusy(true)
            await window.morrigan.updater.checkNow()
        } finally {
            setUpdaterBusy(false)
        }
    }

    const runInstallNow = async () => {
        try {
            setUpdaterBusy(true)
            await window.morrigan.updater.installNow()
        } finally {
            setUpdaterBusy(false)
        }
    }

    const runReleaseBuild = async () => {
        try {
            setReleaseBusy(true)
            await releaseApi.build({ version: releaseVersion.trim() || undefined })
            window.morrigan.auth.notify(
                'Pipeline de release iniciado',
                'Generando instalador NSIS y latest.yml. Puedes seguir el estado abajo.',
                'green'
            )
            const status = await releaseApi.status()
            setReleaseStatus(status)
        } catch (err: any) {
            const detail = String(err?.response?.data?.detail || err?.message || 'Error iniciando release')
            window.morrigan.auth.notify('Error iniciando release', detail, 'red-large')
        } finally {
            setReleaseBusy(false)
        }
    }

    return (
        <div className="dashboard-container">
            <header className="dashboard-header">
                <h1>Centro de Alertas Morrigan</h1>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', WebkitAppRegion: 'no-drag' } as CSSProperties}>
                    <button
                        className="btn btn-primary btn-sm"
                        onClick={() => {
                            window.morrigan.auth.notify(
                                'TEST: SIMULACRO DE INCIDENCIA',
                                'Prueba local de notificacion.'
                            )
                        }}
                    >
                        Probar Noti
                    </button>
                    <div className="status-indicator">
                        <span className={`dot ${morriganWs.isConnected() ? 'online' : 'offline'}`}></span>
                        {morriganWs.isConnected() ? 'Sistema Conectado' : 'Desconectado'}
                    </div>
                </div>
            </header>

            <section className="dashboard-content" style={{ marginTop: 12 }}>
                <h2 className="section-title">Actualizaciones</h2>
                <div className="table-wrapper" style={{ padding: 12 }}>
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
                        <div style={{ fontSize: 13 }}>
                            <strong>Version actual:</strong> {updaterState?.currentVersion || 'desconocida'}
                            {'  .  '}
                            <strong>Estado:</strong> {updaterState?.message || updaterState?.stage || 'sin datos'}
                            {updaterState?.progressPercent !== undefined ? ` (${updaterState.progressPercent}%)` : ''}
                        </div>
                        <div style={{ display: 'flex', gap: 8 }}>
                            <button
                                className="btn btn-primary btn-sm"
                                onClick={runCheckNow}
                                disabled={updaterBusy || updaterState?.stage === 'checking'}
                            >
                                Buscar actualizacion
                            </button>
                            <button
                                className="btn btn-primary btn-sm"
                                onClick={runInstallNow}
                                disabled={updaterBusy || updaterState?.stage !== 'downloaded'}
                            >
                                Instalar y reiniciar
                            </button>
                            {isAdmin && (
                                <button
                                    className="btn btn-primary btn-sm"
                                    onClick={runReleaseBuild}
                                    disabled={releaseBusy || Boolean(releaseStatus?.running)}
                                >
                                    Publicar Version
                                </button>
                            )}
                        </div>
                    </div>
                    {isAdmin && (
                        <div style={{ marginTop: 12, borderTop: '1px solid rgba(148,163,184,0.25)', paddingTop: 10 }}>
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                                <input
                                    value={releaseVersion}
                                    onChange={(e) => setReleaseVersion(e.target.value)}
                                    placeholder="Version (ej: 0.1.8)"
                                    style={{
                                        background: 'rgba(15,23,42,0.5)',
                                        border: '1px solid rgba(148,163,184,0.4)',
                                        color: '#e2e8f0',
                                        borderRadius: 6,
                                        padding: '6px 8px',
                                        minWidth: 180,
                                    }}
                                />
                                <button
                                    className="btn btn-primary btn-sm"
                                    onClick={async () => setReleaseStatus(await releaseApi.status())}
                                >
                                    Refrescar Estado
                                </button>
                                <span style={{ fontSize: 12, opacity: 0.85 }}>
                                    Release: {releaseStatus?.running ? 'en curso' : (releaseStatus?.ok ? 'ok' : (releaseStatus?.step || 'idle'))}
                                </span>
                            </div>
                            {releaseStatus?.artifacts && (
                                <div style={{ fontSize: 12, marginTop: 8 }}>
                                    <div>Installer: {releaseStatus.artifacts.installer?.name || '-'}</div>
                                    <div>latest.yml: {releaseStatus.artifacts.latestYml?.name || '-'}</div>
                                </div>
                            )}
                            {releaseStatus?.logs?.length ? (
                                <pre
                                    style={{
                                        marginTop: 8,
                                        maxHeight: 180,
                                        overflow: 'auto',
                                        background: 'rgba(2,6,23,0.7)',
                                        border: '1px solid rgba(148,163,184,0.25)',
                                        borderRadius: 6,
                                        padding: 8,
                                        fontSize: 11,
                                        whiteSpace: 'pre-wrap',
                                    }}
                                >
                                    {releaseStatus.logs.slice(-60).join('\n')}
                                </pre>
                            ) : null}
                        </div>
                    )}
                </div>
            </section>

            <main className="dashboard-content">
                <h2 className="section-title">
                    Incidencias Activas {incidents.length > 0 && <span className="badge">{incidents.length}</span>}
                </h2>

                {loading ? (
                    <div className="loader">Sincronizando flujo...</div>
                ) : incidents.length === 0 ? (
                    <div className="empty-state">
                        <span className="empty-icon">OK</span>
                        <p>El sistema opera en parametros normales.</p>
                    </div>
                ) : (
                    <div className="table-wrapper">
                        <table className="incidents-table">
                            <thead>
                                <tr>
                                    <th>Organismo</th>
                                    <th>Recurso</th>
                                    <th>Tipo</th>
                                    <th>Razon</th>
                                    <th>Recibido</th>
                                </tr>
                            </thead>
                            <tbody>
                                {incidents.map((inc) => (
                                    <tr key={inc.id}>
                                        <td>{siteLabel(inc.site_id)}</td>
                                        <td className="mono">{inc.resource_id ?? '--'}</td>
                                        <td><span className="type-badge">{inc.incident_type}</span></td>
                                        <td className="reason-col">{inc.reason || inc.error_code || '--'}</td>
                                        <td className="time-col">{new Date(inc.created_at || '').toLocaleTimeString()}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </main>

            <footer className="dashboard-footer">
                Cierra esta ventana para seguir recibiendo alertas de escritorio.
            </footer>
        </div>
    )
}
