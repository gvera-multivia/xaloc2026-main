from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from core.validation.validators import normalize_plate_with_fallback
from .site_adapter import SiteAdapter

logger = logging.getLogger("brain")


class AyuntaPalmaAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )
    DEFAULT_REGEX_EXPEDIENTE = r"^([A-Z]{2}\s?)?\d{7,8}[A-Z]?$"
    LEGACY_REGEX_EXPEDIENTE = r"^([A-Z]{2}\s?)?\d{7,8}$"
    ORGANISME_ALIASES: tuple[str, str] = (
        "%AYUNTAMENT DE PALMA%",
        "%AYUNTAMIENTO DE MALLORCA%",
    )

    def __init__(self):
        super().__init__(site_id="ayunta_palma", priority=3)
        self._regex_cache: dict[str, re.Pattern[str]] = {}
        self._regex_fallback = re.compile(self.DEFAULT_REGEX_EXPEDIENTE)

    @classmethod
    def _upgrade_legacy_regex_expediente(cls, pattern: str) -> str:
        normalized = cls._clean_str(pattern)
        if normalized == cls.LEGACY_REGEX_EXPEDIENTE:
            return cls.DEFAULT_REGEX_EXPEDIENTE
        return normalized

    @staticmethod
    def _clean_str(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _normalize_document_id(doc: Any) -> str:
        if not doc:
            return ""
        d = str(doc).strip().upper()
        if d.startswith("ES") and len(d) > 2:
            d = d[2:]
        return re.sub(r"[^A-Z0-9]+", "", d)

    @staticmethod
    def _normalize_plate(v: Any) -> str:
        return normalize_plate_with_fallback(v)

    @staticmethod
    def _convert_value(v: Any) -> Any:
        from decimal import Decimal

        if isinstance(v, Decimal):
            return float(v)
        return v

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
    def _normalize_text(text: Any) -> str:
        import unicodedata

        if not text:
            return ""
        t = str(text).strip().lower()
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

    @classmethod
    def _build_organisme_patterns(cls, raw: Any) -> list[str]:
        text = cls._clean_str(raw)
        if not text:
            return ["%"]

        # Allow explicit multi-pattern syntax with commas/semicolons, otherwise fallback to space tokens.
        if "," in text or ";" in text:
            chunks = re.split(r"[;,]+", text)
        else:
            chunks = text.split(" ")

        patterns: list[str] = []
        for chunk in chunks:
            p = cls._clean_str(chunk)
            if not p:
                continue
            if p == "%":
                patterns.append(p)
                continue

            # If token has no SQL wildcard, search as contains.
            if "%" not in p and "_" not in p:
                p = f"%{p}%"
            else:
                if not p.startswith("%"):
                    p = f"%{p}"
                if not p.endswith("%"):
                    p = f"{p}%"
            patterns.append(p)

        return patterns or ["%"]

    @classmethod
    def _merge_query_organisme(cls, configured: Any) -> str:
        """
        Ensure Palma known aliases are always included in organismo filter.
        """
        text = cls._clean_str(configured)
        if not text or text == "%":
            return text

        chunks = [cls._clean_str(part) for part in re.split(r"[|;,]+", text)]
        chunks = [part for part in chunks if part]

        existing_upper = {part.upper() for part in chunks}
        for alias in cls.ORGANISME_ALIASES:
            if alias.upper() not in existing_upper:
                chunks.append(alias)
                existing_upper.add(alias.upper())

        return "|".join(chunks)

    @classmethod
    def _build_expone_solicita(cls, fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str]:
        config = cls._load_motivos_config()
        fase_norm = cls._normalize_text(fase_raw)
        selected: dict | None = None
        for key, value in (config or {}).items():
            if cls._normalize_text(key) in fase_norm:
                selected = value
                break

        if not selected:
            return (
                f"Expongo que en relacion con el expediente {expediente} procede revisar las circunstancias del caso.",
                f"Solicito que se admita este escrito en el expediente {expediente} y se practique la revision solicitada.",
            )

        expone = cls._clean_str(selected.get("expone")).replace("{expediente}", expediente).replace(
            "{sujeto_recurso}", sujeto
        )
        solicita = cls._clean_str(selected.get("solicita")).replace("{expediente}", expediente).replace(
            "{sujeto_recurso}", sujeto
        )
        if not expone:
            expone = f"Expongo que en relacion con el expediente {expediente} procede revisar las circunstancias del caso."
        if not solicita:
            solicita = f"Solicito que se admita este escrito en el expediente {expediente} y se practique la revision solicitada."
        return expone, solicita

    @staticmethod
    def _tipo_documento_persona_fisica(doc: str) -> str:
        # Palma usa F (NIF/NIE), X (UE) y P (pasaporte). Por defecto priorizamos F.
        d = AyuntaPalmaAdapter._normalize_document_id(doc)
        if re.match(r"^[A-Z]{2,3}\d{5,9}$", d):
            return "P"
        return "F"

    @classmethod
    def _materialize_from_canonical_if_present(cls, record: dict[str, Any]) -> dict[str, Any]:
        """
        Slice 3: consume canonical consultor data when available, preserving
        backward-compatibility with legacy aliases.
        """
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

        # Canonical -> legacy keys required by this adapter.
        out["idRecurso"] = out.get("idRecurso", resource.get("id"))
        out["idExp"] = out.get("idExp", resource.get("exp_id"))
        out["numclient"] = out.get("numclient", resource.get("numclient"))
        out["Expedient"] = out.get("Expedient", resource.get("expedient"))
        out["SujetoRecurso"] = out.get("SujetoRecurso", resource.get("subject_name"))
        out["FaseProcedimiento"] = out.get("FaseProcedimiento", resource.get("phase"))
        out["Estado"] = out.get("Estado", resource.get("state"))
        out["UsuarioAsignado"] = out.get("UsuarioAsignado", resource.get("assigned_user"))
        out["matricula"] = out.get("matricula", (vehicle.get("plate") or {}).get("value"))
        out["adjuntos"] = out.get("adjuntos", attachments)

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
            raise RuntimeError("[ayunta_palma] fetch_candidates requires injected resource_repo (consultor/repository).")
        cfg = dict(config or {})
        cfg["query_organisme"] = self._merge_query_organisme(cfg.get("query_organisme"))
        configured_regex = self._clean_str(config.get("regex_expediente")) or self.DEFAULT_REGEX_EXPEDIENTE
        regex_pattern = self._upgrade_legacy_regex_expediente(configured_regex) or self.DEFAULT_REGEX_EXPEDIENTE
        if configured_regex and configured_regex != regex_pattern:
            logger.info(
                "[ayunta_palma] regex_expediente legacy detectado; usando patron ampliado. configured=%r upgraded=%r",
                configured_regex,
                regex_pattern,
            )
        regex = self._regex_cache.get(regex_pattern)
        if regex is None:
            try:
                regex = re.compile(regex_pattern)
            except re.error:
                logger.warning("[ayunta_palma] Regex invalido: %r. Usando fallback.", regex_pattern)
                regex = self._regex_fallback
            self._regex_cache[regex_pattern] = regex

        out: list[dict] = []
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=cfg, limit=limit)
        for resource in resources:
            if limit and len(out) >= limit:
                break
            recurso = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            expediente = self._clean_str(recurso.get("Expedient")).upper()
            if not expediente or not regex.match(expediente):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": recurso.get("idRecurso"),
                            "Expedient": expediente,
                            "tipo_incidencia": "REGEX_DISCARDED",
                            "motivo": f"Expediente no valido para ayunta_palma: {expediente}",
                        }
                    )
                continue
            recurso["Expedient"] = expediente

            adjuntos = list(recurso.get("adjuntos") or [])
            for adj in adjuntos:
                if "url" not in adj and adj.get("id") is not None:
                    adj["url"] = self.ADJUNTO_URL_TEMPLATE.format(id=int(adj["id"]))
            recurso["adjuntos"] = adjuntos

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
        payloads: list[dict] = []
        for r in candidates:
            expediente = self._clean_str(r.get("Expedient"))
            if not expediente:
                continue

            # Compatibilidad: algunos caminos legacy todavia pasan tipodecliente.
            cliente_tipo = int(r.get("cliente_tipo") or r.get("tipodecliente") or 0)
            sujeto = self._clean_str(r.get("SujetoRecurso"))
            fase = self._clean_str(r.get("FaseProcedimiento"))
            expone, solicita = self._build_expone_solicita(fase, expediente, sujeto)

            email = get_default_contact_email()
            telefono = get_default_contact_mobile()

            if cliente_tipo == 2:
                es_juridica = True
            elif cliente_tipo == 1:
                es_juridica = False
            else:
                es_juridica = bool(self._clean_str(r.get("cliente_nif_empresa")) or self._clean_str(r.get("cif")))
            tipo_persona = "PersonaJuridica" if es_juridica else "PersonaFisica"

            nif_empresa = self._normalize_document_id(self._clean_str(r.get("cliente_nif_empresa")) or self._clean_str(r.get("cif")))
            razon_social = self._clean_str(
                r.get("cliente_razon_social")
                or r.get("Nombrefiscal")
                or r.get("Empresa")
                or r.get("Nombrejuridico")
                or r.get("Nombrecomercial")
            ) or sujeto
            doc_fisica = self._normalize_document_id(self._clean_str(r.get("cliente_nif")))

            payload = {
                "idRecurso": self._convert_value(r.get("idRecurso")),
                "idExp": self._convert_value(r.get("idExp")),
                "numclient": self._convert_value(r.get("numclient")),
                "expediente": expediente,
                "matricula": self._normalize_plate(r.get("matricula")),
                "sujeto_recurso": sujeto,
                "fase_procedimiento": fase,
                "tipo_persona": tipo_persona,
                "email": email,
                "telefono": telefono,
                "expone": expone,
                "solicita": solicita,
                "adjuntos": r.get("adjuntos") or [],
                "cliente_nombre": self._clean_str(r.get("cliente_nombre")),
                "cliente_apellido1": self._clean_str(r.get("cliente_apellido1")),
                "cliente_apellido2": self._clean_str(r.get("cliente_apellido2")),
                "cliente_razon_social": razon_social,
                "nif": doc_fisica or nif_empresa,
                "name": sujeto,
                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }

            if tipo_persona == "PersonaJuridica":
                payload["nif_empresa"] = nif_empresa
                payload["razon_social"] = razon_social
            else:
                payload["tipo_documento"] = self._tipo_documento_persona_fisica(doc_fisica)
                payload["documento"] = doc_fisica
                payload["nombre"] = self._clean_str(r.get("cliente_nombre")) or sujeto
                payload["apellido1"] = self._clean_str(r.get("cliente_apellido1")) or "N/A"
                payload["apellido2"] = self._clean_str(r.get("cliente_apellido2"))

            # Minimos para controller/worker
            if tipo_persona == "PersonaFisica" and not payload.get("documento"):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": payload.get("idRecurso"),
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": "Persona fisica sin documento (nif/nie/pasaporte).",
                        }
                    )
                continue
            if tipo_persona == "PersonaJuridica" and not payload.get("nif_empresa"):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": payload.get("idRecurso"),
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": "Persona juridica sin nif de empresa.",
                        }
                    )
                continue

            payloads.append(payload)

        return payloads
