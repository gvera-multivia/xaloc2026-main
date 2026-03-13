# ATC (Standalone Smoke)

URL objetivo:
- `https://atc.gencat.cat/es/gestions/certificats/certificats-tributaris/`

Archivos base creados:
- `sites/atc/config.py`
- `sites/atc/data_models.py`
- `sites/atc/controller.py`
- `sites/atc/automation.py`
- `sites/atc/flows/login.py`
- `sites/atc/flows/formulario.py`
- `sites/atc/flows/documentos.py`
- `sites/atc/flows/confirmacion.py`
- `main_atc_payload_by_id.py`

Flujo actual (smoke):
1. Abre la landing de certificados tributarios.
2. Intenta aceptar cookies.
3. Busca CTA de inicio de tramite (`Inicia el tramit/tràmit`, `Tramitar`).
4. Si hay ficheros en payload, intenta subirlos por `input[type=file]`.
5. Se queda en pantalla de tramite y toma screenshot final.

Comandos:
```powershell
python actualizaciones/main_atc_payload_by_id.py --dump-only
python actualizaciones/main_atc_payload_by_id.py --run-flow
```

Pendiente para scraping real:
- Ajustar `SQL_BY_NUMCLIENT` y `build_payload_from_row(...)` en `actualizaciones/main_atc_payload_by_id.py` segun fuente final.
- Ajustar selectores reales en `flows/*` con inspeccion del portal.
- Definir pasos de identificacion/firma cuando se valide el camino de tramite.
