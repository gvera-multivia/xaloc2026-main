"""
Módulo de autenticación y operaciones con GESDOC.

GESDOC es el sistema de gestión documental que permite solicitar
autorizaciones de clientes cuando no están disponibles localmente.

Flujo:
1. Login en http://gesdoc.xvia/gesdoc/login.php
2. POST búsqueda de cliente en http://gesdoc.xvia/gesdoc/index.php
3. El sistema genera el PDF de autorización en \\server-doc\tmp_pdf
"""

import aiohttp
import logging
import re
from urllib.parse import urljoin
from typing import Any, Optional

logger = logging.getLogger("[GESDOC]")

# URLs de GESDOC
GESDOC_BASE_URL = "http://gesdoc.xvia/gesdoc"
GESDOC_LOGIN_URL = f"{GESDOC_BASE_URL}/login.php"
GESDOC_SEARCH_URL = f"{GESDOC_BASE_URL}/index.php"
GESDOC_HOME_URL = f"{GESDOC_BASE_URL}/dash.php"
_GESDOC_USER_RE = re.compile(r'Hola\s+([^<]+?)\s*<a href="cerrarsesion\.php"', re.IGNORECASE)
_GESDOC_SENT_RE = re.compile(r"Solicitud\s+Enviada\s+el\s+([^<]+)", re.IGNORECASE)
_GESDOC_HREF_RE = re.compile(r"""href=['"]([^'"]+)['"]""", re.IGNORECASE)


def extract_gesdoc_logged_user(html: str) -> Optional[str]:
    match = _GESDOC_USER_RE.search(html or "")
    if not match:
        return None
    return " ".join(match.group(1).split()).strip() or None


def extract_gesdoc_sent_requests(html: str) -> list[str]:
    matches = _GESDOC_SENT_RE.findall(html or "")
    out: list[str] = []
    for value in matches:
        text = " ".join(str(value or "").split()).strip()
        if text:
            out.append(text)
    return out


def extract_gesdoc_action_links(html: str, numclient: int) -> dict[str, str]:
    client_token = f"cliente={numclient}"
    links: dict[str, str] = {}
    for href in _GESDOC_HREF_RE.findall(html or ""):
        href_text = str(href or "").strip()
        if not href_text or client_token not in href_text:
            continue
        absolute_href = urljoin(f"{GESDOC_BASE_URL}/", href_text)
        if "carta.php?" in href_text and "plantilla=" in href_text:
            links.setdefault("send", absolute_href)
            continue
        if "generarautorizaciones.php?" not in href_text:
            continue
        if "plantilla=1" in href_text:
            links.setdefault("generate_company", absolute_href)
        elif "plantilla=2" in href_text:
            links.setdefault("generate_particular", absolute_href)
    return links


async def create_gesdoc_session(username: str, password: str) -> aiohttp.ClientSession:
    """
    Crea una sesión autenticada en GESDOC.
    
    Args:
        username: Usuario de GESDOC (desde .env: GESDOC_USER)
        password: Contraseña de GESDOC (desde .env: GESDOC_PWD)
    
    Returns:
        ClientSession autenticada con cookies válidas
    
    Raises:
        ValueError: Si el login falla
    """
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": GESDOC_BASE_URL,
        "Origin": "http://gesdoc.xvia",
        "Connection": "keep-alive",
    }
    
    session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar)
    
    try:
        # Preparar datos de login
        login_data = {
            "username": username,
            "password": password,
            "login": ""  # El botón submit
        }
        
        logger.info(f"Intentando login en GESDOC como: {username}")
        
        # Hacer POST al login
        async with session.post(GESDOC_LOGIN_URL, data=login_data, allow_redirects=True) as response:
            final_url = str(response.url)
            html = await response.text()
            
            # Verificar si el login fue exitoso
            # Si redirige a dash.php o index.php, es exitoso
            # Si vuelve a login.html, falló
            if "login.html" in final_url or "login.php" in final_url:
                logger.error("Login fallido en GESDOC - Credenciales incorrectas")
                await session.close()
                raise ValueError("Login fallido en GESDOC")
            
            # Verificar que estamos autenticados buscando el nombre en el HTML
            user_name = extract_gesdoc_logged_user(html)
            if user_name:
                logger.info(f"✓ Login exitoso en GESDOC como: {user_name}")
            else:
                logger.warning("Login en GESDOC - No se pudo verificar el nombre de usuario")
            
            return session
            
    except Exception as e:
        await session.close()
        logger.error(f"Error durante login en GESDOC: {e}")
        raise


async def trigger_client_authorization(
    session: aiohttp.ClientSession, 
    numclient: int
) -> bool:
    """
    Envía POST para generar la autorización del cliente en GESDOC.
    
    Este POST hace que GESDOC genere el PDF de autorización en:
    - \\\\server-doc\\tmp_pdf\\Autoriza_Particular_YYYYMMDDHHMMSS_{numclient}.pdf
    - \\\\server-doc\\tmp_pdf\\SEDES\\Autoriza_Empresa_solo_YYYYMMDDHHMMSS_{numclient}.pdf
    
    Args:
        session: Sesión autenticada de GESDOC
        numclient: Número de cliente (ej: 43880)
    
    Returns:
        True si el POST fue exitoso, False en caso contrario
    """
    try:
        search_data = {
            "cliente": str(numclient)
        }
        
        logger.info(f"Solicitando generación de autorización para cliente: {numclient}")
        
        async with session.post(GESDOC_SEARCH_URL, data=search_data, allow_redirects=True) as response:
            await response.text()
            
            # Verificar que la búsqueda fue procesada
            # El sistema debería mostrar algún resultado o confirmación
            if response.status == 200:
                logger.info(f"✓ Solicitud de autorización enviada para cliente {numclient}")
                return True
            else:
                logger.error(f"Error en solicitud de autorización: HTTP {response.status}")
                return False
                
    except Exception as e:
        logger.error(f"Error al solicitar autorización para cliente {numclient}: {e}")
        return False


async def search_client_in_gesdoc(
    session: aiohttp.ClientSession,
    numclient: int,
) -> dict[str, Any]:
    search_data = {"cliente": str(numclient)}

    async with session.post(GESDOC_SEARCH_URL, data=search_data, allow_redirects=True) as response:
        html = await response.text()
        sent_entries = extract_gesdoc_sent_requests(html)
        return {
            "status_code": int(response.status),
            "final_url": str(response.url),
            "html": html,
            "logged_user": extract_gesdoc_logged_user(html),
            "sent_request_entries": sent_entries,
            "has_sent_request": bool(sent_entries),
            "has_client_number": f"Num. Cliente: <b>{numclient}</b>" in html,
            "action_links": extract_gesdoc_action_links(html, numclient),
        }


async def execute_gesdoc_action(session: aiohttp.ClientSession, action_url: str) -> dict[str, Any]:
    async with session.get(action_url, allow_redirects=True) as response:
        body = await response.read()
        content_type = str(response.headers.get("Content-Type") or "application/octet-stream")
        return {
            "status_code": int(response.status),
            "final_url": str(response.url),
            "content_type": content_type,
            "content_disposition": str(response.headers.get("Content-Disposition") or ""),
            "body": body,
            "text": body.decode("utf-8", errors="replace") if content_type.startswith("text/") or "html" in content_type else "",
        }


async def close_gesdoc_session(session: aiohttp.ClientSession) -> None:
    """Cierra la sesión de GESDOC de forma limpia."""
    try:
        await session.close()
        logger.debug("Sesión de GESDOC cerrada")
    except Exception as e:
        logger.warning(f"Error cerrando sesión de GESDOC: {e}")
