import { useEffect, useState } from 'react'
import { Providers } from './providers'
import { AppRoutes } from './routes'
import { useAuthStore } from '@/core/auth/auth.store'
import { initRuntimeConfig } from '@/core/config/runtime'
import { apiClient } from '@/core/api/client'
import { AUTH } from '@/core/api/endpoints'
import { morriganWs } from '@/core/api/ws'
import { AuthService } from '@/core/auth/auth.service'
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
                try {
                    await apiClient.get(AUTH.ME)
                    console.log('[App] Session validated via cookie')
                    const persistedToken = useAuthStore.getState().token
                    morriganWs.connectWithToken(persistedToken)
                } catch (err: any) {
                    if (err.response?.status === 401) {
                        console.log('[App] Cookie session invalid, attempting auto-login')
                        const success = await AuthService.autoLogin()
                        if (!success) {
                            clearSession()
                        }
                    } else {
                        throw err
                    }
                }
            } catch (err) {
                console.error('[App] Bootstrap error:', err)
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
