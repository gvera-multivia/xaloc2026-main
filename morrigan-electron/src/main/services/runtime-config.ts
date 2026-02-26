import { app } from 'electron'
import { readFile } from 'fs/promises'
import path from 'path'
import logger from './logger'

export interface RuntimeConfig {
    apiBaseUrl: string
    wsUrl: string
    bootstrapUrl: string
    refreshIntervalSec: number
    source: 'default' | 'local-file' | 'remote-bootstrap'
    updatedAt: string
}

type RuntimeConfigPayload = Partial<{
    apiBaseUrl: string
    wsUrl: string
    bootstrapUrl: string
    refreshIntervalSec: number
    api_base_url: string
    ws_url: string
    bootstrap_url: string
    refresh_interval_sec: number
}>

const DEFAULT_API_BASE_URL =
    process.env.MORRIGAN_API_BASE_URL?.trim() || 'http://192.168.184.72'
const DEFAULT_WS_URL =
    process.env.MORRIGAN_WS_URL?.trim() || 'ws://192.168.184.72/ws/dashboard'
const DEFAULT_BOOTSTRAP_URL =
    process.env.MORRIGAN_BOOTSTRAP_URL?.trim() ||
    'http://192.168.184.72/morrigan-config.json'
const DEFAULT_REFRESH_INTERVAL_SEC = Math.max(
    Number(process.env.MORRIGAN_CONFIG_REFRESH_SEC || 120),
    30
)

let runtimeConfig: RuntimeConfig = {
    apiBaseUrl: DEFAULT_API_BASE_URL,
    wsUrl: DEFAULT_WS_URL,
    bootstrapUrl: DEFAULT_BOOTSTRAP_URL,
    refreshIntervalSec: DEFAULT_REFRESH_INTERVAL_SEC,
    source: 'default',
    updatedAt: new Date().toISOString(),
}

function sanitizeUrl(value: string | undefined, fallback: string): string {
    if (!value) return fallback
    try {
        const parsed = new URL(value.trim())
        return parsed.toString().replace(/\/$/, '')
    } catch {
        return fallback
    }
}

function sanitizeWsUrl(value: string | undefined, fallback: string): string {
    if (!value) return fallback
    try {
        const parsed = new URL(value.trim())
        if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') {
            return fallback
        }
        return parsed.toString().replace(/\/$/, '')
    } catch {
        return fallback
    }
}

function normalizePayload(payload: RuntimeConfigPayload): RuntimeConfigPayload {
    return {
        apiBaseUrl: payload.apiBaseUrl ?? payload.api_base_url,
        wsUrl: payload.wsUrl ?? payload.ws_url,
        bootstrapUrl: payload.bootstrapUrl ?? payload.bootstrap_url,
        refreshIntervalSec:
            payload.refreshIntervalSec ?? payload.refresh_interval_sec,
    }
}

function withPatch(
    base: RuntimeConfig,
    patch: RuntimeConfigPayload,
    source: RuntimeConfig['source']
): RuntimeConfig {
    const normalized = normalizePayload(patch)
    return {
        apiBaseUrl: sanitizeUrl(normalized.apiBaseUrl, base.apiBaseUrl),
        wsUrl: sanitizeWsUrl(normalized.wsUrl, base.wsUrl),
        bootstrapUrl: sanitizeUrl(normalized.bootstrapUrl, base.bootstrapUrl),
        refreshIntervalSec: Math.max(
            Number(normalized.refreshIntervalSec ?? base.refreshIntervalSec),
            30
        ),
        source,
        updatedAt: new Date().toISOString(),
    }
}

async function readLocalConfigFile(): Promise<RuntimeConfigPayload | null> {
    const configPath = path.join(app.getPath('userData'), 'config.json')
    try {
        const raw = await readFile(configPath, 'utf-8')
        const parsed = JSON.parse(raw) as RuntimeConfigPayload
        return parsed
    } catch {
        return null
    }
}

async function fetchRemoteConfig(
    bootstrapUrl: string
): Promise<RuntimeConfigPayload | null> {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
        const response = await fetch(bootstrapUrl, {
            method: 'GET',
            headers: { Accept: 'application/json' },
            signal: controller.signal,
        })
        if (!response.ok) return null
        const parsed = (await response.json()) as RuntimeConfigPayload
        return parsed
    } catch {
        return null
    } finally {
        clearTimeout(timeout)
    }
}

function hasRuntimeChanged(a: RuntimeConfig, b: RuntimeConfig): boolean {
    return (
        a.apiBaseUrl !== b.apiBaseUrl ||
        a.wsUrl !== b.wsUrl ||
        a.bootstrapUrl !== b.bootstrapUrl ||
        a.refreshIntervalSec !== b.refreshIntervalSec
    )
}

export function getRuntimeConfig(): RuntimeConfig {
    return runtimeConfig
}

export function getCspConnectSources(): string[] {
    const apiOrigin = new URL(runtimeConfig.apiBaseUrl).origin
    const wsOrigin = new URL(runtimeConfig.wsUrl).origin
    return Array.from(
        new Set([
            "'self'",
            apiOrigin,
            wsOrigin,
            'http://localhost:8080',
            'ws://localhost:8080',
            'http://192.168.184.72',
            'ws://192.168.184.72',
        ])
    )
}

export async function refreshRuntimeConfig(): Promise<{
    changed: boolean
    config: RuntimeConfig
}> {
    let next: RuntimeConfig = {
        ...runtimeConfig,
        source: 'default',
        updatedAt: new Date().toISOString(),
    }

    const localPayload = await readLocalConfigFile()
    if (localPayload) {
        next = withPatch(next, localPayload, 'local-file')
    }

    const remotePayload = await fetchRemoteConfig(next.bootstrapUrl)
    if (remotePayload) {
        next = withPatch(next, remotePayload, 'remote-bootstrap')
    }

    const changed = hasRuntimeChanged(runtimeConfig, next)
    runtimeConfig = next

    if (changed) {
        logger.info(
            `[RuntimeConfig] Updated (${next.source}) api=${next.apiBaseUrl} ws=${next.wsUrl} refresh=${next.refreshIntervalSec}s`
        )
    }

    return { changed, config: runtimeConfig }
}
