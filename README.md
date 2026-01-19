# Xaloc 2026 - Automatización Web (Playwright + Python)

Herramienta de automatización basada en **Playwright (async)** con una arquitectura **multi-sitio**. El proyecto ha evolucionado para soportar diversos portales (Xaloc Girona, BASE On-line, Ayuntamiento de Madrid) bajo un núcleo común, priorizando la robustez en la navegación y la gestión de certificados digitales.

## Estado Actual del Proyecto

Los siguientes sitios están integrados y funcionales:

- **`xaloc_girona`**:
    - Login con certificado (VALID).
    - Rellenado de formularios STA, adjuntar documentos y confirmación.
    - Screenshot final.
    - **Nota**: El flujo se detiene antes de pulsar "Enviar" para evitar registros reales en pruebas.

- **`base_online`**:
    - Login con certificado.
    - Soporte para múltiples subprocesos:
        - `P1`: Identificación de conductor.
        - `P2`: Alegaciones (adjunta PDF).
        - `P3`: Recurso de reposición (formulario complejo + adjuntos).
    - Navegación completa hasta la pantalla "Signar i Presentar".

- **`madrid` (COMPLETADO)**:
    - **Navegación robusta**: Implementada con tiempos de espera "humanos" (0.5s entre pasos) y recuperación automática de errores.
    - **Gestión de certificado**:
        - Detección automática del popup de Windows.
        - **Timeout de 15s**: Si la automatización falla, espera indefinidamente a que el usuario seleccione el certificado manualmente, evitando bloqueos.
    - **Rellenado de formulario**:
        - Completado de todos los campos (texto, radios, combos, checks) con delays aleatorios para simular interacción humana.
        - Gestión de subida de ficheros (FileUploader).
    - **Bloqueo de popups**: Cierre automático de pestañas de redes sociales o publicidad emergente.

## Estructura del Proyecto

```
core/                 # Núcleo común (configuración base, gestión de sesiones, logging)
sites/                # Implementaciones por portal
  xaloc_girona/       # Automatización específica para Xaloc
  base_online/        # Automatización para BASE (Tarragona)
  madrid/             # Automatización para Ayto. Madrid (Finalizado)
flows/                # (Compatibilidad) Redirige a flujos de xaloc_girona
utils/                # Utilidades (Popup de certificado Windows, manejo de PDF, etc.)
explore-html/         # Documentación de ingeniería inversa y análisis de los portales
pdfs-prueba/          # Archivos dummy para pruebas de subida
profiles/             # Perfiles de navegador persistentes (cookies/sesiones)
logs/                 # Logs de ejecución
screenshots/          # Evidencias visuales de éxito o error
main.py               # Punto de entrada (CLI) con menú interactivo
```

## Uso

El script principal `main.py` ofrece un menú interactivo si no se especifican argumentos:

```powershell
python main.py
```
*Se desplegará un menú para elegir el portal y, si corresponde, el subproceso a ejecutar.*

### Argumentos de línea de comandos
También es posible ejecutar directamente pasando parámetros:

```powershell
# Ejecutar Madrid
python main.py --site madrid

# Ejecutar BASE On-line (Recurso de reposición)
python main.py --site base_online --protocol P3 --p3-file pdfs-prueba/doc.pdf

# Ejecutar en modo Headless (sin interfaz gráfica)
python main.py --site madrid --headless
```

## Recomendaciones y Próximos Pasos

Para seguir mejorando la robustez y funcionalidad del proyecto, se sugieren las siguientes acciones:

1.  **Validación de Fin de Trámite**: Implementar una verificación final más estricta en `madrid` que confirme no solo la subida de archivos, sino la recepción de un "acuse de recibo" o mensaje de éxito explícito (actualmente se llega a la pantalla final).
2.  **Gestor de Certificados**: Abstraer la lógica del certificado (actualmente en `utils/windows_popup.py`) para soportar diferentes keystores o navegadores, no solo el popup nativo de Windows.
3.  **Tests E2E Automatizados**: Crear una batería de tests que usen un servidor "mock" local simulando los formularios de la administración para validar la lógica de rellenado sin depender de la disponibilidad (o lentitud) de las webs reales.
4.  **Refactorización de Configuración**: Unificar la definición de selectores. Actualmente, cada sitio tiene su `config.py`. Podría ser útil un formato común (JSON/YAML) si se planea escalar a muchas más webs, permitiendo cambios sin tocar código Python.
5.  **Logging Estructurado**: Migrar los logs a formato JSON para facilitar su ingesta por herramientas de monitoreo si el proyecto escala a producción masiva.

---
**Desarrollado con Playwright + Python**
