/**
 * Endpoints centralizados del api-gateway
 * Base URL runtime: configurable via main/preload (default morrigan.local)
 */

// ─── Auth ─────────────────────────────────────────────────────────────────────
export const AUTH = {
    LOGIN: '/api/auth/login',
    REGISTER: '/api/auth/register',
    ME: '/api/auth/me',
    LOGOUT: '/api/auth/logout',
} as const

// ─── Cola ─────────────────────────────────────────────────────────────────────
export const QUEUE = {
    CURRENT: '/api/queue/current',
    RECOVER_STUCK: '/api/queue/recover-stuck',
    ITEM: (siteId: string, resourceId: number) =>
        `/api/queue/items/${siteId}/${resourceId}`,
    RECOVER_ITEM: (siteId: string, resourceId: number) =>
        `/api/queue/items/${siteId}/${resourceId}/recover`,
} as const

// ─── Incidencias ──────────────────────────────────────────────────────────────
export const INCIDENTS = {
    LIST: '/api/incidents',
    CLAIM: (id: string) => `/api/incidents/${id}/claim`,
    RELEASE: (id: string) => `/api/incidents/${id}/release`,
} as const

// ─── Control ──────────────────────────────────────────────────────────────────
export const CONTROL = {
    STATUS: '/api/control/status',
    START: (processName: string) => `/api/control/${processName}/start`,
    STOP: (processName: string) => `/api/control/${processName}/stop`,
    RESTART: (processName: string) => `/api/control/${processName}/restart`,
} as const

// ─── Logs ─────────────────────────────────────────────────────────────────────
export const LOGS = {
    GET: (processName: string) => `/api/logs/${processName}`,
} as const

// ─── Config ───────────────────────────────────────────────────────────────────
export const CONFIG = {
    LIST: '/api/config',
    UPDATE: (siteId: string) => `/api/config/${siteId}`,
    TOGGLE_ACTIVE: (siteId: string) => `/api/config/${siteId}/active`,
} as const
