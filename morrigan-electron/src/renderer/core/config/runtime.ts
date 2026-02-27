import { apiClient } from '@/core/api/client'
import { morriganWs } from '@/core/api/ws'
import { ENV } from '@/core/config/env'

export interface RuntimeConfig {
    apiBaseUrl: string
    wsUrl: string
    bootstrapUrl: string
    refreshIntervalSec: number
    source: 'default' | 'local-file' | 'remote-bootstrap'
    updatedAt: string
}

let currentRuntime: RuntimeConfig = {
    apiBaseUrl: ENV.API_BASE_URL,
    wsUrl: ENV.WS_URL,
    bootstrapUrl: ENV.BOOTSTRAP_URL,
    refreshIntervalSec: ENV.CONFIG_REFRESH_SEC,
    source: 'default',
    updatedAt: new Date().toISOString(),
}

function normalizeRuntime(config: RuntimeConfig): RuntimeConfig {
    return {
        ...config,
        apiBaseUrl: config.apiBaseUrl.replace(/\/$/, ''),
        wsUrl: config.wsUrl.replace(/\/$/, ''),
        bootstrapUrl: config.bootstrapUrl.replace(/\/$/, ''),
    }
}

export function getRuntimeConfig(): RuntimeConfig {
    return currentRuntime
}

export function applyRuntimeConfig(config: RuntimeConfig): void {
    const next = normalizeRuntime(config)
    const wsChanged = currentRuntime.wsUrl !== next.wsUrl
    currentRuntime = next

    apiClient.defaults.baseURL = next.apiBaseUrl

    if (wsChanged) {
        morriganWs.setUrl(next.wsUrl)
    }
}

export async function initRuntimeConfig(): Promise<RuntimeConfig> {
    const runtime = await window.morrigan.config.getRuntimeConfig()
    applyRuntimeConfig(runtime)
    window.morrigan.config.onRuntimeConfigUpdated((updated) => {
        applyRuntimeConfig(updated)
    })
    return getRuntimeConfig()
}
