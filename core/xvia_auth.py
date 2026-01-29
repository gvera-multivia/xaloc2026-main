import logging
import re
from typing import Optional
import aiohttp
from pathlib import Path

logger = logging.getLogger("worker")

LOGIN_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/login"

def extract_csrf_token(html: str) -> Optional[str]:
    """
    Extrae el token CSRF buscando el input con name="_token".
    Soporta diferentes órdenes de atributos y comillas simples/dobles.
    """
    # Esta regex es mucho más robusta:
    # 1. Busca la etiqueta <input
    # 2. Se asegura de que contenga name="_token"
    # 3. Captura el contenido de value="..."
    match = re.search(r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']', html)
    if not match:
        # Intento alternativo por si 'value' aparece antes que 'name'
        match = re.search(r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']_token["\']', html)
    
    return match.group(1) if match else None

async def create_authenticated_session(
    email: str,
    password: str,
    login_url: str = LOGIN_URL,
    timeout_seconds: int = 30
) -> aiohttp.ClientSession:
    # Es vital usar un User-Agent real para que el servidor no rechace la petición
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    session = aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=timeout_seconds)
    )
    
    try:
        # 1. Obtener la página de login para extraer el token
        async with session.get(login_url) as response:
            if response.status != 200:
                raise RuntimeError(f"No se pudo cargar la página de login. Status: {response.status}")
            login_page = await response.text()

        token = extract_csrf_token(login_page)
        if not token:
            # Depuración: Si falla, guardamos una muestra del HTML para inspección
            logger.error("Token CSRF no encontrado. Revisando HTML...")
            with open("logs/debug_login.html", "w", encoding="utf-8") as f:
                f.write(login_page[:2000]) # Guardamos solo el inicio para debug
            raise RuntimeError("CSRF token not found in login page. HTML guardado en logs/debug_login.html")

        # 2. Preparar los datos del formulario
        data = {
            "_token": token,
            "email": email,
            "password": password,
            "remember": "on",
        }

        # 3. Realizar el POST del Login
        # Importante: allow_redirects=False porque Laravel suele responder con un 302 hacia el dashboard
        async with session.post(login_url, data=data, allow_redirects=False) as response:
            if response.status in (302, 303):
                logger.info(f"XVIA login succeeded (Status {response.status}).")
                return session
            
            # Si llegamos aquí con un 200, es que el login falló (nos devolvió a la misma página)
            if response.status == 200:
                 raise RuntimeError("Login failed: Credenciales incorrectas o sesión expirada.")
            
            raise RuntimeError(f"Login failed with status {response.status}.")

    except Exception as e:
        await session.close()
        logger.error(f"Error crítico en create_authenticated_session: {e}")
        raise

async def create_authenticated_session_in_place(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    login_url: str = LOGIN_URL
) -> None:
    # 1. Obtener la página de login
    async with session.get(login_url) as response:
        html = await response.text()
        
    token = extract_csrf_token(html)
    if not token:
        raise RuntimeError("No se pudo extraer el token CSRF del HTML.")

    # 2. Datos del POST (Asegúrate de que no hay espacios en las credenciales)
    data = {
        "_token": token,
        "email": email.strip(),
        "password": password.strip(),
        "remember": "on",
    }

    logger.info(f"Intentando login para: {email} (Token: {token[:8]}...)")

    # 3. POST Login
    # Usamos allow_redirects=True para ver a dónde nos manda el servidor
    async with session.post(login_url, data=data, allow_redirects=True) as response:
        final_html = await response.text()
        final_url = str(response.url)
        
        # SI VOLVEMOS AL LOGIN: El servidor rechazó las credenciales
        if "login" in final_url.lower() and response.status == 200:
            # Guardamos el HTML para que veas el mensaje de error (ej: "Estas credenciales no coinciden")
            debug_path = Path("logs/error_login_last.html")
            debug_path.write_text(final_html, encoding="utf-8")
            
            # Buscamos mensajes de error comunes en Laravel
            error_msg = "Credenciales incorrectas o sesión rechazada por el servidor."
            if "invalid" in final_html.lower() or "coinciden" in final_html.lower():
                error_msg = "ERROR DE XVIA: El correo o la contraseña no son válidos."
                
            raise RuntimeError(f"{error_msg} Revisa logs/error_login_last.html")

        if response.status == 200 or "home" in final_url or "dashboard" in final_url:
            logger.info(f"XVIA Login OK. Entramos en: {final_url}")
            return

        raise RuntimeError(f"Fallo inesperado. Status: {response.status}, URL: {final_url}")