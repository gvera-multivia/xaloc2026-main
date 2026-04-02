from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Optional

from .site_adapter import SiteAdapter


class AtcAdapter(SiteAdapter):
    TARGET_ORGANISME_TOKEN = "AGENCIA TRIBUTARIA AUTONOMICA DE CATALUÑA"
    TARGET_ORGANISME_TOKEN_SHORT = "AGENCIA TRIBUTARIA DE CATALUÑA"
    DEFAULT_QUERY_ORGANISME = (
        "%AGENCIA TRIBUTARIA AUTONOMICA DE CATALUÑA%"
        "|%AGENCIA TRIBUTARIA AUTONOMICA DE CATALUNA%"
        "|%AGENCIA TRIBUTARIA DE CATALUÑA%"
        "|%AGENCIA TRIBUTARIA DE CATALUNA%"
        "|%AGÈNCIA TRIBUTARIA DE CATALUÑA%"
        "|%AGÈNCIA TRIBUTÀRIA DE CATALUNYA%"
    )
    CLIENTES_BLOQUEADOS = {13607, 14274}
    REA_RE = re.compile(r"(RECLAMACION\s+(ECONOMICO|ECO)[- ]*(ADMINISTRATIVA|ADVA)|(?<!\w)REA(?!\w))", re.IGNORECASE)
    REPOS_RE = re.compile(r"(RECURSO\s+(EXTRAORDINARIO|REVISION|DE\s+REPOSICION)|(?<!\w)REPOSICION(?!\w))", re.IGNORECASE)
    _TARGET_ORGANISME_PATTERNS = (
        re.compile(r"\bAGENCIA\W+TRIBUTARIA\W+AUTONOMICA\W+DE\W+CATALUN(?:A|YA)\b"),
        re.compile(r"\bAGENCIA\W+TRIBUTARIA\W+DE\W+CATALUN(?:A|YA)\b"),
    )
    _EXPEDIENT_PATTERNS = (
        re.compile(r"\b\d{14}\b"),
        re.compile(r"\b\d{5,}-\d{4}/\d{1,10}-[A-Z]{2,5}\b", re.IGNORECASE),
        re.compile(r"\b\d-\d{4}/\d{1,10}-[A-Z]{2,5}\b", re.IGNORECASE),
        re.compile(r"\b\d{4}/\d{6,}\b"),
    )

    def __init__(self) -> None:
        super().__init__(site_id="atc", priority=7)

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _norm(cls, value: Any) -> str:
        txt = cls._clean(value).upper()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return " ".join(txt.split())

    @classmethod
    def _parse_date(cls, value: Any) -> date | None:
        raw = cls._clean(value)
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(raw.split("+")[0], fmt).date()
            except Exception:
                continue
        return None

    @classmethod
    def _normalize_expediente(cls, value: Any) -> str:
        raw = cls._clean(value)
        if not raw:
            return ""
        text = " ".join(raw.split())
        for rx in cls._EXPEDIENT_PATTERNS:
            m = rx.search(text)
            if m:
                return m.group(0).strip()
        # ATC: cuando llega "expediente + bloque extra", nos quedamos con el primero.
        return text.split(" ", 1)[0].strip()

    @classmethod
    def _infer_protocol(cls, *, csv_acto: str, procedim: str) -> str:
        if not csv_acto:
            return "registro_sin_csv"
        if cls.REA_RE.search(procedim or ""):
            return "rea"
        if cls.REPOS_RE.search(procedim or ""):
            return "reposicio"
        return "reposicio"

    @classmethod
    def _is_target_organisme(cls, organisme: Any) -> bool:
        norm_value = cls._norm(organisme)
        if not norm_value:
            return False
        if cls._norm(cls.TARGET_ORGANISME_TOKEN) in norm_value:
            return True
        # Token corto: cubre "AGÈNCIA TRIBUTARIA DE CATALUÑA" (sin "AUTONOMICA")
        if cls.TARGET_ORGANISME_TOKEN_SHORT in norm_value:
            return True
        return any(pattern.search(norm_value) for pattern in cls._TARGET_ORGANISME_PATTERNS)

    @classmethod
    def _merge_query_organisme(cls, configured: Any) -> str:
        raw = cls._clean(configured)
        if not raw:
            return cls.DEFAULT_QUERY_ORGANISME
        chunks = [cls._clean(part) for part in re.split(r"[|;,]+", raw)]
        chunks = [part for part in chunks if part]
        existing_upper = {part.upper() for part in chunks}
        for token in cls.DEFAULT_QUERY_ORGANISME.split("|"):
            if token.upper() not in existing_upper:
                chunks.append(token)
                existing_upper.add(token.upper())
        return "|".join(chunks)

    @classmethod
    def _materialize_from_canonical_if_present(cls, record: dict[str, Any]) -> dict[str, Any]:
        out = dict(record or {})
        canonical = out.get("__canonical_v1")
        if not isinstance(canonical, dict):
            return out
        resource = canonical.get("resource") or {}
        client = canonical.get("client") or {}
        client_doc = client.get("document") or {}
        client_name = client.get("name") or {}

        out["idRecurso"] = out.get("idRecurso", resource.get("id"))
        out["idExp"] = out.get("idExp", resource.get("exp_id"))
        out["numclient"] = out.get("numclient", resource.get("numclient"))
        out["Expedient"] = out.get("Expedient", resource.get("expedient"))
        out["FaseProcedimiento"] = out.get("FaseProcedimiento", resource.get("phase"))
        out["Organisme"] = out.get("Organisme", resource.get("organism"))
        out["Procedim"] = out.get("Procedim", resource.get("procedure"))
        out["ExpedientePublicacion"] = out.get("ExpedientePublicacion", resource.get("publication_csv"))
        out["fecpres"] = out.get("fecpres", resource.get("submission_date"))
        out["nif"] = out.get("nif", client_doc.get("nif"))
        out["nifempresa"] = out.get("nifempresa", client_doc.get("cif"))
        out["Nombre"] = out.get("Nombre", client_name.get("first"))
        out["Apellido1"] = out.get("Apellido1", client_name.get("last1"))
        out["Apellido2"] = out.get("Apellido2", client_name.get("last2"))
        out["Nombrefiscal"] = out.get("Nombrefiscal", client_name.get("business"))
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
            raise RuntimeError("[atc] fetch_candidates requires injected resource_repo (consultor/repository).")
        config = dict(config or {})
        config["query_organisme"] = self._merge_query_organisme(config.get("query_organisme"))
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=config, limit=limit)
        out: list[dict] = []
        for resource in resources:
            item = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            if not self._is_target_organisme(item.get("Organisme")):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": item.get("idRecurso"),
                            "Expedient": self._clean(item.get("Expedient")),
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": f"Organismo fuera de ATC: {self._clean(item.get('Organisme'))}",
                        }
                    )
                continue
            out.append(item)
        return out

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        payloads: list[dict] = []
        for item in candidates:
            expediente = self._normalize_expediente(item.get("Expedient"))
            csv_acto = self._clean(item.get("ExpedientePublicacion"))
            procedim = self._clean(item.get("Procedim"))
            protocol = self._infer_protocol(csv_acto=csv_acto, procedim=procedim)
            fecpres = self._parse_date(item.get("fecpres"))
            numclient = item.get("numclient")
            nombre = self._clean(item.get("Nombre"))
            apellido1 = self._clean(item.get("Apellido1"))
            apellido2 = self._clean(item.get("Apellido2"))
            nombre_fiscal = self._clean(item.get("Nombrefiscal"))
            representado = nombre_fiscal or " ".join([p for p in [nombre, apellido1, apellido2] if p]).strip()
            if numclient in self.CLIENTES_BLOQUEADOS and isinstance(fecpres, date) and date.today() < fecpres:
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": item.get("idRecurso"),
                            "Expedient": self._clean(item.get("Expedient")),
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": f"ATC bloqueado por fecha fecpres={fecpres.isoformat()} para numclient={numclient}",
                        }
                    )
                continue
            payloads.append(
                {
                    "idRecurso": item.get("idRecurso"),
                    "idExp": item.get("idExp"),
                    "numclient": item.get("numclient"),
                    "expediente": expediente,
                    "fase_procedimiento": self._clean(item.get("FaseProcedimiento")),
                    "FaseProcedimiento": self._clean(item.get("FaseProcedimiento")),
                    "procedim": procedim,
                    "csv_acto": csv_acto,
                    "protocol": protocol,
                    "fecpres": fecpres.isoformat() if fecpres else "",
                    "representado_nif": self._clean(item.get("nifempresa") or item.get("nif")),
                    "representado_nombre": representado,
                    "alegaciones": f"Se formulan alegaciones en relacion con el expediente {expediente}.",
                    "motivo_reposicion": "Altres motius diferents dels anteriors.",
                    "archivos": [],
                }
            )
        return payloads

