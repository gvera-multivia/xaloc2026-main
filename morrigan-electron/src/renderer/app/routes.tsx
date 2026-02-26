import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthGuard } from '@/core/auth/auth.guard'
import { LoginPage } from '@/modules/auth/LoginPage'
import { RegisterPage } from '@/modules/auth/RegisterPage'
import { DashboardView } from './DashboardView'

export function AppRoutes() {
    return (
        <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />

            {/* Ruta principal: Componente con Tabla de Incidencias que escucha en segundo plano */}
            <Route element={<AuthGuard />}>
                <Route path="/" element={<DashboardView />} />
            </Route>

            {/* Fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    )
}

