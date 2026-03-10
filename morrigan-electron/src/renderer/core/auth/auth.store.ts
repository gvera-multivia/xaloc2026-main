import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { UserSession } from '@/core/api/schemas'

interface AuthState {
    user: UserSession | null
    isAuthenticated: boolean
    token: string | null
    credentials: { username: string; password: string } | null
    setSession: (user: UserSession, token?: string) => void
    setCredentials: (credentials: { username: string; password: string } | null) => void
    clearSession: () => void
}

export const useAuthStore = create<AuthState>()(
    persist(
        (set) => ({
            user: null,
            isAuthenticated: false,
            token: null,
            credentials: null,
            setSession: (user, token) => set({ user, isAuthenticated: true, token: token ?? null }),
            setCredentials: (credentials) => set({ credentials }),
            clearSession: () => set({ user: null, isAuthenticated: false, token: null }),
        }),
        {
            name: 'morrigan-auth',
        }
    )
)
