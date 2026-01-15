"""
Utilidades para automatizar popups nativos de Windows.
Usa pyautogui para enviar teclas al sistema operativo.
"""

import time
import logging
import pyautogui

# Configurar pyautogui para seguridad
pyautogui.FAILSAFE = True  # Mover ratón a esquina superior izquierda para abortar
pyautogui.PAUSE = 0.1  # Pausa entre acciones


def esperar_y_aceptar_certificado(timeout: float = 10.0, delay_inicial: float = 2.0) -> bool:
    """
    Espera a que aparezca el popup de selección de certificado de Windows
    y lo acepta automáticamente.
    
    Args:
        timeout: Tiempo máximo de espera en segundos
        delay_inicial: Tiempo a esperar antes de intentar (para que aparezca el popup)
        
    Returns:
        True si se envió Enter, False si hubo error
    """
    try:
        # 1. Espera crucial: da tiempo a que el popup se dibuje y gane foco
        logging.info(f"⏳ Esperando {delay_inicial}s a que aparezca el popup...")
        time.sleep(delay_inicial)
        
        # 2. Navegar por el popup con Shift+Tab
        logging.info("⌨️ Navegando por el diálogo con Shift+Tab x2...")
        pyautogui.hotkey('shift', 'tab')
        time.sleep(0.5)
        pyautogui.hotkey('shift', 'tab')
        time.sleep(0.3)
        
        # 3. Confirmar con Enter
        logging.info("⌨️ Enviando ENTER al popup de Windows...")
        pyautogui.press('enter')
        
        logging.info("✅ Secuencia de teclas enviada correctamente")
        return True
        
    except Exception as e:
        logging.error(f"❌ Error al interactuar con el popup: {e}")
        return False


def navegar_y_aceptar_certificado(tabs_atras: int = 2) -> bool:
    """
    Navega el popup de certificados usando Shift+Tab y acepta.
    
    Args:
        tabs_atras: Número de Shift+Tab para navegar hacia atrás
        
    Returns:
        True si se completó, False si hubo error
    """
    logging.info(f"⌨️ Navegando popup con {tabs_atras} Shift+Tab...")
    
    try:
        # Pequeña pausa inicial para que el popup tenga focus
        time.sleep(2.0)
        
        # Navegar hacia atrás
        for i in range(tabs_atras):
            pyautogui.hotkey('shift', 'tab')
            time.sleep(0.3)
            logging.info(f"  Shift+Tab {i+1}/{tabs_atras}")
        
        # Pulsar Enter para aceptar
        time.sleep(0.3)
        pyautogui.press('enter')
        logging.info("✅ ENTER enviado")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Error: {e}")
        return False
