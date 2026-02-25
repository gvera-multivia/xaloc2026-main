# Hito Firma Programatica Ayunta Palma (Runbook)

## Estado actual (2026-02-25)
- Firma programatica operativa de extremo a extremo en Linux/Docker:
  - Captura `afirma://` por handler XDG.
  - Firma con AutoFirma CLI (`xades`, `sha512`).
  - Inyeccion en frame de firma con callback valido (`procesarFirma`).
  - Reflejo correcto en padre: `estado=Completada` y panel de no-firmada oculto.
- Post-firma robusta:
  - Deteccion de exito por banner y por estado (`Completada/Completat/Registrada/Registrat`).
  - Evita falso negativo por idioma (ES/CA).

## Reglas intocables (evitar regresiones)
- No aceptar callbacks launcher/checker en inyeccion:
  - `firmar*`, `firmarElectronicamente*`, `firmarBiometricamente*`, `comprobar*`, `check*`, `retrieve*`, `poll*`.
- No forzar refresh inmediato justo tras inyeccion de firma.
  - Primero espera pasiva para permitir cierre nativo del flujo.
- Exito real de firma:
  - No basta `callback ok`; debe reflejarse en la pagina padre.

## Indicadores de salud en logs
- Buenos:
  - `[AP-FIRMA] Resultado inyeccion: {'ok': True, 'method': 'callback', 'callback': 'procesarFirma'...}`
  - `[AP-FIRMA] Estado de firma reflejado en pagina padre: {'ok': True, ... 'estado': 'Completada' ...}`
  - `[AP-DIAG] Exito de firma detectado ... by_banner=... by_estado=...`
- Malos (regresion):
  - callback `firmarBiometricamente` o `comprobarFirma`.
  - bucle de `RetrieveService` sin cambio de estado en padre.
  - `No se detecto exito en 120s` seguido de estado pendiente.

## Arranque correcto de stack
- Importante: siempre usar `.env` al levantar servicios, si no el password del PFX puede quedar vacio.

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml up -d --build playwright-runner-service worker-orchestrator-service
```

## Verificacion rapida
```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=200 playwright-runner-service worker-orchestrator-service
```

Checklist:
1. Runner arranca sin restart loop.
2. `Certificado importado en NSS ...`.
3. En firma, callback final no es biometric/checker.
4. Estado padre cambia a completada.
5. Pasa a descarga de justificante.

## Si vuelve a fallar (procedimiento de recuperacion)
1. Confirmar entorno:
   - `PLAYWRIGHT_CERT_PASSWORD` no vacio en compose efectivo (`docker compose --env-file .env ... config`).
2. Revisar callback elegido en inyeccion.
3. Revisar `net_tail`:
   - si solo hay `RetrieveService` y no cambia estado, callback equivocado.
4. Revisar deteccion post-firma:
   - idioma/estado visible y criterios de exito.
5. No tocar primero criptografia:
   - tratar como `integration-gap` (UI/callback/estado), no `crypto-gap`.

## Archivos clave
- `sites/ayunta_palma/flows/firma_programatica.py`
- `sites/ayunta_palma/flows/documentos.py`
- `infra/docker/playwright-runner-entrypoint.sh`
- `infra/docker/docker-compose.microservices.yml`

