import { useEffect, useState } from 'react'
import { useAuthStore } from '@/core/auth/auth.store'
import { morriganWs } from '@/core/api/ws'
import { incidentsApi } from '@/modules/incidents/incidents.api'
import type { IncidentItem } from '@/core/api/schemas'
import '@/styles/globals.css'

export function DashboardView() {
    const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
    const [incidents, setIncidents] = useState<IncidentItem[]>([])
    const [loading, setLoading] = useState(true)
    const [updaterState, setUpdaterState] = useState<
        Awaited<ReturnType<typeof window.morrigan.updater.getState>> | null
    >(null)
    const [updaterBusy, setUpdaterBusy] = useState(false)

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

    // 1. Cargar las incidencias al montar
    useEffect(() => {
        if (isAuthenticated) {
            fetchIncidents()
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

    // 2. Gestionar la conexión WebSocket y lanzar Notificaciones Nativas
    useEffect(() => {
        if (isAuthenticated) {
            const token = useAuthStore.getState().token;
            morriganWs.connectWithToken(token ?? null);

            const unsubscribe = morriganWs.subscribe((ev) => {
                const isIncident = ev.type.toLowerCase().includes('incident') ||
                    ev.type.toLowerCase().includes('error') ||
                    ev.type === 'job.failed'
                const isAdminAlert = ev.type === 'admin.alert'

                if (isIncident) {
                    fetchIncidents()
                    const data = ev.data as any
                    const title = '⚠️ ATENCIÓN: INCIDENCIA EN XALOC'
                    const body = data?.reason || data?.error_code || 'Se ha detectado una nueva incidencia que requiere revisión.'

                    const reasonLower = (body || '').toLowerCase()
                    const typeLower = (data?.incident_type || '').toLowerCase()

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
                    const design_code = data.design_code
                    const iconPrefix =
                        level === 'critical' ? '🚨 ' :
                            level === 'warning' ? '⚠️ ' : 'ℹ️ '

                    let adminNotifType = 'default'
                    if (level === 'critical') adminNotifType = 'red-large'
                    else if (level === 'info') adminNotifType = 'green'

                    // Use property bag instead of just string type
                    window.morrigan.auth.notify(`${iconPrefix}${title}`, body, { type: adminNotifType, design_code } as any)
                }
            })

            return () => {
                unsubscribe()
            }
        }
    }, [isAuthenticated])

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

    return (
        <div className="dashboard-container">
            <header className="dashboard-header">
                <h1>Centro de Alertas Morrigan</h1>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
                    <button
                        className="btn btn-primary btn-sm"
                        onClick={() => {
                            window.morrigan.auth.notify(
                                '⚠️ TEST: SIMULACRO DE INCIDENCIA',
                                'Esto es una prueba local. No se ha registrado en BBDD ni en Redis.'
                            )
                        }}
                    >
                        ⚡ Probar Noti
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
                            {'  ·  '}
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
                        </div>
                    </div>
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
                        <span className="empty-icon">✓</span>
                        <p>El sistema opera en parámetros normales.</p>
                    </div>
                ) : (
                    <div className="table-wrapper">
                        <table className="incidents-table">
                            <thead>
                                <tr>
                                    <th>NUR/NIF</th>
                                    <th>Tipo</th>
                                    <th>Razon</th>
                                    <th>Recibido</th>
                                </tr>
                            </thead>
                            <tbody>
                                {incidents.map((inc) => (
                                    <tr key={inc.id}>
                                        <td className="mono">{inc.site_id}</td>
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
                Cierra esta ventana para seguir recibiendo alertas de escritorio. Build test updater 0.1.2
            </footer>
        </div>
    )
}
