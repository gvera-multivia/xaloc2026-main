from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from decimal import Decimal

import pyodbc

from .site_adapter import SiteAdapter
from core.address_classifier import classify_address_with_ai, classify_address_fallback
from core.client_documentation import build_required_client_documents_for_payload

logger = logging.getLogger("brain")

class BaseOnlineAdapter(SiteAdapter):
    SQL_FETCH_RECURSOS_BASE = """
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
    rs.FAlta,
    e.matricula,
    rs.cif,
    -- Datos detallados del cliente
    c.nif AS cliente_nif,
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
    -- Adjuntos
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
WHERE rs.Organisme LIKE '%BASE%'
  AND rs.TExp IN ({texp_list})
  AND rs.Estado IN (0, 1)
  AND rs.Expedient IS NOT NULL
ORDER BY rs.Estado ASC, rs.idRecurso ASC
"""

    def __init__(self):
        super().__init__(site_id="base_online", priority=1)

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

    @staticmethod
    def _convert_value(v: Any) -> Any:
        if isinstance(v, Decimal):
            return float(v)
        return v

    def _valida_expediente_base(self, expediente: str) -> bool:
        exp = self._clean_str(expediente).upper()
        # GIM: 43150-2026/3320-GIM (4-5 dígitos tras /)
        if re.match(r"^\d{5}-\d{4}/\d{4,5}-GIM$", exp):
            return True
        # GIM alternativo: 43-XXX-XXX-YYYY-MM-XXXXXXX
        if re.match(r"^\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{7}$", exp):
            return True
        # EXE/ECC: 1-2025/27474-EXE o 1-2025-140620-ECC
        if re.match(r"^\d-\d{4}[/\-]\d{4,6}-(EXE|ECC)$", exp):
            return True
        return False

    def _parse_expediente_base(self, expediente: str) -> dict:
        exp = self._clean_str(expediente).upper()
        # GIM
        m_gim = re.match(r"^(?P<id_ens>\d{5})-(?P<any>\d{4})/(?P<num>\d{4,5})-GIM$", exp)
        if m_gim:
            return {
                "expediente_id_ens": m_gim.group("id_ens"),
                "expediente_any": m_gim.group("any"),
                "expediente_num": m_gim.group("num"),
                "num_butlleti": exp,
            }
        # EXE/ECC
        m_exe = re.match(r"^(?P<id_ens>\d)-(?P<any>\d{4})[/\-](?P<num>\d{4,6})-(EXE|ECC)$", exp)
        if m_exe:
            return {
                "expediente_id_ens": m_exe.group("id_ens"),
                "expediente_any": m_exe.group("any"),
                "expediente_num": m_exe.group("num"),
                "num_butlleti": exp,
            }
        return {
            "expediente_id_ens": "",
            "expediente_any": "",
            "expediente_num": "",
            "num_butlleti": exp,
        }

    def _determina_protocolo(self, fase: str) -> str:
        f = self._normalize_text(fase)
        if "identificacion" in f:
            return "P1"
        if any(tag in f for tag in ("denuncia", "propuesta", "subsanacion", "alegacion", "alegaciones")):
            return "P2"
        return "P3"

    def _get_motivos_base(self, fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str]:
        try:
            path = Path("config_motivos.json")
            config = {}
            if path.exists():
                import json
                config = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            config = {}

        fase_norm = self._normalize_text(fase_raw)
        selected = None
        for key, value in (config or {}).items():
            if self._normalize_text(key) in fase_norm:
                selected = value
                break

        exp = self._clean_str(expediente)
        sujeto_txt = self._clean_str(sujeto)

        if not selected:
            return f"Escrito relativo al exp {exp}", f"Se tenga por presentado el escrito. Exp {exp}"

        expone = self._clean_str(selected.get("expone")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)
        solicita = self._clean_str(selected.get("solicita")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)
        return expone, solicita

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        texp_values = [2, 3]
        texp_placeholders = ",".join(["?"] * len(texp_values))
        query = self.SQL_FETCH_RECURSOS_BASE.format(texp_list=texp_placeholders)

        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(query, texp_values)
            columns = [column[0] for column in cursor.description]

            recursos_map: dict[int, dict] = {}
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                rid = record.get("idRecurso")
                if not rid: continue
                rid_int = int(rid)

                if rid_int not in recursos_map:
                    recursos_map[rid_int] = {**record, "adjuntos": []}

                adj_id = record.get("adjunto_id")
                if adj_id:
                    recursos_map[rid_int]["adjuntos"].append({
                        "id": int(adj_id),
                        "filename": record.get("adjunto_filename")
                    })

            out: list[dict] = []
            for _, recurso in recursos_map.items():
                if limit and len(out) >= limit: break
                
                expediente = self._clean_str(recurso.get("Expedient"))
                if not self._valida_expediente_base(expediente):
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

    async def build_payloads(self, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []

        # Preparar datos para clasificación por IA en batch
        from core.address_classifier import classify_address_fallback, classify_addresses_batch_with_ai

        items_for_ia: list[dict] = []
        for r in candidates:
            items_for_ia.append({
                "idRecurso": r.get("idRecurso"),
                "direccion_raw": self._clean_str(r.get("cliente_domicilio")),
                "poblacion": self._clean_str(r.get("cliente_municipio")),
                "numero": self._clean_str(r.get("cliente_numero")),
                "piso": self._clean_str(r.get("cliente_planta")),
                "puerta": self._clean_str(r.get("cliente_puerta")),
            })

        batch_mapping: dict[str, dict] = {}
        if os.getenv("GROQ_API_KEY"):
            try:
                batch_mapping = await classify_addresses_batch_with_ai(items_for_ia)
            except Exception as e:
                logger.warning("[base_online][IA] Falló batch LLM, usando fallback: %s", e)

        payloads: list[dict] = []
        for r in candidates:
            fase_raw = self._clean_str(r.get("FaseProcedimiento"))
            expediente_raw = self._clean_str(r.get("Expedient"))
            protocolo = self._determina_protocolo(fase_raw)

            # SALTAR P1 según requerimiento
            if protocolo == "P1":
                logger.info(f"[base_online] Saltando expediente P1: {expediente_raw}")
                continue

            exp_parts = self._parse_expediente_base(expediente_raw)
            nif = self._clean_str(r.get("cif") or r.get("cliente_nif"))
            
            # Datos de dirección (優先 IA batch -> fallback)
            rid_str = str(r.get("idRecurso"))
            clasif = batch_mapping.get(rid_str)
            
            domicilio_raw = self._clean_str(r.get("cliente_domicilio"))
            poblacion = self._clean_str(r.get("cliente_municipio"))
            numero_db = self._clean_str(r.get("cliente_numero"))
            cp = self._clean_str(r.get("cliente_cp"))
            provincia = self._clean_str(r.get("cliente_provincia")) or poblacion

            if not clasif:
                clasif = classify_address_fallback(domicilio_raw)

            notif_data = {
                "address_sigla": (clasif.get("tipo_via") or "CALLE").upper(),
                "address_street": (clasif.get("calle") or domicilio_raw).upper(),
                "address_number": (clasif.get("numero") or numero_db).upper(),
                "address_zip": cp,
                "address_city": poblacion.upper(),
                "address_province": provincia.upper(),
                "address_country": "ESPAÑA",
                "address_esc": (clasif.get("escalera") or r.get("cliente_escalera") or "").upper(),
                "address_planta": (clasif.get("planta") or r.get("cliente_planta") or "").upper(),
                "address_puerta": (clasif.get("puerta") or r.get("cliente_puerta") or "").upper(),
            }

            expone, solicita = self._get_motivos_base(fase_raw, expediente_raw, r.get("SujetoRecurso"))

            payload = {
                "idRecurso": self._convert_value(r["idRecurso"]),
                "idExp": self._convert_value(r["idExp"]),
                "numclient": self._convert_value(r.get("numclient")),
                "fase_procedimiento": fase_raw,
                "expediente": expediente_raw,
                "protocol": protocolo,
                "user_phone": "932531411",
                "user_email": "info@xvia-serviciosjuridicos.com",
                "plate_number": self._clean_str(r.get("matricula")),
                "nif": nif,
                "name": self._clean_str(r.get("SujetoRecurso")).upper(),
                "cliente_nombre": self._clean_str(r.get("cliente_nombre")),
                "cliente_apellido1": self._clean_str(r.get("cliente_apellido1")),
                "cliente_apellido2": self._clean_str(r.get("cliente_apellido2")),
                "cliente_razon_social": self._clean_str(r.get("cliente_razon_social")),
                **notif_data,
                **exp_parts,
                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }

            # Documentación del cliente
            try:
                from brain import build_sqlserver_connection_string
                conn_str = build_sqlserver_connection_string()
                from core.client_documentation import build_required_client_documents_for_payload
                client_docs = await build_required_client_documents_for_payload(payload, sqlserver_conn_str=conn_str, strict=False)
                payload["archivos"] = [str(p) for p in client_docs]
            except Exception as e:
                logger.warning(f"[base_online] Error cargando documentación: {e}")
                payload["archivos"] = []

            if protocolo == "P2":
                payload.update({
                    "p2_nif": nif,
                    "p2_rao_social": payload["cliente_razon_social"] or payload["name"],
                    "p2_exposo": expone,
                    "p2_solicito": solicita,
                    "exposo": expone,
                    "solicito": solicita,
                })

            if protocolo == "P3":
                payload.update({
                    "p3_tipus_objecte": "IVTM",
                    "p3_dades_especifiques": payload.get("plate_number") or "",
                    "p3_tipus_solicitud_value": "1",
                    "p3_exposo": expone,
                    "p3_solicito": solicita,
                    "exposo": expone,
                    "solicito": solicita,
                })

            payloads.append(payload)
        return payloads
