from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.client_docs_service import get_required_client_documents
from core.sqlserver_utils import build_sqlserver_connection_string
from core.validation.validators import normalize_plate_with_fallback
from .site_adapter import SiteAdapter

logger = logging.getLogger("brain")


class ValenciaAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )
    DEFAULT_REGEX_EXPEDIENTE = r"^.+$"
    TARGET_ORGANISME_TOKENS: tuple[str, ...] = ("AJUNTAMENT DE VALENCIA",)
    EXPEDIENTE_REGEX_LIST: tuple[str, ...] = (
        r"^MU\s\d{4}\s\d{2}\s\d{8}\s\d$",
        r"^MU\s\d{4}\s\d{2}\s\d{8}$",
        r"^\d{5}/\d{4}$",
        r"^\d{4}/\d{4}$",
        r"^\d{8}-\d$",
        r"^\d{2}-\d{3}-\d{3}\.\d{3}-\d$",
        r"^MU\d{14}$",
        r"^U\s\d{4}\s\d{2}\s\d{8}\s\d$",
    )

    def __init__(self) -> None:
        super().__init__(site_id="valencia", priority=6)
        self._regex_cache: dict[str, re.Pattern[str]] = {}
        self._regex_fallback = re.compile(self.DEFAULT_REGEX_EXPEDIENTE)
        self._compiled_expediente_regex = [re.compile(p) for p in self.EXPEDIENTE_REGEX_LIST]
        self._motivos_cache: dict[str, dict[str, Any]] | None = None

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @classmethod
    def _norm(cls, value: Any) -> str:
        txt = cls._clean(value).upper()
        if not txt:
            return ""
        return "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")

    @classmethod
    def _normalize_document(cls, doc: Any) -> str:
        value = cls._clean(doc).upper()
        if value.startswith("ES") and len(value) > 2:
            value = value[2:]
        return re.sub(r"[^A-Z0-9]+", "", value)

    @classmethod
    def _is_target_organisme(cls, organisme: Any) -> bool:
        norm = cls._norm(organisme)
        if not norm:
            return False
        return any(token in norm for token in cls.TARGET_ORGANISME_TOKENS)

    @classmethod
    def _merge_query_organisme(cls, configured: Any) -> str:
        raw = cls._clean(configured)
        if not raw:
            return "%AJUNTAMENT DE VALENCIA%"

        chunks = [cls._clean(part) for part in re.split(r"[|;,]+", raw)]
        chunks = [part for part in chunks if part]
        existing = {part.upper() for part in chunks}
        for token in ("%AJUNTAMENT DE VALENCIA%",):
            if token.upper() not in existing:
                chunks.append(token)
                existing.add(token.upper())
        return "|".join(chunks)

    @staticmethod
    def _normalize_expediente(expediente: Any) -> str:
        return re.sub(r"\s+", " ", str(expediente or "").upper()).strip()

    def _is_valid_expediente(self, expediente: str) -> bool:
        exp = self._normalize_expediente(expediente)
        if not exp:
            return False
        return any(rx.match(exp) for rx in self._compiled_expediente_regex)

    @classmethod
    def _infer_tramite(cls, fase_raw: Any) -> tuple[str, str]:
        fase = cls._norm(fase_raw).lower()
        if "identific" in fase:
            return "identificacion_conductor", "MU.DE.50"
        if "denuncia" in fase or "propuesta" in fase:
            return "alegaciones_denuncia_transito", "MU.DE.30"
        if "sancion" in fase or "embargo" in fase or "apremio" in fase:
            return "recurso_reposicion", "MU.SA.40"
        return "alegaciones_denuncia_transito", "MU.DE.30"

    def _load_motivos(self) -> dict[str, dict[str, Any]]:
        if self._motivos_cache is not None:
            return self._motivos_cache
        path = Path("config_motivos.json")
        if not path.exists():
            self._motivos_cache = {}
            return self._motivos_cache
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            out: dict[str, dict[str, Any]] = {}
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if isinstance(value, dict):
                        out[self._norm(key).lower()] = value
            self._motivos_cache = out
        except Exception:
            self._motivos_cache = {}
        return self._motivos_cache

    def _build_expone_solicita(self, *, fase: str, expediente: str, sujeto: str) -> tuple[str, str]:
        motivos = self._load_motivos()
        motivo = motivos.get(self._norm(fase).lower())
        if motivo:
            expone_tpl = self._clean(motivo.get("expone"))
            solicita_tpl = self._clean(motivo.get("solicita"))
            context = {"expediente": expediente, "sujeto_recurso": sujeto}
            try:
                expone = expone_tpl.format(**context) if expone_tpl else ""
            except Exception:
                expone = expone_tpl
            try:
                solicita = solicita_tpl.format(**context) if solicita_tpl else ""
            except Exception:
                solicita = solicita_tpl
            if expone and solicita:
                return expone, solicita
        fase_txt = self._clean(fase) or "tramite"
        return (
            f"Se presenta escrito relacionado con el expediente {expediente} en fase {fase_txt}.",
            f"Se solicita la admision y tramitacion del expediente {expediente}.",
        )

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

        out["conduc_nom"] = out.get("conduc_nom", client_name.get("first"))
        out["conduc_dni"] = out.get("conduc_dni", client_doc.get("nif"))
        out["conduc_adr"] = out.get("conduc_adr", client_address.get("street_name"))
        out["conduc_codpost"] = out.get("conduc_codpost", client_address.get("zip"))

        out["matricula"] = out.get("matricula", plate.get("value"))
        out["rs_matricula"] = out.get("rs_matricula", plate.get("value") if plate.get("source") == "rs_matricula" else None)
        out["exp_matricula"] = out.get("exp_matricula", plate.get("value") if plate.get("source") == "exp_matricula" else None)
        out["pub_matricula"] = out.get("pub_matricula", plate.get("value") if plate.get("source") == "pub_matricula" else None)
        out["adjuntos"] = out.get("adjuntos", attachments)
        return out

    @staticmethod
    def _resolve_plate(item: dict[str, Any]) -> tuple[str, str, str]:
        rs = normalize_plate_with_fallback(item.get("rs_matricula"))
        exp = normalize_plate_with_fallback(item.get("exp_matricula") or item.get("matricula"))
        pub = normalize_plate_with_fallback(item.get("pub_matricula"))
        normalized = normalize_plate_with_fallback(rs or exp or pub)
        return normalized, exp, pub

    @staticmethod
    def _is_placeholder_text(value: Any) -> bool:
        txt = str(value or "").strip().upper()
        if not txt:
            return True
        return txt in {".", "-", "N/A", "NA", "NULL", "NONE", "S/N", "SN"}

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
            raise RuntimeError("[valencia] fetch_candidates requires injected resource_repo (consultor/repository).")

        cfg = dict(config or {})
        cfg["query_organisme"] = self._merge_query_organisme(cfg.get("query_organisme"))

        regex_pattern = self._clean(cfg.get("regex_expediente")) or self.DEFAULT_REGEX_EXPEDIENTE
        regex = self._regex_cache.get(regex_pattern)
        if regex is None:
            try:
                regex = re.compile(regex_pattern)
            except re.error:
                logger.warning("[valencia] Regex invalido: %r. Usando fallback.", regex_pattern)
                regex = self._regex_fallback
            self._regex_cache[regex_pattern] = regex

        out: list[dict] = []
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=cfg, limit=limit)
        for resource in resources:
            if limit and len(out) >= limit:
                break

            item = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            rid = item.get("idRecurso")
            expediente = self._normalize_expediente(item.get("Expedient"))
            item["Expedient"] = expediente
            organisme = self._clean(item.get("Organisme"))

            if not self._is_target_organisme(organisme):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": f"Organismo fuera de Valencia: {organisme}",
                        }
                    )
                continue

            if not expediente or not regex.match(expediente) or not self._is_valid_expediente(expediente):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "REGEX_DISCARDED",
                            "motivo": f"Expediente no valido para Valencia (patrones oficiales): {expediente}",
                        }
                    )
                continue

            estado = int(item.get("Estado") or 0)
            usuario = self._clean(item.get("UsuarioAsignado"))
            if estado == 1 and authenticated_user and not self._same_user_identity(usuario, authenticated_user):
                continue
            if estado == 1 and not authenticated_user:
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
        if not candidates:
            return payloads

        conn_str = build_sqlserver_connection_string()
        for r in candidates:
            rid = r.get("idRecurso")
            expediente = self._clean(r.get("Expedient"))
            if not expediente:
                continue

            fase = self._clean(r.get("FaseProcedimiento"))
            tramite_tipo, tramite_code = self._infer_tramite(fase)
            tipodecliente = self._clean(r.get("cliente_tipo") or r.get("tipodecliente"))
            is_company = tipodecliente == "2"

            nif = self._normalize_document(r.get("cliente_nif"))
            nifempresa = self._normalize_document(r.get("cliente_nif_empresa") or r.get("cif"))
            conduc_dni = self._normalize_document(r.get("conduc_dni"))
            nombre = self._clean(r.get("cliente_nombre") or r.get("SujetoRecurso"))
            apellido1 = self._clean(r.get("cliente_apellido1"))
            apellido2 = self._clean(r.get("cliente_apellido2"))
            nombrefiscal = self._clean(
                r.get("cliente_razon_social")
                or r.get("Nombrefiscal")
                or r.get("Empresa")
                or r.get("Nombrejuridico")
                or r.get("Nombrecomercial")
                or r.get("SujetoRecurso")
            )
            conduc_nom = self._clean(r.get("conduc_nom"))
            conduc_codpost = self._clean(r.get("conduc_codpost"))
            conduc_adr = self._clean(r.get("conduc_adr"))
            sujeto = self._clean(r.get("SujetoRecurso")) or nombrefiscal or "INTERESADO"
            expone, solicita = self._build_expone_solicita(fase=fase, expediente=expediente, sujeto=sujeto)
            matricula, matricula2, matricula3 = self._resolve_plate(r)

            if is_company and (not nifempresa or not nombrefiscal):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": "Valencia descartado: empresa sin nifempresa o nombrefiscal",
                        }
                    )
                continue

            if (not is_company) and (not nif and not conduc_dni):
                logger.warning(
                    "[valencia] Persona fisica sin nif/conduc_dni idRecurso=%s expediente=%s. "
                    "Se continua (DNI no obligatorio para este flujo).",
                    rid,
                    expediente,
                )

            if tramite_tipo == "identificacion_conductor" and (not conduc_dni or not conduc_nom):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": "Valencia descartado: identificacion de conductor sin Conducdni/ConducNom",
                        }
                    )
                continue

            payload: dict[str, Any] = {
                "idRecurso": r.get("idRecurso"),
                "idExp": r.get("idExp"),
                "numclient": r.get("numclient"),
                "expediente": expediente,
                "fase_procedimiento": fase,
                "sujeto_recurso": sujeto,
                "tramite_tipo": tramite_tipo,
                "tramite_code": tramite_code,
                "tipodecliente": tipodecliente,
                "nif": nif,
                "nifempresa": nifempresa,
                "nombre": nombre,
                "apellido1": apellido1,
                "apellido2": apellido2,
                "nombrefiscal": nombrefiscal,
                "conduc_nom": conduc_nom,
                "conduc_dni": conduc_dni,
                "conduc_codpost": conduc_codpost,
                "conduc_adr": conduc_adr,
                "texp": int(r.get("TExp") or 0),
                "matricula": matricula,
                "plate_number": matricula,
                "matricula2": matricula2,
                "matricula3": matricula3,
                "expone": expone,
                "solicita": solicita,
                "adjuntos": list(r.get("adjuntos") or []),
                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }
            try:
                files = await get_required_client_documents(
                    payload,
                    sqlserver_conn_str=conn_str,
                    strict=False,
                )
                payload["archivos"] = [str(p) for p in files if str(p).strip()]
            except Exception as exc:
                logger.warning("[valencia] Error cargando documentacion cliente idRecurso=%s: %s", rid, exc)
                payload["archivos"] = []

            payloads.append(payload)

        return payloads
