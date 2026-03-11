"""
Controlador del sitio Ayunta Palma.
"""

from __future__ import annotations

from pathlib import Path

from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
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
        # Palma: evitar desactivar ExternalProtocolDialog a nivel global.
        # Necesitamos que Chromium procese el protocolo afirma:// de forma nativa.
        config.autofirma_auto_open = False
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
            if value not in (None, "", []):
                return value
        if canonical_path:
            value = cls._canonical_get(data, canonical_path)
            if value not in (None, "", []):
                return value
        return None

    def map_data(self, data: dict) -> dict:
        tipo_persona = self._pick(data, "tipo_persona", "persona_tipo")
        if not tipo_persona:
            client_type = self._pick(data, "cliente_tipo", "tipodecliente", canonical_path="client.type")
            doc_cif = self._pick(data, "nif_empresa", "cif", canonical_path="client.document.cif")
            if str(client_type) == "2" or bool(doc_cif):
                tipo_persona = "PersonaJuridica"
            else:
                tipo_persona = "PersonaFisica"

        email = self._pick(data, "email", "correo", "cliente_email", canonical_path="client.contact.email")
        telefono = self._pick(data, "telefono", "movil", "cliente_movil", "cliente_tel1", canonical_path="client.contact.mobile")
        if not telefono:
            telefono = self._pick(data, "cliente_tel1", canonical_path="client.contact.phone1")
        if not email:
            email = get_default_contact_email()
        if not telefono:
            telefono = get_default_contact_mobile()

        return {
            "tipo_persona": tipo_persona,
            "tipo_documento": self._pick(data, "tipo_documento"),
            "documento": self._pick(data, "documento", "identificacion", canonical_path="client.document.nif"),
            "nombre": self._pick(data, "nombre", "cliente_nombre", canonical_path="client.name.first"),
            "apellido1": self._pick(data, "apellido1", "cliente_apellido1", canonical_path="client.name.last1"),
            "apellido2": self._pick(data, "apellido2", "cliente_apellido2", canonical_path="client.name.last2"),
            "pais": self._pick(data, "pais"),
            "nif_empresa": self._pick(data, "nif_empresa", "cif", canonical_path="client.document.cif"),
            "razon_social": self._pick(data, "razon_social", "cliente_razon_social", canonical_path="client.name.business"),
            "email": email,
            "telefono": telefono,
            "expediente": self._pick(data, "expediente", "Expedient", canonical_path="resource.expedient"),
            "matricula": self._pick(data, "matricula", "plate_number", canonical_path="vehicle.plate.value"),
            "expone": self._pick(data, "expone"),
            "solicita": self._pick(data, "solicita"),
            "archivos": data.get("archivos") or data.get("documentos"),
            "payload": data,
        }


def get_controller() -> AyuntaPalmaController:
    return AyuntaPalmaController()
