export interface MorriganDiagInfo {
    platform: string
    arch: string
    versions: Record<string, string>
}

export interface MorriganRuntimeConfig {
    apiBaseUrl: string
    wsUrl: string
    bootstrapUrl: string
    refreshIntervalSec: number
    source: 'default' | 'local-file' | 'remote-bootstrap'
    updatedAt: string
}

export type MorriganUpdaterStage =
    | 'disabled'
    | 'idle'
    | 'checking'
    | 'available'
    | 'not-available'
    | 'downloading'
    | 'downloaded'
    | 'error'

export interface MorriganUpdaterState {
    enabled: boolean
    stage: MorriganUpdaterStage
    updateUrl?: string
    currentVersion: string
    availableVersion?: string
    downloadedVersion?: string
    releaseDate?: string
    progressPercent?: number
    lastCheckedAt?: string
    lastError?: string
    message?: string
}

export interface MorriganAPI {
    app: {
        getVersion(): Promise<string>
        getName(): Promise<string>
    }
    shell: {
        openPath(filePath: string): Promise<{ success: boolean; error?: string }>
    }
    diag: {
        getRuntimeInfo(): MorriganDiagInfo
    }
    config: {
        getRuntimeConfig(): Promise<MorriganRuntimeConfig>
        onRuntimeConfigUpdated(callback: (config: MorriganRuntimeConfig) => void): () => void
    }
    auth: {
        notifyLoginStatus(isLoggedIn: boolean): void
        notifyLoginSuccess(): void
        notifyLogout(): void
        notify(title: string, body: string, type?: string): void
        onForceLogout(callback: () => void): () => void
    }
    updater: {
        getState(): Promise<MorriganUpdaterState>
        checkNow(): Promise<{ ok: boolean; reason?: string }>
        installNow(): Promise<{ ok: boolean; reason?: string }>
        onStatusChange(callback: (status: MorriganUpdaterState) => void): () => void
    }
}

declare global {
    interface Window {
        morrigan: MorriganAPI
    }
}
