"""
Re-export de flujos para Ayunta Palma.
"""

from sites.ayunta_palma.flows.alegaciones import completar_alegaciones
from sites.ayunta_palma.flows.documentos import subir_documentos
from sites.ayunta_palma.flows.interesado import registrar_interesado
from sites.ayunta_palma.flows.login import ejecutar_login
from sites.ayunta_palma.flows.representante import indicar_representante

__all__ = [
    "ejecutar_login",
    "registrar_interesado",
    "indicar_representante",
    "completar_alegaciones",
    "subir_documentos",
]
