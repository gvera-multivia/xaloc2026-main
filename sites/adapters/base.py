from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from .site_adapter import SiteAdapter
from core.address_classifier import classify_address_fallback
from core.address_defaults import get_default_country_es_ascii
from core.contact_defaults import get_default_contact_email, get_default_contact_mobile, get_default_contact_phone_fixed
from core.guardians import GroqTokenGuardian, ResourceContext
from core.sqlserver_utils import build_sqlserver_connection_string
from core.validation.validators import normalize_plate_with_fallback

logger = logging.getLogger("brain")


class BaseOnlineAdapter(SiteAdapter):
    DEFAULT_REGEX_EXPEDIENTE = r"^\s*(\d{5}-\d{4}[/\-]\d{1,5}-GIM|\d{5}-\d{4}/\d{1,5}|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{6,7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))\s*$"
    _LEGACY_REGEX_EXPEDIENTE_VARIANTS: tuple[str, ...] = (
        r"^\s*(\d{5}-\d{4}[/\-]\d{4,5}-GIM|\d{5}-\d{4}/\d{1,5}|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{6,7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))\s*$",
        r"^(\d{5}-\d{4}[/\-]\d{4,5}-GIM|\d{5}-\d{4}/\d{1,5}|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{6,7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))$",
        r"^(\d{5}-\d{4}[/\-]\d{1,5}-GIM|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))$",
        r"^(\d{5}-\d{4}[/\-]\d{1,5}-GIM|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{6,7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))$",
        r"^\s*(\d{5}-\d{4}[/\-]\d{1,5}-GIM|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))\s*$",
    )
    _P1_SIGLAS = {
        "AG", "AL", "AP", "AR", "AU", "AV", "AY", "BJ", "BO", "BR", "CA", "CG", "CH", "CI", "CJ", "CL", "CM",
        "CN", "CO", "CP", "CR", "CS", "CT", "CU", "DE", "DP", "DS", "ED", "EM", "EN", "ER", "ES", "EX", "FC",
        "FN", "GL", "GR", "GV", "HT", "JR", "LD", "LG", "MC", "ML", "MN", "MS", "MT", "MZ", "PB", "PD", "PJ",
        "PQ", "PR", "PS", "PT", "PZ", "QT", "RB", "RC", "RD", "RM", "RP", "RR", "RU", "SA", "SD", "SL", "SN",
        "SU", "TN", "TO", "TR", "UR", "VR", "ZN",
    }

    _P1_SIGLA_MAP = {
        "CALLE": "CL",
        "CARRER": "CL",
        "CLL": "CL",
        "AVENIDA": "AV",
        "AVINGUDA": "AV",
        "AVDA": "AV",
        "PLAZA": "PZ",
        "PASSEIG": "PS",
        "PASEO": "PS",
        "CARRETERA": "CR",
        "CAMINO": "CM",
        "RONDA": "RD",
        "RAMBLA": "RB",
        "TRAVESSERA": "TR",
        "TRAVESIA": "TR",
        "URBANIZACION": "UR",
    }

    _PROVINCIAS_CP = {
        "01": "ALAVA", "02": "ALBACETE", "03": "ALICANTE", "04": "ALMERIA", "05": "AVILA",
        "06": "BADAJOZ", "08": "BARCELONA", "09": "BURGOS", "10": "CACERES", "11": "CADIZ",
        "12": "CASTELLON", "13": "CIUDAD REAL", "14": "CORDOBA", "15": "A CORUNA", "16": "CUENCA",
        "17": "GIRONA", "18": "GRANADA", "19": "GUADALAJARA", "20": "GUIPUZCOA", "21": "HUELVA",
        "22": "HUESCA", "23": "JAEN", "24": "LEON", "25": "LLEIDA", "26": "LA RIOJA",
        "27": "LUGO", "28": "MADRID", "29": "MALAGA", "30": "MURCIA", "31": "NAVARRA",
        "32": "OURENSE", "33": "ASTURIAS", "34": "PALENCIA", "36": "PONTEVEDRA", "37": "SALAMANCA",
        "39": "CANTABRIA", "40": "SEGOVIA", "41": "SEVILLA", "42": "SORIA", "43": "TARRAGONA",
        "44": "TERUEL", "45": "TOLEDO", "46": "VALENCIA", "47": "VALLADOLID", "48": "VIZCAYA",
        "49": "ZAMORA", "50": "ZARAGOZA", "51": "CEUTA", "52": "MELILLA",
    }

    def __init__(self):
        super().__init__(site_id="base_online", priority=1)
        self._regex_expediente_cache: dict[str, re.Pattern[str]] = {}
        self._regex_expediente_fallback = re.compile(self.DEFAULT_REGEX_EXPEDIENTE)
        self._groq_guardian = GroqTokenGuardian(logger=logger)

    @staticmethod
    def _clean_str(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @classmethod
    def _upgrade_legacy_regex_expediente(cls, pattern: str) -> str:
        normalized = cls._clean_str(pattern)
        if normalized in cls._LEGACY_REGEX_EXPEDIENTE_VARIANTS:
            return cls.DEFAULT_REGEX_EXPEDIENTE
        return normalized

    @staticmethod
    def _normalize_text(text: Any) -> str:
        import unicodedata

        if not text:
            return ""
        t = str(text).strip().lower()
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

    @staticmethod
    def _convert_value(v: Any) -> Any:
        if isinstance(v, Decimal):
            return float(v)
        return v

    @staticmethod
    def _normalize_document_id(doc: Any) -> str:
        if not doc:
            return ""
        d = str(doc).strip().upper()
        if d.startswith("ES") and len(d) > 2:
            d = d[2:]
        return re.sub(r"[^A-Z0-9]+", "", d)

    @staticmethod
    def _normalize_cp(cp: Any) -> str:
        txt = re.sub(r"\D+", "", str(cp or "").strip())
        if not txt:
            return ""
        if len(txt) > 5:
            txt = txt[:5]
        return txt.zfill(5)

    @staticmethod
    def _format_date_ddmmyyyy(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        raw = str(value).strip()
        if not raw:
            return ""
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.split("+")[0], fmt).strftime("%d/%m/%Y")
            except Exception:
                continue
        return ""

    @classmethod
    def _infer_provincia_from_cp(cls, cp: str) -> str:
        if not cp or len(cp) != 5 or not cp.isdigit():
            return ""
        p2 = cp[:2]
        p3 = cp[:3]
        if p2 == "07":
            if "070" <= p3 <= "076":
                return "MALLORCA"
            if p3 == "077":
                return "MENORCA"
            return "IBIZA/FORMENTERA"
        if p2 == "35":
            if "350" <= p3 <= "354":
                return "GRAN CANARIA"
            if p3 == "355":
                return "LANZAROTE"
            return "FUERTEVENTURA"
        if p2 == "38":
            if "380" <= p3 <= "386":
                return "TENERIFE"
            if p3 == "387":
                return "LA PALMA"
            if p3 == "388":
                return "LA GOMERA"
            return "EL HIERRO"
        return cls._PROVINCIAS_CP.get(p2, "")

    @classmethod
    def _normalize_sigla_for_p1(cls, sigla_raw: str) -> str:
        sigla = cls._clean_str(sigla_raw).upper()
        if sigla in cls._P1_SIGLAS:
            return sigla
        return cls._P1_SIGLA_MAP.get(sigla, "CL")

    @classmethod
    def _valida_expediente_base(cls, expediente: str) -> bool:
        exp = cls._clean_str(expediente).upper()
        if re.match(r"^\d{5}-\d{4}[/\-]\d{3,5}-GIM$", exp):
            return True
        if re.match(r"^\d{5}-\d{4}/\d{1,5}$", exp):
            return True
        if re.match(r"^\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{7}$", exp):
            return True
        if re.match(r"^\d-\d{4}[/\-]\d{4,6}-(EXE|ECC)$", exp):
            return True
        return False

    @classmethod
    def _valida_expediente_gim(cls, expediente: str) -> bool:
        exp = cls._clean_str(expediente).upper()
        return bool(re.match(r"^\d{5}-\d{4}[/\-]\d{1,5}(?:-GIM)?$", exp))

    @classmethod
    def _materialize_from_canonical_if_present(cls, record: dict[str, Any]) -> dict[str, Any]:
        out = dict(record or {})
        canonical = out.get("__canonical_v1")
        if not isinstance(canonical, dict):
            return out

        resource = canonical.get("resource") or {}
        client = canonical.get("client") or {}
        vehicle = canonical.get("vehicle") or {}
        attachments = canonical.get("attachments") or []
        client_doc = client.get("document") or {}
        client_name = client.get("name") or {}
        client_contact = client.get("contact") or {}
        client_address = client.get("address") or {}
        plate = vehicle.get("plate") or {}

        out["idRecurso"] = out.get("idRecurso", resource.get("id"))
        out["idExp"] = out.get("idExp", resource.get("exp_id"))
        out["numclient"] = out.get("numclient", resource.get("numclient"))
        out["Expedient"] = out.get("Expedient", resource.get("expedient"))
        out["Organisme"] = out.get("Organisme", resource.get("organism"))
        out["TExp"] = out.get("TExp", resource.get("texp"))
        out["Estado"] = out.get("Estado", resource.get("state"))
        out["UsuarioAsignado"] = out.get("UsuarioAsignado", resource.get("assigned_user"))
        out["FaseProcedimiento"] = out.get("FaseProcedimiento", resource.get("phase"))
        out["SujetoRecurso"] = out.get("SujetoRecurso", resource.get("subject_name"))
        out["FUsuarioCompletado"] = out.get("FUsuarioCompletado", resource.get("completed_at"))

        out["cliente_tipo"] = out.get("cliente_tipo", client.get("type"))
        out["cliente_nif"] = out.get("cliente_nif", client_doc.get("nif"))
        out["cliente_nif_empresa"] = out.get("cliente_nif_empresa", client_doc.get("cif"))
        out["cif"] = out.get("cif", client_doc.get("cif"))
        out["cliente_nombre"] = out.get("cliente_nombre", client_name.get("first"))
        out["cliente_apellido1"] = out.get("cliente_apellido1", client_name.get("last1"))
        out["cliente_apellido2"] = out.get("cliente_apellido2", client_name.get("last2"))
        out["cliente_razon_social"] = out.get("cliente_razon_social", client_name.get("business"))
        out["Empresa"] = out.get("Empresa", client_name.get("business"))
        out["Nombrefiscal"] = out.get("Nombrefiscal", client_name.get("business"))
        out["cliente_email"] = out.get("cliente_email", client_contact.get("email"))
        out["cliente_tel1"] = out.get("cliente_tel1", client_contact.get("phone1"))
        out["cliente_tel2"] = out.get("cliente_tel2", client_contact.get("phone2"))
        out["cliente_movil"] = out.get("cliente_movil", client_contact.get("mobile"))

        out["cliente_domicilio"] = out.get("cliente_domicilio", client_address.get("street_name"))
        out["cliente_numero"] = out.get("cliente_numero", client_address.get("number"))
        out["cliente_escalera"] = out.get("cliente_escalera", client_address.get("stair"))
        out["cliente_planta"] = out.get("cliente_planta", client_address.get("floor"))
        out["cliente_puerta"] = out.get("cliente_puerta", client_address.get("door"))
        out["cliente_cp"] = out.get("cliente_cp", client_address.get("zip"))
        out["cliente_municipio"] = out.get("cliente_municipio", client_address.get("city"))
        out["cliente_provincia"] = out.get("cliente_provincia", client_address.get("province"))
        out["address_sigla"] = out.get("address_sigla", client_address.get("street_type"))

        out["conduc_adr"] = out.get("conduc_adr", client_address.get("street_name"))
        out["conduc_codpost"] = out.get("conduc_codpost", client_address.get("zip"))
        out["conduc_pobl"] = out.get("conduc_pobl", client_address.get("city"))
        out["conduc_prov"] = out.get("conduc_prov", client_address.get("province"))

        out["matricula"] = out.get("matricula", plate.get("value"))
        out["rs_matricula"] = out.get("rs_matricula", plate.get("value") if plate.get("source") == "rs_matricula" else None)
        out["exp_matricula"] = out.get("exp_matricula", plate.get("value") if plate.get("source") == "exp_matricula" else None)
        out["pub_matricula"] = out.get("pub_matricula", plate.get("value") if plate.get("source") == "pub_matricula" else None)
        out["dia_denuncia"] = out.get("dia_denuncia", vehicle.get("incident_date"))
        out["adjuntos"] = out.get("adjuntos", attachments)
        return out

    def _parse_expediente_base(self, expediente: str) -> dict:
        exp = self._clean_str(expediente).upper()
        m_gim = re.match(r"^(?P<id_ens>\d{5})-(?P<any>\d{4})[/\-](?P<num>\d{1,5})-GIM$", exp)
        if m_gim:
            return {
                "expediente_id_ens": m_gim.group("id_ens"),
                "expediente_any": m_gim.group("any"),
                "expediente_num": m_gim.group("num"),
                "num_butlleti": exp,
            }
        m_base = re.match(r"^(?P<id_ens>\d{5})-(?P<any>\d{4})[/\-](?P<num>\d{1,5})$", exp)
        if m_base:
            return {
                "expediente_id_ens": m_base.group("id_ens"),
                "expediente_any": m_base.group("any"),
                "expediente_num": m_base.group("num"),
                "num_butlleti": exp,
            }
        m_exe = re.match(r"^(?P<id_ens>\d)-(?P<any>\d{4})[/\-](?P<num>\d{4,6})-(EXE|ECC)$", exp)
        if m_exe:
            return {
                "expediente_id_ens": m_exe.group("id_ens"),
                "expediente_any": m_exe.group("any"),
                "expediente_num": m_exe.group("num"),
                "num_butlleti": exp,
            }
        return {
            "expediente_id_ens": "",
            "expediente_any": "",
            "expediente_num": "",
            "num_butlleti": exp,
        }

    def _determina_protocolo(self, fase: str) -> str:
        f = self._normalize_text(fase)
        if "identificacion" in f:
            return "P1"
        if any(tag in f for tag in ("denuncia", "propuesta", "subsanacion", "alegacion", "alegaciones")):
            return "P2"
        return "P3"

    def _get_motivos_base(self, fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str]:
        try:
            path = Path("config_motivos.json")
            config = {}
            if path.exists():
                import json

                config = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            config = {}

        fase_norm = self._normalize_text(fase_raw)
        selected = None
        for key, value in (config or {}).items():
            if self._normalize_text(key) in fase_norm:
                selected = value
                break

        exp = self._clean_str(expediente)
        sujeto_txt = self._clean_str(sujeto)

        if not selected:
            return f"Escrito relativo al exp {exp}", f"Se tenga por presentado el escrito. Exp {exp}"

        expone = self._clean_str(selected.get("expone")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)
        solicita = self._clean_str(selected.get("solicita")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)
        return expone, solicita

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
        resource_repo: Any | None = None,
    ) -> list[dict]:
        if resource_repo is None:
            raise RuntimeError("[base_online] fetch_candidates requires injected resource_repo (consultor/repository).")
        configured_regex = self._clean_str(config.get("regex_expediente")) or self.DEFAULT_REGEX_EXPEDIENTE
        regex_pattern = self._upgrade_legacy_regex_expediente(configured_regex) or self.DEFAULT_REGEX_EXPEDIENTE
        if configured_regex and configured_regex != regex_pattern:
            logger.info(
                "[base_online] regex_expediente legacy detectado; usando patron ampliado. configured=%r upgraded=%r",
                configured_regex,
                regex_pattern,
            )
        regex = self._regex_expediente_cache.get(regex_pattern)
        if regex is None:
            try:
                regex = re.compile(regex_pattern)
            except re.error:
                logger.warning(f"[base_online] Regex invalido en config.regex_expediente: {regex_pattern!r}. Usando fallback.")
                regex = self._regex_expediente_fallback
            self._regex_expediente_cache[regex_pattern] = regex

        recursos_map: dict[int, dict] = {}
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=config, limit=limit)
        for resource in resources:
            record = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            rid = record.get("idRecurso")
            if not rid:
                continue
            rid_int = int(rid)
            recursos_map[rid_int] = record

        out: list[dict] = []
        for _, recurso in recursos_map.items():
            if limit and len(out) >= limit:
                break

            expediente = self._clean_str(recurso.get("Expedient")).upper()
            expediente = re.sub(r"\s+", "", expediente)
            if not expediente or not regex.match(expediente):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": recurso.get("idRecurso"),
                            "Expedient": expediente,
                            "tipo_incidencia": "REGEX_DISCARDED",
                            "motivo": f"Expediente no valido para BASE: {expediente}",
                        }
                    )
                continue
            recurso["Expedient"] = expediente

            estado = int(recurso.get("Estado") or 0)
            usuario = self._clean_str(recurso.get("UsuarioAsignado"))
            if estado == 1 and authenticated_user and usuario != authenticated_user:
                continue
            if estado == 1 and not authenticated_user:
                continue

            out.append(recurso)
        return out

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        if not candidates:
            return []

        items_for_ia: list[dict] = []
        context_by_id: dict[str, ResourceContext] = {}
        for r in candidates:
            fase_raw = self._clean_str(r.get("FaseProcedimiento"))
            protocolo = self._determina_protocolo(fase_raw)
            rid_txt = str(r.get("idRecurso") or "").strip()
            if rid_txt:
                context_by_id[rid_txt] = ResourceContext(site_id=self.site_id, protocol=protocolo)
            items_for_ia.append(
                {
                    "idRecurso": r.get("idRecurso"),
                    "direccion_raw": self._clean_str(r.get("conduc_adr") or r.get("cliente_domicilio")),
                    "poblacion": self._clean_str(r.get("conduc_pobl") or r.get("cliente_municipio")),
                    "numero": self._clean_str(r.get("cliente_numero")),
                    "piso": self._clean_str(r.get("cliente_planta")),
                    "puerta": self._clean_str(r.get("cliente_puerta")),
                }
            )

        batch_mapping = await self._groq_guardian.classify_batch(items=items_for_ia, context_by_id=context_by_id)

        payloads: list[dict] = []
        for r in candidates:
            fase_raw = self._clean_str(r.get("FaseProcedimiento"))
            expediente_raw = self._clean_str(r.get("Expedient"))
            protocolo = self._determina_protocolo(fase_raw)

            exp_parts = self._parse_expediente_base(expediente_raw)
            nif = self._normalize_document_id(self._clean_str(r.get("cif") or r.get("cliente_nif")))
            conductor_dni = self._normalize_document_id(self._clean_str(r.get("conduc_dni")))
            conductor_name = self._clean_str(r.get("conduc_nom"))

            rid_str = str(r.get("idRecurso"))
            clasif = batch_mapping.get(rid_str)

            domicilio_raw = self._clean_str(r.get("conduc_adr") or r.get("cliente_domicilio"))
            poblacion = self._clean_str(r.get("conduc_pobl") or r.get("cliente_municipio"))
            numero_db = self._clean_str(r.get("cliente_numero"))
            cp = self._normalize_cp(r.get("conduc_codpost") or r.get("cliente_cp"))
            provincia = (
                self._clean_str(r.get("conduc_prov"))
                or self._clean_str(r.get("cliente_provincia"))
                or self._infer_provincia_from_cp(cp)
                or poblacion
            )

            if not clasif:
                clasif = classify_address_fallback(domicilio_raw)

            address_number = (clasif.get("numero") or numero_db).upper()
            if protocolo == "P1" and not self._clean_str(address_number):
                address_number = "S/N"

            address_sigla_raw = (clasif.get("tipo_via") or "CALLE").upper()
            address_sigla = self._normalize_sigla_for_p1(address_sigla_raw) if protocolo == "P1" else address_sigla_raw

            notif_data = {
                "address_sigla": address_sigla,
                "address_street": (clasif.get("calle") or domicilio_raw).upper(),
                "address_number": address_number,
                "address_zip": cp,
                "address_city": poblacion.upper(),
                "address_province": provincia.upper(),
                "address_country": get_default_country_es_ascii(),
                "address_pais": get_default_country_es_ascii(),
                "address_esc": (clasif.get("escalera") or r.get("cliente_escalera") or "").upper(),
                "address_planta": (clasif.get("planta") or r.get("cliente_planta") or "").upper(),
                "address_puerta": (clasif.get("puerta") or r.get("cliente_puerta") or "").upper(),
            }

            if protocolo == "P1":
                if not self._valida_expediente_gim(expediente_raw):
                    if on_discard:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": r.get("idRecurso"),
                                "Expedient": expediente_raw,
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": "P1 solo admite expedientes base validos (con o sin -GIM)",
                            }
                        )
                    continue
                if not cp:
                    if on_discard:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": r.get("idRecurso"),
                                "Expedient": expediente_raw,
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": "P1 descartado: codigo postal vacio o no inferible",
                            }
                        )
                    continue
                if not conductor_dni:
                    if on_discard:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": r.get("idRecurso"),
                                "Expedient": expediente_raw,
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": "P1 descartado: falta documento del conductor",
                            }
                        )
                    continue
                if not conductor_name:
                    if on_discard:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": r.get("idRecurso"),
                                "Expedient": expediente_raw,
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": "P1 descartado: falta nombre completo del conductor",
                            }
                        )
                    continue

            expone, solicita = self._get_motivos_base(fase_raw, expediente_raw, r.get("SujetoRecurso"))
            data_denuncia = self._format_date_ddmmyyyy(r.get("dia_denuncia")) or self._format_date_ddmmyyyy(r.get("FAlta"))
            contact_mobile = get_default_contact_mobile()
            contact_fixed = get_default_contact_phone_fixed()
            contact_email = get_default_contact_email()

            payload = {
                "idRecurso": self._convert_value(r["idRecurso"]),
                "idExp": self._convert_value(r["idExp"]),
                "numclient": self._convert_value(r.get("numclient")),
                "fase_procedimiento": fase_raw,
                "expediente": expediente_raw,
                "protocol": protocolo,
                "user_phone": contact_mobile,
                "p1_telefon_mobil": contact_mobile,
                "p1_telefon_fix": contact_fixed,
                "user_email": contact_email,
                "p1_correu": contact_email,
                "plate_number": normalize_plate_with_fallback(r.get("matricula")),
                "data_denuncia": data_denuncia,
                "nif": nif,
                "name": self._clean_str(r.get("SujetoRecurso")).upper(),
                "sujeto_recurso": self._clean_str(r.get("SujetoRecurso")).upper(),
                "cliente_nombre": self._clean_str(r.get("cliente_nombre")),
                "cliente_apellido1": self._clean_str(r.get("cliente_apellido1")),
                "cliente_apellido2": self._clean_str(r.get("cliente_apellido2")),
                "cliente_razon_social": self._clean_str(
                    r.get("cliente_razon_social")
                    or r.get("Nombrefiscal")
                    or r.get("Empresa")
                    or r.get("Nombrejuridico")
                    or r.get("Nombrecomercial")
                ),
                **notif_data,
                **exp_parts,
                "num_butlleti": expediente_raw,
                "disable_gesdoc": False,
                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }

            try:
                from core.client_docs_service import get_required_client_documents

                conn_str = build_sqlserver_connection_string()
                client_docs = await get_required_client_documents(
                    payload,
                    sqlserver_conn_str=conn_str,
                    strict=False,
                )
                payload["archivos"] = [str(p) for p in client_docs]
            except Exception as e:
                logger.warning("[base_online] Error cargando documentacion: %s", e)
                payload["archivos"] = []

            if protocolo == "P1":
                p1_name = conductor_name
                payload.update(
                    {
                        "p1_identificacio": conductor_dni,
                        "p1_llicencia_conduccio": conductor_dni,
                        "llicencia_conduccio": conductor_dni,
                        "p1_nom_complet": p1_name,
                    }
                )
                required = [
                    "expediente_id_ens",
                    "expediente_any",
                    "expediente_num",
                    "num_butlleti",
                    "data_denuncia",
                    "plate_number",
                    "p1_identificacio",
                    "p1_llicencia_conduccio",
                    "p1_nom_complet",
                    "address_sigla",
                    "address_street",
                    "address_number",
                    "address_zip",
                    "address_city",
                    "address_province",
                    "address_pais",
                ]
                missing = [k for k in required if not self._clean_str(payload.get(k))]
                if missing:
                    if on_discard:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": payload.get("idRecurso"),
                                "Expedient": payload.get("expediente"),
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": f"P1 descartado por faltantes: {', '.join(sorted(set(missing)))}",
                            }
                        )
                    continue

            if protocolo == "P2":
                payload.update(
                    {
                        "p2_nif": nif,
                        "p2_rao_social": payload["cliente_razon_social"] or payload["name"],
                        "p2_exposo": expone,
                        "p2_solicito": solicita,
                        "exposo": expone,
                        "solicito": solicita,
                    }
                )

            if protocolo == "P3":
                payload.update(
                    {
                        "p3_tipus_objecte": "IVTM",
                        "p3_dades_especifiques": payload.get("plate_number") or "",
                        "p3_tipus_solicitud_value": "1",
                        "p3_exposo": expone,
                        "p3_solicito": solicita,
                        "exposo": expone,
                        "solicito": solicita,
                    }
                )

            payloads.append(payload)
        return payloads
