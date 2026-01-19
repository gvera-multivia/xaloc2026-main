"""
Utilidades para automatizar popups nativos de Windows.
Usa pyautogui para enviar teclas al sistema operativo.
"""

import time
import logging
import ctypes
from ctypes import wintypes

import pyautogui

# Configurar pyautogui para seguridad
pyautogui.FAILSAFE = True  # Mover ratón a esquina superior izquierda para abortar
pyautogui.PAUSE = 0.1  # Pausa entre acciones


def _detectar_ventana_certificado() -> bool:
    """
    Detecta si hay una ventana de selección de certificado de Windows activa.
    
    Busca ventanas con títulos típicos del diálogo de certificados:
    - "Seguridad de Windows" (español)
    - "Windows Security" (inglés)
    - "Seleccionar un certificado" (español)
    - "Select a Certificate" (inglés)
    
    Returns:
        True si se detecta una ventana de certificados, False en caso contrario
    """
    try:
        # Obtener el handle de la ventana activa
        user32 = ctypes.windll.user32
        
        # Obtener la ventana en primer plano
        hwnd = user32.GetForegroundWindow()
        
        if hwnd:
            # Obtener el título de la ventana
            length = user32.GetWindowTextLengthW(hwnd) + 1
            buffer = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buffer, length)
            titulo = buffer.value.lower()
            
            # Lista de títulos que indican el diálogo de certificados
            titulos_certificado = [
                "seguridad de windows",
                "windows security",
                "seleccionar un certificado",
                "select a certificate",
                "certificado",
                "certificate",
            ]
            
            for titulo_buscar in titulos_certificado:
                if titulo_buscar in titulo:
                    logging.info(f"✓ Ventana de certificado detectada: '{buffer.value}'")
                    return True
            
            logging.debug(f"Ventana activa: '{buffer.value}' (no es certificado)")
            return False
            
    except Exception as e:
        logging.debug(f"Error detectando ventana: {e}")
    
    return False


def esperar_y_aceptar_certificado(timeout: float = 15.0, delay_inicial: float = 4.0) -> bool:
    """
    Espera a que aparezca el popup de selección de certificado de Windows
    y lo acepta automáticamente.
    
    IMPORTANTE: Solo envía las teclas si detecta que la ventana de certificados
    está realmente abierta. Si no aparece (ej: página de redirección), no hace nada.
    
    Args:
        timeout: Tiempo máximo de espera en segundos
        delay_inicial: Tiempo a esperar antes de intentar (para que aparezca el popup)
        
    Returns:
        True si se envió Enter, False si hubo error o no apareció el diálogo
    """
    try:
        # 1. Espera inicial más larga para dar tiempo a la pasarela
        logging.info(f"⏳ Esperando {delay_inicial}s a que aparezca el popup de certificado...")
        time.sleep(delay_inicial)
        
        # 2. Intentar detectar la ventana de certificados durante el timeout
        inicio = time.time()
        ventana_detectada = False
        
        while time.time() - inicio < timeout:
            if _detectar_ventana_certificado():
                ventana_detectada = True
                break
            # Esperar un poco antes de volver a comprobar
            time.sleep(0.5)
        
        # 3. Si no se detectó la ventana, no hacer nada
        if not ventana_detectada:
            logging.info("ℹ️ No se detectó ventana de certificados (puede ser redirección automática)")
            logging.info("ℹ️ No se envían teclas para evitar interferencias")
            return False
        
        # 4. Pequeña pausa adicional para asegurar que el diálogo tiene foco
        time.sleep(0.5)
        
        # 5. Navegar por el popup con Shift+Tab
        logging.info("⌨️ Navegando por el diálogo con Shift+Tab x2...")
        pyautogui.hotkey('shift', 'tab')
        time.sleep(0.5)
        pyautogui.hotkey('shift', 'tab')
        time.sleep(0.3)
        
        # 6. Confirmar con Enter
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
        # Espera inicial más larga
        time.sleep(3.0)
        
        # Verificar si hay ventana de certificados
        if not _detectar_ventana_certificado():
            logging.info("ℹ️ No se detectó ventana de certificados, saltando...")
            return False
        
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
