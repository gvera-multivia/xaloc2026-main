import { Session } from 'electron'

/**
 * Aplica una Content Security Policy restrictiva a la sesion de Electron.
 *
 * Directivas clave:
 *  - default-src 'self'    -> Solo recursos locales por defecto
 *  - connect-src dinamico  -> Calculado desde runtime-config (apiBaseUrl + wsUrl)
 *  - worker-src 'none'     -> Bloquea Web Workers no autorizados
 *  - media-src 'none'      -> Bloquea audio/video remotos
 *  - object-src 'none'     -> Bloquea plugins
 *  - frame-src 'none'      -> Bloquea iframes externos
 *  - base-uri 'self'       -> Previene base tag injection
 */
export function applyCSP(
    session: Session,
    getConnectSources: () => string[]
): void {
    session.webRequest.onHeadersReceived((details, callback) => {
        const dynamicConnectSources = getConnectSources()
            .map((source) => String(source || '').trim())
            .filter(Boolean)

        const connectSources = dynamicConnectSources.length > 0
            ? dynamicConnectSources.join(' ')
            : "'self'"

        callback({
            responseHeaders: {
                ...details.responseHeaders,
                'Content-Security-Policy': [
                    [
                        "default-src 'self'",
                        "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
                        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
                        "font-src 'self' https://fonts.gstatic.com",
                        "img-src 'self' data: blob:",
                        `connect-src ${connectSources}`,
                        "worker-src 'none'",
                        "media-src 'none'",
                        "object-src 'none'",
                        "frame-src 'none'",
                        "base-uri 'self'",
                    ].join('; '),
                ],
            },
        })
    })
}
