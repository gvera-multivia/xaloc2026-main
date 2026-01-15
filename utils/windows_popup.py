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


def esperar_y_aceptar_certificado(timeout: float = 10.0, delay_inicial: float = 1.5) -> bool:
    """
    Espera a que aparezca el popup de selección de certificado de Windows
    y lo acepta automáticamente.
    
    El popup de Windows tiene esta estructura:
    - Lista de certificados (el primero ya está seleccionado)
    - Botón "Aceptar" (generalmente tiene el focus por defecto)
    - Botón "Cancelar"
    
    Args:
        timeout: Tiempo máximo de espera en segundos
        delay_inicial: Tiempo a esperar antes de intentar (para que aparezca el popup)
        
    Returns:
        True si se envió Enter, False si hubo error
    """
try:
        # 1. Espera crucial: da tiempo a que el popup se dibuje y gane foco
        logging.info("⏳ Esperando 2 segundos a que aparezca el popup...")
        time.sleep(2) 
        
        # 2. Navegar por el popup
        # Usamos hotkey para combinaciones de teclas
        logging.info("⌨️ Navegando por el diálogo con Shift+Tab...")
        pyautogui.hotkey('shift', 'tab')
        time.sleep(0.5) # Pequeña pausa entre pulsaciones para mayor estabilidad
        pyautogui.hotkey('shift', 'tab')
        
        # 3. Confirmar
        logging.info("⌨️ Enviando ENTER al popup de Windows...")
        pyautogui.press('enter')
        
        logging.info("✅ ENTER enviado correctamente")
        return True
        
    except Exception as e:
        logging.error(f"❌ Error al interactuar con el popup: {e}")
        return False


def navegar_y_aceptar_certificado(tabs_atras: int = 0) -> bool:
    """
    Navega el popup de certificados usando Tab/Shift+Tab y acepta.
    
    Args:
        tabs_atras: Número de Shift+Tab para navegar hacia atrás
        
    Returns:
        True si se completó, False si hubo error
    """
    logging.info(f"⌨️ Navegando popup con {tabs_atras} Shift+Tab...")
    
    try:
        # Pequeña pausa inicial
        time.sleep(1.5)
        
        # Navegar hacia atrás si es necesario
        for i in range(tabs_atras):
            pyautogui.hotkey('shift', 'tab')
            time.sleep(0.2)
            logging.info(f"  Shift+Tab {i+1}/{tabs_atras}")
        
        # Pulsar Enter para aceptar
        time.sleep(0.3)
        pyautogui.press('enter')
        logging.info("✅ ENTER enviado")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Error: {e}")
        return False
