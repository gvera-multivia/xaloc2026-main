/**
 * Variables de entorno del renderer
 * Usar import.meta.env en desarrollo; en producción Electron
 * puede pasar valores via window.__ENV__ inyectado desde main.
 */
export const ENV = {
    API_BASE_URL:
        (import.meta.env.VITE_MORRIGAN_API_BASE_URL as string) ??
        'http://192.168.184.72',
    WS_URL:
        (import.meta.env.VITE_MORRIGAN_WS_URL as string) ??
        'ws://192.168.184.72/ws/dashboard',
    WS_USE_TOKEN_QUERY:
        String(import.meta.env.VITE_MORRIGAN_WS_USE_TOKEN_QUERY ?? '0').toLowerCase() === '1',
    BOOTSTRAP_URL:
        (import.meta.env.VITE_MORRIGAN_BOOTSTRAP_URL as string) ??
        'http://192.168.184.72/morrigan-config.json',
    CONFIG_REFRESH_SEC:
        Number(import.meta.env.VITE_MORRIGAN_CONFIG_REFRESH_SEC as string) || 120,
    APP_NAME:
        (import.meta.env.VITE_MORRIGAN_APP_NAME as string) ?? 'Morrigan',
    LOG_LEVEL:
        (import.meta.env.VITE_MORRIGAN_LOG_LEVEL as string) ?? 'info',
} as const

export type EnvConfig = typeof ENV
