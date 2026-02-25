# Diagnostico Extenso: Certificado Digital en Docker (Playwright Runner)

## 1) Contexto y objetivo
Este documento resume, con detalle operativo, el estado actual del problema de autenticacion con certificado en entorno Docker Linux, los cambios aplicados, los bloqueos detectados y el plan de cierre.

Objetivo principal:
- Conseguir que los flujos con certificado (especialmente `xaloc_girona`) completen el login en `valid.aoc.cat` y vuelvan al formulario STA sin timeout.

Objetivo secundario:
- Disponer de observabilidad real para depurar con evidencia (logs del navegador, red y, cuando sea posible, visualizacion del navegador dentro del contenedor).

## 2) Sintoma principal
Error repetido en worker/runner:
- `Timeout esperando retorno al formulario STA tras login con certificado`
- URL final observada: `https://valid.aoc.cat/o/oauth2/auth?...redirect_uri=https://seu.xalocgirona.cat/sta/Relec/TramitaNoCertForm...`

Interpretacion operacional:
- El flujo pulsa el boton de certificado, pero no se completa la seleccion/aceptacion efectiva del certificado para retornar a STA.

## 3) Arquitectura implicada
Piezas clave:
- `worker-orchestrator-service` envia ejecuciones a:
- `playwright-runner-service` (FastAPI + Playwright).

Inyeccion de certificado en Linux:
- `playwright-runner-entrypoint.sh`:
  - importa `certificate.pfx` con `pk12util` a NSS DB.
  - prepara DB con `certutil`.
  - escribe policy `AutoSelectCertificateForUrls` para Chromium.

Flujo funcional:
- `sites/xaloc_girona/flows/login.py` abre VALid, pulsa certificado y espera retorno a STA.

## 4) Problemas detectados (reales)
### 4.1 Desalineacion de perfil/browser vs NSS (ya corregido)
Antes:
- Python usaba perfil por defecto `profiles/edge`.
- Runner inyectaba NSS en `/app/profiles/worker`.

Consecuencia:
- El navegador podia arrancar con un perfil distinto al que contenia el certificado.

Correccion aplicada:
- `core/base_config.py` ahora toma `PLAYWRIGHT_PROFILE_DIR` para `perfil_path`.

### 4.2 Fallback frecuente por lock de perfil
Logs repetidos:
- `Chromium profile lock detectado...`
- `Persisten locks del perfil. Fallback a perfil temporal clonado.`

Consecuencia:
- El runner termina usando perfil temporal. Este perfil se clona e intenta importar cert, pero complica trazabilidad y estabilidad.

### 4.3 Falta de observabilidad util en momento critico (ya mejorada)
Se carecia de trazas de:
- navegacion fina alrededor del click de certificado,
- eventos de red hacia `valid.aoc.cat`,
- estado de pestañas/contexto durante el bloqueo.

Correccion aplicada:
- Instrumentacion `CERT-DBG` en `sites/xaloc_girona/flows/login.py`.
- Flags de debug de Chromium en `core/base_automation.py`.

### 4.4 Build Docker bloqueado por input interactivo tzdata (ya corregido)
Durante build aparecia:
- `Please select the geographic area...`

Consecuencia:
- el proceso quedaba esperando input manual.

Correccion aplicada:
- `infra/docker/Dockerfile.playwright-runner` con:
  - `DEBIAN_FRONTEND=noninteractive`
  - `TZ=Etc/UTC`

### 4.5 noVNC mostrando "Failed to connect server"
Significado tecnico:
- Se abre UI web de noVNC, pero no hay backend VNC operativo/accesible.

Causa inmediata verificada en una iteracion:
- El servicio `playwright-runner-service` estaba caido/no levantado en ese momento.

Riesgos adicionales a validar:
- stack visual no arrancado dentro de contenedor,
- `websockify` enlazando destino incorrecto,
- puertos no publicados o colisionados.

## 5) Cambios aplicados en codigo
### 5.1 Perfil por entorno para Playwright
Archivo:
- `core/base_config.py`

Cambio:
- `perfil_path` ahora se inicializa desde `PLAYWRIGHT_PROFILE_DIR` con fallback local.

### 5.2 Debug certificado en flujo Xaloc
Archivo:
- `sites/xaloc_girona/flows/login.py`

Añadido:
- Flag `XALOC_CERT_DEBUG`.
- Logs `[CERT-DBG]` de consola, dialogos JS, requests/responses relevantes, estado periodico de contexto/pestañas.
- screenshot en timeout (`screenshots/xaloc_cert_timeout.png`).

### 5.3 Debug Chromium a bajo nivel
Archivo:
- `core/base_automation.py`

Añadido:
- `XALOC_BROWSER_DEBUG` -> `--enable-logging=stderr --log-level=0 --v=1`
- `XALOC_CHROMIUM_NETLOG` opcional.

### 5.4 Modo visual para runner (en progreso de validacion operativa)
Archivos:
- `infra/docker/playwright-runner-visual-entrypoint.sh` (nuevo)
- `infra/docker/Dockerfile.playwright-runner`
- `infra/docker/docker-compose.microservices.yml`

Objetivo:
- levantar `Xvfb + x11vnc + noVNC` y exponer `6080/5900`.

### 5.5 Build no interactivo
Archivo:
- `infra/docker/Dockerfile.playwright-runner`

Añadido:
- `DEBIAN_FRONTEND=noninteractive`
- `TZ=Etc/UTC`

## 6) Estado actual
Confirmado en logs previos:
- Certificado importado correctamente en NSS (perfil y global).
- Policy `AutoSelectCertificateForUrls` escrita.
- El flujo sigue pudiendo quedar en `valid.aoc.cat` con timeout.

Estado de visualizacion:
- Intentos de despliegue visual interrumpidos en distintas iteraciones.
- noVNC llego a cargar UI, pero con `Failed to connect server` en un intento (runner no estaba operativo en ese punto).

## 7) Que queremos conseguir (definicion exacta)
Resultado esperado funcional:
1. Se lanza job `xaloc_girona`.
2. Se abre VALid.
3. Se selecciona certificado automaticamente (sin bloqueo silencioso).
4. Redirige a `seu.xalocgirona.cat/sta/...`.
5. Flujo continua sin timeout.

Resultado esperado de observabilidad:
1. Ver navegador en vivo por noVNC cuando `XALOC_VISUAL_DEBUG=1`.
2. Capturar `[CERT-DBG]` en logs de runner.
3. Correlacionar click de certificado con requests/responses reales.

## 8) Hipotesis tecnicas pendientes (orden de probabilidad)
1. Auto-seleccion no aplicada de forma efectiva en runtime (policy/arg presentes pero no efectivos en ese proceso concreto).
2. Seleccion de certificado queda en dialogo nativo no visible/controlable en headless.
3. Inestabilidad por `profile lock` + fallback temporal en cada ejecucion.
4. Diferencias de comportamiento del IdP AOC en entorno Linux headless.

## 9) Plan de cierre propuesto
### Fase A: cerrar modo visual
1. Levantar runner con build completo no-interactivo.
2. Verificar procesos dentro de contenedor:
   - `Xvfb`, `x11vnc`, `websockify`, `fluxbox`.
3. Abrir `http://localhost:6080/vnc.html` y confirmar sesion.

### Fase B: ejecutar caso controlado
1. Lanzar solo 1 job `xaloc_girona`.
2. Capturar:
   - logs runner completos,
   - bloques `[CERT-DBG]`,
   - screenshot timeout si ocurre.
3. Confirmar visualmente si aparece selector de certificado o bloqueo previo.

### Fase C: mitigacion segun evidencia
- Si hay selector sin seleccion automatica: revisar y endurecer reglas de autoselect.
- Si no aparece selector y no hay request de certificado: revisar handshake TLS/client-auth de `valid.aoc.cat` y perfil efectivo.
- Si lock de perfil domina: forzar estrategia de perfil unico limpio por job o desactivar concurrencia del perfil.

## 10) Comandos de referencia (Windows CMD)
Ver logs runner (completo):
```bat
docker logs -f xaloc-playwright-runner
```

Filtrar diagnostico cert:
```bat
docker logs xaloc-playwright-runner --since 30m | findstr /C:"[CERT-DBG]"
```

Levantar runner:
```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml up -d --build playwright-runner-service
```

Ver estado servicio:
```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml ps playwright-runner-service
```

## 11) Criterio de exito final
Se considerara resuelto cuando:
- 3 ejecuciones consecutivas de `xaloc_girona` completen login y retorno a STA sin timeout,
- sin intervencion manual,
- con logs trazables de la secuencia completa.

---
Documento generado para consolidar diagnostico tecnico y ejecucion operativa del incidente de certificado en Docker.
