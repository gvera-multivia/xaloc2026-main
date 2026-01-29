from __future__ import annotations

from pathlib import Path

from sites.xaloc_girona.config import XalocConfig
from sites.xaloc_girona.data_models import DatosMulta, DatosMandatario


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
            "archivos_adjuntos": data.get("archivos_adjuntos") or data.get("archivos"),
            # NUEVO: Datos del mandatario
            "mandatario": data.get("mandatario"),
            # NUEVO: Fase del procedimiento (para organizar justificantes)
            "fase_procedimiento": data.get("fase_procedimiento"),
        }

    def create_target(
        self,
        *,
        email: str | None,
        num_denuncia: str | None,
        matricula: str | None,
        num_expediente: str | None,
        motivos: str | None,
        archivos_adjuntos: list[Path] | list[str] | None,
        mandatario: dict | None = None,
        **kwargs,
    ) -> DatosMulta:
        def _require(name: str, value: str | None) -> str:
            v = (value or "").strip()
            if not v:
                raise ValueError(f"xaloc_girona: falta '{name}'.")
            return v

        if not archivos_adjuntos:
            raise ValueError("xaloc_girona: falta 'archivos_adjuntos' (al menos 1 archivo).")

        paths: list[Path] = [Path(a) if isinstance(a, str) else a for a in archivos_adjuntos]
        if not paths:
            raise ValueError("xaloc_girona: falta 'archivos_adjuntos' (al menos 1 archivo).")

        # Crear objeto DatosMandatario si existe
        datos_mandatario = None
        if mandatario:
            datos_mandatario = DatosMandatario(**mandatario)

        return DatosMulta(
            email=_require("email", email),
            num_denuncia=_require("num_denuncia", num_denuncia),
            matricula=_require("matricula", matricula),
            num_expediente=_require("num_expediente", num_expediente),
            motivos=_require("motivos", motivos),
            archivos_adjuntos=paths,
            mandatario=datos_mandatario,
        )


def get_controller() -> XalocGironaController:
    return XalocGironaController()


__all__ = ["XalocGironaController", "get_controller"]

