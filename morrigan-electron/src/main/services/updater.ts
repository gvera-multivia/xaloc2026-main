import { app, BrowserWindow, ipcMain } from 'electron'
import { autoUpdater, type UpdateInfo } from 'electron-updater'
import logger from './logger'

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

    logger.info('[Updater] Instalacion inmediata solicitada por el renderer')
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
    if (isInitialized) {
        return
    }
    isInitialized = true
    registerIpcHandlers()

    state.currentVersion = app.getVersion()
    const testMode = parseBoolEnv(process.env.MORRIGAN_UPDATER_TEST_MODE)
    const allowUpdater = app.isPackaged || testMode

    if (!allowUpdater) {
        logger.info('[Updater] Modo desarrollo - auto-updater desactivado (habilita MORRIGAN_UPDATER_TEST_MODE=1 para pruebas)')
        setDisabled('Auto-updater desactivado en desarrollo (usa MORRIGAN_UPDATER_TEST_MODE=1)')
        return
    }

    const updateUrl = process.env.MORRIGAN_UPDATE_URL?.trim()
    if (!updateUrl) {
        logger.warn('[Updater] MORRIGAN_UPDATE_URL no configurada - updater desactivado')
        setDisabled('MORRIGAN_UPDATE_URL no configurada')
        return
    }

    autoUpdater.logger = logger
    autoUpdater.autoDownload = true
    autoUpdater.autoInstallOnAppQuit = true
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
