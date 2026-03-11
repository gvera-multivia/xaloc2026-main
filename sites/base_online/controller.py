from __future__ import annotations

import os
from pathlib import Path

from core.address_defaults import get_default_country_es_ascii
from core.contact_defaults import get_default_contact_email, get_default_contact_phone_fixed
from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import (
    BaseOnlineAddressData,
    BaseOnlineP1ContactData,
    BaseOnlineP1Data,
    BaseOnlineP1IdentificacionData,
    BaseOnlineP2Data,
    BaseOnlineReposicionData,
    BaseOnlineTarget,
)


class BaseOnlineController:
    site_id = "base_online"
    display_name = "BASE On-line"

    def create_config(self, *, headless: bool) -> BaseOnlineConfig:
        config = BaseOnlineConfig()
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
            if value not in (None, "", []):
                return value
        if canonical_path:
            value = cls._canonical_get(data, canonical_path)
            if value not in (None, "", []):
                return value
        return None

    def create_target(
        self,
        *,
        protocol: str | None = None,
        payload: dict | None = None,
        # P1: Solicitud de identificación de conductor
        p1_telefon_mobil: str | None = None,
        p1_telefon_fix: str | None = None,
        p1_correu: str | None = None,
        p1_expedient_id_ens: str | None = None,
        p1_expedient_any: str | None = None,
        p1_expedient_num: str | None = None,
        p1_num_butlleti: str | None = None,
        p1_data_denuncia: str | None = None,
        p1_matricula: str | None = None,
        p1_identificacio: str | None = None,
        p1_llicencia_conduccio: str | None = None,
        p1_nom_complet: str | None = None,
        p1_adreca: str | None = None,
        p1_address_sigla: str | None = None,
        p1_address_street: str | None = None,
        p1_address_number: str | None = None,
        p1_address_zip: str | None = None,
        p1_address_city: str | None = None,
        p1_address_province: str | None = None,
        p1_address_pais: str | None = None,
        p1_address_ampliacion_municipio: str | None = None,
        p1_address_ampliacion_calle: str | None = None,
        p1_archivos: list[Path] | list[str] | None = None,
        # P2: Alegaciones
        p2_nif: str | None = None,
        p2_rao_social: str | None = None,
        p2_exposo: str | None = None,
        p2_solicito: str | None = None,
        p2_archivos: list[Path] | list[str] | None = None,
        # P3: Recurso de reposición
        p3_tipus_objecte: str | None = None,
        p3_dades_especifiques: str | None = None,
        p3_tipus_solicitud_value: str | None = None,
        p3_exposo: str | None = None,
        p3_solicito: str | None = None,
        p3_archivos: list[Path] | list[str] | None = None,
        **_kwargs,
    ) -> BaseOnlineTarget:
        def _require(name: str, value: str | None) -> str:
            v = (value or "").strip()
            if not v:
                raise ValueError(f"base_online: falta '{name}'.")
            return v

        def _resolve_contact_phones() -> tuple[str, str | None]:
            movil = (p1_telefon_mobil or "").strip()
            fijo = (p1_telefon_fix or "").strip()
            if not movil and not fijo:
                fallback = (os.getenv("BASE_ONLINE_DEFAULT_PHONE") or "").strip() or get_default_contact_phone_fixed()
                if fallback:
                    movil = fallback
            if not movil and not fijo:
                raise ValueError("base_online: falta telefono de contacto (p1_telefon_mobil o p1_telefon_fix).")
            if not movil:
                movil = fijo
            return movil, (fijo or None)

        def _resolve_contact_email() -> str:
            email = (p1_correu or "").strip()
            if not email:
                email = (os.getenv("BASE_ONLINE_DEFAULT_EMAIL") or "").strip() or get_default_contact_email()
            if not email:
                raise ValueError("base_online: falta correo de contacto (p1_correu).")
            return email

        def _require_paths(name: str, value: list[Path] | list[str] | None) -> list[Path]:
            if not value:
                raise ValueError(f"base_online: falta '{name}' (al menos 1 archivo).")
            paths = [Path(v) if isinstance(v, str) else v for v in value]
            if not paths:
                raise ValueError(f"base_online: falta '{name}' (al menos 1 archivo).")
            return paths

        protocol_norm = _require("protocol", protocol).upper()
        if protocol_norm not in {"P1", "P2", "P3"}:
            raise ValueError("base_online: 'protocol' inválido (usa P1, P2 o P3).")

        if protocol_norm == "P1":
            telefon_mobil, telefon_fix = _resolve_contact_phones()
            correu = _resolve_contact_email()
            contacte = BaseOnlineP1ContactData(
                telefon_mobil=telefon_mobil,
                telefon_fix=telefon_fix,
                correu=correu,
            )

            adreca = (p1_adreca or "").strip() or None
            adreca_detall = None
            if not adreca:
                adreca_detall = BaseOnlineAddressData(
                    sigla=_require("p1_address_sigla", p1_address_sigla),
                    calle=_require("p1_address_street", p1_address_street),
                    numero=_require("p1_address_number", p1_address_number),
                    codigo_postal=_require("p1_address_zip", p1_address_zip),
                    municipio=_require("p1_address_city", p1_address_city),
                    provincia=_require("p1_address_province", p1_address_province),
                    pais=_require("p1_address_pais", p1_address_pais),
                    ampliacion_municipio=(p1_address_ampliacion_municipio or "").strip() or None,
                    ampliacion_calle=(p1_address_ampliacion_calle or "").strip() or None,
                )

            identificacio = BaseOnlineP1IdentificacionData(
                expedient_id_ens=_require("p1_expedient_id_ens", p1_expedient_id_ens),
                expedient_any=_require("p1_expedient_any", p1_expedient_any),
                expedient_num=_require("p1_expedient_num", p1_expedient_num),
                num_butlleti=_require("p1_num_butlleti", p1_num_butlleti),
                data_denuncia=_require("p1_data_denuncia", p1_data_denuncia),
                matricula=_require("p1_matricula", p1_matricula),
                identificacio=_require("p1_identificacio", p1_identificacio),
                llicencia_conduccio=_require("p1_llicencia_conduccio", p1_llicencia_conduccio),
                nom_complet=_require("p1_nom_complet", p1_nom_complet),
                adreca=adreca,
                adreca_detall=adreca_detall,
            )

            p1 = BaseOnlineP1Data(
                contacte=contacte,
                identificacio=identificacio,
                archivos_adjuntos=_require_paths("p1_archivos", p1_archivos),
            )
            return BaseOnlineTarget(protocol=protocol_norm, p1=p1, payload=payload)

        if protocol_norm == "P2":
            telefon_mobil, telefon_fix = _resolve_contact_phones()
            correu = _resolve_contact_email()
            contacte = BaseOnlineP1ContactData(
                telefon_mobil=telefon_mobil,
                telefon_fix=telefon_fix,
                correu=correu,
            )

            # El flujo valida que exista expediente o butlletí; aquí exigimos lo mismo.
            has_expediente = bool((p1_expedient_id_ens or "").strip() or (p1_expedient_any or "").strip() or (p1_expedient_num or "").strip())
            has_butlleti = bool((p1_num_butlleti or "").strip())
            if not (has_expediente or has_butlleti):
                raise ValueError("base_online: P2 requiere expediente (id_ens/any/num) o butlletí.")

            p2 = BaseOnlineP2Data(
                nif=_require("p2_nif", p2_nif),
                rao_social=_require("p2_rao_social", p2_rao_social),
                contacte=contacte,
                expedient_id_ens=(p1_expedient_id_ens or "").strip() or None,
                expedient_any=(p1_expedient_any or "").strip() or None,
                expedient_num=(p1_expedient_num or "").strip() or None,
                butlleti=(p1_num_butlleti or "").strip() or None,
                exposo=_require("p2_exposo", p2_exposo),
                solicito=_require("p2_solicito", p2_solicito),
                archivos_adjuntos=_require_paths("p2_archivos", p2_archivos),
            )
            return BaseOnlineTarget(protocol=protocol_norm, p2=p2, payload=payload)

        reposicion = BaseOnlineReposicionData(
            tipus_objecte=_require("p3_tipus_objecte", p3_tipus_objecte),
            dades_especifiques=(p3_dades_especifiques or ".").strip() or None,
            tipus_solicitud_value=_require("p3_tipus_solicitud_value", p3_tipus_solicitud_value),
            exposo=_require("p3_exposo", p3_exposo),
            solicito=_require("p3_solicito", p3_solicito),
            archivos_adjuntos=_require_paths("p3_archivos", p3_archivos),
        )
        return BaseOnlineTarget(protocol=protocol_norm, p3=reposicion, reposicion=reposicion, payload=payload)

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genéricas de DB/JSON a argumentos de create_target.
        """
        return {
            "payload": data,
            "p1_telefon_mobil": (
                self._pick(data, "p1_telefon_mobil", "user_phone", "telefono", "telefono1", "cliente_tel1", "cliente_movil", "movil", "mobile")
                or self._pick(data, canonical_path="client.contact.mobile")
                or self._pick(data, canonical_path="client.contact.phone1")
            ),
            "p1_telefon_fix": (
                self._pick(data, "p1_telefon_fix", "telefono2", "cliente_tel2", "phone")
                or self._pick(data, canonical_path="client.contact.phone2")
            ),
            "p1_correu": (
                self._pick(data, "p1_correu", "user_email", "email", "correo", "cliente_email", canonical_path="client.contact.email")
                or (os.getenv("BASE_ONLINE_DEFAULT_EMAIL") or "").strip()
                or get_default_contact_email()
            ),
            "p1_matricula": self._pick(data, "p1_matricula", "plate_number", canonical_path="vehicle.plate.value"),
            "p1_expedient_id_ens": self._pick(data, "p1_expedient_id_ens", "expediente_id_ens"),
            "p1_expedient_any": self._pick(data, "p1_expedient_any", "expediente_any"),
            "p1_expedient_num": self._pick(data, "p1_expedient_num", "expediente_num", canonical_path="resource.expedient"),
            "p1_num_butlleti": data.get("p1_num_butlleti") or data.get("num_butlleti"),
            "p1_data_denuncia": data.get("p1_data_denuncia") or data.get("data_denuncia"),
            "p1_identificacio": self._pick(data, "p1_identificacio", "nif", canonical_path="client.document.nif"),
            "p1_llicencia_conduccio": data.get("p1_llicencia_conduccio") or data.get("llicencia_conduccio"),
            "p1_nom_complet": data.get("p1_nom_complet"),
            "p1_adreca": data.get("p1_adreca"),
            "p1_address_sigla": data.get("p1_address_sigla") or data.get("address_sigla") or "CL",
            "p1_address_street": self._pick(data, "p1_address_street", "address_street", canonical_path="client.address.street_name"),
            "p1_address_number": data.get("p1_address_number") or data.get("address_number") or "S/N",
            "p1_address_zip": self._pick(data, "p1_address_zip", "address_zip", canonical_path="client.address.zip"),
            "p1_address_city": self._pick(data, "p1_address_city", "address_city", canonical_path="client.address.city"),
            "p1_address_province": self._pick(data, "p1_address_province", "address_province", canonical_path="client.address.province"),
            "p1_address_pais": self._pick(data, "p1_address_pais", "address_pais", "address_country", canonical_path="client.address.country")
            or get_default_country_es_ascii(),
            "p1_address_ampliacion_municipio": data.get("p1_address_ampliacion_municipio"),
            "p1_address_ampliacion_calle": data.get("p1_address_ampliacion_calle"),
            "p2_nif": data.get("p2_nif") or data.get("nif") or data.get("cliente_nif") or data.get("cif"),
            "p2_rao_social": data.get("p2_rao_social") or data.get("cliente_razon_social") or data.get("name"),
            "p2_exposo": data.get("p2_exposo") or data.get("exposo"),
            "p2_solicito": data.get("p2_solicito") or data.get("solicito"),
            "p3_tipus_objecte": data.get("p3_tipus_objecte"),
            "p3_dades_especifiques": data.get("p3_dades_especifiques"),
            "p3_tipus_solicitud_value": data.get("p3_tipus_solicitud_value"),
            "p3_exposo": data.get("p3_exposo") or data.get("exposo"),
            "p3_solicito": data.get("p3_solicito") or data.get("solicito"),
            "p1_archivos": data.get("p1_archivos") or data.get("archivos"),
            "p2_archivos": data.get("p2_archivos") or data.get("archivos"),
            "p3_archivos": data.get("p3_archivos") or data.get("archivos"),
        }


def get_controller() -> BaseOnlineController:
    return BaseOnlineController()


__all__ = ["BaseOnlineController", "get_controller"]

