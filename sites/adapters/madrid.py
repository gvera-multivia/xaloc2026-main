from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pyodbc

from core.address_classifier import classify_address_fallback, classify_addresses_batch_with_ai
from .base import SiteAdapter

logger = logging.getLogger("brain")


class MadridAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )

    SQL_FETCH_RECURSOS_MADRID = """
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
    rs.notas,
    rs.matricula AS rs_matricula,

    e.matricula,
    e.Idpublic AS exp_idpublic,

    pe.publicación AS pub_publicacion,

    rs.cif,

    -- Datos detallados del cliente para NOTIFICACIÓN
    c.nif AS cliente_nif,
    c.nifempresa AS cliente_nif_empresa,
    c.tipodecliente AS cliente_tipo,
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

    -- Adjuntos (agrupados luego)
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
        super().__init__(site_id="madrid", priority=0, target_queue_depth=2, max_refill_batch=5)
        self._regex_madrid = re.compile(r"^(\d{3}/\d{9}\.\d|\d{9}\.\d)$")

    @staticmethod
    def _clean_str(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _normalize_text(text: Any) -> str:
        import unicodedata

        if not text:
            return ""
        t = str(text).strip().lower()
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
    ) -> list[dict]:
        texp_values = [2, 3]
        texp_placeholders = ",".join(["?"] * len(texp_values))

        # Manejar múltiples patrones LIKE (separados por espacios)
        query_organisme_raw = config.get("query_organisme", "%")
        patterns = [p.strip() for p in query_organisme_raw.split(" ") if p.strip()]

        if not patterns:
            patterns = ["%"]

        like_clauses = ["rs.Organisme LIKE ?"] * len(patterns)
        organisme_like_clause = " AND ".join(like_clauses)

        query = self.SQL_FETCH_RECURSOS_MADRID.format(organisme_like_clause=organisme_like_clause, texp_list=texp_placeholders)

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
                if not expediente or not self._regex_madrid.match(expediente):
                    continue

                fase_norm = self._normalize_text(recurso.get("FaseProcedimiento"))
                if any(x in fase_norm for x in ["reclamacion", "embargo", "apremio"]):
                    continue

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

        m1 = re.match(r"^(?P<nnn>\d{3})/(?P<exp>\d{9})\.(?P<d>\d)$", exp)
        if m1:
            return {
                "expediente_completo": exp,
                "expediente_tipo": "opcion1",
                "expediente_nnn": m1.group("nnn"),
                "expediente_eeeeeeeee": m1.group("exp"),
                "expediente_d": m1.group("d"),
                "expediente_lll": "",
                "expediente_aaaa": "",
                "expediente_exp_num": "",
            }

        m3 = re.match(r"^(?P<exp>\d{9})\.(?P<d>\d)$", exp)
        if m3:
            prefijo = MadridAdapter._inferir_prefijo_expediente(fase_raw=fase_raw, es_empresa=es_empresa)
            exp_reconstruido = f"{prefijo}/{exp}"
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
        # - "A": Alegación
        # - "R": Recurso (incluye Resolución sancionadora, Apremio, Embargo, etc.)
        # - "I": Identificación del conductor
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

        # 3. Regex en texto (Publicación o Notas)
        # Regex mejorada que permite espacios y guiones opcionales pero respeta word boundaries
        regex = r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}[\s-]*[A-Z]{1,2})\b"

        def _try_extract(text: str, source_name: str) -> tuple[str, str] | None:
            if not text:
                return None
            m = re.search(regex, text.upper())
            if m:
                # Limpiar la matrícula encontrada de espacios y guiones
                clean_plate = m.group(1).replace(" ", "").replace("-", "")
                return clean_plate, source_name
            return None

        # 3.a Publicación
        res_pub = _try_extract(MadridAdapter._clean_str(recurso.get("pub_publicacion")), "pubExp.publicación")
        if res_pub:
            return res_pub

        # 3.b Notas
        res_notas = _try_extract(MadridAdapter._clean_str(recurso.get("notas")), "rs.notas")
        if res_notas:
            return res_notas

        return "", ""

    @staticmethod
    def _detectar_tipo_documento(doc: str) -> str:
        if not doc:
            return "NIF"
        d = doc.strip().upper()
        if re.match(r"^[A-Z]{3}[0-9]+", d):
            return "PS"
        return "NIF"

    @staticmethod
    def _convert_value(v: Any) -> Any:
        from decimal import Decimal

        if isinstance(v, Decimal):
            return float(v)
        return v

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
            raise ValueError(f"Payload Madrid inválido, faltan campos: {', '.join(sorted(set(missing)))}")

    async def build_payloads(self, candidates: list[dict]) -> list[dict]:
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

        batch_mapping: dict[str, dict] = {}
        if os.getenv("GROQ_API_KEY"):
            try:
                batch_mapping = await classify_addresses_batch_with_ai(items)
            except Exception as e:
                logger.warning("[MADRID][IA] Falló batch LLM, usando fallback local: %s", e)
                batch_mapping = {}

        payloads: list[dict] = []
        for r in candidates:
            expediente_raw = self._clean_str(r.get("Expedient")).upper()
            cif_recurso = self._clean_str(r.get("cif"))
            nif_individual = self._clean_str(r.get("cliente_nif"))
            nif_empresa = self._clean_str(r.get("cliente_nif_empresa"))
            tipo_cliente = int(r.get("cliente_tipo") or 0)

            # Lógica de selección de NIF
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
                # Es física: Usar cliente_nif
                nif = nif_individual

            if not nif:
                logger.warning("[MADRID] Recurso %s sin NIF válido. Saltando.", r.get("idRecurso"))
                continue

            nif = nif.strip().upper()
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
            notif_numero = (clasif.get("numero") or numero_db).upper()
            notif_escalera = ((clasif.get("escalera") or escalera_db) or "").upper()
            notif_planta = ((clasif.get("planta") or piso_db) or "").upper()
            notif_puerta = ((clasif.get("puerta") or puerta_db) or "").upper()

            tipo_numeracion = "NUM" if self._clean_str(notif_numero) else "S/N"
            provincia_notif = self._clean_str(r.get("cliente_provincia")).upper() or poblacion.upper()

            representante = {
                "rep_tipo_via": "RONDA",
                "rep_tipo_numeracion": "NUM",
                "representative_city": "BARCELONA",
                "representative_province": "BARCELONA",
                "representative_country": "ESPAÑA",
                "representative_street": "GENERAL MITRE, DEL",
                "representative_number": "169",
                "representative_zip": "08022",
                "representative_email": "info@xvia-serviciosjuridicos.com",
                "representative_phone": "932531411",
                "rep_nombre_via": "GENERAL MITRE, DEL",
                "rep_numero": "169",
                "rep_cp": "08022",
                "rep_municipio": "BARCELONA",
                "rep_provincia": "BARCELONA",
                "rep_pais": "ESPAÑA",
                "rep_email": "info@xvia-serviciosjuridicos.com",
                "rep_movil": "932531411",
                "rep_telefono": "932531411",
                "rep_tipo_numeracion": "NUM",
            }

            payload = {
                "idRecurso": self._convert_value(r.get("idRecurso")),
                "idExp": self._convert_value(r.get("idExp")),
                "expediente": expediente_raw,
                "numclient": self._convert_value(r.get("numclient")),
                "sujeto_recurso": self._clean_str(r.get("SujetoRecurso")),
                "fase_procedimiento": fase_raw,
                "plate_number": plate_number,
                "plate_number_source": plate_src,
                "user_phone": "932531411",
                "inter_telefono": "932531411",
                "inter_email_check": bool(self._clean_str(r.get("cliente_email"))),
                **representante,
                "notif_tipo_documento": self._detectar_tipo_documento(nif),
                "notif_numero_documento": nif,
                "notif_name": self._clean_str(r.get("cliente_nombre")).upper(),
                "notif_surname1": self._clean_str(r.get("cliente_apellido1")).upper(),
                "notif_surname2": self._clean_str(r.get("cliente_apellido2")).upper(),
                "notif_razon_social": self._clean_str(r.get("cliente_razon_social")).upper(),
                "notif_pais": "ESPAÑA",
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
                "notif_email": "info@xvia-serviciosjuridicos.com",
                "notif_movil": "",
                "notif_telefono": "932531411",
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

            self._prevalidate_required_fields(payload)
            payloads.append(payload)

        return payloads
