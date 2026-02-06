from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pyodbc

from .base import SiteAdapter
from core.nt_expediente_fixer import is_nt_pattern, fix_nt_expediente
from core.xaloc_expediente_utils import is_valid_format, fix_format


class XalocAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )

    SQL_FETCH_RECURSOS_XALOC = """
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
    
    e.matricula,     -- Ahora viene de la tabla expedientes
    
    rs.cif,          -- Para determinar JURIDICA vs FISICA
    c.nifempresa,    -- Fallback CIF
    rs.Empresa,      -- Razón social
    c.Nombrefiscal,  -- Fallback Razón social
    
    c.nif AS cliente_nif,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename

FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
WHERE {organisme_like_clause}
  AND rs.TExp IN ({texp_list})
  AND rs.Estado IN (0, 1)
  AND rs.Expedient IS NOT NULL
ORDER BY rs.Estado ASC, rs.idRecurso ASC
"""

    def __init__(self):
        super().__init__(site_id="xaloc_girona", priority=1, target_queue_depth=5, max_refill_batch=10)

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
    def _determinar_tipo_persona(cif_value: str | None, empresa_value: str | None = None) -> str:
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
        v = str(value).strip() if value is not None else ""
        cleaned = re.sub(r"\s+", "", v).upper()
        if not cleaned:
            return "." # Fallback explícito
        return cleaned

    @staticmethod
    def _convert_value(v: Any) -> Any:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
        return v

    def _build_mandatario_data(self, row: dict) -> dict:
        cif_raw = row.get("cif") or row.get("nifempresa")
        empresa_raw = row.get("Empresa") or row.get("Nombrefiscal")
        
        tipo_persona = self._determinar_tipo_persona(cif_raw, empresa_raw)
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
                # Fallback si no hay NIF (aunque debería haber)
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
        # Lógica duplicada de xaloc_task.py para asegurar compatibilidad
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


    def fetch_candidates(self, *, config: dict, conn_str: str, authenticated_user: Optional[str], limit: int) -> list[dict]:
        texp_values = [2, 3] # Hardcoded logic from xaloc_task.py
        texp_placeholders = ",".join(["?"] * len(texp_values))
        
        query_organisme_raw = config.get("query_organisme", "%XALOC%")
        # Simplemente asumimos un solo patrón para Xaloc normalmente, pero soportamos split
        patterns = [p.strip() for p in query_organisme_raw.split(" ") if p.strip()]
        if not patterns:
            patterns = ["%XALOC%"]
            
        like_clauses = ["rs.Organisme LIKE ?"] * len(patterns)
        organisme_like_clause = " AND ".join(like_clauses)
        
        query = self.SQL_FETCH_RECURSOS_XALOC.format(
            organisme_like_clause=organisme_like_clause,
            texp_list=texp_placeholders
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
                if not rid: continue
                rid_int = int(rid)

                if rid_int not in recursos_map:
                    recursos_map[rid_int] = {**record, "adjuntos": []}

                adj_id = record.get("adjunto_id")
                if adj_id:
                    filename = self._clean_str(record.get("adjunto_filename"))
                    if filename:
                        recursos_map[rid_int]["adjuntos"].append({
                            "id": int(adj_id),
                            "filename": filename,
                            "url": self.ADJUNTO_URL_TEMPLATE.format(id=int(adj_id)),
                        })

            out: list[dict] = []
            for _, recurso in recursos_map.items():
                if limit and len(out) >= limit: break
                
                rid = recurso.get("idRecurso")
                id_exp = recurso.get("idExp")
                expediente_raw = self._clean_str(recurso.get("Expedient"))
                estado = int(recurso.get("Estado") or 0)
                usuario = self._clean_str(recurso.get("UsuarioAsignado"))
                
                # 1. Validar formato y aplicar correcciones
                expediente = expediente_raw
                is_valid = is_valid_format(expediente)
                
                # Caso A: Patrón NT/
                if not is_valid and is_nt_pattern(expediente):
                    corrected = fix_nt_expediente(conn_str, id_exp)
                    if corrected:
                        expediente = corrected
                        recurso["Expedient"] = corrected
                        is_valid = is_valid_format(expediente)
                
                # Caso B: Otros errores de formato (guiones, falta de L)
                if not is_valid:
                    fixed = fix_format(expediente)
                    if fixed != expediente:
                        if is_valid_format(fixed):
                            # Actualizar base de datos de manera exhaustiva (como en NT fixer)
                            try:
                                # 1. UPDATE expedientes
                                cursor.execute(
                                    "UPDATE expedientes SET numexpediente = ? WHERE idexpediente = ?",
                                    (fixed, id_exp)
                                )
                                # 2. UPDATE recursos.RecursosExp
                                cursor.execute(
                                    "UPDATE recursos.RecursosExp SET Expedient = ? WHERE IdExp = ?",
                                    (fixed, id_exp)
                                )
                                # 3. UPDATE ListasPresentacion
                                cursor.execute(
                                    "UPDATE ListasPresentacion SET numexpediente = ? WHERE Idexpediente = ?",
                                    (fixed, id_exp)
                                )
                                # 4. UPDATE pubExp
                                cursor.execute("""
                                    UPDATE p 
                                    SET p.Exp = ?
                                    FROM pubExp p 
                                    JOIN recursos.RecursosExp r ON r.IdPublic = p.idpublic
                                    WHERE r.IdExp = ?
                                """, (fixed, id_exp))
                                
                                conn.commit()
                                print(f"✅ Expediente '{expediente_raw}' corregido a '{fixed}' en todas las tablas para idExp={id_exp}")
                                
                                expediente = fixed
                                recurso["Expedient"] = fixed
                                is_valid = True
                            except Exception as e:
                                print(f"Error actualizando expediente mal formateado {rid}: {e}")
                                conn.rollback()

                if not is_valid:
                    continue  # Descartar si el formato sigue siendo inválido

                # 2. Regla de usuario asignado
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
                "user_email": "INFO@XVIA-SERVICIOSJURIDICOS.COM",
                "denuncia_num": expediente,
                "plate_number": self._normalize_plate(r.get("matricula")),
                "expediente_num": expediente,
                "expediente": expediente,  # Alias para el orquestador
                "sujeto_recurso": sujeto_recurso,
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
