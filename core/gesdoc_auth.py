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
from typing import Optional

logger = logging.getLogger("[GESDOC]")

# URLs de GESDOC
GESDOC_BASE_URL = "http://gesdoc.xvia/gesdoc"
GESDOC_LOGIN_URL = f"{GESDOC_BASE_URL}/login.php"
GESDOC_SEARCH_URL = f"{GESDOC_BASE_URL}/index.php"
GESDOC_HOME_URL = f"{GESDOC_BASE_URL}/dash.php"


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
            # Patrón: <span class="d-none d-md-inline">Hola NOMBRE <a href="cerrarsesion.php">
            match = re.search(r'Hola\s+([A-Z\s]+)\s*<a href="cerrarsesion\.php"', html)
            if match:
                user_name = match.group(1).strip()
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
    - \\server-doc\tmp_pdf\Autoriza_Particular_YYYYMMDDHHMMSS_{numclient}.pdf
    - \\server-doc\tmp_pdf\SEDES\Autoriza_Empresa_solo_YYYYMMDDHHMMSS_{numclient}.pdf
    
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
            html = await response.text()
            
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


async def close_gesdoc_session(session: aiohttp.ClientSession) -> None:
    """Cierra la sesión de GESDOC de forma limpia."""
    try:
        await session.close()
        logger.debug("Sesión de GESDOC cerrada")
    except Exception as e:
        logger.warning(f"Error cerrando sesión de GESDOC: {e}")
