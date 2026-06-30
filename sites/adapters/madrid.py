from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.address_classifier import classify_address_fallback
from core.address_defaults import (
    get_default_country_es_label,
    get_representative_city,
    get_representative_number,
    get_representative_province,
    get_representative_street_name,
    get_representative_street_type,
    get_representative_zip,
)
from core.contact_defaults import get_default_contact_email, get_default_contact_phone_fixed
from core.guardians import GroqTokenGuardian, ResourceContext
from core.validation.validators import normalize_plate_with_fallback
from .site_adapter import SiteAdapter

logger = logging.getLogger("brain")


class MadridAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )
    DEFAULT_REGEX_EXPEDIENTE = r"^(\d{3}[/-]\d{8,9}\.\d|\d{8,9}\.\d)$"
    DEFAULT_QUERY_ORGANISME = (
        "%SUBDIRECCION GNAL GESTION MULTAS DE MADRID%|%AYUNTAMIENTO DE MADRID%"
    )

    RE_DNI = re.compile(r"^\d{8}[A-Z]$")
    RE_NIE = re.compile(r"^[XYZ]\d{7}[A-Z]$")
    RE_CIF = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")
    RE_PASAPORTE_SIMPLE = re.compile(r"^[A-Z]{2,3}\d{5,9}$")

    def __init__(self):
        super().__init__(site_id="madrid", priority=0)
        self._regex_expediente_cache: dict[str, re.Pattern[str]] = {}
        self._regex_expediente_fallback = re.compile(self.DEFAULT_REGEX_EXPEDIENTE)
        self._groq_guardian = GroqTokenGuardian(logger=logger)

    @staticmethod
    def _clean_str(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @classmethod
    def _sanitize_query_organisme(cls, configured: Any) -> str:
        """
        Evita patrones excesivamente amplios (p.ej. %MADRID%) que capturan
        recursos de otras sedes y generan descartes/ruido cruzado.
        """
        raw = cls._clean_str(configured)
        if not raw:
            return cls.DEFAULT_QUERY_ORGANISME

        tokens = [t.strip() for t in raw.split("|") if cls._clean_str(t)]
        filtered: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            norm = token.strip().upper()
            if norm == "%MADRID%":
                continue
            if norm in seen:
                continue
            seen.add(norm)
            filtered.append(token)

        required_tokens = (
            "%SUBDIRECCION GNAL GESTION MULTAS DE MADRID%",
            "%AYUNTAMIENTO DE MADRID%",
        )
        for token in required_tokens:
            if token not in seen:
                filtered.append(token)
                seen.add(token)

        if not filtered:
            return cls.DEFAULT_QUERY_ORGANISME
        return "|".join(filtered)

    @staticmethod
    def _normalize_document_id(doc: Any) -> str:
        """
        Normaliza documentos (NIF/NIE/PASAPORTE) para uso en formularios:
        - Uppercase
        - Elimina prefijo 'ES' si existe (p.ej. 'ESB12345678')
        - Elimina separadores (espacios, guiones, puntos, etc.)
        """
        if not doc:
            return ""
        d = str(doc).strip().upper()
        if d.startswith("ES") and len(d) > 2:
            d = d[2:]
        d = re.sub(r"[^A-Z0-9]+", "", d)
        return d

    @staticmethod
    def _normalize_text(text: Any) -> str:
        import unicodedata

        if not text:
            return ""
        t = str(text).strip().lower()
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

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

        out["matricula"] = out.get("matricula", plate.get("value"))
        out["rs_matricula"] = out.get("rs_matricula", plate.get("value") if plate.get("source") == "rs_matricula" else None)
        out["exp_matricula"] = out.get("exp_matricula", plate.get("value") if plate.get("source") == "exp_matricula" else None)
        out["pub_matricula"] = out.get("pub_matricula", plate.get("value") if plate.get("source") == "pub_matricula" else None)
        out["pub_publicacion"] = out.get("pub_publicacion", vehicle.get("publication_text"))

        out["adjuntos"] = out.get("adjuntos", attachments)
        return out

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
            raise RuntimeError("[madrid] fetch_candidates requires injected resource_repo (consultor/repository).")
        regex_pattern = self._clean_str(config.get("regex_expediente")) or self.DEFAULT_REGEX_EXPEDIENTE
        regex = self._regex_expediente_cache.get(regex_pattern)
        if regex is None:
            try:
                regex = re.compile(regex_pattern)
            except re.error:
                logger.warning(f"[madrid] Regex invalido en config.regex_expediente: {regex_pattern!r}. Usando fallback.")
                regex = self._regex_expediente_fallback
            self._regex_expediente_cache[regex_pattern] = regex

        config = dict(config or {})
        config["query_organisme"] = self._sanitize_query_organisme(config.get("query_organisme"))

        recursos_map: dict[int, dict] = {}
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=config, limit=limit)
        for resource in resources:
            record = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            rid = record.get("idRecurso")
            if not rid:
                continue
            rid_int = int(rid)
            adjuntos: list[dict[str, Any]] = []
            for adj in list(record.get("adjuntos") or []):
                adj_copy = dict(adj or {})
                adj_id = adj_copy.get("id")
                if adj_id is not None and "url" not in adj_copy:
                    adj_copy["url"] = self.ADJUNTO_URL_TEMPLATE.format(id=int(adj_id))
                adjuntos.append(adj_copy)
            record["adjuntos"] = adjuntos
            recursos_map[rid_int] = record

        out: list[dict] = []
        for _, recurso in recursos_map.items():
            if limit and len(out) >= limit:
                break

            expediente = self._clean_str(recurso.get("Expedient")).upper()
            expediente = re.sub(r"\s+", "", expediente)
            if not expediente or not regex.match(expediente):
                if on_discard:
                    try:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": recurso.get("idRecurso"),
                                "Expedient": expediente,
                                "tipo_incidencia": "REGEX_DISCARDED",
                                "motivo": f"Expediente no valido para madrid: {expediente}",
                            }
                        )
                    except Exception:
                        pass
                continue
            recurso["Expedient"] = expediente

            fase_norm = self._normalize_text(recurso.get("FaseProcedimiento"))
            if any(x in fase_norm for x in ["reclamacion", "embargo", "apremio"]):
                if on_discard:
                    try:
                        on_discard(
                            {
                                "site_id": "madrid",
                                "idRecurso": recurso.get("idRecurso"),
                                "Expedient": recurso.get("Expedient"),
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": (
                                    "Madrid:trámites no reclamable por regla de sede (fase negra: "
                                    f"{self._clean_str(recurso.get('FaseProcedimiento'))}). "
                                    "Revisar si eltrámites estÃ¡ mal formado o si debe tratarse manualmente."
                                ),
                            }
                        )
                    except Exception:
                        pass
                continue

            estado = int(recurso.get("Estado") or 0)
            usuario = self._clean_str(recurso.get("UsuarioAsignado"))
            if estado == 1 and authenticated_user and usuario != authenticated_user:
                continue
            if estado == 1 and not authenticated_user:
                continue

            out.append(recurso)
        return out

    @staticmethod
    def _inferir_prefijo_expediente(*, fase_raw: str, es_empresa: bool) -> str:
        fase_norm = MadridAdapter._normalize_text(fase_raw)
        if "identificacion" in fase_norm:
            return "911" if es_empresa else "912"
        if "denuncia" in fase_norm:
            return "911" if es_empresa else "912"
        if "sancion" in fase_norm or "resolucion" in fase_norm:
            return "931" if es_empresa else "935"
        return "935"

    @staticmethod
    def _parse_expediente(expediente: str, *, fase_raw: str = "", es_empresa: bool = False) -> dict:
        exp = MadridAdapter._clean_str(expediente).upper()

        m1 = re.match(r"^(?P<nnn>\d{3})[/-](?P<exp>\d{8,9})\.(?P<d>\d)$", exp)
        if m1:
            exp_reconstruido = f"{m1.group('nnn')}/{m1.group('exp')}.{m1.group('d')}"
            return {
                "expediente_completo": exp_reconstruido,
                "expediente_tipo": "opcion1",
                "expediente_nnn": m1.group("nnn"),
                "expediente_eeeeeeeee": m1.group("exp"),
                "expediente_d": m1.group("d"),
                "expediente_lll": "",
                "expediente_aaaa": "",
                "expediente_exp_num": "",
            }

        m3 = re.match(r"^(?P<exp>\d{8,9})\.(?P<d>\d)$", exp)
        if m3:
            prefijo = MadridAdapter._inferir_prefijo_expediente(fase_raw=fase_raw, es_empresa=es_empresa)
            exp_reconstruido = f"{prefijo}/{m3.group('exp')}.{m3.group('d')}"
            return {
                "expediente_completo": exp_reconstruido,
                "expediente_tipo": "opcion1",
                "expediente_nnn": prefijo,
                "expediente_eeeeeeeee": m3.group("exp"),
                "expediente_d": m3.group("d"),
                "expediente_lll": "",
                "expediente_aaaa": "",
                "expediente_exp_num": "",
            }

        return {
            "expediente_completo": exp,
            "expediente_tipo": "",
            "expediente_nnn": "",
            "expediente_eeeeeeeee": "",
            "expediente_d": "",
            "expediente_lll": "",
            "expediente_aaaa": "",
            "expediente_exp_num": "",
        }

    @staticmethod
    def _load_motivos_config() -> dict:
        try:
            path = Path("config_motivos.json")
            if not path.exists():
                return {}
            import json as _json

            return _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _build_expone_solicita(fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str, str]:
        config = MadridAdapter._load_motivos_config()
        fase_norm = MadridAdapter._normalize_text(fase_raw)

        selected: dict | None = None
        selected_key = ""
        for key, value in (config or {}).items():
            key_norm = MadridAdapter._normalize_text(key)
            if key_norm and key_norm in fase_norm:
                selected = value
                selected_key = key
                break

        asunto = ""
        expone = ""
        solicita = ""
        if selected:
            asunto = MadridAdapter._clean_str(selected.get("asunto")).replace("{expediente}", expediente).replace(
                "{sujeto_recurso}", sujeto
            )
            expone = MadridAdapter._clean_str(selected.get("expone")).replace("{expediente}", expediente).replace(
                "{sujeto_recurso}", sujeto
            )
            solicita = (
                MadridAdapter._clean_str(selected.get("solicita"))
                .replace("{expediente}", expediente)
                .replace("{sujeto_recurso}", sujeto)
            )

        selected_key_norm = MadridAdapter._normalize_text(selected_key)
        blob = " ".join(
            [
                selected_key_norm,
                fase_norm,
                MadridAdapter._normalize_text(asunto),
                MadridAdapter._normalize_text(expone),
                MadridAdapter._normalize_text(solicita),
            ]
        )

        # Naturaleza del escrito:
        # - "A": AlegaciÃ³n
        # - "R": Recurso (incluye ResoluciÃ³n sancionadora, Apremio, Embargo, etc.)
        # - "I": IdentificaciÃ³n del conductor
        #
        # Regla: si hay match en config_motivos, preferimos mapping por key para evitar falsos positivos
        # (p.ej. "propuesta de resolucion" puede contener la palabra "recurso" en el texto).
        naturaleza = "A"
        if selected_key_norm in {"identificacion"} or "identificacion" in blob:
            naturaleza = "I"
        elif selected_key_norm in {"denuncia", "propuesta de resolucion", "subsanacion"}:
            naturaleza = "A"
        elif selected_key_norm in {
            "sancion",
            "apremio",
            "embargo",
            "reclamaciones",
            "requerimiento embargo",
            "extraordinario de revision",
        }:
            naturaleza = "R"
        elif any(
            tag in blob
            for tag in [
                "recurso",
                "reposicion",
                "reclamacion",
                "revision",
                "apremio",
                "embargo",
                "resolucion sancionadora",
                "sancion",
            ]
        ):
            naturaleza = "R"

        if not (asunto and expone and solicita):
            asunto = asunto or f"Recurso expediente {expediente}"
            expone = expone or "..."
            solicita = solicita or "..."

        return expone, solicita, naturaleza

    @staticmethod
    def _resolve_plate_number(recurso: dict) -> tuple[str, str]:
        # 1. Prioridad: Tabla recursosexp (rs.matricula)
        plate_rs = MadridAdapter._clean_str(recurso.get("rs_matricula"))
        if plate_rs:
            return re.sub(r"\s+", "", plate_rs).upper(), "Recursos.RecursosExp.matricula"

        # 2. Prioridad: Tabla expedientes (e.matricula)
        plate_exp = MadridAdapter._clean_str(recurso.get("matricula"))
        if plate_exp:
            return re.sub(r"\s+", "", plate_exp).upper(), "expedientes.matricula"

        # 3. Regex en texto (PublicaciÃ³n o Notas)
        # Regex mejorada que permite espacios y guiones opcionales pero respeta word boundaries
        regex = r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}[\s-]*[A-Z]{1,2})\b"

        def _try_extract(text: str, source_name: str) -> tuple[str, str] | None:
            if not text:
                return None
            m = re.search(regex, text.upper())
            if m:
                # Limpiar la matrÃ­cula encontrada de espacios y guiones
                clean_plate = m.group(1).replace(" ", "").replace("-", "")
                return clean_plate, source_name
            return None

        # 3.a PublicaciÃ³n
        res_pub = _try_extract(MadridAdapter._clean_str(recurso.get("pub_publicacion")), "pubExp.publicaciÃ³n")
        if res_pub:
            return res_pub

        # 3.b Notas
        res_notas = _try_extract(MadridAdapter._clean_str(recurso.get("notas")), "rs.notas")
        if res_notas:
            return res_notas

        return "", ""

    @staticmethod
    def _detectar_tipo_documento(doc: str) -> str:
        """
        Detecta el tipo de documento para el selector del formulario de Madrid.
        Valores esperados: NIF, NIE, PASAPORTE.
        """
        d = MadridAdapter._normalize_document_id(doc)
        if not d:
            return "NIF"

        if MadridAdapter.RE_NIE.match(d) or re.match(r"^[XYZ]\d{7,8}$", d):
            return "NIE"

        # DNI/NIF persona fÃ­sica o CIF persona jurÃ­dica (Madrid usa "NIF" para ambos)
        if MadridAdapter.RE_DNI.match(d) or MadridAdapter.RE_CIF.match(d) or re.match(r"^[KLM]\d{7}[A-Z0-9]$", d):
            return "NIF"

        # Pasaportes: muy variables, pero suele ser alfanumÃ©rico.
        if MadridAdapter.RE_PASAPORTE_SIMPLE.match(d) or (re.search(r"[A-Z]", d) and re.search(r"\d", d) and 6 <= len(d) <= 15):
            return "PASAPORTE"

        return "NIF"

    @staticmethod
    def _convert_value(v: Any) -> Any:
        from decimal import Decimal

        if isinstance(v, Decimal):
            return float(v)
        return v

    @staticmethod
    def _extract_street_name_from_raw(raw_address: str) -> str:
        """
        Intenta recuperar un nombre de vÃ­a desde una direcciÃ³n libre cuando la IA/fallback no lo devuelve.
        """
        raw = MadridAdapter._clean_str(raw_address).upper()
        if not raw:
            return ""

        # Quitar separadores frecuentes y espacios redundantes.
        text = re.sub(r"[,;]+", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""

        tokens = text.split(" ")
        filtered: list[str] = []
        for tok in tokens:
            # Omitimos tokens tÃ­picos de numeraciÃ³n o puerta.
            if re.fullmatch(r"\d+[A-Z]?", tok):
                continue
            if tok in {"S/N", "SN", "N", "NUM", "NUMERO", "NÂº", "PISO", "PTA", "PUERTA", "ESC", "ESCALERA"}:
                continue
            filtered.append(tok)

        return " ".join(filtered).strip()

    @staticmethod
    def _prevalidate_required_fields(payload: dict) -> None:
        required = [
            "idRecurso",
            "expediente_tipo",
            "naturaleza",
            "expone",
            "solicita",
            "rep_tipo_via",
            "rep_tipo_numeracion",
            "rep_cp",
            "rep_municipio",
            "rep_provincia",
            "rep_pais",
            "notif_tipo_documento",
            "notif_numero_documento",
            "notif_name",
            "notif_surname1",
            "notif_pais",
            "notif_provincia",
            "notif_municipio",
            "notif_tipo_via",
            "notif_nombre_via",
            "notif_tipo_numeracion",
            "notif_codigo_postal",
        ]
        missing = [k for k in required if not str(payload.get(k) or "").strip()]
        if payload.get("notif_tipo_numeracion") == "NUM" and not str(payload.get("notif_numero") or "").strip():
            missing.append("notif_numero")
        if missing:
            raise ValueError(f"Payload Madrid invÃ¡lido, faltan campos: {', '.join(sorted(set(missing)))}")

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        if not candidates:
            return []

        items: list[dict] = []
        for r in candidates:
            items.append(
                {
                    "idRecurso": r.get("idRecurso"),
                    "direccion_raw": self._clean_str(r.get("cliente_domicilio")),
                    "poblacion": self._clean_str(r.get("cliente_municipio")),
                    "numero": self._clean_str(r.get("cliente_numero")),
                    "piso": self._clean_str(r.get("cliente_planta")),
                    "puerta": self._clean_str(r.get("cliente_puerta")),
                }
            )

        context_by_id: dict[str, ResourceContext] = {}
        for r in candidates:
            rid = str(r.get("idRecurso") or "").strip()
            if rid:
                context_by_id[rid] = ResourceContext(site_id=self.site_id, protocol="")
        batch_mapping = await self._groq_guardian.classify_batch(items=items, context_by_id=context_by_id)

        payloads: list[dict] = []
        for r in candidates:
            expediente_raw = self._clean_str(r.get("Expedient")).upper()
            cif_recurso = self._clean_str(r.get("cif"))
            nif_individual = self._clean_str(r.get("cliente_nif"))
            nif_empresa = self._clean_str(r.get("cliente_nif_empresa"))
            tipo_cliente = int(r.get("cliente_tipo") or 0)

            # LÃ³gica de selecciÃ³n de NIF
            if tipo_cliente == 2:
                # Es empresa: Prioridad 1: nifempresa, Prioridad 2: rs.cif
                nif = nif_empresa or cif_recurso
                if not nif:
                    logger.warning(
                        "[MADRID] Cliente %s (%s) marcado como empresa (tipo 2) pero sin nifempresa ni cif. Saltando.",
                        r.get("numclient"),
                        r.get("SujetoRecurso"),
                    )
                    continue
            else:
                # Es fÃ­sica: Usar cliente_nif
                nif = nif_individual

            if not nif:
                logger.warning("[MADRID] Recurso %s sin NIF valido. Saltando.", r.get("idRecurso"))
                continue

            nif = self._normalize_document_id(nif)
            fase_raw = self._clean_str(r.get("FaseProcedimiento"))

            exp_parts = self._parse_expediente(expediente_raw, fase_raw=fase_raw, es_empresa=(tipo_cliente == 2))
            expediente_para_textos = exp_parts.get("expediente_completo", expediente_raw)

            expone, solicita, naturaleza = self._build_expone_solicita(
                fase_raw,
                expediente_para_textos,
                self._clean_str(r.get("SujetoRecurso")),
            )

            plate_number, plate_src = self._resolve_plate_number(r)

            rid = str(r.get("idRecurso"))
            clasif = batch_mapping.get(rid)
            domicilio_raw = self._clean_str(r.get("cliente_domicilio"))
            numero_db = self._clean_str(r.get("cliente_numero"))
            poblacion = self._clean_str(r.get("cliente_municipio"))
            piso_db = self._clean_str(r.get("cliente_planta"))
            puerta_db = self._clean_str(r.get("cliente_puerta"))
            escalera_db = self._clean_str(r.get("cliente_escalera"))

            if not clasif:
                clasif = classify_address_fallback(domicilio_raw)

            notif_tipo_via = (clasif.get("tipo_via") or "CALLE").upper()
            notif_nombre_via = (clasif.get("calle") or "").upper()
            if not notif_nombre_via:
                notif_nombre_via = self._extract_street_name_from_raw(domicilio_raw)
            if not notif_nombre_via and poblacion:
                # Ãšltimo fallback para pasar validaciÃ³n mÃ­nima.
                notif_nombre_via = poblacion.upper()
            notif_numero = (clasif.get("numero") or numero_db).upper()
            notif_escalera = ((clasif.get("escalera") or escalera_db) or "").upper()
            notif_planta = ((clasif.get("planta") or piso_db) or "").upper()
            notif_puerta = ((clasif.get("puerta") or puerta_db) or "").upper()

            tipo_numeracion = "NUM" if self._clean_str(notif_numero) else "S/N"
            provincia_notif = self._clean_str(r.get("cliente_provincia")).upper() or poblacion.upper()
            representative_city = get_representative_city()
            representative_province = get_representative_province()
            representative_street_name = get_representative_street_name()
            representative_number = get_representative_number()
            representative_zip = get_representative_zip()
            representative_street_type = get_representative_street_type()

            representante = {
                "rep_tipo_via": representative_street_type,
                "rep_tipo_numeracion": "NUM",
                "representative_city": representative_city,
                "representative_province": representative_province,
                "representative_country": get_default_country_es_label(),
                "representative_street": representative_street_name,
                "representative_number": representative_number,
                "representative_zip": representative_zip,
                "representative_email": get_default_contact_email(),
                "representative_phone": get_default_contact_phone_fixed(),
                "rep_nombre_via": representative_street_name,
                "rep_numero": representative_number,
                "rep_cp": representative_zip,
                "rep_municipio": representative_city,
                "rep_provincia": representative_province,
                "rep_pais": get_default_country_es_label(),
                "rep_email": get_default_contact_email(),
                "rep_movil": get_default_contact_phone_fixed(),
                "rep_telefono": get_default_contact_phone_fixed(),
                "rep_tipo_numeracion": "NUM",
            }

            payload = {
                "idRecurso": self._convert_value(r.get("idRecurso")),
                "idExp": self._convert_value(r.get("idExp")),
                "expediente": expediente_raw,
                "numclient": self._convert_value(r.get("numclient")),
                "sujeto_recurso": self._clean_str(r.get("SujetoRecurso")),
                "fase_procedimiento": fase_raw,
                "plate_number": normalize_plate_with_fallback(plate_number),
                "plate_number_source": plate_src,
                "user_phone": get_default_contact_phone_fixed(),
                "inter_telefono": get_default_contact_phone_fixed(),
                "inter_email_check": bool(self._clean_str(r.get("cliente_email"))),
                **representante,
                "notif_tipo_documento": self._detectar_tipo_documento(nif),
                "notif_numero_documento": nif,
                "notif_name": self._clean_str(r.get("cliente_nombre")).upper(),
                "notif_surname1": self._clean_str(r.get("cliente_apellido1")).upper(),
                "notif_surname2": self._clean_str(r.get("cliente_apellido2")).upper(),
                "notif_razon_social": self._clean_str(
                    r.get("cliente_razon_social")
                    or r.get("Nombrefiscal")
                    or r.get("Empresa")
                    or r.get("Nombrejuridico")
                    or r.get("Nombrecomercial")
                ).upper(),
                "notif_pais": get_default_country_es_label(),
                "notif_provincia": provincia_notif,
                "notif_municipio": poblacion.upper(),
                "notif_tipo_via": notif_tipo_via,
                "notif_nombre_via": notif_nombre_via,
                "notif_tipo_numeracion": tipo_numeracion,
                "notif_numero": self._clean_str(notif_numero),
                "notif_portal": "",
                "notif_escalera": self._clean_str(notif_escalera),
                "notif_planta": self._clean_str(notif_planta),
                "notif_puerta": self._clean_str(notif_puerta),
                "notif_codigo_postal": self._clean_str(r.get("cliente_cp")),
                "notif_email": get_default_contact_email(),
                "notif_movil": "",
                "notif_telefono": get_default_contact_phone_fixed(),
                **exp_parts,
                # Alias directos para el controller (evita depender de map_data)
                "exp_tipo": exp_parts.get("expediente_tipo"),
                "exp_nnn": exp_parts.get("expediente_nnn"),
                "exp_eeeeeeeee": exp_parts.get("expediente_eeeeeeeee"),
                "exp_d": exp_parts.get("expediente_d"),
                "exp_lll": exp_parts.get("expediente_lll"),
                "exp_aaaa": exp_parts.get("expediente_aaaa"),
                "exp_exp_num": exp_parts.get("expediente_exp_num"),
                "naturaleza": naturaleza,
                "expone": expone,
                "solicita": solicita,
                "adjuntos": r.get("adjuntos") or [],
                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }

            try:
                self._prevalidate_required_fields(payload)
            except ValueError as e:
                logger.warning(
                    "[MADRID] Recurso %s descartado por payload invÃ¡lido: %s",
                    r.get("idRecurso"),
                    e,
                )
                continue

            payloads.append(payload)

        return payloads
