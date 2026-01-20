# DOM Recorder MVP (Extension)

Esta extensión de Edge/Chrome permite grabar interacciones en portales web administrativos para generar código Playwright posteriormente.

## Características

*   **Persistencia:** Soporta navegación, redirecciones y recargas.
*   **Inspección:** Guarda `outerHTML` del elemento interactuado y contexto (etiquetas, formularios).
*   **Selects:** Captura todas las opciones de los elementos `<select>`.
*   **Iframes:** Soporta iframes del mismo origen.
*   **Exportación:** Genera un archivo JSON estructurado por URL y visitas.

## Instalación (Modo Desarrollador)

1.  Abre Edge (`edge://extensions/`) o Chrome (`chrome://extensions/`).
2.  Activa el **Modo de desarrollador** (esquina superior derecha/izquierda).
3.  Haz clic en **Cargar descomprimida** (Load unpacked).
4.  Selecciona la carpeta `browser_extension` dentro de este repositorio.

## Uso

1.  Navega a la web que quieres automatizar.
2.  Haz clic en el icono de la extensión (puzzle).
3.  Pulsa **Start Recording**.
    *   El estado cambiará a "Recording...".
4.  Realiza las acciones (clics, rellenar formularios, seleccionar opciones, subir archivos).
5.  Navega libremente. La extensión agrupará las acciones por URL.
6.  Cuando termines, pulsa el icono de nuevo y haz clic en **Stop Recording**.
7.  Aparecerá el botón **Download JSON**. Púlsalo para descargar `recording.json`.

## Formato de Salida

El JSON generado tiene la siguiente estructura:

```json
{
  "meta": { ... },
  "pages": [
    {
      "topUrl": "https://...",
      "visits": [
        {
          "interactions": [
            {
              "action": "click|fill|change...",
              "element": { "outerHTML": "..." },
              "context": { "labelText": "..." },
              "locatorCandidates": [ ... ]
            }
          ]
        }
      ]
    }
  ]
}
```

## Notas Técnicas

*   Los eventos de teclado en inputs de texto se registran al perder el foco (`blur`) para capturar el valor final.
*   Los `<select>` guardan todas sus opciones.
*   Los `input[type=file]` guardan los nombres de los archivos seleccionados (no la ruta completa por seguridad del navegador).
