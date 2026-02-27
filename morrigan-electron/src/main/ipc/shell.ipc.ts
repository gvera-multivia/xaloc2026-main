import { ipcMain, shell } from 'electron'
import * as path from 'path'
import * as os from 'os'

// Rutas base permitidas para apertura de archivos
const ALLOWED_BASE_PATHS = [
    os.homedir(),
    os.tmpdir(),
]

function isPathAllowed(filePath: string): boolean {
    const normalized = path.normalize(filePath)
    return ALLOWED_BASE_PATHS.some((base) =>
        normalized.startsWith(path.normalize(base))
    )
}

/**
 * IPC handlers de filesystem/shell controlado
 */
export function registerShellIpc(): void {
    ipcMain.handle('shell:openPath', async (_event, filePath: string) => {
        if (!isPathAllowed(filePath)) {
            return { success: false, error: 'Ruta no permitida' }
        }
        const result = await shell.openPath(filePath)
        return { success: result === '', error: result || undefined }
    })
}
