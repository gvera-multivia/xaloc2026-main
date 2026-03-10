import { apiClient } from '@/core/api/client'
import { AUTH } from '@/core/api/endpoints'
import { UserSessionSchema } from '@/core/api/schemas'
import { morriganWs } from '@/core/api/ws'
import { useAuthStore } from './auth.store'

export const AuthService = {
    async login(username: string, password: string): Promise<void> {
        console.log('[AuthService] Attempting login for:', username)
        const loginRes = await apiClient.post(AUTH.LOGIN, { username, password })

        const userData = loginRes.data?.user
        const rawToken = loginRes.data?.token ?? loginRes.data?.access_token ?? null

        if (!userData) throw new Error('No user in login response')

        const session = UserSessionSchema.parse(userData)
        const { setSession, setCredentials } = useAuthStore.getState()

        setSession(session, rawToken)
        setCredentials({ username, password })

        morriganWs.connectWithToken(rawToken)

        if (window.morrigan?.auth?.notifyLoginSuccess) {
            window.morrigan.auth.notifyLoginSuccess()
        }
    },

    async autoLogin(): Promise<boolean> {
        const { credentials } = useAuthStore.getState()

        if (!credentials) {
            console.log('[AuthService] No credentials stored for auto-login')
            return false
        }

        try {
            console.log('[AuthService] Attempting auto-login for:', credentials.username)
            await this.login(credentials.username, credentials.password)
            return true
        } catch (err: any) {
            console.error('[AuthService] Auto-login failed:', err)

            // Si las credenciales ya no son válidas, las borramos para no entrar en bucle
            if (err.response?.status === 401) {
                useAuthStore.getState().setCredentials(null)
            }
            return false
        }
    },

    async logout(): Promise<void> {
        const { clearSession, setCredentials } = useAuthStore.getState()
        clearSession()
        setCredentials(null)
        morriganWs.connectWithToken(null)
        window.location.hash = '/login'
    }
}
