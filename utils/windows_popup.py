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


def _activar_ventana_activa() -> None:
    """
    Best-effort: intenta asegurar que la ventana activa tiene el foco.
    PyAutoGUI integra PyGetWindow en Windows y expone getActiveWindow().
    """
    try:
        win = pyautogui.getActiveWindow()
        if win:
            try:
                win.activate()
            except Exception:
                pass
    except Exception:
        pass


def _titulo_ventana_activa() -> str:
    try:
        win = pyautogui.getActiveWindow()
        return (win.title or "") if win else ""
    except Exception:
        return ""


def _buscar_ventana_certificado():
    """
    Intenta localizar el diálogo nativo de selección de certificado.
    Devuelve la ventana (PyGetWindow) o None.
    """
    posibles = [
        "Seleccionar un certificado",
        "Seleccionar certificado",
        "certificado para la autenticación",
        "Select a certificate",
        "certificate",
        "certificado",
    ]
    try:
        for texto in posibles:
            wins = pyautogui.getWindowsWithTitle(texto)
            if wins:
                return wins[0]
    except Exception:
        return None
    return None


def dialogo_certificado_presente() -> bool:
    return _buscar_ventana_certificado() is not None


def aceptar_popup_certificado(*, tabs_atras: int = 2, delay_inicial: float = 0.0) -> bool:
    """
    Acepta el popup de certificado: Shift+Tab xN + Enter.
    Prioriza activar el diálogo de certificado si se encuentra.
    """
    try:
        time.sleep(max(0.0, delay_inicial))
        win = _buscar_ventana_certificado()
        if win:
            try:
                win.activate()
            except Exception:
                pass
        else:
            _activar_ventana_activa()

        for _ in range(tabs_atras):
            pyautogui.hotkey("shift", "tab")
            time.sleep(0.2)
        pyautogui.press("enter")
        return True
    except Exception as e:
        logging.error(f"Error aceptando popup de certificado: {e}")
        return False


def enviar_shift_tab_enter(tabs_atras: int = 2, *, evitar_browser: bool = True) -> bool:
    """
    Envía Shift+Tab xN y Enter.
    Útil para aceptar diálogos nativos (p.ej. selección de certificado) sin sleeps internos.
    """
    try:
        win = _buscar_ventana_certificado()
        if win:
            try:
                win.activate()
            except Exception:
                pass
        else:
            _activar_ventana_activa()
            titulo = _titulo_ventana_activa().lower()
            if evitar_browser and any(x in titulo for x in ("chrome", "edge", "firefox", "opera", "brave")):
                logging.warning("Ventana activa parece ser el navegador; abortando Shift+Tab/Enter.")
                return False

        for _ in range(tabs_atras):
            pyautogui.hotkey("shift", "tab")
            time.sleep(0.2)
        pyautogui.press("enter")
        return True
    except Exception as e:
        logging.error(f"Error enviando Shift+Tab/Enter: {e}")
        return False


def confirmar_reenvio_formulario(*, delay_inicial: float = 1.0) -> bool:
    """
    Confirma el reenvío de formulario tras un refresh.
    Secuencia: TAB -> ENTER
    """
    try:
        time.sleep(max(0.0, delay_inicial))
        _activar_ventana_activa()
        pyautogui.press("tab")
        time.sleep(0.2)
        pyautogui.press("enter")
        return True
    except Exception as e:
        logging.error(f"Error confirmando reenvío de formulario: {e}")
        return False


def esperar_y_aceptar_certificado(timeout: float = 20.0, delay_inicial: float = 5.0) -> bool:
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
        _activar_ventana_activa()
        titulo = _titulo_ventana_activa().lower()
        if any(x in titulo for x in ("chrome", "edge", "firefox", "opera", "brave")):
            logging.warning("Ventana activa parece ser el navegador; no se envían teclas al popup.")
            return False
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
        time.sleep(3.0)
        
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
