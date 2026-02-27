import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { autoUpdater, type UpdateInfo } from 'electron-updater'
import logger from './logger'
import { loadMainEnv } from './env-loader'
import { getRuntimeConfig } from './runtime-config'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

type UpdaterStage =
    | 'disabled'
    | 'idle'
    | 'checking'
    | 'available'
    | 'not-available'
    | 'downloading'
    | 'downloaded'
    | 'error'

interface UpdaterState {
    enabled: boolean
    stage: UpdaterStage
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

let isInitialized = false
let checkInFlight = false
let isDevTestMode = false

const state: UpdaterState = {
    enabled: false,
    stage: 'idle',
    currentVersion: app.getVersion(),
}

function snapshotState(): UpdaterState {
    return { ...state }
}

function setState(patch: Partial<UpdaterState>): void {
    Object.assign(state, patch)
    broadcastToAllWindows('morrigan:update-status', snapshotState())
}

function setDisabled(message: string): void {
    setState({
        enabled: false,
        stage: 'disabled',
        message,
    })
}

function parseBoolEnv(value: string | undefined): boolean {
    const normalized = String(value || '').trim().toLowerCase()
    return normalized === '1' || normalized === 'true' || normalized === 'yes' || normalized === 'on'
}

function sanitizeHttpUrl(value: string | undefined): string | null {
    const raw = String(value || '').trim()
    if (!raw) return null
    try {
        const parsed = new URL(raw)
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
            return null
        }
        return parsed.toString().replace(/\/$/, '')
    } catch {
        return null
    }
}

function resolveUpdateUrl(): string | null {
    const explicitUrl = sanitizeHttpUrl(process.env.MORRIGAN_UPDATE_URL)
    if (explicitUrl) {
        return explicitUrl
    }

    const envApiBase = sanitizeHttpUrl(process.env.MORRIGAN_API_BASE_URL)
    if (envApiBase) {
        return `${envApiBase}/updates`
    }

    const runtimeApiBase = sanitizeHttpUrl(getRuntimeConfig().apiBaseUrl)
    if (runtimeApiBase) {
        return `${runtimeApiBase}/updates`
    }

    return null
}

function findLatestPendingInstaller(cacheDirName: string): string | null {
    const localAppData =
        process.env.LOCALAPPDATA?.trim() ||
        path.join(os.homedir(), 'AppData', 'Local')
    const pendingDir = path.join(localAppData, cacheDirName, 'pending')
    if (!fs.existsSync(pendingDir)) {
        return null
    }
    const candidates = fs
        .readdirSync(pendingDir)
        .filter((name) => name.toLowerCase().endsWith('.exe'))
        .map((name) => path.join(pendingDir, name))
        .filter((fullPath) => {
            try {
                return fs.statSync(fullPath).isFile()
            } catch {
                return false
            }
        })
    if (candidates.length === 0) {
        return null
    }
    candidates.sort((a, b) => {
        const aTime = fs.statSync(a).mtimeMs
        const bTime = fs.statSync(b).mtimeMs
        return bTime - aTime
    })
    return candidates[0]
}

async function checkForUpdatesNow(): Promise<{ ok: boolean; reason?: string }> {
    if (!state.enabled) {
        return { ok: false, reason: state.message || 'updater_disabled' }
    }
    if (checkInFlight) {
        return { ok: false, reason: 'check_in_flight' }
    }

    checkInFlight = true
    setState({
        stage: 'checking',
        lastCheckedAt: new Date().toISOString(),
        lastError: undefined,
        message: 'Comprobando actualizaciones...',
    })

    try {
        await autoUpdater.checkForUpdates()
        return { ok: true }
    } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        logger.warn(`[Updater] checkForUpdates fallo: ${message}`)
        setState({
            stage: 'error',
            lastError: message,
            message: 'Error comprobando actualizaciones',
        })
        return { ok: false, reason: message }
    } finally {
        checkInFlight = false
    }
}

function installNow(): { ok: boolean; reason?: string } {
    if (!state.enabled) {
        return { ok: false, reason: state.message || 'updater_disabled' }
    }
    if (state.stage !== 'downloaded') {
        return { ok: false, reason: 'update_not_downloaded' }
    }

    if (isDevTestMode && !app.isPackaged) {
        const installerPath = findLatestPendingInstaller('morrigan-updater-dev')
        if (!installerPath) {
            return { ok: false, reason: 'pending_installer_not_found' }
        }
        logger.info(`[Updater] Dev test mode install requested. Launching installer: ${installerPath}`)
        // shell.openPath triggers normal shell execution; empty string means success.
        void shell.openPath(installerPath).then((errorMessage) => {
            if (errorMessage) {
                logger.error(`[Updater] No se pudo abrir instalador en dev test mode: ${errorMessage}`)
                return
            }
            setTimeout(() => app.quit(), 300)
        })
        return { ok: true }
    }

    logger.info('[Updater] Instalacion inmediata solicitada por el renderer')
    // Silent install avoids leaving a hidden installer wizard and force-run
    // guarantees reopening Morrigan after update is applied.
    autoUpdater.quitAndInstall(true, true)
    return { ok: true }
}

function registerIpcHandlers(): void {
    ipcMain.removeHandler('updater:get-state')
    ipcMain.removeHandler('updater:check-now')
    ipcMain.removeHandler('updater:install-now')

    ipcMain.handle('updater:get-state', () => snapshotState())
    ipcMain.handle('updater:check-now', () => checkForUpdatesNow())
    ipcMain.handle('updater:install-now', () => installNow())
}

/**
 * Inicializa el auto-updater para builds empaquetadas.
 */
export function initUpdater(): void {
    loadMainEnv()

    if (isInitialized) {
        return
    }
    isInitialized = true
    registerIpcHandlers()

    state.currentVersion = app.getVersion()
    const testMode = parseBoolEnv(process.env.MORRIGAN_UPDATER_TEST_MODE)
    isDevTestMode = testMode
    const allowUpdater = app.isPackaged || testMode

    if (!allowUpdater) {
        logger.info('[Updater] Modo desarrollo - auto-updater desactivado (habilita MORRIGAN_UPDATER_TEST_MODE=1 para pruebas)')
        setDisabled('Auto-updater desactivado en desarrollo (usa MORRIGAN_UPDATER_TEST_MODE=1)')
        return
    }

    const updateUrl = resolveUpdateUrl()
    if (!updateUrl) {
        logger.warn('[Updater] URL de actualizacion no configurada (MORRIGAN_UPDATE_URL / MORRIGAN_API_BASE_URL)')
        setDisabled('URL de actualizacion no configurada')
        return
    }

    autoUpdater.logger = logger
    autoUpdater.autoDownload = true
    autoUpdater.autoInstallOnAppQuit = true
    autoUpdater.disableWebInstaller = true
    // Permite probar updater en dev con dev-app-update.yml.
    autoUpdater.forceDevUpdateConfig = !app.isPackaged && testMode
    autoUpdater.setFeedURL({
        provider: 'generic',
        url: updateUrl,
    })

    setState({
        enabled: true,
        stage: 'idle',
        updateUrl,
        message: testMode && !app.isPackaged
            ? 'Updater inicializado en modo prueba'
            : 'Updater inicializado',
    })

    autoUpdater.on('checking-for-update', () => {
        logger.info(`[Updater] Comprobando actualizaciones en ${updateUrl}`)
        setState({
            stage: 'checking',
            lastCheckedAt: new Date().toISOString(),
            message: 'Comprobando actualizaciones...',
            lastError: undefined,
        })
    })

    autoUpdater.on('update-available', (info: UpdateInfo) => {
        logger.info(`[Updater] Actualizacion disponible: v${info.version}`)
        setState({
            stage: 'available',
            availableVersion: info.version,
            releaseDate: info.releaseDate,
            progressPercent: 0,
            message: `Actualizacion disponible: v${info.version}`,
        })
        broadcastToAllWindows('morrigan:update-available', {
            version: info.version,
            releaseDate: info.releaseDate,
        })
    })

    autoUpdater.on('update-not-available', (info: UpdateInfo) => {
        logger.info(`[Updater] Sin actualizaciones - version actual: v${info.version}`)
        setState({
            stage: 'not-available',
            message: `Sin actualizaciones (v${info.version})`,
            progressPercent: undefined,
        })
    })

    autoUpdater.on('download-progress', (progress) => {
        const percent = Math.max(0, Math.min(100, Math.round(progress.percent)))
        setState({
            stage: 'downloading',
            progressPercent: percent,
            message: `Descargando actualizacion... ${percent}%`,
        })
        broadcastToAllWindows('morrigan:update-download-progress', { percent })
    })

    autoUpdater.on('update-downloaded', (info: UpdateInfo) => {
        logger.info(`[Updater] Descarga completada - v${info.version} lista para instalar`)
        setState({
            stage: 'downloaded',
            downloadedVersion: info.version,
            availableVersion: info.version,
            progressPercent: 100,
            message: `Actualizacion v${info.version} lista para instalar`,
        })
        broadcastToAllWindows('morrigan:update-downloaded', {
            version: info.version,
        })
    })

    autoUpdater.on('error', (err) => {
        const message = err?.message || String(err)
        logger.error(`[Updater] Error: ${message}`)
        setState({
            stage: 'error',
            lastError: message,
            message: 'Error en el proceso de actualizacion',
        })
    })

    setTimeout(() => {
        void checkForUpdatesNow()
    }, 10_000)

    logger.info(`[Updater] Inicializado - canal: ${updateUrl}`)
}

function broadcastToAllWindows(channel: string, payload: unknown): void {
    BrowserWindow.getAllWindows().forEach((win) => {
        if (!win.isDestroyed()) {
            win.webContents.send(channel, payload)
        }
    })
}
