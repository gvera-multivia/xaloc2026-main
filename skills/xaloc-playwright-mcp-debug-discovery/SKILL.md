---
name: xaloc-playwright-mcp-debug-discovery
description: Usar Playwright MCP para recorrer una sede existente o nueva, seguir el flujo real, detectar donde falla y mapearlo al codigo de Xaloc. Usar cuando haya que reproducir un fallo UI/browser, descubrir una pagina nueva o aislar si la rotura es de selector, timing, popup, redireccion, certificado, firma o flujo.
---

# Xaloc Playwright MCP Debug Discovery

## Overview

Investigar el comportamiento real de una sede con Playwright MCP y aterrizar el hallazgo en el punto de codigo correcto del repo. Priorizar reproduccion del fallo, snapshots, consola y red antes de proponer cambios.

## Workflow

1. Fijar objetivo y alcance.
- site existente con error reproducible
- pagina nueva a entender antes de implementar
- paso exacto a validar: login, formulario, adjuntos, firma, confirmacion

2. Preparar el mapa de codigo del site.
- Ejecutar:
`python skills/xaloc-playwright-mcp-debug-discovery/scripts/map_site_files.py --site-id <site_id>`
- Identificar `config.py`, `controller.py`, `automation.py` y `flows/*.py`

3. Explorar con Playwright MCP.
- navegar
- capturar `browser_snapshot`
- inspeccionar consola
- inspeccionar red cuando haya redirecciones, APIs o descargas
- capturar el primer punto donde diverge del flujo esperado

4. Clasificar el tipo de fallo.
- selector roto
- timing / espera insuficiente
- popup o iframe no contemplado
- certificado o login especial
- AutoFirma / protocolo externo
- payload insuficiente para ese paso
- cambio estructural de la sede

5. Mapear al codigo del repo.
- login -> `flows/login.py`
- datos / transformacion -> `controller.py`
- secuencia general -> `automation.py`
- paso funcional -> `flows/formulario.py`, `flows/documentos.py`, `flows/confirmacion.py`
- timeouts / URLs / selectores -> `config.py`

## Required References

- Loop de diagnostico MCP:
  - `references/mcp-debug-loop.md`
- Mapa entre hallazgo browser y codigo Xaloc:
  - `references/site-code-mapping.md`
- Artefactos y evidencias a conservar:
  - `references/playwright-artifacts.md`

## Output Contract

Al cerrar una ejecucion con esta skill, devolver:

1. URL/paso analizado.
2. Flujo esperado vs flujo observado.
3. Evidencia MCP relevante: snapshot, consola, red, popup, captura.
4. Tipo de fallo.
5. Archivo(s) y funcion(es) donde probablemente hay que corregir.
6. Cambio tecnico propuesto y como revalidarlo.

## Non-goals

- No implementar un site completo automaticamente.
- No quedarse solo en una captura si faltan snapshot o consola.
- No culpar a Playwright si el problema real es payload o negocio fuera del navegador.
