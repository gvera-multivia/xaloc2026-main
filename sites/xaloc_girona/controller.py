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

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genéricas de DB a argumentos de create_target.
        """
        return {
            "email": data.get("email") or data.get("user_email"),
            "num_denuncia": data.get("num_denuncia") or data.get("denuncia_num"),
            "matricula": data.get("matricula") or data.get("plate_number"),
            "num_expediente": data.get("num_expediente") or data.get("expediente_num"),
            "motivos": data.get("motivos"),
            # En un caso real, los archivos podrían venir de otra forma o descargarse
            "archivos_adjuntos": data.get("archivos_adjuntos") or data.get("archivos")
        }

    def create_target(
        self,
        email: str | None = None,
        num_denuncia: str | None = None,
        matricula: str | None = None,
        num_expediente: str | None = None,
        motivos: str | None = None,
        archivos_adjuntos: list[Path] | list[str] | None = None,
        **kwargs
    ) -> DatosMulta:
        if not archivos_adjuntos:
            archivos_adjuntos = [Path("pdfs-prueba") / "test1.pdf"]

        # Asegurar que sean Path
        paths = []
        for a in archivos_adjuntos:
            if isinstance(a, str):
                paths.append(Path(a))
            else:
                paths.append(a)

        return DatosMulta(
            email=email or "test@example.com",
            num_denuncia=num_denuncia or "DEN/2024/001",
            matricula=matricula or "1234ABC",
            num_expediente=num_expediente or "EXP/2024/001",
            motivos=motivos or "Alegación de prueba.",
            archivos_adjuntos=paths,
        )

    def create_target_strict(
        self,
        email: str | None = None,
        num_denuncia: str | None = None,
        matricula: str | None = None,
        num_expediente: str | None = None,
        motivos: str | None = None,
        archivos_adjuntos: list[Path] | list[str] | None = None,
        **kwargs
    ) -> DatosMulta:
        paths = []
        if archivos_adjuntos:
            for a in archivos_adjuntos:
                if isinstance(a, str):
                    paths.append(Path(a))
                else:
                    paths.append(a)

        return DatosMulta(
            email=email or "",
            num_denuncia=num_denuncia or "",
            matricula=matricula or "",
            num_expediente=num_expediente or "",
            motivos=motivos or "",
            archivos_adjuntos=paths,
        )

    def create_demo_data(self) -> DatosMulta:
        return self.create_target(
            email="test@example.com",
            num_denuncia="DEN/2024/001",
            matricula="1234ABC",
            num_expediente="EXP/2024/001",
            motivos="Alegación de prueba.",
            archivos_adjuntos=[Path("pdfs-prueba") / "test1.pdf"]
        )


def get_controller() -> XalocGironaController:
    return XalocGironaController()


__all__ = ["XalocGironaController", "get_controller"]

