"""
Script de prueba de integración para el sistema GESDOC.

Valida que la integración completa funcione correctamente:
1. Autenticación en GESDOC
2. Determinación de tipo de cliente desde SQL Server
3. Búsqueda de autorizaciones en carpetas temporales
4. Trigger de generación de autorización
5. Movimiento de archivos a carpetas correctas
"""

import asyncio
import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Añadir el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from core.client_documentation import build_required_client_documents_for_payload
from core.sqlserver_utils import build_sqlserver_connection_string

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("[TEST-GESDOC-INTEGRATION]")

# Cargar variables de entorno
load_dotenv()

GESDOC_USER = os.getenv("GESDOC_USER")
GESDOC_PWD = os.getenv("GESDOC_PWD")


async def test_integration_with_missing_docs():
    """
    Prueba el flujo completo cuando NO hay documentación local.
    
    Este test simula el escenario donde:
    - El worker intenta procesar un recurso
    - No encuentra documentación del cliente
    - El sistema automáticamente usa GESDOC para obtenerla
    """
    logger.info("=" * 60)
    logger.info("TEST: Integración completa con documentación faltante")
    logger.info("=" * 60)
    
    # IMPORTANTE: Cambiar estos valores por un cliente real de prueba
    test_payload = {
        "numclient": 43880,  # ⚠️ CAMBIAR por número de cliente real
        "expediente": "2025/191501-MUL",  # ⚠️ CAMBIAR por expediente real
        "idRecurso": 88573,
        "sujeto_recurso": "NOMBRE DEL CLIENTE",
        "fase_procedimiento": "identificacion"
    }
    
    logger.info(f"Payload de prueba: {test_payload}")
    
    if not GESDOC_USER or not GESDOC_PWD:
        logger.error("❌ Faltan credenciales GESDOC_USER y/o GESDOC_PWD en .env")
        return False
    
    try:
        # Llamar a la función integrada
        docs = await build_required_client_documents_for_payload(
            test_payload,
            gesdoc_user=GESDOC_USER,
            gesdoc_pwd=GESDOC_PWD,
            sqlserver_conn_str=build_sqlserver_connection_string(),
            strict=True,
            merge_if_multiple=False
        )
        
        logger.info(f"✅ Documentos obtenidos: {len(docs)}")
        for doc in docs:
            logger.info(f"   - {doc.name} ({doc.stat().st_size} bytes)")
        
        return True
        
    except ValueError as e:
        error_msg = str(e)
        if "No se pudo obtener autorización" in error_msg:
            logger.error(f"❌ Error de GESDOC: {e}")
        elif "Credenciales GESDOC no configuradas" in error_msg:
            logger.error(f"❌ GESDOC no configurado: {e}")
        else:
            logger.error(f"❌ Error de validación: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_integration_with_existing_docs():
    """
    Prueba el flujo cuando SÍ hay documentación local.
    
    En este caso, GESDOC NO debería ser llamado.
    """
    logger.info("=" * 60)
    logger.info("TEST: Integración con documentación existente")
    logger.info("=" * 60)
    
    # IMPORTANTE: Cambiar por un cliente que SÍ tenga documentación
    test_payload = {
        "numclient": 12345,  # ⚠️ CAMBIAR por cliente con docs
        "expediente": "2025/123456-MUL",
        "idRecurso": 99999,
        "cliente_nombre": "Juan",
        "cliente_apellido1": "Pérez",
        "cliente_apellido2": "García",
        "fase_procedimiento": "identificacion"
    }
    
    logger.info(f"Payload de prueba: {test_payload}")
    
    try:
        docs = await build_required_client_documents_for_payload(
            test_payload,
            gesdoc_user=GESDOC_USER,
            gesdoc_pwd=GESDOC_PWD,
            sqlserver_conn_str=build_sqlserver_connection_string(),
            strict=True,
            merge_if_multiple=False
        )
        
        logger.info(f"✅ Documentos obtenidos: {len(docs)}")
        for doc in docs:
            logger.info(f"   - {doc.name}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return False


async def main():
    """Ejecuta todos los tests de integración."""
    logger.info("🚀 Iniciando tests de integración GESDOC")
    logger.info("")
    
    # Test 1: Con documentación faltante (usa GESDOC)
    logger.info("⚠️  NOTA: Asegúrate de configurar GESDOC_USER y GESDOC_PWD en .env")
    logger.info("⚠️  NOTA: Cambia los valores de test_payload por datos reales")
    logger.info("")
    
    # Descomentar cuando estés listo para probar
    # result1 = await test_integration_with_missing_docs()
    # logger.info("")
    
    # Test 2: Con documentación existente (no usa GESDOC)
    # result2 = await test_integration_with_existing_docs()
    # logger.info("")
    
    logger.info("=" * 60)
    logger.info("⚠️  Tests comentados - Descomentar cuando esté listo para probar")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
