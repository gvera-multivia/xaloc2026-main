from __future__ import annotations

import os
import re
import unicodedata

from core.address_defaults import (
    get_representative_city,
    get_representative_country,
    get_representative_province,
    get_representative_street_full,
    get_representative_street_type,
    get_representative_zip,
)
from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from sites.redsara.config import RedsaraConfig
from sites.redsara.data_models import RedsaraTarget

REP_STREET_TYPE_FIXED = get_representative_street_type().title()
REP_ADDRESS_FIXED = get_representative_street_full()
REP_COUNTRY_FIXED = get_representative_country()
REP_PROVINCE_FIXED = get_representative_province()
REP_CITY_FIXED = get_representative_city()
REP_ZIP_FIXED = get_representative_zip()

PHONE_FIXED = get_default_contact_mobile()
EMAIL_FIXED = get_default_contact_email()

_RE_NIF = re.compile(r"^\d{8}[A-Z]$", re.IGNORECASE)
_RE_NIE = re.compile(r"^[XYZ]\d{7}[A-Z]$", re.IGNORECASE)
_RE_CIF = re.compile(r"^[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J]$", re.IGNORECASE)
_RE_PASS = re.compile(r"^[A-Z0-9]{3,20}$", re.IGNORECASE)

_DOC_TYPE_ALIASES = {
    "NIF": "NIF",
    "DNI": "NIF",
    "NIE": "NIE",
    "CIF": "CIF",
    "NIF/NIE": "NIE",
    "NIF NIE": "NIE",
    "PASAPORTE": "PASAPORTE",
    "PASS": "PASAPORTE",
    "PASSPORT": "PASAPORTE",
    "DOCUMENTO EXTRANJERO": "PASAPORTE",
}


def _normalize_person_name_for_redsara(raw: str | None) -> str:
    """
    Sanea caracteres conflictivos en nombres/apellidos para el formulario REDSARA.
    Convierte ordinales (p.ej. Mª) en separador de espacio sin truncar texto.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    # U+00AA (ª), U+00BA (º) y variantes mojibake comunes ("Âª", "Âº").
    # Importante: primero secuencias dobles para no dejar "\u00C2" colgando.
    text = text.replace("\u00C2\u00AA", " ").replace("\u00C2\u00BA", " ")
    text = text.replace("\u00AA", " ").replace("\u00BA", " ")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_doc_number(raw: str | None) -> str:
    value = str(raw or "").strip().upper()
    return re.sub(r"[\s\-_/]", "", value)


def _infer_doc_type(doc_number: str | None) -> str | None:
    doc = _normalize_doc_number(doc_number)
    if not doc:
        return None
    if _RE_NIF.match(doc):
        return "NIF"
    if _RE_NIE.match(doc):
        return "NIE"
    if _RE_CIF.match(doc):
        return "CIF"
    # Si no encaja con NIF/NIE/CIF, tratar como pasaporte/documento extranjero.
    if _RE_PASS.match(doc):
        return "PASAPORTE"
    return None


def _normalize_doc_type(raw: str | None) -> str | None:
    value = str(raw or "").strip().upper()
    if not value:
        return None
    return _DOC_TYPE_ALIASES.get(value, value)


def _is_doc_type_compatible(doc_type: str | None, doc_number: str | None) -> bool:
    t = _normalize_doc_type(doc_type)
    doc = _normalize_doc_number(doc_number)
    if not t or not doc:
        return False
    if t == "NIF":
        return bool(_RE_NIF.match(doc))
    if t == "NIE":
        return bool(_RE_NIE.match(doc))
    if t == "CIF":
        return bool(_RE_CIF.match(doc))
    if t == "PASAPORTE":
        return not (_RE_NIF.match(doc) or _RE_NIE.match(doc) or _RE_CIF.match(doc))
    return False


def _resolve_doc_type(doc_number: str | None, explicit_doc_type: str | None) -> str | None:
    """
    Prioriza inferencia por nÃƒÂºmero para evitar tipos incoherentes (ej. NIF con NIE).
    """
    inferred = _infer_doc_type(doc_number)
    explicit = _normalize_doc_type(explicit_doc_type)
    if inferred:
        return inferred
    if explicit and _is_doc_type_compatible(explicit, doc_number):
        return explicit
    return explicit


def _is_company_by_cliente_tipo(value: object) -> bool:
    try:
        return int(str(value).strip()) == 2
    except Exception:
        return False


_REDSARA_STREET_TYPES = [
    "Alameda",
    "Avenida",
    "Avinguda",
    "Barrio",
    "Bulevar",
    "Calle",
    "Calleja",
    "CamÃƒÂ­",
    "Camino",
    "Campo",
    "Carrer",
    "Carrera",
    "Carretera",
    "Cuesta",
    "Edificio",
    "Enparantza",
    "Estrada",
    "Glorieta",
    "Jardines",
    "Jardins",
    "Kalea",
    "Otros",
    "Parque",
    "Pasaje",
    "Paseo",
    "Passatge",
    "Passeig",
    "PlaÃƒÂ§a",
    "Placeta",
    "Plaza",
    "Plazuela",
    "Poblado",
    "PolÃƒÂ­gono",
    "Praza",
    "Rambla",
    "Ronda",
    "RÃƒÂºa",
    "Sector",
    "TravesÃƒÂ­a",
    "Travessera",
    "UrbanizaciÃƒÂ³n",
    "Via",
]


def _normalize_street_type_key(raw: str | None) -> str:
    text = str(raw or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[\s\.,;:/_\\-]+", " ", text).strip()
    return text


_STREET_TYPE_MAP: dict[str, str] = {
    _normalize_street_type_key(v): v for v in _REDSARA_STREET_TYPES
}
_STREET_TYPE_MAP.update(
    {
        "cl": "Calle",
        "c": "Calle",
        "c/": "Calle",
        "av": "Avenida",
        "avda": "Avenida",
        "rda": "Ronda",
        "ctra": "Carretera",
        "pl": "Plaza",
        "pg": "Paseo",
        "ps": "Paseo",
        "cami": "CamÃƒÂ­",
        "trav": "TravesÃƒÂ­a",
        "trv": "TravesÃƒÂ­a",
        "urb": "UrbanizaciÃƒÂ³n",
        "pol": "PolÃƒÂ­gono",
    }
)


def _infer_street_type(street_type: str | None, sigla: str | None, street_name: str | None) -> str | None:
    direct = _normalize_street_type_key(street_type)
    if direct:
        return _STREET_TYPE_MAP.get(direct)

    sig = _normalize_street_type_key(sigla)
    if sig:
        mapped = _STREET_TYPE_MAP.get(sig)
        if mapped:
            return mapped

    # Inferencia por prefijo del nombre de la direccion.
    name = str(street_name or "").strip()
    if not name:
        return None
    first = _normalize_street_type_key(re.split(r"[\\s,.-]+", name, maxsplit=1)[0])
    return _STREET_TYPE_MAP.get(first)


def _normalize_city_for_redsara(raw: str | None) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    value_norm = unicodedata.normalize("NFD", value.lower())
    value_norm = "".join(ch for ch in value_norm if unicodedata.category(ch) != "Mn")
    value_norm = " ".join(value_norm.split())
    if value_norm == "fornells de la seva":
        return "FORNELLS DE LA SELVA"

    # 1) Formato "NUCLEO - MUNICIPIO" -> usar municipio.
    split_parts = re.split(r"\s+-\s+", value, maxsplit=1)
    candidate = split_parts[1].strip() if len(split_parts) == 2 and split_parts[1].strip() else value

    # 2) Reordenar articulo inicial al final: "Les X" -> "X, LES".
    m = re.match(r"^\s*(?P<article>les|la|el|los|las)\s+(?P<body>.+?)\s*$", candidate, flags=re.IGNORECASE)
    if m:
        article = m.group("article").strip().upper()
        body = m.group("body").strip().upper()
        candidate = f"{body}, {article}"
        body_norm = unicodedata.normalize("NFD", body.lower())
        body_norm = "".join(ch for ch in body_norm if unicodedata.category(ch) != "Mn")
        body_norm = " ".join(body_norm.split())
        if body_norm == "franqueses del valles" and article == "LES":
            candidate = "FRANQUESES DEL VALLES, LES"

    return candidate


def _split_full_name(full_name: str | None) -> tuple[str, str, str]:
    """
    Split a full name into (given_name, surname1, surname2).
    Never returns fabricated values.
    """
    tokens = [t for t in re.split(r"\s+", str(full_name or "").strip()) if t]
    if not tokens:
        return "", "", ""
    if len(tokens) == 1:
        return tokens[0], "", ""
    if len(tokens) == 2:
        return tokens[0], tokens[1], ""
    return tokens[0], tokens[1], " ".join(tokens[2:])


class RedsaraController:
    site_id = "redsara"
    display_name = "REG RedSara"

    def create_config(self, *, headless: bool) -> RedsaraConfig:
        config = RedsaraConfig()
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

    def map_data(self, data: dict) -> dict:
        base_doc_number = self._pick(
            data,
            "interested_doc_number",
            "nif",
            "interested_nif",
            canonical_path="client.document.nif",
        ) or self._pick(data, "cif", "cliente_nif_empresa", canonical_path="client.document.cif")
        doc_type = _resolve_doc_type(
            base_doc_number,
            self._pick(data, "interested_doc_type", "tipo_doc_interesado"),
        )
        is_empresa = _is_company_by_cliente_tipo(self._pick(data, "cliente_tipo", canonical_path="client.type")) or bool(data.get("interested_is_company")) or (
            (doc_type or "").strip().upper() == "CIF"
        )
        if is_empresa:
            doc_number = self._pick(data, "interested_doc_number", "cif", "cliente_nif_empresa", canonical_path="client.document.cif")
            doc_type = "CIF"
        else:
            doc_number = base_doc_number
        street_name = (
            self._pick(data, "interested_address", "address_street", "cliente_domicilio", "domicilio", canonical_path="client.address.street_name")
        )
        street_name = str(street_name or "").strip()
        street_type = _infer_street_type(
            data.get("interested_street_type"),
            data.get("address_sigla"),
            street_name,
        )
        if not street_type:
            street_type = "Otros"
        if is_empresa:
            # Para empresa: el campo "name" del formulario equivale a businessName (razon social).
            interested_name = (
                self._pick(data, "interested_razon_social", "razon_social", "empresa", "cliente_razon_social", canonical_path="client.name.business")
            )
            interested_surname1 = ""
            interested_surname2 = ""
        else:
            # Para persona fisica: usar campos estructurados de cliente.
            interested_name = (
                self._pick(data, "interested_name", "nombre", "cliente_nombre", canonical_path="client.name.first")
            )
            interested_surname1 = (
                self._pick(data, "interested_surname1", "surname1", "cliente_apellido1", canonical_path="client.name.last1")
            )
            interested_surname2 = (
                self._pick(data, "interested_surname2", "surname2", "cliente_apellido2", canonical_path="client.name.last2")
                or ""
            )
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
            "interested_doc_type": doc_type,
            "interested_doc_number": doc_number,
            "interested_name": _normalize_person_name_for_redsara(interested_name),
            "interested_surname1": _normalize_person_name_for_redsara(interested_surname1),
            # Nunca inventar apellido2: si no existe, se deja vacio.
            "interested_surname2": _normalize_person_name_for_redsara(interested_surname2),
            "interested_street_type": street_type,
            "interested_address": street_name,
            "interested_province": self._pick(data, "interested_province", "address_province", canonical_path="client.address.province"),
            "interested_city": _normalize_city_for_redsara(
                self._pick(data, "interested_city", "address_city", canonical_path="client.address.city")
            ),
            "interested_zip": self._pick(data, "interested_zip", "address_zip", canonical_path="client.address.zip"),
            # Contacto interesado fijo (datos corporativos)
            "interested_phone": PHONE_FIXED,
            "interested_email": EMAIL_FIXED,
            "interested_is_company": is_empresa,
            "email_alert": data.get("email_alert"),
            "destination_organism_code": self._pick(data, "destination_organism_code", "organism_code"),
            "subject": self._pick(data, "subject", "asunto"),
            "exposes": self._pick(data, "exposes", "expone"),
            "solicit": self._pick(data, "solicit", "solicita"),
            "archivos": data.get("archivos") or [],
        }

    def create_target(
        self,
        *,
        payload: dict | None = None,
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
        interested_is_company: bool | None = None,
        email_alert: bool | None = None,
        destination_organism_code: str | None = None,
        subject: str | None = None,
        exposes: str | None = None,
        solicit: str | None = None,
        archivos: list | None = None,
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

        def _pick_required(value: str | None, env_key: str, field_name: str) -> str:
            text = (value or "").strip()
            if text:
                return text
            env_text = (os.getenv(env_key) or "").strip()
            if env_text:
                return env_text
            raise ValueError(f"redsara: falta '{field_name}'.")

        resolved_doc_number = _pick_required(interested_doc_number, "REDSARA_INT_DOC_NUMBER", "interested_doc_number")
        resolved_doc_type = _resolve_doc_type(
            resolved_doc_number,
            (interested_doc_type or "").strip() or (os.getenv("REDSARA_INT_DOC_TYPE") or "").strip(),
        ) or ""
        if not resolved_doc_type:
            raise ValueError("redsara: no se pudo inferir 'interested_doc_type' a partir del documento.")
        payload_cliente_tipo = (payload or {}).get("cliente_tipo") if isinstance(payload, dict) else None
        is_empresa = (
            True if interested_is_company is True else False
        ) or _is_company_by_cliente_tipo(payload_cliente_tipo) or (resolved_doc_type.upper() == "CIF")
        if is_empresa:
            resolved_doc_type = "CIF"
        resolved_street_type = _infer_street_type(
            interested_street_type,
            None,
            interested_address,
        ) or _infer_street_type(
            (os.getenv("REDSARA_INT_STREET_TYPE") or "").strip(),
            None,
            interested_address,
        ) or "Otros"
        if is_empresa:
            # Para empresa: interested_name es razon social y apellidos vacios.
            resolved_name = _normalize_person_name_for_redsara(
                _pick_required(interested_name, "REDSARA_INT_NAME", "interested_name (razon social)")
            )
            resolved_surname1 = ""
            resolved_surname2 = ""
        else:
            candidate_name = _normalize_person_name_for_redsara(
                (interested_name or "").strip() or (os.getenv("REDSARA_INT_NAME") or "").strip()
            )
            candidate_surname1 = _normalize_person_name_for_redsara(
                (interested_surname1 or "").strip() or (os.getenv("REDSARA_INT_SURNAME1") or "").strip()
            )
            candidate_surname2 = _normalize_person_name_for_redsara(
                (interested_surname2 or "").strip() or (os.getenv("REDSARA_INT_SURNAME2") or "").strip()
            )

            if not candidate_name:
                raise ValueError("redsara: falta 'interested_name'.")
            if not candidate_surname1:
                raise ValueError("redsara: falta 'interested_surname1'.")

            resolved_name = _normalize_person_name_for_redsara(candidate_name)
            resolved_surname1 = _normalize_person_name_for_redsara(candidate_surname1)
            resolved_surname2 = _normalize_person_name_for_redsara(candidate_surname2 or "")

        return RedsaraTarget(
            payload=dict(payload or {}),
            represented_street_type=_pick(represented_street_type, "REDSARA_REP_STREET_TYPE", REP_STREET_TYPE_FIXED),
            represented_address=_pick(represented_address, "REDSARA_REP_ADDRESS", REP_ADDRESS_FIXED),
            represented_province=_pick(represented_province, "REDSARA_REP_PROVINCE", REP_PROVINCE_FIXED),
            represented_city=_pick(represented_city, "REDSARA_REP_CITY", REP_CITY_FIXED),
            represented_zip=_pick(represented_zip, "REDSARA_REP_ZIP", REP_ZIP_FIXED),
            represented_phone=_pick(represented_phone, "REDSARA_REP_PHONE", PHONE_FIXED),
            represented_email=_pick(represented_email, "REDSARA_REP_EMAIL", EMAIL_FIXED),
            interested_doc_type=resolved_doc_type,
            interested_doc_number=resolved_doc_number,
            interested_name=resolved_name,
            interested_surname1=resolved_surname1,
            interested_surname2=resolved_surname2,
            interested_street_type=resolved_street_type,
            interested_address=_pick_required(interested_address, "REDSARA_INT_ADDRESS", "interested_address"),
            interested_province=_pick_required(interested_province, "REDSARA_INT_PROVINCE", "interested_province"),
            interested_city=_normalize_city_for_redsara(_pick_required(interested_city, "REDSARA_INT_CITY", "interested_city")),
            interested_zip=_pick_required(interested_zip, "REDSARA_INT_ZIP", "interested_zip"),
            interested_phone=_pick(interested_phone, "REDSARA_INT_PHONE", PHONE_FIXED),
            interested_email=_pick(interested_email, "REDSARA_INT_EMAIL", EMAIL_FIXED),
            interested_is_company=is_empresa,
            email_alert=True if email_alert is None else bool(email_alert),
            destination_organism_code=_pick_required(destination_organism_code, "REDSARA_DEST_ORGANISM_CODE", "destination_organism_code"),
            subject=_pick_required(subject, "REDSARA_SUBJECT", "subject"),
            exposes=_pick_required(exposes, "REDSARA_EXPOSES", "exposes"),
            solicit=_pick_required(solicit, "REDSARA_SOLICIT", "solicit"),
            archivos=list(archivos or []),
        )


def get_controller() -> RedsaraController:
    return RedsaraController()


__all__ = ["RedsaraController", "get_controller"]
