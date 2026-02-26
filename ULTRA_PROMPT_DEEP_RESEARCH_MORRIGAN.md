## Ultra Prompt - Deep Research Morrigan Electron (Windows trust + size)

Eres un investigador senior en distribución de apps Electron para Windows (packaging, trust, SmartScreen, code signing, optimización de tamaño y hardening). Tu misión es diseñar un plan ejecutable para que esta app se distribuya con menos fricción de seguridad y con un instalador más pequeño.

Trabaja con enfoque de auditoría técnica + plan de implementación. No quiero respuestas genéricas; quiero decisiones justificadas con impacto, esfuerzo y riesgo.

### 1) Contexto del proyecto (real)

- Proyecto monorepo: `xaloc2026-main`
- App desktop: `morrigan-electron/`
- Stack backend en Docker: `infra/docker/docker-compose.microservices.yml`
- API gateway expuesto en `:8080`, noVNC en `:6080`
- Servicio API sirve artefactos de Morrigan desde `services/api_gateway/app.py`
- Bootstrap runtime config de Electron:
  - `morrigan-electron/src/main/services/runtime-config.ts`
  - defaults actuales:
    - `apiBaseUrl`: `http://192.168.184.72:8080`
    - `wsUrl`: `ws://192.168.184.72:8080/ws/dashboard`
    - `bootstrapUrl`: `http://192.168.184.72:8080/morrigan-config.json`

### 2) Estado actual de empaquetado

Archivos clave:
- `morrigan-electron/package.json`
- `morrigan-electron/electron-builder.yml`
- `MORRIGAN_PACKAGING_ISSUE.md`

Build targets actuales:
- `nsis` + `msi` (x64)
- `asar: true`
- `disableDefaultIgnoredFiles: true`
- `signAndEditExecutable: false`
- icono win: `build/icon.png`

Scripts:
- `npm run dist`
- `npm run dist:nsis`
- `npm run dist:msi`
- `npm run dist:dir`

### 3) Métricas actuales (medidas reales)

- `release/win-unpacked` total: **277.26 MB** (`290,729,203 bytes`)
- `release/Morrigan Setup 0.1.0.exe`: **76.72 MB**
- `release/Morrigan 0.1.0.msi`: **86.64 MB**
- `release/win-unpacked/Morrigan.exe`: **172.47 MB**
- `release/win-unpacked/resources/app.asar`: **19.40 MB**

Top pesos:
- `Morrigan.exe` 172.47 MB
- `app.asar` 19.40 MB
- `icudtl.dat` 9.98 MB
- `LICENSES.chromium.html` 9.01 MB
- `libGLESv2.dll` 7.69 MB
- `resources.pak` 5.29 MB
- `vk_swiftshader.dll` 5.22 MB
- `d3dcompiler_47.dll` 4.69 MB
- muchos `locales/*.pak` (idiomas no usados)

### 4) Problemas a resolver

1. Windows marca el `.exe` como inseguro/no confiable (fricción SmartScreen/Defender/Unknown Publisher).
2. Peso alto para una app funcionalmente simple (277 MB unpacked).
3. Necesidad de estrategia de distribución interna robusta (red corporativa) con mínimo soporte manual.

### 5) Objetivos de investigación (debes cubrir todos)

1. **Trust en Windows**:
   - Diferenciar claramente qué soluciona cada capa:
     - firma Authenticode OV
     - EV code signing
     - timestamping
     - reputación SmartScreen
     - políticas GPO/Intune/Defender en entorno corporativo
   - Diseñar plan mínimo viable y plan ideal (con costes aproximados).
   - Incluir flujo CI/CD de firma recomendado para Windows.

2. **Reducción de tamaño**:
   - Explicar cuánto es “normal” en Electron vs cuánto es optimizable.
   - Proponer optimizaciones con estimación de ahorro:
     - prune de `files` (evitar incluir basura)
     - `asar` tuning
     - exclusión de mapas/source maps/tests
     - reducción de `locales`
     - compresión NSIS (`solid`, `lzma`, etc.)
     - impacto real de `msi` vs `nsis`
     - posibilidad de `electron-vite`/tree shaking adicional
   - Señalar límites inevitables por runtime Chromium.

3. **Modelo de distribución interna**:
   - Recomendación entre:
     - instalador firmado distribuido por share interno
     - winget privado / Intune / GPO software deployment
     - auto-update interno (`electron-updater` provider genérico)
   - Riesgos operativos y seguridad de cada opción.

4. **Hardening Electron**:
   - Checklist de seguridad en main/preload/renderer:
     - `contextIsolation`, `nodeIntegration`, `sandbox`, CSP, `shell.openExternal`, navegación
   - Confirmar qué controles ya existen y qué faltaría para nivel “producción corporativa”.

### 6) Entregables esperados (formato obligatorio)

Devuelve exactamente esta estructura:

1. **Diagnóstico ejecutivo** (10-15 líneas, sin relleno).
2. **Tabla de palancas de mejora**:
   - columna: Acción
   - columna: Impacto esperado (% o MB / reducción de alertas)
   - columna: Esfuerzo (S/M/L)
   - columna: Riesgo
   - columna: Prioridad
3. **Plan de implementación en 3 fases**:
   - Fase 1 (quick wins, 1-2 días)
   - Fase 2 (industrialización, 1-2 semanas)
   - Fase 3 (escala corporativa)
4. **Cambios concretos sugeridos en `electron-builder.yml` y `package.json`**:
   - propone snippets listos para aplicar
   - cada snippet con justificación breve.
5. **Plan de firma de código Windows**:
   - proveedores recomendados (sin sesgo comercial)
   - OV vs EV comparativo real
   - gestión segura de certificados
   - timestamp y verificación post-build
6. **Plan de validación**:
   - pruebas en máquinas limpias Windows 10/11
   - cómo medir reducción de falsos positivos/avisos
   - KPIs de éxito.
7. **Riesgos y decisiones abiertas**:
   - lista corta de preguntas que el equipo debe resolver.

### 7) Restricciones y calidad

- No dar teoría genérica: todo debe aterrizarse a este proyecto y estos archivos.
- Si propones cambios, deben ser compatibles con Electron 31 + electron-builder 25.
- Prioriza soluciones prácticas para entorno corporativo interno.
- Marca explícitamente qué recomendaciones dependen de presupuesto (certificados EV, MDM, etc.).
- Si faltan datos, enumera exactamente qué comando ejecutar para obtenerlos.

### 8) Datos adicionales útiles

- En `morrigan-electron/src/main/index.ts` se configura `openAtLogin: true` y gestión tray.
- En `morrigan-electron/src/main/services/updater.ts` el auto-update está pendiente (`TODO`).
- En Docker compose se exponen variables:
  - `MORRIGAN_API_BASE_URL`
  - `MORRIGAN_WS_URL`
  - `MORRIGAN_BOOTSTRAP_URL`
  - `MORRIGAN_CONFIG_REFRESH_SEC`

Tu respuesta final debe ser accionable para ejecutar cambios reales en el repo sin interpretación ambigua.
