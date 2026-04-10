# Site Code Mapping

## Mapa base

### `sites/<site_id>/config.py`

- URLs
- selectores
- timeouts
- flags de comportamiento browser

### `sites/<site_id>/controller.py`

- transforma payload Xaloc en modelo del site
- mirar aqui si el formulario falla por datos faltantes o formato inesperado

### `sites/<site_id>/automation.py`

- secuencia principal del tramite
- punto de entrada para seguir el orden real del flujo

### `sites/<site_id>/flows/login.py`

- login, certificado, pre-home, cookies, redirecciones iniciales

### `sites/<site_id>/flows/formulario.py`

- navegacion y relleno principal

### `sites/<site_id>/flows/documentos.py`

- subida de adjuntos
- firma
- validaciones de documento

### `sites/<site_id>/flows/confirmacion.py`

- submit final
- justificante
- numero de registro
- comprobaciones post-envio

## Regla practica

- si MCP no encuentra el elemento: mirar `config.py` y el flow del paso
- si el elemento existe pero la accion no avanza: mirar espera, popup, red o JS
- si la UI pide un dato inesperado: mirar `controller.py`
