import { BrowserWindow, session } from 'electron'
import * as path from 'path'
import { applyCSP } from './security/csp'

export function createMainWindow(
    isDev: boolean,
    getConnectSources: () => string[]
): BrowserWindow {
    const win = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        backgroundColor: '#0a0a0c',
        titleBarStyle: 'hidden',
        titleBarOverlay: {
            color: '#0a0a0c',
            symbolColor: '#7c3aed',
            height: 32,
        },
        webPreferences: {
            preload: path.join(__dirname, '../preload/index.js'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
            webSecurity: true,
            allowRunningInsecureContent: false,
        },
        show: false,
    })

    // Keep hidden by default. Tray actions control visibility.
    win.once('ready-to-show', () => {
        // win.show()
    })

    if (!isDev) {
        applyCSP(session.defaultSession, getConnectSources)
    }

    return win
}
