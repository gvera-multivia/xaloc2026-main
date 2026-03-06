import { useEffect, useState } from 'react'
import { Providers } from './providers'
import { AppRoutes } from './routes'
import { useAuthStore } from '@/core/auth/auth.store'
import { initRuntimeConfig } from '@/core/config/runtime'
import { apiClient } from '@/core/api/client'
import { AUTH } from '@/core/api/endpoints'
import { UserSessionSchema } from '@/core/api/schemas'
import { morriganWs } from '@/core/api/ws'
import type { AxiosError } from 'axios'

export function App() {
    const [bootReady, setBootReady] = useState(false)
    const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
    const setSession = useAuthStore((s) => s.setSession)
    const clearSession = useAuthStore((s) => s.clearSession)

    useEffect(() => {
        let mounted = true

        const bootstrap = async () => {
            try {
                await initRuntimeConfig()

                // Validate persisted cookie session on each startup.
                const meRes = await apiClient.get(AUTH.ME)
                const session = UserSessionSchema.parse(meRes.data.user)
                const persistedToken = useAuthStore.getState().token
                setSession(session, persistedToken ?? undefined)
                morriganWs.connectWithToken(persistedToken)
            } catch (err) {
                // Only clear persisted session when backend explicitly says auth is invalid.
                // On network/CORS/timeout errors we keep local session to avoid false logout
                // right after updater restart.
                const axiosErr = err as AxiosError | undefined
                const status = axiosErr?.response?.status
                const shouldInvalidate = status === 401 || status === 403
                const currentSession = useAuthStore.getState().user
                if (!currentSession || shouldInvalidate) {
                    clearSession()
                }
            } finally {
                if (mounted) {
                    setBootReady(true)
                }
            }
        }

        bootstrap()

        return () => {
            mounted = false
        }
    }, [setSession, clearSession])

    useEffect(() => {
        if (!bootReady) return

        window.morrigan.auth.notifyLoginStatus(isAuthenticated)
        if (isAuthenticated) {
            const token = useAuthStore.getState().token
            morriganWs.connectWithToken(token ?? null)
        }

        const unsubscribe = window.morrigan.auth.onForceLogout(() => {
            clearSession()
        })

        return () => {
            unsubscribe()
        }
    }, [bootReady, isAuthenticated, clearSession])

    if (!bootReady) {
        return <div style={{ color: '#cbd5e1', padding: 16 }}>Iniciando Morrigan...</div>
    }

    return (
        <Providers>
            <AppRoutes />
        </Providers>
    )
}
