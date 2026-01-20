"""
Compatibilidad: utilidades históricas para popups nativos de Windows.

Este proyecto ya NO usa PyAutoGUI. La selección de certificados se resuelve con
políticas de Edge (AutoSelectCertificateForUrls) y perfil persistente.

Las funciones se conservan para no romper imports antiguos, pero no hacen nada.
"""

from __future__ import annotations

import logging


def dialogo_certificado_presente() -> bool:
    return False


def aceptar_popup_certificado(*, tabs_atras: int = 2, delay_inicial: float = 0.0) -> bool:
    logging.warning("aceptar_popup_certificado() deshabilitado (PyAutoGUI eliminado).")
    return False


def enviar_shift_tab_enter(tabs_atras: int = 2, *, evitar_browser: bool = True) -> bool:
    logging.warning("enviar_shift_tab_enter() deshabilitado (PyAutoGUI eliminado).")
    return False


def confirmar_reenvio_formulario(*, delay_inicial: float = 1.0) -> bool:
    logging.warning("confirmar_reenvio_formulario() deshabilitado (PyAutoGUI eliminado).")
    return False


def esperar_y_aceptar_certificado(timeout: float = 20.0, delay_inicial: float = 5.0) -> bool:
    logging.warning("esperar_y_aceptar_certificado() deshabilitado (PyAutoGUI eliminado).")
    return False


def navegar_y_aceptar_certificado(tabs_atras: int = 2) -> bool:
    logging.warning("navegar_y_aceptar_certificado() deshabilitado (PyAutoGUI eliminado).")
    return False


__all__ = [
    "aceptar_popup_certificado",
    "confirmar_reenvio_formulario",
    "dialogo_certificado_presente",
    "enviar_shift_tab_enter",
    "esperar_y_aceptar_certificado",
    "navegar_y_aceptar_certificado",
]

