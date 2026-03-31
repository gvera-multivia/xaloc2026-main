from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pyodbc

from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from core.validation.validators import normalize_plate_with_fallback
from sites.diputacio_bcn.texts import resolve_phase_texts
from sites.diputacio_bcn.municipio_codes import MUNICIPIO_TO_CODE, resolve_codmuni

from .site_adapter import SiteAdapter

logger = logging.getLogger("brain")


class DiputacioBcnAdapter(SiteAdapter):
    ORGT_IDENTIFICACIO_URL = (
        "https://orgt.diba.cat/es/Home/selecciomunicipi?areaToReturn=TramitsPagaments"
        "&viewToReturn=idconductor&controllerToReturn=IdentificacioConductor"
        "&concepteTramit=NO&codiError=WEB00011&parametre=V&keyModel=modelIDCONDUCTOR"
    )
    EXCLUDED_ORGANISMES = {"AJUNTAMENT DE MANRESA", "AJUNTAMENT DE RIPOLLET"}
    BLOCKED_PHASE_TOKENS = ("IDENTIFIC",)
    EXTRA_QUERY_ORGANISMES = (
        "%ORGANISME DE GESTI%TRIBUT%ORGT%DIPUTACI%BARCELONA%",
        "%ORGANISMO DE GESTION TRIBUT%ORGT%DIPUTACION DE BARCELONA%",
    )
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )

    def __init__(self) -> None:
        super().__init__(site_id="diputacio_bcn", priority=6)
        self._allowed_organismes_cache: set[str] | None = None
        self._organisme_urls_cache: dict[str, set[str]] | None = None
        self._motivos_cache: dict[str, dict[str, Any]] | None = None

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @classmethod
    def _norm(cls, value: Any) -> str:
        txt = cls._clean(value).upper()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return " ".join(txt.split())

    @classmethod
    def _norm_membership_key(cls, value: Any) -> str:
        norm = cls._norm(value)
        if not norm:
            return ""
        norm = re.sub(r"[^A-Z0-9]+", " ", norm)
        return " ".join(norm.split())

    @classmethod
    def _normalize_document(cls, value: Any) -> str:
        doc = cls._clean(value).upper()
        if doc.startswith("ES") and len(doc) > 2:
            doc = doc[2:]
        return re.sub(r"[^A-Z0-9]+", "", doc)

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
        client_address = client.get("address") or {}
        plate = vehicle.get("plate") or {}

        out["idRecurso"] = out.get("idRecurso", resource.get("id"))
        out["idExp"] = out.get("idExp", resource.get("exp_id"))
        out["numclient"] = out.get("numclient", resource.get("numclient"))
        out["automatic_id"] = out.get("automatic_id", resource.get("automatic_id"))
        out["Expedient"] = out.get("Expedient", resource.get("expedient"))
        out["Organisme"] = out.get("Organisme", resource.get("organism"))
        out["Estado"] = out.get("Estado", resource.get("state"))
        out["UsuarioAsignado"] = out.get("UsuarioAsignado", resource.get("assigned_user"))
        out["FaseProcedimiento"] = out.get("FaseProcedimiento", resource.get("phase"))
        out["SujetoRecurso"] = out.get("SujetoRecurso", resource.get("subject_name"))
        out["tipodecliente"] = out.get("tipodecliente", client.get("type"))
        out["nif"] = out.get("nif", client_doc.get("nif"))
        out["nifempresa"] = out.get("nifempresa", client_doc.get("cif"))
        out["Nombre"] = out.get("Nombre", client_name.get("first"))
        out["Apellido1"] = out.get("Apellido1", client_name.get("last1"))
        out["Apellido2"] = out.get("Apellido2", client_name.get("last2"))
        out["Nombrefiscal"] = out.get("Nombrefiscal", client_name.get("business"))
        out["cliente_municipio"] = out.get("cliente_municipio", client_address.get("city"))
        out["MunicipioPoblacion"] = out.get("MunicipioPoblacion", client_address.get("city"))
        out["poblacion"] = out.get("poblacion", client_address.get("city"))
        out["municipio"] = out.get("municipio", client_address.get("city"))
        out["conduc_pobl"] = out.get("conduc_pobl", client_address.get("city"))
        out["matricula"] = out.get("matricula", plate.get("value"))
        out["rs_matricula"] = out.get("rs_matricula", plate.get("value") if plate.get("source") == "rs_matricula" else None)
        out["exp_matricula"] = out.get("exp_matricula", plate.get("value") if plate.get("source") == "exp_matricula" else None)
        out["pub_matricula"] = out.get("pub_matricula", plate.get("value") if plate.get("source") == "pub_matricula" else None)
        out["adjuntos"] = out.get("adjuntos", attachments)
        return out

    def _load_allowed_organismes(self, conn_str: str) -> set[str]:
        if self._allowed_organismes_cache is not None:
            return self._allowed_organismes_cache

        out: set[str] = set()
        excluded = {self._norm_membership_key(v) for v in self.EXCLUDED_ORGANISMES}
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT organismo
                    FROM org_identif_direct
                    WHERE url = ?
                    """,
                    (self.ORGT_IDENTIFICACIO_URL,),
                )
                rows = cur.fetchall()
                for row in rows:
                    value = self._norm_membership_key(row[0] if row else "")
                    if not value or value in excluded:
                        continue
                    out.add(value)
        self._allowed_organismes_cache = out
        return out

    def _load_organisme_urls(self, conn_str: str) -> dict[str, set[str]]:
        if self._organisme_urls_cache is not None:
            return self._organisme_urls_cache

        out: dict[str, set[str]] = {}
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT organismo, url
                    FROM org_identif_direct
                    WHERE organismo IS NOT NULL
                      AND url IS NOT NULL
                    """
                )
                for row in cur.fetchall():
                    organisme = self._norm_membership_key(row[0] if row else "")
                    url = self._clean(row[1] if row else "")
                    if not organisme or not url:
                        continue
                    out.setdefault(organisme, set()).add(url)
        self._organisme_urls_cache = out
        return out

    @classmethod
    def _merge_query_organisme(cls, configured: Any) -> str:
        configured_txt = cls._clean(configured)
        parts = [p.strip() for p in configured_txt.split("|") if p and p.strip()] if configured_txt else []
        seen = {p.upper() for p in parts}
        for extra in cls.EXTRA_QUERY_ORGANISMES:
            token = str(extra or "").strip()
            if not token:
                continue
            key = token.upper()
            if key in seen:
                continue
            parts.append(token)
            seen.add(key)
        return "|".join(parts)

    @classmethod
    def _has_direct_non_orgt_route(
        cls,
        organisme: str,
        organisme_urls: dict[str, set[str]],
    ) -> bool:
        urls = organisme_urls.get(cls._norm_membership_key(organisme)) or set()
        if not urls:
            return False
        return any(str(url).strip() != cls.ORGT_IDENTIFICACIO_URL for url in urls)

    @classmethod
    def _extract_explicit_organismes_from_query(cls, configured: Any) -> set[str]:
        txt = cls._clean(configured)
        if not txt:
            return set()

        excluded = {cls._norm_membership_key(v) for v in cls.EXCLUDED_ORGANISMES}
        out: set[str] = set()
        for raw_part in txt.split("|"):
            token = str(raw_part or "").strip()
            if not token:
                continue
            # Mantener solo patrones exactos con wildcard opcional al inicio/fin.
            # Evitamos patrones con wildcard interno para no abrir un allowlist demasiado amplio.
            inner = token.strip("%").strip()
            if not inner:
                continue
            if "%" in inner or "_" in inner:
                continue
            norm = cls._norm_membership_key(inner)
            if not norm or norm in excluded:
                continue
            out.add(norm)
        return out

    @classmethod
    def _is_orgt_diba_alias(cls, organisme: Any) -> bool:
        norm = cls._norm(organisme)
        if not norm:
            return False
        # Match robusto para variaciones de acentos/codificacion y textos
        # incompletos detectados en XVIA/SQL.
        has_orgt = "ORGT" in norm or "GESTION TRIBUTA" in norm or "GESTIO TRIBUTA" in norm
        has_diba = "DIPUTAC" in norm or "DIBA" in norm
        has_bcn_hint = "BARCELONA" in norm or "OFICINA DE MULTES" in norm
        return bool(has_orgt and has_diba and has_bcn_hint)

    @classmethod
    def _is_blocked_phase(cls, fase: Any) -> bool:
        fase_norm = cls._norm(fase)
        if not fase_norm:
            return False
        return any(token in fase_norm for token in cls.BLOCKED_PHASE_TOKENS)

    @classmethod
    def _resolve_plate(cls, item: dict[str, Any]) -> str:
        for key in ("rs_matricula", "exp_matricula", "pub_matricula", "matricula"):
            normalized = normalize_plate_with_fallback(item.get(key))
            if normalized != ".":
                return normalized
        return ""

    @classmethod
    def _extract_municipio_from_organisme(cls, organisme: Any) -> str:
        norm = cls._norm(organisme)
        if not norm:
            return ""
        if cls._is_orgt_diba_alias(norm):
            # ORGT Diputacio es un ente agregador, no un municipio concreto.
            return ""
        patterns = (
            r"\b(?:AJUNTAMENT|AYUNTAMENT|AYUNTAMIENTO|AYTO\.?)\s+(?:DE|DEL|DE LA|DE LES|DE LOS|DE LAS)\s+(.+)",
            r"\b(?:AJUNTAMENT|AYUNTAMENT|AYUNTAMIENTO|AYTO\.?)\s+(.+)",
        )
        for pattern in patterns:
            match = re.search(pattern, norm)
            if not match:
                continue
            candidate = re.split(r"\s+-\s+|\s+\|\s+|;|,", match.group(1), maxsplit=1)[0]
            candidate = re.sub(r"\s+", " ", candidate).strip(" -'")
            if candidate:
                return candidate
        return ""

    @classmethod
    def _extract_municipio_from_cliente_direccion(cls, value: Any) -> str:
        raw = cls._norm(value)
        if not raw:
            return ""
        for municipio in sorted(MUNICIPIO_TO_CODE.keys(), key=len, reverse=True):
            if municipio and municipio in raw:
                return municipio
        return ""

    @classmethod
    def _resolve_municipio_for_payload(cls, item: dict[str, Any]) -> str:
        # Prioridad al municipio del organismo sancionador cuando sea resoluble
        # en el combo de Diputacio BCN; ORGT queda cubierto porque retorna "".
        organisme_municipio = cls._extract_municipio_from_organisme(item.get("Organisme"))
        if organisme_municipio and resolve_codmuni(organisme_municipio):
            return organisme_municipio

        first_candidate = organisme_municipio
        for key in ("cliente_municipio", "MunicipioPoblacion", "poblacion", "municipio", "conduc_pobl"):
            value = cls._clean(item.get(key))
            if not value:
                continue
            if resolve_codmuni(value):
                return value
            if not first_candidate:
                first_candidate = value

        direccion_municipio = cls._extract_municipio_from_cliente_direccion(
            item.get("cliente_domicilio")
            or item.get("direccion_raw")
            or item.get("domicilio")
            or item.get("address")
        )
        if direccion_municipio and resolve_codmuni(direccion_municipio):
            return direccion_municipio
        return first_candidate

    @classmethod
    def _should_route_to_redsara_barcelona(cls, item: dict[str, Any]) -> bool:
        if not cls._is_orgt_diba_alias(item.get("Organisme")):
            return False
        if cls._is_blocked_phase(item.get("FaseProcedimiento")):
            return False
        return cls._norm(item.get("cliente_municipio")) == "BARCELONA"

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
            raise RuntimeError("[diputacio_bcn] fetch_candidates requires injected resource_repo (consultor/repository).")

        cfg = dict(config or {})
        if not str(cfg.get("query_organisme") or "").strip():
            cfg["query_organisme"] = "%AJUNTAMENT%|%AYUNTAMIENTO%|%ORGT%|%DIPUTACIO DE BARCELONA%"
        cfg["query_organisme"] = self._merge_query_organisme(cfg.get("query_organisme"))
        configured_organismes = self._extract_explicit_organismes_from_query(cfg.get("query_organisme"))
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=cfg, limit=limit)
        allowed_organismes = self._load_allowed_organismes(conn_str) | configured_organismes
        organisme_urls = self._load_organisme_urls(conn_str)

        out: list[dict] = []
        for resource in resources:
            if limit and len(out) >= limit:
                break

            item = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            rid = item.get("idRecurso")
            organisme = self._norm_membership_key(item.get("Organisme"))
            fase = self._clean(item.get("FaseProcedimiento"))
            expediente = self._clean(item.get("Expedient"))

            if self._should_route_to_redsara_barcelona(item):
                continue

            if organisme not in allowed_organismes:
                is_alias = self._is_orgt_diba_alias(organisme)
                if not is_alias:
                    # Algunos organismos entran por la query amplia (%AJUNTAMENT%|%AYUNTAMIENTO%)
                    # pero tienen sede directa propia y no deben generar incidencia de ORGT.
                    if self._has_direct_non_orgt_route(organisme, organisme_urls):
                        continue
                    if on_discard:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": rid,
                                "Expedient": expediente,
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": f"Organismo fuera del catalogo ORGT soportado: {self._clean(item.get('Organisme'))}",
                            }
                        )
                    continue

            if self._is_blocked_phase(fase):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": f"Fase bloqueada temporalmente para Diputacio BCN: {fase}",
                        }
                    )
                continue

            estado = int(item.get("Estado") or 0)
            usuario = self._clean(item.get("UsuarioAsignado"))
            if estado == 1 and authenticated_user and not self._same_user_identity(usuario, authenticated_user):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "RESOURCE_ASSIGNED_TO_OTHER_USER",
                            "motivo": (
                                "Recurso asignado a otro usuario en XVIA "
                                f"(asignado={usuario!r}, actual={self._clean(authenticated_user)!r})."
                            ),
                        }
                    )
                continue
            if estado == 1 and not authenticated_user:
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "RESOURCE_ASSIGNED_WITHOUT_SESSION",
                            "motivo": "Recurso ya asignado en XVIA y no hay usuario autenticado para validarlo.",
                        }
                    )
                continue

            adjuntos = list(item.get("adjuntos") or [])
            for adj in adjuntos:
                if "url" not in adj and adj.get("id") is not None:
                    adj["url"] = self.ADJUNTO_URL_TEMPLATE.format(id=int(adj["id"]))
            item["adjuntos"] = adjuntos
            out.append(item)
        return out

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        payloads: list[dict] = []
        for item in candidates:
            expediente = self._clean(item.get("Expedient"))
            if not expediente:
                continue

            tipodecliente = self._clean(item.get("tipodecliente"))
            is_company = tipodecliente == "2"
            nombre = self._clean(item.get("Nombre"))
            apellido1 = self._clean(item.get("Apellido1"))
            apellido2 = self._clean(item.get("Apellido2"))
            nombrefiscal = self._clean(item.get("Nombrefiscal"))
            sujeto = self._clean(item.get("SujetoRecurso")) or nombrefiscal or " ".join(
                [part for part in [nombre, apellido1, apellido2] if part]
            ).strip()

            nif = self._normalize_document(item.get("nif"))
            nifempresa = self._normalize_document(item.get("nifempresa"))
            nif_interessat = nifempresa if is_company else nif
            if not nif_interessat:
                nif_interessat = nif or nifempresa

            fase = self._clean(item.get("FaseProcedimiento"))
            asunto, expone, solicita = resolve_phase_texts(
                fase_procedimiento=fase,
                expediente=expediente,
                sujeto_recurso=sujeto,
            )
            municipio_value = self._resolve_municipio_for_payload(item)
            codmuni = resolve_codmuni(municipio_value)
            if not codmuni:
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": item.get("idRecurso"),
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": (
                                "No se pudo resolver codmuni de Diputacio BCN "
                                f"(municipio={municipio_value!r}, organismo={self._clean(item.get('Organisme'))!r})"
                            ),
                        }
                    )
                continue

            payloads.append(
                {
                    "idRecurso": item.get("idRecurso"),
                    "idExp": item.get("idExp"),
                    "numclient": item.get("numclient"),
                    "automatic_id": item.get("automatic_id"),
                    "expediente": expediente,
                    "exp_sancionador": expediente,
                    "fase_procedimiento": fase,
                    "matricula": self._resolve_plate(item),
                    "municipio": municipio_value,
                    "codmuni": codmuni,
                    "organismo": self._clean(item.get("Organisme")),
                    "tipo_representado": "juridica" if is_company else "fisica",
                    "tipodecliente": tipodecliente,
                    "sujeto_recurso": sujeto,
                    "nif": nif,
                    "nifempresa": nifempresa,
                    "nif_interessat": nif_interessat,
                    "nom_cr4": nombre,
                    "cognom1": apellido1,
                    "cognom2": apellido2,
                    "nom_juridica": nombrefiscal or sujeto,
                    "asunto": asunto,
                    "expone": expone,
                    "solicita": solicita,
                    "comentari": f"Presentacio documentacio expedient sancionador {expediente}",
                    "telefon": get_default_contact_mobile(),
                    "email": get_default_contact_email(),
                    "adjuntos": list(item.get("adjuntos") or []),
                    "archivos": [],
                    "doc_acreditativa": "",
                    "doc_tramite": "",
                    "trace_tag": f"id{item.get('idRecurso')}_{re.sub(r'[^0-9]+', '', expediente) or 'sinexp'}",
                    "source": "brain_orchestrator",
                    "claimed_at": datetime.now().isoformat(),
                }
            )
        return payloads
