'use strict'

const fs = require('fs')
const path = require('path')

const PRUNE_BINARIES = [
    'vk_swiftshader.dll',
    'vk_swiftshader_icd.json',
    'libGLESv2.dll',
    'libEGL.dll',
]

const ALLOWED_LOCALES = new Set(['en-US.pak', 'es.pak'])

/**
 * @param {import('electron-builder').AfterPackContext} context
 */
exports.default = async function afterPack(context) {
    const appOutDir = context.appOutDir

    console.log('\n--- Morrigan afterPack: pruning de binarios Chromium ---')

    let prunedCount = 0
    for (const file of PRUNE_BINARIES) {
        const fullPath = path.join(appOutDir, file)
        if (!fs.existsSync(fullPath)) {
            continue
        }
        try {
            fs.unlinkSync(fullPath)
            console.log(`  [ok] Prunado: ${file}`)
            prunedCount++
        } catch (err) {
            // No-fatal: no romper el build por una limpieza opcional.
            console.warn(`  [warn] No se pudo eliminar ${file}: ${err.message}`)
        }
    }

    if (prunedCount === 0) {
        console.log('  (no se encontraron binarios a eliminar)')
    }

    const localesDir = path.join(appOutDir, 'locales')
    if (fs.existsSync(localesDir)) {
        const allLocales = fs.readdirSync(localesDir)
        let localesPruned = 0

        for (const file of allLocales) {
            if (ALLOWED_LOCALES.has(file)) {
                continue
            }
            try {
                fs.unlinkSync(path.join(localesDir, file))
                localesPruned++
            } catch (err) {
                console.warn(`  [warn] No se pudo eliminar locale ${file}: ${err.message}`)
            }
        }

        if (localesPruned > 0) {
            console.log(`  [ok] Locales eliminados: ${localesPruned} archivos .pak`)
        } else {
            console.log('  [ok] Locales: solo en-US.pak y es.pak presentes')
        }
    }

    try {
        const totalBytes = getDirSize(appOutDir)
        const totalMb = (totalBytes / 1024 / 1024).toFixed(2)
        console.log(`\n  Tamano final win-unpacked: ${totalMb} MB`)
    } catch {
        // No-fatal
    }

    console.log('--- afterPack completado ---\n')
}

function getDirSize(dirPath) {
    let total = 0
    for (const entry of fs.readdirSync(dirPath, { withFileTypes: true })) {
        const entryPath = path.join(dirPath, entry.name)
        if (entry.isDirectory()) {
            total += getDirSize(entryPath)
        } else if (entry.isFile()) {
            try {
                total += fs.statSync(entryPath).size
            } catch {
                // Ignora archivos no accesibles.
            }
        }
    }
    return total
}
