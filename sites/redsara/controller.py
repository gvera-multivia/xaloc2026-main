from __future__ import annotations

import os

from sites.redsara.config import RedsaraConfig
from sites.redsara.data_models import RedsaraTarget

REP_STREET_TYPE_FIXED = "RONDA"
REP_ADDRESS_FIXED = "GENERAL MITRE"
REP_COUNTRY_FIXED = "ESPANA"
REP_PROVINCE_FIXED = "BARCELONA"
REP_CITY_FIXED = "BARCELONA"
REP_ZIP_FIXED = "08022"

PHONE_FIXED = "722761154"
EMAIL_FIXED = "info@xvia-serviciosjuridicos.com"


class RedsaraController:
    site_id = "redsara"
    display_name = "REG RedSara"

    def create_config(self, *, headless: bool) -> RedsaraConfig:
        config = RedsaraConfig()
        config.navegador.headless = bool(headless)
        return config

    def map_data(self, data: dict) -> dict:
        return {
            "payload": data,
            # Representante fijo (datos corporativos)
            "represented_street_type": REP_STREET_TYPE_FIXED,
            "represented_address": REP_ADDRESS_FIXED,
            "represented_province": REP_PROVINCE_FIXED,
            "represented_city": REP_CITY_FIXED,
            "represented_zip": REP_ZIP_FIXED,
            "represented_phone": PHONE_FIXED,
            "represented_email": EMAIL_FIXED,
            "interested_doc_type": data.get("interested_doc_type") or data.get("tipo_doc_interesado"),
            "interested_doc_number": data.get("interested_doc_number") or data.get("nif") or data.get("interested_nif"),
            "interested_name": data.get("interested_name") or data.get("name"),
            "interested_surname1": data.get("interested_surname1") or data.get("surname1"),
            "interested_surname2": data.get("interested_surname2") or data.get("surname2"),
            "interested_street_type": data.get("interested_street_type") or data.get("address_sigla"),
            "interested_address": data.get("interested_address") or data.get("address_street"),
            "interested_province": data.get("interested_province") or data.get("address_province"),
            "interested_city": data.get("interested_city") or data.get("address_city"),
            "interested_zip": data.get("interested_zip") or data.get("address_zip"),
            # Contacto interesado fijo (datos corporativos)
            "interested_phone": PHONE_FIXED,
            "interested_email": EMAIL_FIXED,
            "email_alert": data.get("email_alert"),
            "destination_organism_code": data.get("destination_organism_code") or data.get("organism_code"),
            "subject": data.get("subject") or data.get("asunto"),
            "exposes": data.get("exposes") or data.get("expone"),
            "solicit": data.get("solicit") or data.get("solicita"),
        }

    def create_target(
        self,
        *,
        represented_street_type: str | None = None,
        represented_address: str | None = None,
        represented_province: str | None = None,
        represented_city: str | None = None,
        represented_zip: str | None = None,
        represented_phone: str | None = None,
        represented_email: str | None = None,
        interested_doc_type: str | None = None,
        interested_doc_number: str | None = None,
        interested_name: str | None = None,
        interested_surname1: str | None = None,
        interested_surname2: str | None = None,
        interested_street_type: str | None = None,
        interested_address: str | None = None,
        interested_province: str | None = None,
        interested_city: str | None = None,
        interested_zip: str | None = None,
        interested_phone: str | None = None,
        interested_email: str | None = None,
        email_alert: bool | None = None,
        destination_organism_code: str | None = None,
        subject: str | None = None,
        exposes: str | None = None,
        solicit: str | None = None,
        **_kwargs,
    ) -> RedsaraTarget:
        def _pick(value: str | None, env_key: str, fallback: str) -> str:
            text = (value or "").strip()
            if text:
                return text
            env_text = (os.getenv(env_key) or "").strip()
            if env_text:
                return env_text
            return fallback

        return RedsaraTarget(
            represented_street_type=_pick(represented_street_type, "REDSARA_REP_STREET_TYPE", REP_STREET_TYPE_FIXED),
            represented_address=_pick(represented_address, "REDSARA_REP_ADDRESS", REP_ADDRESS_FIXED),
            represented_province=_pick(represented_province, "REDSARA_REP_PROVINCE", REP_PROVINCE_FIXED),
            represented_city=_pick(represented_city, "REDSARA_REP_CITY", REP_CITY_FIXED),
            represented_zip=_pick(represented_zip, "REDSARA_REP_ZIP", REP_ZIP_FIXED),
            represented_phone=_pick(represented_phone, "REDSARA_REP_PHONE", PHONE_FIXED),
            represented_email=_pick(represented_email, "REDSARA_REP_EMAIL", EMAIL_FIXED),
            interested_doc_type=_pick(interested_doc_type, "REDSARA_INT_DOC_TYPE", "NIF"),
            interested_doc_number=_pick(interested_doc_number, "REDSARA_INT_DOC_NUMBER", "12345678Z"),
            interested_name=_pick(interested_name, "REDSARA_INT_NAME", "NOMBRE"),
            interested_surname1=_pick(interested_surname1, "REDSARA_INT_SURNAME1", "APELLIDO1"),
            interested_surname2=_pick(interested_surname2, "REDSARA_INT_SURNAME2", "APELLIDO2"),
            interested_street_type=_pick(interested_street_type, "REDSARA_INT_STREET_TYPE", "CALLE"),
            interested_address=_pick(interested_address, "REDSARA_INT_ADDRESS", "CALLE INTERESADO 2"),
            interested_province=_pick(interested_province, "REDSARA_INT_PROVINCE", "MADRID"),
            interested_city=_pick(interested_city, "REDSARA_INT_CITY", "MADRID"),
            interested_zip=_pick(interested_zip, "REDSARA_INT_ZIP", "28002"),
            interested_phone=_pick(interested_phone, "REDSARA_INT_PHONE", PHONE_FIXED),
            interested_email=_pick(interested_email, "REDSARA_INT_EMAIL", EMAIL_FIXED),
            email_alert=True if email_alert is None else bool(email_alert),
            destination_organism_code=_pick(destination_organism_code, "REDSARA_DEST_ORGANISM_CODE", "LA0007892"),
            subject=_pick(subject, "REDSARA_SUBJECT", "PRUEBA REDSARA"),
            exposes=_pick(exposes, "REDSARA_EXPOSES", "Texto de prueba para el campo expone."),
            solicit=_pick(solicit, "REDSARA_SOLICIT", "Texto de prueba para el campo solicita."),
        )


def get_controller() -> RedsaraController:
    return RedsaraController()


__all__ = ["RedsaraController", "get_controller"]
