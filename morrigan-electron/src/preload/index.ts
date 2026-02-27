import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('morrigan', {
    app: {
        getVersion: (): Promise<string> =>
            ipcRenderer.invoke('app:getVersion'),
        getName: (): Promise<string> =>
            ipcRenderer.invoke('app:getName'),
    },
    shell: {
        openPath: (filePath: string): Promise<{ success: boolean; error?: string }> =>
            ipcRenderer.invoke('shell:openPath', filePath),
    },
    diag: {
        getRuntimeInfo: () => ({
            platform: process.platform,
            arch: process.arch,
            versions: process.versions,
        }),
    },
    config: {
        getRuntimeConfig: () => ipcRenderer.invoke('config:getRuntime'),
        onRuntimeConfigUpdated: (
            callback: (config: {
                apiBaseUrl: string
                wsUrl: string
                bootstrapUrl: string
                refreshIntervalSec: number
                source: 'default' | 'local-file' | 'remote-bootstrap'
                updatedAt: string
            }) => void
        ): (() => void) => {
            const listener = (_event: Electron.IpcRendererEvent, config: unknown) =>
                callback(config as {
                    apiBaseUrl: string
                    wsUrl: string
                    bootstrapUrl: string
                    refreshIntervalSec: number
                    source: 'default' | 'local-file' | 'remote-bootstrap'
                    updatedAt: string
                })
            ipcRenderer.on('morrigan:runtime-config-updated', listener)
            return () => {
                ipcRenderer.removeListener('morrigan:runtime-config-updated', listener)
            }
        },
    },
    auth: {
        notifyLoginStatus: (isLoggedIn: boolean) => ipcRenderer.send('renderer:login-status', isLoggedIn),
        notifyLoginSuccess: () => ipcRenderer.send('renderer:login-success'),
        notifyLogout: () => ipcRenderer.send('renderer:logout'),
        notify: (title: string, body: string, type?: string | { type?: string; design_code?: string }) => ipcRenderer.send('renderer:notify', { title, body, type }),
        onForceLogout: (callback: () => void): (() => void) => {
            const listener = () => callback()
            ipcRenderer.on('morrigan:force-logout', listener)
            return () => {
                ipcRenderer.removeListener('morrigan:force-logout', listener)
            }
        }
    },
    updater: {
        getState: () => ipcRenderer.invoke('updater:get-state'),
        checkNow: () => ipcRenderer.invoke('updater:check-now'),
        installNow: () => ipcRenderer.invoke('updater:install-now'),
        onStatusChange: (
            callback: (status: {
                enabled: boolean
                stage: 'disabled' | 'idle' | 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'
                updateUrl?: string
                currentVersion: string
                availableVersion?: string
                downloadedVersion?: string
                releaseDate?: string
                progressPercent?: number
                lastCheckedAt?: string
                lastError?: string
                message?: string
            }) => void
        ): (() => void) => {
            const listener = (_event: Electron.IpcRendererEvent, status: unknown) =>
                callback(status as {
                    enabled: boolean
                    stage: 'disabled' | 'idle' | 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'
                    updateUrl?: string
                    currentVersion: string
                    availableVersion?: string
                    downloadedVersion?: string
                    releaseDate?: string
                    progressPercent?: number
                    lastCheckedAt?: string
                    lastError?: string
                    message?: string
                })
            ipcRenderer.on('morrigan:update-status', listener)
            return () => {
                ipcRenderer.removeListener('morrigan:update-status', listener)
            }
        },
    }
})
