# DOM Recorder MVP (Extension)

Esta extension de Edge/Chrome permite grabar interacciones DOM y navegacion para generar automatizaciones (p.ej. Playwright) posteriormente.

## Caracteristicas

- **Persistencia:** Soporta navegacion, redirecciones y recargas.
- **Inspeccion (raw):** Guarda `outerHTML` del elemento interactuado y contexto (labels, formularios).
- **Selects:** Captura todas las opciones de los elementos `<select>`.
- **Iframes:** Soporta iframes (incluye `all_frames`). En algunos iframes cross-origin puede haber restricciones segun el sitio.
- **Exportacion:** Genera 2 salidas: `recording.raw.json` (raw actual, sin cambios) y `recording.flowmap.json` (FlowMap compacto).

## Instalacion (Modo Desarrollador)

1. Abre Edge (`edge://extensions/`) o Chrome (`chrome://extensions/`).
2. Activa el **Modo de desarrollador**.
3. Haz clic en **Cargar descomprimida** (Load unpacked).
4. Selecciona la carpeta `browser_extension` dentro de este repositorio.

## Uso (Grabacion)

1. Navega a la web que quieres automatizar.
2. Haz clic en el icono de la extension.
3. Pulsa **Start Recording**.
4. Realiza las acciones (clics, rellenar formularios, selects, subir archivos).
5. Navega libremente: se agrupa por URL y visitas.
6. Pulsa **Stop Recording**.
7. En estado Idle, pulsa **Export raw + flowmap** para descargar:
   - `recording.raw.json`
   - `recording.flowmap.json`

## Convertir un JSON raw a FlowMap (sin grabar)

En el popup (estado Idle):

- **Convert raw JSON file -> flowmap**: selecciona un `.json` raw (o pegalo) y pulsa **Build FlowMap** para descargar el `.flowmap.json`.

## Formato de salida

### 1) `recording.raw.json` (sin cambios)

Estructura (igual que antes):

```json
{
  "meta": { "...": "..." },
  "pages": [
    {
      "topUrl": "https://...",
      "visits": [
        {
          "startedAt": "...",
          "interactions": [
            {
              "ts": "...",
              "action": "click|fill|change|submit|upload",
              "frameUrl": "https://...",
              "element": { "tag": "INPUT", "outerHTML": "...", "attributes": { "...": "..." } },
              "state": { "...": "..." },
              "selectOptions": [ { "...": "..." } ],
              "context": { "labelText": "...", "heading": "...", "formOuterHTML": "..." },
              "locatorCandidates": [ { "type": "css", "value": "#id" } ]
            }
          ]
        }
      ]
    }
  ]
}
```

### 2) `recording.flowmap.json` (FlowMap compacto)

Resumen "estructura + acciones" pensado para consumo por LLM:

- Agrupa por `topUrl` y crea `visits[]` en orden.
- En cada visita, registra `elements[]` (elementos unicos tocados) y `steps[]` (acciones normalizadas).
- Los `<select>` guardan sus opciones completas una sola vez en `selectOptionsStore` y se referencian por `optionsId`.
- Iframes: si hay interacciones fuera del top frame, se anade `frames[]` y los elementos de iframe incluyen `frameKey`.

## Notas tecnicas

- Inputs de texto se registran en `blur` para capturar el valor final.
- `<select>` guarda opciones y el valor seleccionado.
- `input[type=file]` guarda nombres de archivo (no la ruta completa por seguridad del navegador).

