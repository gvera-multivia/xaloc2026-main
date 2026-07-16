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


class TerrassaAdapter(SiteAdapter):
    TARGET_ORGANISME = "AYUNTAMIENTO DE TERRASSA"
    # Pattern DSL provided by business team: '#' means one digit.
    EXPEDIENTE_PATTERNS = [
        "R#########",
        "PQ####I########",
        "#####/####",
        "E##V######",
        "RC########",
        "MU####I########",
        "MU####S#######",
        "PJ####I########",
        "###########ML##L######",
        "EC#V######",
        "C#########",
        "P########",
        "P#########",
        "RJ########",
        "Q#T/####",
        "CJ########",
        "CC########",
        "############",
        "##############",
        "G########",
        "V#########",
        "VJ########",
        "PC#######",
        "PC########",
        "RD########",
        "RD####P########",
        "######/####",
        "#####-####",
        "####/####",
        "###########PJ##L######",
        "###########PQ##L######",
        "PD#######",
        "####EXP########",
        "Q#J/####",
        "####-#####",
        "RC####P########",
        "IC####P########",
        "MU############",
        "VC########",
        "Q#T####A",
        "Q#T/####C",
        "##########",
        "MULT-#####/####",
        "MURC-#####-####",
        "MURC-#####/####",
        "MURC-###/####",
        "MURC-####/####",
        "ED#V######",
        "VD########",
        "###########RC##R######",
        "CC#############",
        "GC#######",
        "UR####I########",
        "SADM#######",
        "PQ############",
    ]

    def __init__(self):
        super().__init__(site_id="terrassa", priority=5)
        self._compiled_expediente_regex = [re.compile(self._pattern_to_regex(p)) for p in self.EXPEDIENTE_PATTERNS]
        self._organisme_norm = self._norm(self.TARGET_ORGANISME)

    @staticmethod
    def _clean(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @classmethod
    def _norm(cls, v: Any) -> str:
        txt = cls._clean(v).upper()
        if not txt:
            return ""
        return "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")

    @staticmethod
    def _pattern_to_regex(pattern: str) -> str:
        out: list[str] = ["^"]
        for ch in pattern:
            if ch == "#":
                out.append(r"\d")
            else:
                out.append(re.escape(ch))
        out.append("$")
        return "".join(out)

    def _is_valid_expediente(self, expediente: str) -> bool:
        exp = self._clean(expediente).upper()
        if not exp:
            return False
        return any(rx.match(exp) for rx in self._compiled_expediente_regex)

    def _normalize_expediente(self, expediente: Any) -> str:
        exp = self._clean(expediente).upper()
        if not exp:
            return ""
        first_token = exp.split()[0].strip(" ,.;")
        if first_token and self._is_valid_expediente(first_token):
            return first_token
        return exp

    def _is_target_organisme(self, organisme: Any) -> bool:
        return self._organisme_norm in self._norm(organisme)

    @staticmethod
    def _normalize_doc(v: Any) -> str:
        doc = str(v or "").strip().upper()
        if doc.startswith("ES") and len(doc) > 2:
            doc = doc[2:]
        return re.sub(r"[^A-Z0-9]+", "", doc)

    @staticmethod
    def _format_date_ddmmyyyy(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        raw = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.split("+")[0], fmt).strftime("%d/%m/%Y")
            except Exception:
                continue
        return raw

    def _resolve_plate(self, row: dict[str, Any]) -> tuple[str, str]:
        for key, src in (
            ("rs_matricula", "Recursos.RecursosExp.Matricula"),
            ("exp_matricula", "expedientes.matricula"),
            ("pub_matricula", "pubExp.matricula"),
        ):
            value = self._clean(row.get(key))
            if value:
                return re.sub(r"[^A-Z0-9]+", "", value.upper()), src

        txt = self._clean(row.get("pub_publicacion")).upper()
        if txt:
            m = re.search(r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}[\s-]*[A-Z]{1,2})\b", txt)
            if m:
                return re.sub(r"[^A-Z0-9]+", "", m.group(1).upper()), "pubExp.publicacion(regex)"
        return "", ""

    @staticmethod
    def _infer_document_type_value(document: str, is_company: bool) -> str:
        if is_company:
            if re.match(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$", document):
                return "7"
            return "10"
        if re.match(r"^[XYZ]\d{7}[A-Z]$", document):
            return "3"
        if re.match(r"^[0-9]{8}[A-Z]$", document):
            return "1"
        return "2"

    @staticmethod
    def _load_motivos() -> dict[str, dict[str, str]]:
        path = Path("config_motivos.json")
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _build_texts_by_fase(self, *, fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str, str]:
        cfg = self._load_motivos()
        fase = self._norm(fase_raw).lower()
        selected: dict[str, str] | None = None
        for key, value in cfg.items():
            if self._norm(key).lower() in fase:
                selected = value
                break

        if selected:
            asunto = self._clean(selected.get("asunto")).replace("{expediente}", expediente).replace(
                "{sujeto_recurso}", sujeto
            )
            expone = self._clean(selected.get("expone")).replace("{expediente}", expediente).replace(
                "{sujeto_recurso}", sujeto
            )
            solicita = self._clean(selected.get("solicita")).replace("{expediente}", expediente).replace(
                "{sujeto_recurso}", sujeto
            )
        else:
            asunto = f"Alegaciones expediente {expediente}"
            expone = f"Se presentan alegaciones en relacion con el expediente {expediente}."
            solicita = f"Se solicita que se admita el escrito para el expediente {expediente}."

        alegaciones = f"ASUNTO: {asunto}\n\nEXPONE: {expone}"
        observaciones = f"SOLICITA: {solicita}"
        return asunto, alegaciones, observaciones

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
        out["cliente_domicilio"] = out.get("cliente_domicilio", client_address.get("street_name"))
        out["cliente_cp"] = out.get("cliente_cp", client_address.get("zip"))
        out["cliente_municipio"] = out.get("cliente_municipio", client_address.get("city"))
        out["cliente_provincia"] = out.get("cliente_provincia", client_address.get("province"))

        out["matricula"] = out.get("matricula", plate.get("value"))
        out["rs_matricula"] = out.get("rs_matricula", plate.get("value") if plate.get("source") == "rs_matricula" else None)
        out["exp_matricula"] = out.get("exp_matricula", plate.get("value") if plate.get("source") == "exp_matricula" else None)
        out["pub_matricula"] = out.get("pub_matricula", plate.get("value") if plate.get("source") == "pub_matricula" else None)
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
            raise RuntimeError("[terrassa] fetch_candidates requires injected resource_repo (consultor/repository).")
        repo = resource_repo
        resources = repo.get_pending_resources(site_id=self.site_id, config=config, limit=limit)

        out: list[dict] = []
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
                            "motivo": f"Organismo fuera de Terrassa: {organisme}",
                        }
                    )
                continue

            if not self._is_valid_expediente(expediente):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "REGEX_DISCARDED",
                            "motivo": f"Expediente no valido para Terrassa: {expediente}",
                        }
                    )
                continue

            estado = int(item.get("Estado") or 0)
            usuario = self._clean(item.get("UsuarioAsignado"))
            if estado == 1 and authenticated_user and not self._same_user_identity(usuario, authenticated_user):
                continue
            if estado == 1 and not authenticated_user:
                continue

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
            expediente = self._normalize_expediente(r.get("Expedient"))
            is_company = str(r.get("cliente_tipo") or "") == "2"
            doc = self._normalize_doc(r.get("cliente_nif_empresa") if is_company else r.get("cliente_nif"))

            if not doc:
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": "Terrassa descartado: documento identificativo vacio",
                        }
                    )
                continue

            if is_company:
                nombre = self._clean(
                    r.get("cliente_razon_social")
                    or r.get("Nombrefiscal")
                    or r.get("Empresa")
                    or r.get("Nombrejuridico")
                    or r.get("Nombrecomercial")
                    or r.get("SujetoRecurso")
                )
                apellido1 = ""
                apellido2 = ""
            else:
                nombre = self._clean(r.get("cliente_nombre") or r.get("SujetoRecurso"))
                apellido1 = self._clean(r.get("cliente_apellido1"))
                apellido2 = self._clean(r.get("cliente_apellido2"))

            fecha_infraccion = self._format_date_ddmmyyyy(r.get("FAlta"))
            matricula_raw, matricula_source = self._resolve_plate(r)
            matricula = normalize_plate_with_fallback(matricula_raw)

            sujeto = self._clean(r.get("SujetoRecurso") or nombre)
            asunto, alegaciones, observaciones = self._build_texts_by_fase(
                fase_raw=self._clean(r.get("FaseProcedimiento")),
                expediente=expediente,
                sujeto=sujeto,
            )

            payload: dict[str, Any] = {
                "idRecurso": rid,
                "idExp": r.get("idExp"),
                "numclient": r.get("numclient"),
                "expediente": expediente,
                "is_company": is_company,
                "document_type_value": self._infer_document_type_value(doc, is_company),
                "document_number": doc,
                "nombre": nombre,
                "apellido1": apellido1,
                "apellido2": apellido2,
                "fecha_infraccion": fecha_infraccion,
                "matricula": matricula,
                "matricula_source": matricula_source,
                "marca": "Otros",
                "asunto": asunto,
                "alegaciones": alegaciones,
                "observaciones": observaciones,
                "fase_procedimiento": self._clean(r.get("FaseProcedimiento")),
                "sujeto_recurso": sujeto,
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
                archivos = [str(p) for p in files if str(p).strip()]
            except Exception as exc:
                logger.warning("[terrassa] Error cargando documentacion cliente idRecurso=%s: %s", rid, exc)
                archivos = []

            payload["archivos"] = archivos
            payload["documentos"] = [
                {
                    "fitxer": p,
                    "descripcio": Path(p).stem[:70] or "Documento",
                    "tipus": "Al-legacio",
                }
                for p in archivos
            ]
            payloads.append(payload)
        return payloads
