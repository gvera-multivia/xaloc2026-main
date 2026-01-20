# 🎙️ Recorder Guide (Guía de Uso)

El `recorder` es una herramienta interna diseñada para acelerar la creación de nuevos flujos de automatización. Permite grabar interacciones manuales en el navegador y transformarlas automáticamente en documentación y esqueletos de código Python listos para usar.

## 🚀 Cómo empezar

### 1. Ejecutar el Grabador
Para iniciar una sesión de grabación, ejecuta el siguiente comando desde la raíz del proyecto:

```powershell
python recorder/record.py --site <nombre_del_sitio>
```

*   `--site`: Nombre identificador del portal (ej: `redsara`, `aeat`).
*   `--protocol` (Opcional): Identificador de un sub-proceso o protocolo.

### 2. Grabar Acciones
Se abrirá una instancia de Microsoft Edge. Todas las acciones interactivas serán capturadas:
- **Clicks**: En botones, enlaces y elementos interactivos.
- **Rellenado (Fill)**: En campos de texto, áreas de texto y selectores.
- **Checkboxes/Radio**: Marcado y desmarcado.
- **Navegación**: Cambios de URL y cambios significativos en el contenido (H1).

### 3. Captura Automática (Checkpoints)
El sistema toma **screenshots automáticamente** cada vez que detecta un cambio de pantalla (nueva URL o nuevo encabezado H1). Estas imágenes se guardan en `screenshots/<site>/`.

### 4. Finalizar la Grabación
Cuando hayas terminado el flujo, vuelve a la terminal y pulsa:
`Ctrl + C`

El grabador cerrará el navegador y comenzará el **post-procesamiento**.

## 📦 Resultados (Outputs)

Una vez finalizada la grabación, el sistema genera los siguientes archivos:

1.  **Documentación MD**: Un resumen visual y textual del flujo en `explore-html/<site>-recording.md`.
2.  **Modelos de Datos**: Un archivo `sites/<site>/data_models.py` con las clases `dataclass` detectadas.
3.  **Configuración**: Un archivo `sites/<site>/config.py` con la URL base y selectores.
4.  **Flujos (Flows)**: Archivos `sites/<site>/flows/phase_XX.py` con el código Playwright inicial para replicar los pasos grabados.

## 💡 Consejos para una mejor grabación

- **Interactúa con calma**: Espera a que las páginas carguen totalmente antes de clicar.
- **Usa Etiquetas (Labels)**: El grabador prefiere selectores basados en texto y etiquetas (`getByLabel`, `getByRole`) por ser más robustos.
- **Evita clicks innecesarios**: Solo clica en lo que sea estrictamente necesario para el flujo.
- **Certificados**: Si el portal requiere certificado, el grabador usará el perfil persistente de la carpeta `user_data/`. Asegúrate de tener el certificado instalado en el sistema.

## 🛠️ Estructura Interna

- `record.py`: Entrypoint del grabador.
- `inject_recorder.js`: Script JS inyectado en el navegador para capturar eventos del DOM.
- `compile.py`: Compilador que analiza los eventos `.jsonl` y genera el código/documentación.
- `extract.py`: Lógica para decidir cuál es el mejor selector (Locator) para cada acción.
- `capture.py`: Gestor de capturas de pantalla.
