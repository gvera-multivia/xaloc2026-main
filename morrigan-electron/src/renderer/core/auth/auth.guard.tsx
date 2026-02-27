import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/core/auth/auth.store'

/**
 * Guard de autenticación — redirige a /login si no hay sesión
 */
export function AuthGuard() {
    const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
    if (!isAuthenticated) return <Navigate to="/login" replace />
    return <Outlet />
}

/**
 * Guard de rol admin — redirige al dashboard si el usuario no es admin
 */
export function AdminGuard() {
    const user = useAuthStore((s) => s.user)
    if (user?.role !== 'admin') {
        return <Navigate to="/dashboard" replace />
    }
    return <Outlet />
}
