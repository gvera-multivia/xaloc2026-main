import { BrowserWindow, screen, ipcMain, app } from 'electron'
import * as path from 'path'

const TOAST_WIDTH = 400
const TOAST_HEIGHT = 110

let activeToast: BrowserWindow | null = null

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
    type?: string
}) {
    const { title, body, duration = 6000, type } = opts

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

    const htmlPath = path.join(assetsDir, 'notification.html')
    toast.loadFile(htmlPath)

    // Cuando el HTML esté listo, enviarle los datos
    toast.webContents.on('did-finish-load', () => {
        if (toast.isDestroyed()) return
        toast.webContents.send('notification:data', { title, body, duration, type })

        // Auto-destruir después de la duración + animación de salida (350ms)
        setTimeout(() => {
            if (!toast.isDestroyed()) toast.destroy()
            if (activeToast === toast) activeToast = null
        }, duration + 400)
    })

    // El usuario puede cerrarlo manualmente antes
    ipcMain.once('notification:close', () => {
        if (!toast.isDestroyed()) toast.destroy()
        if (activeToast === toast) activeToast = null
    })
}
