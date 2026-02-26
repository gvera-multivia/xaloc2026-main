import axios, { type AxiosError } from 'axios'
import { ENV } from '@/core/config/env'
import { useAuthStore } from '@/core/auth/auth.store'

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
            // En desarrollo Electron, las cookies cross-origin fallan a menudo. 
            // Si ya tenemos sesión en el store, no la limpiamos ni redirigimos
            // porque el usuario es persistente localmente.
            const hasPersistedUser = !!useAuthStore.getState().user
            if (hasPersistedUser) {
                return Promise.reject(error)
            }

            // Limpiar sesión y redirigir a login solo si realmente no estamos autenticados
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
