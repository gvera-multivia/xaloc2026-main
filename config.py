"""
Compatibilidad.

El proyecto ahora soporta múltiples sitios bajo `sites/` y un núcleo común en `core/`.
Este módulo mantiene imports antiguos: `from config import Config, DatosMulta`.
"""

from sites.xaloc_girona.config import XalocConfig as Config
from sites.xaloc_girona.data_models import DatosMulta

__all__ = ["Config", "DatosMulta"]

