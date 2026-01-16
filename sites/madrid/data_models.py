"""
Modelos de datos para el sitio Madrid Ayuntamiento.
Versión inicial: solo navegación hasta el formulario.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MadridFormData:
    """
    Datos del formulario de Madrid (placeholder para futura implementación).
    Por ahora solo navegamos hasta el formulario.
    """
    # Campos a definir cuando se capture el HTML del formulario real
    # Por ejemplo:
    # dni: str | None = None
    # nombre: str | None = None
    # expediente: str | None = None
    # etc.
    pass


@dataclass
class MadridTarget:
    """
    Contenedor principal de datos para la automatización de Madrid.
    Similar a BaseOnlineTarget.
    """
    # Datos del formulario (futuro)
    form_data: MadridFormData | None = None
    
    # Archivos adjuntos (futuro)
    archivos_adjuntos: list[Path] = field(default_factory=list)
    
    # Metadatos de ejecución
    headless: bool = True
