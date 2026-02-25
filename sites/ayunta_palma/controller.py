"""
Controlador del sitio Ayunta Palma.
"""

from __future__ import annotations

from pathlib import Path

from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.data_models import (
    AyuntaPalmaAlegaciones,
    AyuntaPalmaContacto,
    AyuntaPalmaPersonaFisica,
    AyuntaPalmaPersonaJuridica,
    AyuntaPalmaTarget,
)


class AyuntaPalmaController:
    site_id = "ayunta_palma"
    display_name = "Ayuntamiento de Palma"

    def create_config(self, *, headless: bool) -> AyuntaPalmaConfig:
        config = AyuntaPalmaConfig()
        config.navegador.headless = bool(headless)
        return config

    def create_target_strict(
        self,
        *,
        tipo_persona: str,
        email: str,
        telefono: str,
        tipo_documento: str | None = None,
        documento: str | None = None,
        nombre: str | None = None,
        apellido1: str | None = None,
        apellido2: str | None = None,
        pais: str | None = None,
        nif_empresa: str | None = None,
        razon_social: str | None = None,
        expediente: str,
        matricula: str,
        expone: str,
        solicita: str,
        archivos: list[str] | None = None,
        payload: dict | None = None,
    ) -> AyuntaPalmaTarget:
        def _require(name: str, value: str | None) -> str:
            v = (value or "").strip()
            if not v:
                raise ValueError(f"ayunta_palma: falta '{name}'.")
            return v

        persona_tipo_norm = _require("tipo_persona", tipo_persona)
        if persona_tipo_norm not in {"PersonaFisica", "PersonaJuridica"}:
            raise ValueError("ayunta_palma: 'tipo_persona' debe ser PersonaFisica o PersonaJuridica.")

        contacto = AyuntaPalmaContacto(
            correo=_require("email", email),
            telefono=_require("telefono", telefono),
        )

        fisica = None
        juridica = None
        if persona_tipo_norm == "PersonaFisica":
            fisica = AyuntaPalmaPersonaFisica(
                tipo_documento=_require("tipo_documento", tipo_documento),
                documento=_require("documento", documento),
                nombre=_require("nombre", nombre),
                apellido1=_require("apellido1", apellido1),
                apellido2=(apellido2 or "").strip() or None,
                pais=(pais or "").strip() or None,
            )
        else:
            juridica = AyuntaPalmaPersonaJuridica(
                nif=_require("nif_empresa", nif_empresa),
                razon_social=_require("razon_social", razon_social),
            )

        alegaciones = AyuntaPalmaAlegaciones(
            expediente=_require("expediente", expediente),
            matricula=_require("matricula", matricula),
            expone=_require("expone", expone),
            solicita=_require("solicita", solicita),
        )

        archivos_paths = [Path(p) for p in archivos] if archivos else None

        return AyuntaPalmaTarget(
            tipo_persona=persona_tipo_norm,
            contacto=contacto,
            fisica=fisica,
            juridica=juridica,
            alegaciones=alegaciones,
            archivos=archivos_paths,
            payload=payload,
        )

    create_target = create_target_strict

    def map_data(self, data: dict) -> dict:
        return {
            "tipo_persona": data.get("tipo_persona") or data.get("persona_tipo"),
            "tipo_documento": data.get("tipo_documento"),
            "documento": data.get("documento") or data.get("identificacion"),
            "nombre": data.get("nombre"),
            "apellido1": data.get("apellido1"),
            "apellido2": data.get("apellido2"),
            "pais": data.get("pais"),
            "nif_empresa": data.get("nif_empresa"),
            "razon_social": data.get("razon_social"),
            "email": data.get("email") or data.get("correo"),
            "telefono": data.get("telefono") or data.get("movil"),
            "expediente": data.get("expediente"),
            "matricula": data.get("matricula"),
            "expone": data.get("expone"),
            "solicita": data.get("solicita"),
            "archivos": data.get("archivos") or data.get("documentos"),
            "payload": data,
        }


def get_controller() -> AyuntaPalmaController:
    return AyuntaPalmaController()