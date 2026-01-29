#!/usr/bin/env python
"""
test_login_simple.py - Test minimalista que replica EXACTAMENTE el worker.

Este script hace login de la misma forma que worker.py para diagnosticar
por qué test_brain.py falla.
"""

import asyncio
import os
import aiohttp
from dotenv import load_dotenv
from core.xvia_auth import create_authenticated_session_in_place

load_dotenv()

async def main():
    email = os.getenv("XVIA_EMAIL")
    password = os.getenv("XVIA_PASSWORD")
    
    print("=" * 60)
    print("TEST DE LOGIN SIMPLE (réplica exacta del worker)")
    print("=" * 60)
    print(f"Email: {email}")
    print(f"Password: {'*' * len(password) if password else 'None'}")
    print()
    
    # Configuración EXACTA del worker (líneas 304-314)
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/login",
        "Origin": "http://www.xvia-grupoeuropa.net",
        "DNT": "1",
        "Connection": "keep-alive",
    }
    
    async with aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar) as session:
        try:
            print("Intentando login...")
            # Llamada EXACTA del worker (línea 320) - SIN pasar login_url
            await create_authenticated_session_in_place(session, email, password)
            print("✅ LOGIN EXITOSO")
            print(f"Cookies: {len(session.cookie_jar)}")
            return 0
        except Exception as e:
            print(f"❌ LOGIN FALLÓ: {e}")
            return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    print("=" * 60)
    exit(exit_code)
