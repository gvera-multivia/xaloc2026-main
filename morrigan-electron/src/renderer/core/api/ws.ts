import { ENV } from '@/core/config/env'
import type { WsEvent } from '@/core/api/schemas'
import { WsEventSchema } from '@/core/api/schemas'

type WsEventHandler = (event: WsEvent) => void

const BACKOFF_STEPS = [1000, 2000, 5000, 10000, 30000]

class MorriganWebSocket {
    private ws: WebSocket | null = null
    private wsUrl = ENV.WS_URL
    private wsToken: string | null = null
    private handlers: Set<WsEventHandler> = new Set()
    private retryIndex = 0
    private retryTimer: ReturnType<typeof setTimeout> | null = null
    private connected = false
    private destroyed = false

    private buildUrl(): string {
        if (!ENV.WS_USE_TOKEN_QUERY || !this.wsToken) return this.wsUrl
        const sep = this.wsUrl.includes('?') ? '&' : '?'
        return `${this.wsUrl}${sep}token=${encodeURIComponent(this.wsToken)}`
    }

    connectWithToken(token: string | null): void {
        this.wsToken = token
        this.ws?.close()
        this.ws = null
        this.connect()
    }

    connect(): void {
        if (this.destroyed) return
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return
        }
        try {
            this.ws = new WebSocket(this.buildUrl())

            this.ws.onopen = () => {
                this.connected = true
                this.retryIndex = 0
                console.log('[WS] Conectado a', this.wsUrl)
                window.dispatchEvent(new CustomEvent('morrigan:ws-connected'))
            }

            this.ws.onmessage = (event) => {
                try {
                    const raw = JSON.parse(event.data as string)
                    const parsed = WsEventSchema.safeParse(raw)
                    if (parsed.success) {
                        this.handlers.forEach((h) => h(parsed.data))
                    }
                } catch {
                    // Ignorar mensajes malformados
                }
            }

            this.ws.onclose = (event) => {
                this.connected = false
                this.ws = null
                if (event.code === 4401) {
                    console.warn('[WS] Conexion rechazada por autenticacion invalida (4401)')
                }
                // Fallback robusto: si el handshake falla con token en query,
                // reintentar sin token para usar la cookie de sesion.
                if (!this.connected && this.wsToken) {
                    console.warn('[WS] Handshake fallido con token query; fallback a cookie auth.')
                    this.wsToken = null
                    this.retryIndex = 0
                }
                if (!this.destroyed) {
                    this.scheduleReconnect()
                }
                window.dispatchEvent(new CustomEvent('morrigan:ws-disconnected'))
            }

            this.ws.onerror = () => {
                this.ws?.close()
            }
        } catch {
            this.scheduleReconnect()
        }
    }

    setUrl(nextUrl: string): void {
        const sanitized = nextUrl.replace(/\/$/, '')
        if (sanitized === this.wsUrl) return
        this.wsUrl = sanitized
        if (this.retryTimer) {
            clearTimeout(this.retryTimer)
            this.retryTimer = null
        }
        this.connected = false
        this.ws?.close()
        this.connect()
    }

    private scheduleReconnect(): void {
        const delay = BACKOFF_STEPS[Math.min(this.retryIndex, BACKOFF_STEPS.length - 1)]
        this.retryIndex++
        console.log(`[WS] Reconectando en ${delay}ms (intento ${this.retryIndex})`)
        this.retryTimer = setTimeout(() => this.connect(), delay)
    }

    subscribe(handler: WsEventHandler): () => void {
        this.handlers.add(handler)
        return () => this.handlers.delete(handler)
    }

    send(data: unknown): void {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data))
        }
    }

    isConnected(): boolean {
        return this.connected
    }

    destroy(): void {
        this.destroyed = true
        if (this.retryTimer) clearTimeout(this.retryTimer)
        this.ws?.close()
        this.handlers.clear()
    }
}

// Singleton global
export const morriganWs = new MorriganWebSocket()
