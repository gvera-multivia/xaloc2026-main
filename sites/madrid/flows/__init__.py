"""
Flujos de automatización para Madrid Ayuntamiento.
"""

from sites.madrid.flows.navegacion import ejecutar_navegacion_madrid
from sites.madrid.flows.formulario import ejecutar_formulario_madrid
from sites.madrid.flows.upload import ejecutar_upload_madrid

__all__ = [
    "ejecutar_navegacion_madrid",
    "ejecutar_formulario_madrid",
    "ejecutar_upload_madrid",
]
