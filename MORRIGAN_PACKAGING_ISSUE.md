# Morrigan Electron - Estado, Objetivo y Error Recurrente

## 1. Qué tenemos ahora

- Proyecto Electron en `morrigan-electron/` con build de renderer y main funcionando.
- Comandos que sí terminan bien:
  - `npm run build:renderer`
  - `npm run build:electron`
- Se genera `dist/renderer/*` y `dist/main/*` correctamente.
- El problema aparece en `electron-builder` durante `npm run dist`.

## 2. Qué queremos conseguir

- Generar instalador Windows (`NSIS`) de Morrigan (`.exe`) de forma estable.
- Que el paquete final incluya:
  - `package.json`
  - `dist/main/index.js` (entrypoint de Electron)
  - `dist/preload/*`
  - `dist/renderer/*`
- Dejarlo listo para distribución plug-and-play en la red interna.

## 3. Error que aparece todo el rato

Durante `npm run dist`, `electron-builder` falla al validar `app.asar`:

- Error principal repetido:
  - `Application entry file "dist\\main\\index.js" ... does not exist`
- En intentos intermedios también apareció:
  - `Application "package.json" ... does not exist`

Esto indica que el empaquetado está dejando fuera archivos críticos del `app.asar`.

## 4. Señales observadas

- `vite build` completa bien.
- `tsc -p tsconfig.node.json` completa bien.
- El fallo aparece en fase:
  - `packaging platform=win32 arch=x64`
  - `sanityCheckPackage`
- Es decir: no es fallo de compilación, es fallo de **contenido empaquetado**.

## 5. Qué se ha tocado ya

- Ajustes en `morrigan-electron/electron-builder.yml` para controlar `files`.
- Limpieza de BOM UTF-8 en `morrigan-electron/package.json` (hubo error de JSON inválido por `﻿`).
- Añadido `author` en `package.json` (warning no bloqueante).

## 6. Diagnóstico técnico resumido

El problema no es que `dist/main/index.js` no exista en disco; sí existe.
El problema es que **las reglas `files` de electron-builder no lo están metiendo en `app.asar`** de forma consistente.

## 7. Comandos de verificación útiles

```bat
cd morrigan-electron
npm run build
npx asar l release\win-unpacked\resources\app.asar | findstr /i "dist\\main\\index.js"
npx asar l release\win-unpacked\resources\app.asar | findstr /i "package.json"
```

Si no aparecen esos paths dentro de `app.asar`, `electron-builder` volverá a fallar.

## 8. Objetivo inmediato de resolución

- Dejar `electron-builder.yml` con una estrategia de inclusión inequívoca.
- Verificar explícitamente que `app.asar` contiene `dist/main/index.js` y `package.json` antes de distribuir.

## 8.1 Nuevo hallazgo (icono Windows)

En el último intento apareció:

- `image ...\\build\\icon.ico has unknown format`

Esto significa que `icon.ico` no es un ICO válido (cabecera incorrecta), por lo que NSIS falla aunque el resto del empaquetado avance.

## 9. Configuración aplicada (estable)

Se ha dejado `morrigan-electron/electron-builder.yml` con:

- `asar: true`.
- `disableDefaultIgnoredFiles: true` (evita que `.gitignore` excluya `dist/`).
- `files` explícito para incluir:
  - `package.json`
  - `dist/**`
  - `node_modules/**`
  - exclusión de `*.map`
- icono Windows temporalmente apuntando a `build/icon.png` para evitar bloqueo por `icon.ico` inválido.

Además, en `package.json`:

- `main: "dist/main/index.js"` confirmado.
- script `dist:dir` añadido para inspección sin generar instalador.

## 10. Protocolo recomendado desde ahora

```bat
cd morrigan-electron
rmdir /s /q release
npm run dist:dir
npx asar list release\\win-unpacked\\resources\\app.asar | findstr /i "package.json"
npx asar list release\\win-unpacked\\resources\\app.asar | findstr /i "dist/main/index.js"
npx asar list release\\win-unpacked\\resources\\app.asar | findstr /i "dist/preload"
npx asar list release\\win-unpacked\\resources\\app.asar | findstr /i "dist/renderer"
```

Si todo está en `app.asar`, ejecutar build final:

```bat
rmdir /s /q release
npm run dist
```

---

Documento creado para seguimiento del bloqueo de packaging de Morrigan Electron.
