"""
Script de prueba para el sistema GESDOC de autorizaciones.

Prueba el flujo completo:
1. Login en GESDOC
2. Trigger de búsqueda de cliente
3. Búsqueda de archivo en tmp_pdf
4. Movimiento a carpetas correctas
"""

import asyncio
import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Añadir el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from core.gesdoc_auth import create_gesdoc_session, trigger_client_authorization, close_gesdoc_session
from core.authorization_fetcher import (
    find_authorization_in_tmp,
    move_authorization_to_destinations,
    verify_network_access
)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("[TEST-GESDOC]")

# Cargar variables de entorno
load_dotenv()

GESDOC_USER = os.getenv("GESDOC_USER")
GESDOC_PWD = os.getenv("GESDOC_PWD")


async def test_gesdoc_login():
    """Prueba el login en GESDOC."""
    logger.info("=" * 60)
    logger.info("TEST 1: Login en GESDOC")
    logger.info("=" * 60)
    
    if not GESDOC_USER or not GESDOC_PWD:
        logger.error("❌ Faltan credenciales GESDOC_USER y/o GESDOC_PWD en .env")
        return False
    
    try:
        session = await create_gesdoc_session(GESDOC_USER, GESDOC_PWD)
        logger.info("✅ Login exitoso")
        await close_gesdoc_session(session)
        return True
    except Exception as e:
        logger.error(f"❌ Login fallido: {e}")
        return False


async def test_trigger_authorization(numclient: int):
    """Prueba el trigger de autorización para un cliente."""
    logger.info("=" * 60)
    logger.info(f"TEST 2: Trigger de autorización para cliente {numclient}")
    logger.info("=" * 60)
    
    if not GESDOC_USER or not GESDOC_PWD:
        logger.error("❌ Faltan credenciales GESDOC_USER y/o GESDOC_PWD en .env")
        return False
    
    try:
        session = await create_gesdoc_session(GESDOC_USER, GESDOC_PWD)
        success = await trigger_client_authorization(session, numclient)
        await close_gesdoc_session(session)
        
        if success:
            logger.info("✅ Trigger enviado exitosamente")
            return True
        else:
            logger.error("❌ Trigger falló")
            return False
    except Exception as e:
        logger.error(f"❌ Error en trigger: {e}")
        return False


def test_network_access():
    """Prueba el acceso a las rutas de red."""
    logger.info("=" * 60)
    logger.info("TEST 3: Verificación de acceso a rutas de red")
    logger.info("=" * 60)
    
    if verify_network_access():
        logger.info("✅ Todas las rutas de red son accesibles")
        return True
    else:
        logger.error("❌ Algunas rutas de red no son accesibles")
        return False


def test_find_authorization(numclient: int):
    """Prueba la búsqueda de autorización en tmp_pdf."""
    logger.info("=" * 60)
    logger.info(f"TEST 4: Búsqueda de autorización para cliente {numclient}")
    logger.info("=" * 60)
    
    auth_file = find_authorization_in_tmp(numclient)
    
    if auth_file:
        logger.info(f"✅ Autorización encontrada: {auth_file}")
        return True
    else:
        logger.warning(f"⚠️  No se encontró autorización para cliente {numclient}")
        return False


async def test_full_flow(numclient: int, expediente: str):
    """Prueba el flujo completo de obtención de autorización."""
    logger.info("=" * 60)
    logger.info(f"TEST 5: Flujo completo para cliente {numclient}")
    logger.info("=" * 60)
    
    # 1. Verificar acceso a red
    if not verify_network_access():
        logger.error("❌ No hay acceso a rutas de red")
        return False
    
    # 2. Buscar autorización existente
    auth_file = find_authorization_in_tmp(numclient)
    
    if not auth_file:
        logger.info("No se encontró autorización existente, generando nueva...")
        
        # 3. Login y trigger
        try:
            session = await create_gesdoc_session(GESDOC_USER, GESDOC_PWD)
            success = await trigger_client_authorization(session, numclient)
            await close_gesdoc_session(session)
            
            if not success:
                logger.error("❌ Trigger falló")
                return False
            
            # 4. Esperar generación del PDF
            logger.info("Esperando 3 segundos para generación del PDF...")
            await asyncio.sleep(3)
            
            # 5. Buscar de nuevo
            auth_file = find_authorization_in_tmp(numclient)
            
            if not auth_file:
                logger.error("❌ No se generó el archivo de autorización")
                return False
        except Exception as e:
            logger.error(f"❌ Error en flujo: {e}")
            return False
    
    # 6. Determinar tipo de cliente
    client_type = "empresa" if "Empresa" in auth_file.name else "particular"
    logger.info(f"Tipo de cliente detectado: {client_type}")
    
    # 7. Mover a carpetas correctas
    success = move_authorization_to_destinations(
        auth_file,
        expediente,
        numclient,
        client_type
    )
    
    if success:
        logger.info("✅ Flujo completo exitoso")
        return True
    else:
        logger.error("❌ Error moviendo archivos")
        return False


async def main():
    """Ejecuta todos los tests."""
    logger.info("🚀 Iniciando tests del sistema GESDOC")
    logger.info("")
    
    # Test 1: Login
    await test_gesdoc_login()
    logger.info("")
    
    # Test 2: Verificar acceso a red
    test_network_access()
    logger.info("")
    
    # Test 3: Trigger (usar un cliente de ejemplo)
    # CAMBIAR ESTE NÚMERO POR UN CLIENTE REAL
    test_numclient = 43880
    await test_trigger_authorization(test_numclient)
    logger.info("")
    
    # Test 4: Buscar autorización
    test_find_authorization(test_numclient)
    logger.info("")
    
    # Test 5: Flujo completo (descomentar cuando esté listo para probar)
    # test_expediente = "2025/191501-MUL"
    # await test_full_flow(test_numclient, test_expediente)
    
    logger.info("=" * 60)
    logger.info("✅ Tests completados")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
