from __future__ import annotations

from pathlib import Path

from sites.xaloc_girona.config import XalocConfig
from sites.xaloc_girona.data_models import DatosMandatario, DatosMulta


class XalocGironaController:
    site_id = "xaloc_girona"
    display_name = "Xaloc Girona"

    def create_config(self, *, headless: bool) -> XalocConfig:
        config = XalocConfig()
        config.navegador.headless = bool(headless)
        return config

    @staticmethod
    def _canonical_get(data: dict, path: str):
        canonical = (data or {}).get("__canonical_v1")
        node = canonical if isinstance(canonical, dict) else None
        for part in path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node

    @classmethod
    def _pick(cls, data: dict, *keys: str, canonical_path: str | None = None):
        for key in keys:
            value = data.get(key)
            if value is not None and str(value).strip():
                return value
        if canonical_path:
            value = cls._canonical_get(data, canonical_path)
            if value is not None and str(value).strip():
                return value
        return None

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genericas de DB a argumentos de create_target.
        """

        return {
            "email": self._pick(data, "email", "user_email", "cliente_email", canonical_path="client.contact.email"),
            "num_denuncia": self._pick(data, "num_denuncia", "denuncia_num", "numero_denuncia", "nExp", canonical_path="resource.expedient"),
            "matricula": self._pick(data, "matricula", "plate_number", "rs_matricula", canonical_path="vehicle.plate.value"),
            "num_expediente": self._pick(
                data,
                "num_expediente",
                "expediente_num",
                "expediente",
                "Expedient",
                "numero_expediente",
                canonical_path="resource.expedient",
            ),
            "motivos": self._pick(data, "motivos", "body", "texto_recurso"),
            "archivos_adjuntos": data.get("archivos_adjuntos") or data.get("archivos"),
            "mandatario": data.get("mandatario"),
            "fase_procedimiento": self._pick(data, "fase_procedimiento", canonical_path="resource.phase"),
            "interesado_doc": self._pick(data, "interesado_doc", "cliente_nif"),
            "interesado_nombre": self._pick(data, "interesado_nombre", "cliente_nombre"),
            "interesado_apellido1": self._pick(data, "interesado_apellido1", "cliente_apellido1"),
            "interesado_apellido2": self._pick(data, "interesado_apellido2", "cliente_apellido2"),
            "xvia_recurso_path": data.get("xvia_recurso_path"),
            "xvia_attachment_paths": data.get("xvia_attachment_paths"),
            "required_client_doc_paths": data.get("required_client_doc_paths"),
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
        fase_procedimiento: str | None = None,
        interesado_doc: str | None = None,
        interesado_nombre: str | None = None,
        interesado_apellido1: str | None = None,
        interesado_apellido2: str | None = None,
        xvia_recurso_path: str | Path | None = None,
        xvia_attachment_paths: list[Path] | list[str] | None = None,
        required_client_doc_paths: list[Path] | list[str] | None = None,
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

        datos_mandatario = None
        if mandatario:
            datos_mandatario = DatosMandatario(**mandatario)

        def _to_paths(values: list[Path] | list[str] | None) -> list[Path] | None:
            if not values:
                return None
            return [Path(v) if isinstance(v, str) else v for v in values if v]

        return DatosMulta(
            email=_require("email", email),
            num_denuncia=_require("num_denuncia", num_denuncia),
            matricula=_require("matricula", matricula),
            num_expediente=_require("num_expediente", num_expediente),
            motivos=_require("motivos", motivos),
            archivos_adjuntos=paths,
            mandatario=datos_mandatario,
            fase_procedimiento=fase_procedimiento,
            interesado_doc=(interesado_doc or "").strip() or None,
            interesado_nombre=(interesado_nombre or "").strip() or None,
            interesado_apellido1=(interesado_apellido1 or "").strip() or None,
            interesado_apellido2=(interesado_apellido2 or "").strip() or None,
            xvia_recurso_path=Path(xvia_recurso_path) if xvia_recurso_path else None,
            xvia_attachment_paths=_to_paths(xvia_attachment_paths),
            required_client_doc_paths=_to_paths(required_client_doc_paths),
        )


def get_controller() -> XalocGironaController:
    return XalocGironaController()


__all__ = ["XalocGironaController", "get_controller"]
