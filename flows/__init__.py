"""
Módulo de flujos de automatización para Xaloc
"""
from sites.xaloc_girona.flows import confirmar_tramite, ejecutar_login, rellenar_formulario, subir_documento

__all__ = ["ejecutar_login", "rellenar_formulario", "subir_documento", "confirmar_tramite"]
