import axios, { type AxiosError } from 'axios'
import { ENV } from '@/core/config/env'
import { useAuthStore } from '@/core/auth/auth.store'
import { AuthService } from '@/core/auth/auth.service'

export const apiClient = axios.create({
    baseURL: ENV.API_BASE_URL,
    withCredentials: true,
    timeout: 20_000,
    headers: {
        'Content-Type': 'application/json',
    },
})

// ─── Interceptor de respuesta ─────────────────────────────────────────────────
apiClient.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
        const status = error.response?.status

        if (status === 401) {
            // Empujar autoreintento si tenemos credenciales
            const { credentials } = useAuthStore.getState()
            const originalRequest = error.config as any

            if (credentials && !originalRequest?._retry) {
                originalRequest._retry = true
                console.log('[apiClient] 401 detected, attempting transparent auto-login...')
                const success = await AuthService.autoLogin()
                if (success) {
                    console.log('[apiClient] Auto-login successful, retrying original request')
                    return apiClient(originalRequest)
                }
            }

            // Si llegamos aquí es que no había credenciales o falló el auto-login
            useAuthStore.getState().clearSession()
            window.location.hash = '/login'
            return Promise.reject(error)
        }

        if (status === 409) {
            // Conflicto funcional — el componente debe manejarlo
            return Promise.reject(error)
        }

        if (status !== undefined && status >= 500) {
            // 5xx — toast global (disparar evento custom)
            window.dispatchEvent(
                new CustomEvent('morrigan:api-error', {
                    detail: {
                        status,
                        message: error.message,
                        url: error.config?.url,
                    },
                })
            )
        }

        return Promise.reject(error)
    }
)
