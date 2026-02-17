import logging

import aiohttp

from core.xvia_auth import extract_csrf_token

TELEMATICOS_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
ASIGNADO_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/Asignado"

logger = logging.getLogger("xvia_deselect")


async def deselect_resource(session: aiohttp.ClientSession, id_recurso: int) -> bool:
    """Libera un recurso en XVIA marcandolo como no seleccionado."""
    try:
        async with session.get(TELEMATICOS_URL) as response:
            html = await response.text()
            csrf_token = extract_csrf_token(html)
            if not csrf_token:
                logger.error("No se pudo extraer token CSRF para deseleccionar recurso %s", id_recurso)
                return False

        form_data = {
            "_token": csrf_token,
            "recurso_id": str(id_recurso),
            "id": str(id_recurso),
            "recursosSel": "0",
        }
        async with session.post(ASIGNADO_URL, data=form_data) as response:
            ok = response.status in (200, 302, 303)
            if ok:
                logger.info("Recurso %s deseleccionado en XVIA.", id_recurso)
            else:
                logger.error("Fallo al deseleccionar recurso %s. Status=%s", id_recurso, response.status)
            return ok
    except Exception as exc:
        logger.error("Error deseleccionando recurso %s: %s", id_recurso, exc)
        return False
