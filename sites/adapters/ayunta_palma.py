from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pyodbc

from .site_adapter import SiteAdapter

logger = logging.getLogger("brain")


class AyuntaPalmaAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )
    DEFAULT_REGEX_EXPEDIENTE = r"^([A-Z]{2}\s?)?\d{7,8}$"

    SQL_FETCH_RECURSOS_PALMA = """
SELECT
    rs.idRecurso,
    rs.idExp,
    rs.Expedient,
    rs.Organisme,
    rs.TExp,
    rs.Estado,
    rs.numclient,
    rs.SujetoRecurso,
    rs.FaseProcedimiento,
    rs.UsuarioAsignado,
    rs.cif,
    rs.notas,
    rs.matricula AS rs_matricula,

    e.matricula,
    e.Idpublic AS exp_idpublic,

    pe.publicación AS pub_publicacion,

    c.tipodecliente AS cliente_tipo,
    c.nif AS cliente_nif,
    c.nifempresa AS cliente_nif_empresa,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    c.Nombrefiscal AS cliente_razon_social,
    c.email AS cliente_email,
    c.telefono1 AS cliente_tel1,
    c.movil AS cliente_movil,

    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN pubExp pe ON pe.Idpublic = e.Idpublic
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
WHERE {organisme_like_clause}
  AND rs.TExp IN ({texp_list})
  AND rs.Estado IN (0, 1)
  AND rs.Expedient IS NOT NULL
ORDER BY rs.Estado ASC, rs.idRecurso ASC
"""

    def __init__(self):
        super().__init__(site_id="ayunta_palma", priority=3)
        self._regex_cache: dict[str, re.Pattern[str]] = {}
        self._regex_fallback = re.compile(self.DEFAULT_REGEX_EXPEDIENTE)

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
        txt = str(v or "").strip().upper()
        return re.sub(r"\s+", "", txt)

    @staticmethod
    def _resolve_plate_number(recurso: dict) -> tuple[str, str]:
        # 1) Prioridad: Recursos.RecursosExp.matricula
        plate_rs = AyuntaPalmaAdapter._clean_str(recurso.get("rs_matricula"))
        if plate_rs:
            return re.sub(r"\s+", "", plate_rs).upper(), "Recursos.RecursosExp.matricula"

        # 2) Prioridad: expedientes.matricula
        plate_exp = AyuntaPalmaAdapter._clean_str(recurso.get("matricula"))
        if plate_exp:
            return re.sub(r"\s+", "", plate_exp).upper(), "expedientes.matricula"

        # 3) Regex en publicación / notas
        regex = r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}[\s-]*[A-Z]{1,2})\b"

        def _try_extract(text: str, source_name: str) -> tuple[str, str] | None:
            if not text:
                return None
            m = re.search(regex, text.upper())
            if not m:
                return None
            clean_plate = m.group(1).replace(" ", "").replace("-", "")
            return clean_plate, source_name

        res_pub = _try_extract(AyuntaPalmaAdapter._clean_str(recurso.get("pub_publicacion")), "pubExp.publicación")
        if res_pub:
            return res_pub

        res_notas = _try_extract(AyuntaPalmaAdapter._clean_str(recurso.get("notas")), "rs.notas")
        if res_notas:
            return res_notas

        return "", ""

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

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        regex_pattern = self._clean_str(config.get("regex_expediente")) or self.DEFAULT_REGEX_EXPEDIENTE
        regex = self._regex_cache.get(regex_pattern)
        if regex is None:
            try:
                regex = re.compile(regex_pattern)
            except re.error:
                logger.warning("[ayunta_palma] Regex invalido: %r. Usando fallback.", regex_pattern)
                regex = self._regex_fallback
            self._regex_cache[regex_pattern] = regex

        filtro_texp = self._clean_str(config.get("filtro_texp")) or "2,3"
        texp_values = [int(x.strip()) for x in filtro_texp.split(",") if x.strip().isdigit()]
        if not texp_values:
            texp_values = [2, 3]
        texp_placeholders = ",".join(["?"] * len(texp_values))

        patterns = self._build_organisme_patterns(config.get("query_organisme"))
        like_clauses = ["rs.Organisme LIKE ?"] * len(patterns)
        organisme_like_clause = " AND ".join(like_clauses)

        query = self.SQL_FETCH_RECURSOS_PALMA.format(
            organisme_like_clause=organisme_like_clause,
            texp_list=texp_placeholders,
        )

        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(query, patterns + texp_values)
            columns = [column[0] for column in cursor.description]

            recursos_map: dict[int, dict] = {}
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                rid = record.get("idRecurso")
                if not rid:
                    continue
                rid_int = int(rid)

                if rid_int not in recursos_map:
                    recursos_map[rid_int] = {**record, "adjuntos": []}

                adj_id = record.get("adjunto_id")
                if adj_id:
                    filename = self._clean_str(record.get("adjunto_filename"))
                    if filename:
                        recursos_map[rid_int]["adjuntos"].append(
                            {
                                "id": int(adj_id),
                                "filename": filename,
                                "url": self.ADJUNTO_URL_TEMPLATE.format(id=int(adj_id)),
                            }
                        )

            out: list[dict] = []
            for _, recurso in recursos_map.items():
                if limit and len(out) >= limit:
                    break

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

                estado = int(recurso.get("Estado") or 0)
                usuario = self._clean_str(recurso.get("UsuarioAsignado"))
                if estado == 1 and authenticated_user and usuario != authenticated_user:
                    continue
                if estado == 1 and not authenticated_user:
                    continue

                out.append(recurso)

            return out
        finally:
            conn.close()

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

            cliente_tipo = int(r.get("cliente_tipo") or 0)
            sujeto = self._clean_str(r.get("SujetoRecurso"))
            fase = self._clean_str(r.get("FaseProcedimiento"))
            expone, solicita = self._build_expone_solicita(fase, expediente, sujeto)

            email = "info@xvia-serviciosjuridicos.com"
            telefono = "722761154"

            es_juridica = bool(cliente_tipo == 2 or self._clean_str(r.get("cliente_nif_empresa")) or self._clean_str(r.get("cif")))
            tipo_persona = "PersonaJuridica" if es_juridica else "PersonaFisica"

            nif_empresa = self._normalize_document_id(self._clean_str(r.get("cliente_nif_empresa")) or self._clean_str(r.get("cif")))
            razon_social = self._clean_str(r.get("cliente_razon_social")) or sujeto
            doc_fisica = self._normalize_document_id(self._clean_str(r.get("cliente_nif")))
            plate_number, plate_src = self._resolve_plate_number(r)

            payload = {
                "idRecurso": self._convert_value(r.get("idRecurso")),
                "idExp": self._convert_value(r.get("idExp")),
                "numclient": self._convert_value(r.get("numclient")),
                "expediente": expediente,
                "matricula": plate_number,
                "matricula_source": plate_src,
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
                "cliente_razon_social": self._clean_str(r.get("cliente_razon_social")),
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
            if not payload.get("matricula"):
                payload["matricula"] = "."
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
