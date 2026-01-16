"""
Controlador del sitio Madrid Ayuntamiento.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sites.madrid.config import MadridConfig
from sites.madrid.data_models import MadridFormData, MadridTarget


class MadridController:
    site_id = "madrid"
    display_name = "Madrid Ayuntamiento"

    def create_config(self, *, headless: bool) -> MadridConfig:
        """Crea la configuración para el sitio Madrid."""
        config = MadridConfig()
        config.navegador.headless = bool(headless)
        return config

    def create_demo_data(
        self,
        *,
        headless: bool = True,
    ) -> MadridTarget:
        """
        Crea datos de demostración para el sitio Madrid.
        Por ahora solo navegación, sin datos de formulario.
        """
        return MadridTarget(
            form_data=None,  # Futuro: MadridFormData con datos de prueba
            archivos_adjuntos=[],  # Futuro: archivos de prueba
            headless=headless,
        )


def get_controller() -> MadridController:
    """Factory function para el registro de sitios."""
    return MadridController()


__all__ = ["MadridController", "get_controller"]
