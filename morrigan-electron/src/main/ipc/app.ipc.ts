import { ipcMain, app } from 'electron'
import { getRuntimeConfig } from '../services/runtime-config'

/**
 * IPC handlers de nivel de aplicación
 */
export function registerAppIpc(): void {
    ipcMain.handle('app:getVersion', () => {
        return app.getVersion()
    })

    ipcMain.handle('app:getName', () => {
        return app.getName()
    })

    ipcMain.handle('config:getRuntime', () => {
        return getRuntimeConfig()
    })
}
