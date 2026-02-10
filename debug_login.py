#!/usr/bin/env python
"""
debug_login.py - Script de diagnóstico para verificar credenciales.

Este script muestra exactamente qué se está enviando al servidor.
"""

import os
from dotenv import load_dotenv

load_dotenv()

email = os.getenv("XVIA_EMAIL")
password = os.getenv("XVIA_PASSWORD")

print("=" * 60)
print("DIAGNÓSTICO DE CREDENCIALES")
print("=" * 60)
print(f"Email: '{email}'")
print(f"  - Longitud: {len(email) if email else 0}")
print(f"  - Después de strip: '{email.strip() if email else ''}'")
print(f"  - Longitud después de strip: {len(email.strip()) if email else 0}")
print()
print(f"Password: '{password}'")
print(f"  - Longitud: {len(password) if password else 0}")
print(f"  - Después de strip: '{password.strip() if password else ''}'")
print(f"  - Longitud después de strip: {len(password.strip()) if password else 0}")
print(f"  - Bytes: {password.encode('utf-8') if password else b''}")
print()
print("Caracteres especiales en password:")
if password:
    for i, char in enumerate(password):
        print(f"  [{i}] '{char}' (ord={ord(char)})")
print("=" * 60)
