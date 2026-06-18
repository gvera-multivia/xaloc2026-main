from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.contact_defaults import get_default_contact_email
from core.validation.validators import normalize_plate_with_fallback
from .site_adapter import SiteAdapter
from core.xaloc_expediente_utils import is_valid_format, fix_format


class XalocAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )

    def __init__(self):
        super().__init__(site_id="xaloc_girona", priority=1)

    @staticmethod
    def _clean_str(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _strip_trailing_pdf_suffix(text: Any) -> str:
        value = str(text or "").strip()
        return re.sub(r"\.PDF$", "", value, flags=re.IGNORECASE)

    @staticmethod
    def _normalize_text(text: Any) -> str:
        import unicodedata
        if not text:
            return ""
        t = str(text).strip().lower()
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

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
    def _determinar_tipo_persona(
        cliente_tipo: Any,
        cif_value: str | None,
        empresa_value: str | None = None,
    ) -> str:
        try:
            tipo = int(str(cliente_tipo).strip())
            if tipo == 2:
                return "JURIDICA"
            if tipo == 1:
                return "FISICA"
        except Exception:
            pass

        cif_clean = (cif_value or "").strip()
        empresa_clean = (empresa_value or "").strip()
        if cif_clean or empresa_clean:
            return "JURIDICA"
        return "FISICA"

    @staticmethod
    def _extraer_documento_control(documento: str) -> tuple[str, str]:
        doc_clean = documento.strip().upper()
        if len(doc_clean) < 2:
            return doc_clean, ""
        return doc_clean[:-1], doc_clean[-1]

    @staticmethod
    def _detectar_tipo_documento(doc: str) -> str:
        if not doc:
            return "NIF"
        d = doc.strip().upper()
        if re.match(r"^[A-Z]{3}[0-9]+", d):
            return "PS"
        return "NIF"

    @staticmethod
    def _normalize_plate(value: Any) -> str:
        return normalize_plate_with_fallback(value)

    @staticmethod
    def _convert_value(v: Any) -> Any:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
        return v

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
        plate = vehicle.get("plate") or {}

        out["idRecurso"] = out.get("idRecurso", resource.get("id"))
        out["idExp"] = out.get("idExp", resource.get("exp_id"))
        out["numclient"] = out.get("numclient", resource.get("numclient"))
        out["Expedient"] = out.get("Expedient", resource.get("expedient"))
        out["Organisme"] = out.get("Organisme", resource.get("organism"))
        out["TExp"] = out.get("TExp", resource.get("texp"))
        out["Estado"] = out.get("Estado", resource.get("state"))
        out["UsuarioAsignado"] = out.get("UsuarioAsignado", resource.get("assigned_user"))
        out["FUsuarioCompletado"] = out.get("FUsuarioCompletado", resource.get("completed_at"))
        out["FaseProcedimiento"] = out.get("FaseProcedimiento", resource.get("phase"))
        out["SujetoRecurso"] = out.get("SujetoRecurso", resource.get("subject_name"))

        out["cliente_tipo"] = out.get("cliente_tipo", client.get("type"))
        out["cliente_nif"] = out.get("cliente_nif", client_doc.get("nif"))
        out["nifempresa"] = out.get("nifempresa", client_doc.get("cif"))
        out["cif"] = out.get("cif", client_doc.get("cif"))
        out["cliente_razon_social"] = out.get("cliente_razon_social", client_name.get("business"))
        out["Empresa"] = out.get("Empresa", client_name.get("business"))
        out["Nombrefiscal"] = out.get("Nombrefiscal", client_name.get("business"))
        out["cliente_nombre"] = out.get("cliente_nombre", client_name.get("first"))
        out["cliente_apellido1"] = out.get("cliente_apellido1", client_name.get("last1"))
        out["cliente_apellido2"] = out.get("cliente_apellido2", client_name.get("last2"))
        out["matricula"] = out.get("matricula", plate.get("value"))
        out["adjuntos"] = out.get("adjuntos", attachments)
        return out

    def _build_mandatario_data(self, row: dict) -> dict:
        cif_raw = row.get("cif") or row.get("nifempresa")
        empresa_raw = (
            row.get("cliente_razon_social")
            or row.get("Empresa")
            or row.get("Nombrefiscal")
            or row.get("Nombrejuridico")
            or row.get("Nombrecomercial")
        )
        
        tipo_persona = self._determinar_tipo_persona(row.get("cliente_tipo"), cif_raw, empresa_raw)
        mandatario: dict = {"tipo_persona": tipo_persona}
        
        if tipo_persona == "JURIDICA":
            razon_social = (empresa_raw or "").strip().upper()
            cif_clean = (cif_raw or "").strip().upper()
            
            if cif_clean:
                doc_numero, doc_control = self._extraer_documento_control(cif_clean)
                mandatario.update({
                    "cif_documento": doc_numero,
                    "cif_control": doc_control,
                })
            else:
                mandatario.update({
                    "cif_documento": "",
                    "cif_control": "",
                })
            mandatario["razon_social"] = razon_social
        else:
            nif_raw = row.get("cliente_nif")
            nif_clean = (nif_raw or "").strip().upper()
            
            if nif_clean:
                doc_numero, doc_control = self._extraer_documento_control(nif_clean)
                tipo_doc = self._detectar_tipo_documento(nif_clean)
            else:
                # Fallback si no hay NIF (aunque deberÃƒÂ­a haber)
                doc_numero, doc_control = "", ""
                tipo_doc = "NIF"
                
            mandatario.update({
                "tipo_doc": tipo_doc,
                "doc_numero": doc_numero,
                "doc_control": doc_control,
                "nombre": (row.get("cliente_nombre") or "").strip().upper(),
                "apellido1": (row.get("cliente_apellido1") or "").strip().upper(),
                "apellido2": (row.get("cliente_apellido2") or "").strip().upper(),
            })
            
        return mandatario

    def get_motivos_por_fase(self, fase_raw: Any, expediente: str, sujeto_recurso: str = "") -> str:
        config_map = self._load_motivos_config()
        # LÃƒÂ³gica duplicada de xaloc_task.py para asegurar compatibilidad
        expediente_txt = self._clean_str(expediente)
        sujeto_txt = self._clean_str(sujeto_recurso).upper()
        fase_norm = self._normalize_text(fase_raw)

        selected: dict | None = None
        for key, value in (config_map or {}).items():
            key_norm = self._normalize_text(key)
            if key_norm and key_norm in fase_norm:
                selected = value
                break
        
        if not selected:
             # Fallback simple si no hay config
             return f"ASUNTO: Recurso {expediente_txt}\n\nEXPONE: ...\n\nSOLICITA: ..."

        asunto = self._clean_str(selected.get("asunto")).replace("{expediente}", expediente_txt).replace("{sujeto_recurso}", sujeto_txt)
        expone = self._clean_str(selected.get("expone")).replace("{expediente}", expediente_txt).replace("{sujeto_recurso}", sujeto_txt)
        solicita = self._clean_str(selected.get("solicita")).replace("{expediente}", expediente_txt).replace("{sujeto_recurso}", sujeto_txt)

        return f"ASUNTO: {asunto}\n\nEXPONE: {expone}\n\nSOLICITA: {solicita}"


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
            raise RuntimeError("[xaloc_girona] fetch_candidates requires injected resource_repo (consultor/repository).")

        recursos_map: dict[int, dict] = {}
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=config, limit=limit)
        for resource in resources:
            record = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            rid = record.get("idRecurso")
            if not rid:
                continue
            rid_int = int(rid)
            adjuntos = list(record.get("adjuntos") or [])
            for adj in adjuntos:
                if "url" not in adj and adj.get("id") is not None:
                    adj["url"] = self.ADJUNTO_URL_TEMPLATE.format(id=int(adj["id"]))
            record["adjuntos"] = adjuntos
            recursos_map[rid_int] = record

        out: list[dict] = []
        for _, recurso in recursos_map.items():
            if limit and len(out) >= limit:
                break

            rid = recurso.get("idRecurso")
            expediente_raw = self._strip_trailing_pdf_suffix(recurso.get("Expedient"))
            estado = int(recurso.get("Estado") or 0)
            usuario = self._clean_str(recurso.get("UsuarioAsignado"))
            fecha_completado = recurso.get("FUsuarioCompletado")

            if fecha_completado is not None and str(fecha_completado).strip() and estado == 0:
                # En XALOC hay recursos reabiertos o desasignados manualmente con
                # FUsuarioCompletado histórico. La fuente de verdad para claim es
                # Estado/UsuarioAsignado, así que no debemos descartarlos aquí.
                pass

            expediente = expediente_raw
            is_valid = is_valid_format(expediente)
            if not is_valid:
                fixed = fix_format(expediente)
                if fixed != expediente and is_valid_format(fixed):
                    expediente = fixed
                    recurso["Expedient"] = fixed
                    is_valid = True

            if not is_valid:
                if on_discard:
                    try:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": rid,
                                "Expedient": expediente_raw,
                                "tipo_incidencia": "REGEX_DISCARDED",
                                "motivo": f"Expediente no valido para xaloc_girona: {expediente_raw}",
                            }
                        )
                    except Exception:
                        pass
                continue

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
            
        payloads: list[dict] = []
        for r in candidates:
            expediente = self._clean_str(r.get("Expedient"))
            fase_raw = r.get("FaseProcedimiento")
            sujeto_recurso = self._clean_str(r.get("SujetoRecurso"))
            
            # 1. Motivos
            motivos_text = self.get_motivos_por_fase(fase_raw, expediente, sujeto_recurso)
            
            # 2. Mandatario
            mandatario = self._build_mandatario_data(r)
            
            # 3. Datos comunes
            payload = {
                "idRecurso": self._convert_value(r.get("idRecurso")),
                "idExp": self._convert_value(r.get("idExp")),
                "numclient": self._convert_value(r.get("numclient")),
                "user_email": get_default_contact_email(uppercase=True),
                "denuncia_num": expediente,
                "plate_number": self._normalize_plate(r.get("matricula")),
                "expediente_num": expediente,
                "expediente": expediente,  # Alias para el orquestador
                "sujeto_recurso": sujeto_recurso,
                "cif": self._clean_str(r.get("cif") or r.get("nifempresa")),
                "empresa": self._clean_str(
                    r.get("cliente_razon_social")
                    or r.get("Empresa")
                    or r.get("Nombrefiscal")
                    or r.get("Nombrejuridico")
                    or r.get("Nombrecomercial")
                ),
                "cliente_razon_social": self._clean_str(
                    r.get("cliente_razon_social")
                    or r.get("Nombrefiscal")
                    or r.get("Empresa")
                    or r.get("Nombrejuridico")
                    or r.get("Nombrecomercial")
                ),
                "cliente_nif": self._clean_str(r.get("cliente_nif")),
                "cliente_nombre": self._clean_str(r.get("cliente_nombre")),
                "cliente_apellido1": self._clean_str(r.get("cliente_apellido1")),
                "cliente_apellido2": self._clean_str(r.get("cliente_apellido2")),
                "interesado_doc": self._clean_str(r.get("cliente_nif")),
                "interesado_nombre": self._clean_str(r.get("cliente_nombre")),
                "interesado_apellido1": self._clean_str(r.get("cliente_apellido1")),
                "interesado_apellido2": self._clean_str(r.get("cliente_apellido2")),
                "motivos": motivos_text,
                "adjuntos": r.get("adjuntos") or [],
                "mandatario": mandatario,
                "fase_procedimiento": self._clean_str(fase_raw),
                
                # Metadata
                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }
            payloads.append(payload)
            
        return payloads
