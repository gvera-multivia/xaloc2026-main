import {
    app,
    BrowserWindow,
    shell,
    ipcMain,
    Tray,
    Menu,
    nativeImage,
} from 'electron'
import * as path from 'path'
import { createMainWindow } from './window'
import { registerAppIpc } from './ipc/app.ipc'
import { registerShellIpc } from './ipc/shell.ipc'
import logger from './services/logger'
import { iconBase64 } from './icon-base64'
import { showOverlayNotification } from './notification-window'
import {
    getCspConnectSources,
    getRuntimeConfig,
    refreshRuntimeConfig,
} from './services/runtime-config'
import { initUpdater } from './services/updater'

const isDev = !app.isPackaged

// Prevent multiple instances.
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
    app.quit()
}

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let runtimeRefreshTimer: NodeJS.Timeout | null = null

// True quit vs. hide-to-tray.
let isQuiting = false

function broadcastRuntimeConfig(): void {
    const config = getRuntimeConfig()
    BrowserWindow.getAllWindows().forEach((win) => {
        if (!win.isDestroyed()) {
            win.webContents.send('morrigan:runtime-config-updated', config)
        }
    })
}

function restartRuntimeRefreshLoop(): void {
    if (runtimeRefreshTimer) {
        clearInterval(runtimeRefreshTimer)
        runtimeRefreshTimer = null
    }

    const intervalMs = getRuntimeConfig().refreshIntervalSec * 1000
    runtimeRefreshTimer = setInterval(async () => {
        const { changed } = await refreshRuntimeConfig()
        if (changed) {
            broadcastRuntimeConfig()
            restartRuntimeRefreshLoop()
        }
    }, intervalMs)
}

app.on('ready', async () => {
    // Improves Windows native toast routing to Action Center for packaged app.
    if (process.platform === 'win32') {
        app.setAppUserModelId('com.xaloc.morrigan')
    }

    await refreshRuntimeConfig()

    logger.info('[Main] App ready, creating window (hidden)')

    // Avoid auto-start side effects while developing/testing updater flows.
    if (app.isPackaged) {
        app.setLoginItemSettings({
            openAtLogin: true,
            openAsHidden: true,
        })
    }

    mainWindow = createMainWindow(isDev, getCspConnectSources)

    registerAppIpc()
    registerShellIpc()
    initUpdater()

    mainWindow.on('close', (event) => {
        if (!isQuiting) {
            event.preventDefault()
            mainWindow?.hide()
        }
    })

    if (isDev) {
        mainWindow.loadURL('http://localhost:5173')
    } else {
        mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
    }

    // Tray setup.
    const iconBuffer = Buffer.from(iconBase64, 'base64')
    const icon = nativeImage.createFromBuffer(iconBuffer)

    const trayIcon = icon.resize({ width: 16, height: 16 })
    tray = new Tray(trayIcon)
    const contextMenu = Menu.buildFromTemplate([
        { label: 'Morrigan Notificator', enabled: false },
        { type: 'separator' },
        {
            label: 'Mostrar ventana',
            click: () => {
                mainWindow?.show()
                mainWindow?.focus()
            },
        },
        {
            label: 'Cerrar Sesion',
            click: () => {
                mainWindow?.show()
                mainWindow?.focus()
                mainWindow?.webContents.send('morrigan:force-logout')
            },
        },
        { type: 'separator' },
        {
            label: 'Salir',
            click: () => {
                isQuiting = true
                app.quit()
            },
        },
    ])
    tray.setToolTip('Morrigan Xaloc')
    tray.setContextMenu(contextMenu)

    tray.on('double-click', () => {
        if (mainWindow?.isVisible()) {
            mainWindow?.hide()
        } else {
            mainWindow?.show()
            mainWindow?.focus()
        }
    })

    ipcMain.on('renderer:login-status', (_event, isLoggedIn: boolean) => {
        if (isLoggedIn) {
            mainWindow?.hide()
            logger.info('[Main] User is logged in, hiding window to background')
        } else {
            mainWindow?.show()
            logger.info('[Main] User not logged in, forcing window check login')
        }
    })

    ipcMain.on('renderer:login-success', () => {
        mainWindow?.hide()
        logger.info('[Main] Login success event received, hiding window')
    })

    ipcMain.on('renderer:logout', () => {
        mainWindow?.show()
        mainWindow?.focus()
        logger.info('[Main] Logout event received, showing login window')
    })

    ipcMain.on(
        'renderer:notify',
        (
            _event,
            { title, body, duration, type }: { title: string; body: string; duration?: number; type?: string }
        ) => {
            logger.info(`[Main] Showing unified notification: ${title} (Type: ${type || 'default'})`)
            showOverlayNotification({
                title,
                body,
                duration: duration ?? 7000,
                type,
                persistToSystem: true,
            })
        }
    )

    mainWindow.webContents.on('will-navigate', (event, url) => {
        const allowed = isDev
            ? ['http://localhost:5173', getRuntimeConfig().apiBaseUrl]
            : ['app://.']
        const isAllowed = allowed.some((origin) => url.startsWith(origin))
        if (!isAllowed) {
            logger.warn(`[Main] Blocked navigation to: ${url}`)
            event.preventDefault()
        }
    })

    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        const ALLOWED_EXTERNAL = ['https://']
        if (ALLOWED_EXTERNAL.some((prefix) => url.startsWith(prefix))) {
            shell.openExternal(url)
        }
        return { action: 'deny' }
    })

    broadcastRuntimeConfig()
    restartRuntimeRefreshLoop()
})

app.on('before-quit', () => {
    isQuiting = true
    if (runtimeRefreshTimer) {
        clearInterval(runtimeRefreshTimer)
        runtimeRefreshTimer = null
    }
})

// Fired by electron-updater when quitAndInstall() starts update shutdown.
;(app as any).on('before-quit-for-update', () => {
    isQuiting = true
})

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        // Keep in tray.
    }
})

app.on('second-instance', () => {
    if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.show()
        mainWindow.focus()
    }
})
