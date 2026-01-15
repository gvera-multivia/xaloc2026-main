from __future__ import annotations

from pathlib import Path

from sites.xaloc_girona.config import XalocConfig
from sites.xaloc_girona.data_models import DatosMulta


class XalocGironaController:
    site_id = "xaloc_girona"
    display_name = "Xaloc Girona"

    def create_config(self, *, headless: bool) -> XalocConfig:
        config = XalocConfig()
        config.navegador.headless = bool(headless)
        return config

    def create_demo_data(self) -> DatosMulta:
        archivos_a_enviar = [
            Path("pdfs-prueba") / "test1.pdf",
            # Path("pdfs-prueba") / "test2.pdf",
        ]
        return DatosMulta(
            email="test@example.com",
            num_denuncia="DEN/2024/001",
            matricula="1234ABC",
            num_expediente="EXP/2024/001",
            motivos="Alegación de prueba.",
            archivos_adjuntos=archivos_a_enviar,
        )


def get_controller() -> XalocGironaController:
    return XalocGironaController()


__all__ = ["XalocGironaController", "get_controller"]

