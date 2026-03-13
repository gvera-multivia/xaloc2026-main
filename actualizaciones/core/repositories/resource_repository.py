from __future__ import annotations

import logging
from typing import Any

import pyodbc

from core.domain import ResourceDomain


class ResourceRepository:
    """
    Canonical retrieval contract:
    - one superset SQL profile for all supported sites
    - site behavior differences are handled by adapters/validators, not query shape
    """

    SUPPORTED_SITES: set[str] = {
        "madrid",
        "base_online",
        "xaloc_girona",
        "ayunta_palma",
        "redsara",
        "terrassa",
    }

    SQL_CANONICAL_SUPERSET = """
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
    rs.FUsuarioCompletado,
    rs.UsuarioAsignado,
    rs.notas,
    rs.FAlta,
    rs.cif,
    rs.Empresa,
    rs.Matricula AS rs_matricula,

    e.matricula,
    e.matricula AS exp_matricula,
    e.Idpublic AS exp_idpublic,
    e.dia AS dia_denuncia,

    pe.[publicación] AS pub_publicacion,
    pe.matricula AS pub_matricula,

    c.tipodecliente AS cliente_tipo,
    c.nif AS cliente_nif,
    c.nifempresa AS cliente_nif_empresa,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    c.Nombrefiscal AS cliente_razon_social,
    c.provincia AS cliente_provincia,
    c.poblacion AS cliente_municipio,
    c.calle AS cliente_domicilio,
    c.numero AS cliente_numero,
    c.escalera AS cliente_escalera,
    c.piso AS cliente_planta,
    c.puerta AS cliente_puerta,
    c.Cpostal AS cliente_cp,
    c.email AS cliente_email,
    c.telefono1 AS cliente_tel1,
    c.telefono2 AS cliente_tel2,
    c.movil AS cliente_movil,

    CASE WHEN rs.TExp = 2 THEN rs.ConducNom ELSE di.ConducNom END AS conduc_nom,
    CASE WHEN rs.TExp = 2 THEN rs.Conducdni ELSE di.Conducdni END AS conduc_dni,
    CASE WHEN rs.TExp = 2 THEN rs.ConducAdr ELSE di.ConducAdr END AS conduc_adr,
    CASE WHEN rs.TExp = 2 THEN rs.ConducCodpost ELSE di.ConducCodpost END AS conduc_codpost,
    CASE WHEN rs.TExp = 2 THEN rs.ConducPobl ELSE di.ConducPobl END AS conduc_pobl,
    CASE WHEN rs.TExp = 2 THEN rs.Conducprov ELSE NULL END AS conduc_prov,

    att.id AS adjunto_id,
    att.Filename AS adjunto_filename

FROM Recursos.RecursosExp rs
LEFT JOIN clientes c ON rs.numclient = c.numerocliente
LEFT JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN pubExp pe ON pe.Idpublic = e.Idpublic
LEFT JOIN DadesIdentif di ON rs.idExp = di.idExp
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id

WHERE {organisme_like_clause}
  AND rs.TExp IN ({texp_list})
  AND rs.Estado IN (0, 1)
  AND rs.Expedient IS NOT NULL

ORDER BY rs.Estado ASC, rs.idRecurso ASC
"""

    def __init__(self, *, conn_str: str, logger: logging.Logger | None = None):
        self.conn_str = str(conn_str or "").strip()
        self.logger = logger or logging.getLogger("resource_repository")

    @staticmethod
    def _clean_str(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @classmethod
    def _normalize_like_pattern(cls, raw: Any) -> str:
        token = cls._clean_str(raw)
        if not token:
            return ""
        if token == "%":
            return token

        has_wildcard = ("%" in token) or ("_" in token)
        if not has_wildcard:
            return f"%{token}%"

        if not token.startswith("%"):
            token = f"%{token}"
        if not token.endswith("%"):
            token = f"{token}%"
        return token

    def _parse_organisme_patterns(self, raw: Any) -> tuple[list[str], str]:
        text = self._clean_str(raw)
        if not text:
            return ["%"], "or"

        if "|" in text:
            parts = [self._normalize_like_pattern(chunk) for chunk in text.split("|")]
            patterns = [chunk for chunk in parts if chunk]
            return patterns or ["%"], "or"

        patterns = [self._normalize_like_pattern(chunk) for chunk in text.split(" ")]
        patterns = [chunk for chunk in patterns if chunk]
        self.logger.warning(
            "query_organisme en formato legacy (sin '|'). Compatibilidad activa con split por espacios + AND "
            "(normalizando wildcards LIKE); actualiza a formato OR por '|'. Valor=%r",
            text,
        )
        return patterns or ["%"], "and"

    @staticmethod
    def _parse_texp(config: dict[str, Any]) -> list[int]:
        raw = str(config.get("filtro_texp") or "").strip()
        if not raw:
            return [2, 3]
        values: list[int] = []
        for token in raw.split(","):
            item = token.strip()
            if not item:
                continue
            try:
                values.append(int(item))
            except Exception:
                continue
        return values or [2, 3]

    def _build_query(self, *, site_id: str, config: dict[str, Any]) -> tuple[str, list[Any]]:
        site = str(site_id or "").strip()
        if site not in self.SUPPORTED_SITES:
            raise ValueError(f"Site no soportado por ResourceRepository: {site}")

        patterns, mode = self._parse_organisme_patterns(config.get("query_organisme"))
        operator = " OR " if mode == "or" else " AND "
        like_clauses = ["rs.Organisme LIKE ?"] * len(patterns)
        organisme_like_clause = "(" + operator.join(like_clauses) + ")"

        texp_values = self._parse_texp(config)
        texp_placeholders = ",".join(["?"] * len(texp_values))
        query = self.SQL_CANONICAL_SUPERSET.format(organisme_like_clause=organisme_like_clause, texp_list=texp_placeholders)
        params: list[Any] = [*patterns, *texp_values]
        return query, params

    def get_pending_resources(self, *, site_id: str, config: dict[str, Any], limit: int) -> list[ResourceDomain]:
        if int(limit or 0) <= 0:
            return []

        query, params = self._build_query(site_id=site_id, config=config)
        conn = pyodbc.connect(self.conn_str)
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            columns = [column[0] for column in cur.description]
            grouped: dict[int, dict[str, Any]] = {}
            order: list[int] = []
            for row in cur.fetchall():
                record = dict(zip(columns, row))
                rid_raw = record.get("idRecurso")
                try:
                    rid = int(rid_raw)
                except Exception:
                    continue

                item = grouped.get(rid)
                if item is None:
                    item = {**record, "adjuntos": []}
                    grouped[rid] = item
                    order.append(rid)

                adj_id = record.get("adjunto_id")
                if adj_id:
                    filename = self._clean_str(record.get("adjunto_filename"))
                    if filename:
                        item["adjuntos"].append({"id": int(adj_id), "filename": filename})

            out: list[ResourceDomain] = []
            for rid in order:
                if len(out) >= int(limit):
                    break
                raw_item = grouped[rid]
                out.append(ResourceDomain.from_row(site_id=site_id, row=raw_item))
            return out
        finally:
            conn.close()
