# RedSARA TODO + Action Plan

## Objetivo
Dejar `sites/redsara` operativo en el stack actual con flujo completo Playwright/Python, con paridad funcional razonable respecto al legacy de `RecursosSubir/pruebaGroovy copy.groovy`, empezando por una prueba controlada desde un entrypoint local.

## Estado actual
- Existe `sites/redsara` con:
  - `config.py`, `data_models.py`, `controller.py`, `automation.py`
  - `flows/` para login/certificado/formulario/documentacion/envio
- Compila correctamente (`python -m compileall sites\redsara`).
- No está registrado en `core/site_registry.py`.
- No hay task runner/entrypoint dedicado para probarlo aislado.

## TODO (pendientes)

1. Registro del site en runtime
- [ ] Añadir `redsara` en `core/site_registry.py`.
- [ ] (Opcional) Exportarlo en `sites/__init__.py` si se usa para autodiscovery.

2. Entry point de prueba desde root
- [ ] Crear `redsara_task.py` (patrón `madrid_task.py` / `xaloc_task.py`).
- [ ] Soportar:
  - [ ] `--payload-json <path>`
  - [ ] `--headless 0/1`
  - [ ] `--dry-run` (opcional: ejecutar sin click final de firma).
- [ ] Log claro de fases y screenshot final.

3. Router de organismo (port del `switch` Groovy)
- [ ] Implementar clasificador de portal en Python (nuevo módulo, por ejemplo `core/portal_router.py` o `services/payload_router.py`).
- [ ] Incluir reglas REDSARA del bloque `setPortal(...)`:
  - [ ] patrones de organismos que deben ir a REDSARA
  - [ ] casos frontera (p.ej. Ajuntaments de Catalunya hacia Dipu según `municipiosDipu.json`)
- [ ] Integrar el router en el flujo de encolado para asignar `site_id` correcto.

4. Normalización de organismo (paridad legacy)
- [ ] Consolidar reglas del bloque de REDSARA legacy:
  - [ ] Barcelona -> `INSTITUTO MUNICIPAL DE HACIENDA`
  - [ ] León -> `E00130201`
  - [ ] Palma -> `L01070407`
  - [ ] Migjorn -> `L01079028`
  - [ ] Jefatura territorial Pontevedra -> `E03102801`
  - [ ] normalización Bizkaia y TEA específicos
- [ ] Centralizar en función reusable (`sites/redsara/normalization.py`).

5. Preproceso documental (paridad con Groovy/Python legacy)
- [ ] Portar selección inteligente de PDFs por términos (`AUT`, `DNI`, `NIE`, `CIF`, `ESCR`).
- [ ] Portar fusión de adjuntos múltiples.
- [ ] Portar compresión PDF por tamaño límite (10MB).
- [ ] Portar resolución de carpeta cliente (`DOCUMENTACION`, `DOCUMENTACIÓN`, `DOCUMENTACION RECURSOS`).
- [ ] Integrar esto antes de `set_input_files`.

6. Normalización geográfica robusta
- [ ] Integrar normalizador provincia/localidad basado en `provincia_localidades.json`.
- [ ] Aplicar fallback `gerentPobl` vs `poblacion`.
- [ ] Añadir waits robustos para selects dependientes provincia->ciudad.

7. Justificante y rutas finales
- [ ] Definir contrato de `payload` para `ruta_cliente` o calcularlo dentro del site.
- [ ] Copiar justificante a `RECURSOS TELEMATICOS[/fase]`.
- [ ] Limpieza de archivos temporales y de recurso original (si procede).

8. Endurecer selectores y estabilidad UI
- [ ] Reemplazar selectores frágiles por selectores robustos y/o helpers.
- [ ] Añadir retries y validaciones intermedias por fase.
- [ ] Capturar HTML + screenshot en errores de cada fase.

9. Tests mínimos
- [ ] Unit test de `controller.create_target`.
- [ ] Unit test de normalización de organismo.
- [ ] Unit test de normalización de fase/asunto-expone-solicita.
- [ ] Smoke test local con payload fijo.

10. Integración progresiva (sin docker al inicio)
- [ ] Fase 1: correr local por script dedicado.
- [ ] Fase 2: alta en `site_registry`.
- [ ] Fase 3: activación en encolador/router para casos REDSARA.
- [ ] Fase 4: habilitar en worker productivo.
- [ ] Fase 5: incorporación a docker/compose.

## Plan de acción propuesto

### Fase A - Ejecutable de prueba (rápido)
1. Crear `redsara_task.py` en root.
2. Registrar `redsara` en `core/site_registry.py`.
3. Añadir un payload JSON de ejemplo para test manual.
4. Ejecutar prueba manual y validar:
   - llega a formulario
   - sube docs
   - intenta firma
   - descarga justificante (si el entorno lo permite)

### Fase B - Paridad de negocio
1. Portar normalización de organismo exacta del legacy.
2. Portar `setEscritos` + mapeo de fases.
3. Portar pipeline de documentos (selección/fusión/compresión/rutas).

### Fase C - Enrutamiento automático
1. Implementar módulo de router de organismo.
2. Integrarlo en scripts de claim/sync para enrutar a `redsara`.
3. Añadir trazabilidad en logs del motivo de ruteo.

### Fase D - Calidad y despliegue
1. Añadir tests de controller/normalizaciones.
2. Añadir smoke test reproducible.
3. Activar en worker.
4. Activar en docker.

## Criterios de aceptación (Definition of Done)
- [ ] Se puede ejecutar desde root con `python redsara_task.py --payload-json ...`.
- [ ] `site_registry` reconoce `redsara`.
- [ ] Al menos 1 caso real REDSARA finaliza con screenshot + justificante guardado.
- [ ] Router enruta correctamente organismos REDSARA según reglas legacy.
- [ ] Tests mínimos pasan en local.

## Riesgos y mitigaciones
- UI dinámica y certificados: usar perfil persistente + watcher certificado + waits robustos.
- Variabilidad de organismos y nombres: centralizar normalización y versionarla.
- Dependencia de paths de red: validar acceso y fallback controlado.
- Cambios de frontend RedSARA: documentar selectores y mantener utilidades de inspección.
