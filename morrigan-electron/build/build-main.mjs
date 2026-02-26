/**
 * build-main.mjs — Bundle del main process y preload con esbuild
 *
 * Reemplaza la compilación TSC pura por un bundle con esbuild.
 * Ventajas:
 *   - Los módulos de npm (electron-log, electron-updater, axios, zod…) se
 *     inlinan en un único archivo, eliminando la carpeta node_modules del asar.
 *   - app.asar pasa de ~12 MB a ~1-2 MB.
 *   - El tree-shaking elimina rutas de código muertas.
 *
 * Módulos marcados como external:
 *   - 'electron'          → runtime del host, no se puede bundlear
 *   - 'electron-updater'  → usa __dirname internamente y carga DLLs nativos
 *   - 'electron-log'      → escribe a disco en rutas calculadas en runtime
 *
 * Uso:
 *   node build/build-main.mjs
 *   (invocado desde el script npm run build:electron)
 */

import * as esbuild from 'esbuild'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = resolve(__dirname, '..')

/** @type {import('esbuild').BuildOptions} */
const sharedOptions = {
    bundle: true,
    platform: 'node',
    target: 'node20',
    format: 'cjs',
    sourcemap: true,
    minify: false,            // Mantener legible para depuración — el asar ya comprime
    treeShaking: true,
    // Módulos que Electron provee en runtime — NO bundlear
    external: [
        'electron',
        'electron-updater',   // Carga plugins nativos (.node) en runtime
        'electron-log',       // Escribe a AppData — necesita paths de runtime
    ],
    define: {
        'process.env.NODE_ENV': '"production"',
    },
}

async function build() {
    console.log('► Bundling main process...')
    await esbuild.build({
        ...sharedOptions,
        entryPoints: [resolve(root, 'src/main/index.ts')],
        outfile: resolve(root, 'dist/main/index.js'),
        // Alias para que los imports relativos de los servicios funcionen
        // dentro del bundle único
    })
    console.log('  ✓ dist/main/index.js')

    // Notification preload (JS puro, sin TypeScript)
    await esbuild.build({
        ...sharedOptions,
        entryPoints: [resolve(root, 'src/main/notification-preload.js')],
        outfile: resolve(root, 'dist/main/notification-preload.js'),
    })
    console.log('  ✓ dist/main/notification-preload.js')

    console.log('► Bundling preload...')
    await esbuild.build({
        ...sharedOptions,
        entryPoints: [resolve(root, 'src/preload/index.ts')],
        outfile: resolve(root, 'dist/preload/index.js'),
        // El preload se ejecuta en un contexto híbrido Node+Browser
        platform: 'node',
    })
    console.log('  ✓ dist/preload/index.js')

    console.log('\n✓ Build completado\n')
}

build().catch((err) => {
    console.error('✗ Build fallido:', err)
    process.exit(1)
})
