from __future__ import annotations

from pathlib import Path

from sites.selva.config import SelvaConfig
from sites.selva.data_models import DatosSolicitud


class SelvaController:
    site_id = "selva"
    display_name = "Selva"

    def create_config(self, *, headless: bool) -> SelvaConfig:
        config = SelvaConfig()
        config.navegador.headless = bool(headless)
        return config

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genéricas a argumentos de create_target.
        """
        return {
            "contact_phone": data.get("phone"),
            "contact_mobile": data.get("mobile"),
            "contact_fax": data.get("fax"),
            "contact_other_phone": data.get("other_phone"),
            "municipality": data.get("municipality"),
            "theme": data.get("theme"),
            "expose_text": data.get("expose"),
            "request_text": data.get("request"),
            "attachments": data.get("attachments")
        }

    def create_target(
        self,
        contact_phone: str | None = None,
        contact_mobile: str | None = None,
        contact_fax: str | None = None,
        contact_other_phone: str | None = None,
        municipality: str | None = None,
        theme: str | None = None,
        expose_text: str | None = None,
        request_text: str | None = None,
        attachments: list[Path] | list[str] | None = None,
        **kwargs
    ) -> DatosSolicitud:

        # Ensure paths
        paths = []
        if attachments:
            for a in attachments:
                if isinstance(a, str):
                    paths.append(Path(a))
                else:
                    paths.append(a)
        else:
             # Default test files if needed, or empty
             paths = []

        return DatosSolicitud(
            contact_phone=contact_phone or "601353054",
            contact_mobile=contact_mobile or "601353054",
            contact_fax=contact_fax or "601353054",
            contact_other_phone=contact_other_phone or "601353054",
            municipality=municipality or "100100400058455206120", # Caldes de Malavella
            theme=theme or "CADASTRE",
            expose_text=expose_text or "Exposicion de ejemplo",
            request_text=request_text or "Solicitud de ejemplo",
            attachments=paths
        )

    def create_demo_data(self) -> DatosSolicitud:
        return self.create_target(
            contact_phone="601353054",
            municipality="100100400058455206120",
            theme="CADASTRE",
            expose_text="Demo Expose",
            request_text="Demo Request",
            attachments=[Path("pdfs-prueba") / "test1.pdf"]
        )


def get_controller() -> SelvaController:
    return SelvaController()


__all__ = ["SelvaController", "get_controller"]
