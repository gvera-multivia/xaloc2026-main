import { BrowserWindow, screen, ipcMain, app, Notification } from 'electron'
import * as path from 'path'
import logger from './services/logger'

const TOAST_WIDTH = 400
const TOAST_HEIGHT = 110

let activeToast: BrowserWindow | null = null

function parseBoolEnv(value: string | undefined, fallback = true): boolean {
    if (value === undefined) return fallback
    const normalized = String(value).trim().toLowerCase()
    return normalized === '1' || normalized === 'true' || normalized === 'yes' || normalized === 'on'
}

export function showSystemNotification(opts: { title: string; body: string }): void {
    const enabled = parseBoolEnv(process.env.MORRIGAN_SYSTEM_NOTIFICATIONS, true)
    if (!enabled) {
        return
    }
    if (!Notification.isSupported()) {
        return
    }
    try {
        const notif = new Notification({
            title: opts.title,
            body: opts.body,
            silent: false,
        })
        notif.show()
    } catch (err) {
        logger.debug(`[Notification] No se pudo mostrar notificacion nativa: ${String(err)}`)
    }
}

/**
 * Muestra una notificación overlay personalizada tipo antivirus.
 * - Siempre por encima de todas las ventanas
 * - Sin barra de título ni bordes
 * - Transparente / glassmorphism
 * - No roba el foco del usuario
 * - Se auto-cierra a los `duration` ms y emite una animación de salida antes
 */
export function showOverlayNotification(opts: {
    title: string
    body: string
    duration?: number  // ms, default 6000
    type?: string | { type?: string; design_code?: string }
    persistToSystem?: boolean
}) {
    let { title, body, duration = 6000, type, persistToSystem = false } = opts
    let design_code: string | undefined

    if (type && typeof type === 'object') {
        design_code = type.design_code
        type = type.type || 'default'
    }

    // Si ya hay una activa, cerrarla antes de mostrar la nueva
    if (activeToast && !activeToast.isDestroyed()) {
        activeToast.destroy()
        activeToast = null
    }

    const { workArea } = screen.getPrimaryDisplay()
    const margin = 16
    const currentHeight = type === 'red-large' ? TOAST_HEIGHT + 30 : TOAST_HEIGHT
    const x = workArea.x + workArea.width - TOAST_WIDTH - margin
    const y = workArea.y + workArea.height - currentHeight - margin

    // En dev __dirname = dist/main pero el HTML está en src/main (tsc no copia assets)
    // En prod el HTML debe estar junto al JS compilado
    const isDev = !app.isPackaged
    const assetsDir = isDev
        ? path.join(__dirname, '../../src/main')
        : __dirname

    const toast = new BrowserWindow({
        x,
        y,
        width: TOAST_WIDTH,
        height: currentHeight,
        frame: false,
        transparent: true,
        resizable: false,
        movable: false,
        minimizable: false,
        maximizable: false,
        skipTaskbar: true,
        focusable: false,
        alwaysOnTop: true,
        type: 'toolbar',
        webPreferences: {
            contextIsolation: true,
            nodeIntegration: false,
            preload: path.join(assetsDir, 'notification-preload.js'),
        }
    })

    // Siempre por encima (nivel screen-saver, igual que antivirus)
    toast.setAlwaysOnTop(true, 'screen-saver')
    toast.setVisibleOnAllWorkspaces(true)

    activeToast = toast
    let persisted = false

    const persistOnce = () => {
        if (!persistToSystem || persisted) return
        persisted = true
        showSystemNotification({ title, body })
    }

    const htmlPath = path.join(assetsDir, 'notification.html')
    toast.loadFile(htmlPath)
    toast.webContents.on('did-fail-load', (_event, code, description) => {
        logger.error(`[Notification] did-fail-load code=${code} reason=${description} file=${htmlPath}`)
    })

    // Cuando el HTML esté listo, enviarle los datos
    toast.webContents.on('did-finish-load', () => {
        if (toast.isDestroyed()) return
        toast.webContents.send('notification:data', { title, body, duration, type, design_code })

        // Auto-destruir después de la duración + animación de salida (350ms)
        setTimeout(() => {
            persistOnce()
            if (!toast.isDestroyed()) toast.destroy()
            if (activeToast === toast) activeToast = null
        }, duration + 400)
    })

    // El usuario puede cerrarlo manualmente antes
    ipcMain.once('notification:close', () => {
        persistOnce()
        if (!toast.isDestroyed()) toast.destroy()
        if (activeToast === toast) activeToast = null
    })
}
