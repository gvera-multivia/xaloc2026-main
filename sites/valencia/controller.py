from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path
from typing import Any

from .config import ValenciaConfig
from .data_models import ValenciaTarget

logger = logging.getLogger("xaloc_automation.valencia")


class ValenciaController:
    site_id = "valencia"
    display_name = "Valencia Ayuntamiento"
    _motivos_cache: dict[str, dict[str, Any]] | None = None

    def create_config(self, *, headless: bool) -> ValenciaConfig:
        cfg = ValenciaConfig()
        cfg.navegador.headless = headless
        return cfg

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _to_int(value: object, default: int = 0) -> int:
        try:
            return int(str(value or "").strip() or default)
        except Exception:
            return default

    @classmethod
    def _norm(cls, value: object) -> str:
        txt = cls._clean(value).lower()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return " ".join(txt.split())

    @classmethod
    def _load_motivos(cls) -> dict[str, dict[str, Any]]:
        if cls._motivos_cache is not None:
            return cls._motivos_cache
        config_path = Path(__file__).resolve().parents[2] / "config_motivos.json"
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cls._motivos_cache = {
                    cls._norm(k): v for k, v in raw.items() if isinstance(k, str) and isinstance(v, dict)
                }
            else:
                cls._motivos_cache = {}
        except Exception:
            cls._motivos_cache = {}
        return cls._motivos_cache

    @classmethod
    def _format_template(cls, template: str, *, expediente: str, sujeto_recurso: str) -> str:
        tpl = cls._clean(template)
        if not tpl:
            return ""
        try:
            return tpl.format(expediente=expediente, sujeto_recurso=sujeto_recurso)
        except Exception:
            return tpl

    @classmethod
    def _build_sujeto_recurso(cls, src: dict[str, Any], *, nombre: str, apellido1: str, apellido2: str, nombrefiscal: str) -> str:
        from_payload = cls._clean(src.get("sujeto_recurso") or src.get("SujetoRecurso"))
        if from_payload:
            return from_payload
        if nombrefiscal:
            return nombrefiscal
        return " ".join([p for p in [nombre, apellido1, apellido2] if p]).strip()

    @staticmethod
    def _payload_dict(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def _infer_tramite(cls, fase_procedimiento: str) -> tuple[str, str]:
        fase = cls._norm(fase_procedimiento)
        if "identific" in fase:
            return "identificacion_conductor", "MU.DE.50"
        if "denuncia" in fase or "propuesta" in fase:
            return "alegaciones_denuncia_transito", "MU.DE.30"
        if "sancion" in fase or "embargo" in fase or "apremio" in fase:
            return "recurso_reposicion", "MU.SA.40"
        return "alegaciones_denuncia_transito", "MU.DE.30"

    @classmethod
    def _resolve_expone_solicita(
        cls,
        src: dict[str, Any],
        *,
        expediente: str,
        fase_procedimiento: str,
        nombre: str,
        apellido1: str,
        apellido2: str,
        nombrefiscal: str,
    ) -> tuple[str, str]:
        expone = cls._clean(src.get("expone") or src.get("alegaciones") or src.get("motivos"))
        solicita = cls._clean(src.get("solicita") or src.get("observaciones"))
        if expone and solicita:
            return expone, solicita

        fase_key = cls._norm(fase_procedimiento or src.get("FaseProcedimiento"))
        motivos = cls._load_motivos()
        motivo = motivos.get(fase_key) if fase_key else None
        if not motivo:
            return expone, solicita

        sujeto_recurso = cls._build_sujeto_recurso(
            src,
            nombre=nombre,
            apellido1=apellido1,
            apellido2=apellido2,
            nombrefiscal=nombrefiscal,
        )
        if not expone:
            expone = cls._format_template(
                cls._clean(motivo.get("expone")),
                expediente=expediente,
                sujeto_recurso=sujeto_recurso,
            )
        if not solicita:
            solicita = cls._format_template(
                cls._clean(motivo.get("solicita")),
                expediente=expediente,
                sujeto_recurso=sujeto_recurso,
            )
        return expone, solicita

    def map_data(self, data: dict[str, Any]) -> dict[str, Any]:
        src = dict(data or {})
        expediente = self._clean(src.get("expediente") or src.get("Expedient"))
        fase_procedimiento = self._clean(src.get("fase_procedimiento") or src.get("FaseProcedimiento"))
        inferred_tipo, inferred_code = self._infer_tramite(fase_procedimiento)
        tramite_tipo = self._clean(src.get("tramite_tipo")) or inferred_tipo
        tramite_code = self._clean(src.get("tramite_code")) or inferred_code
        nombre = self._clean(src.get("nombre") or src.get("Nombre") or src.get("SujetoRecurso"))
        apellido1 = self._clean(src.get("apellido1") or src.get("Apellido1"))
        apellido2 = self._clean(src.get("apellido2") or src.get("Apellido2"))
        nombrefiscal = self._clean(src.get("nombrefiscal") or src.get("Nombrefiscal"))
        expone, solicita = self._resolve_expone_solicita(
            src,
            expediente=expediente,
            fase_procedimiento=fase_procedimiento,
            nombre=nombre,
            apellido1=apellido1,
            apellido2=apellido2,
            nombrefiscal=nombrefiscal,
        )
        return {
            "idRecurso": src.get("idRecurso"),
            "idExp": src.get("idExp"),
            "expediente": expediente,
            "fase_procedimiento": fase_procedimiento,
            "tramite_tipo": tramite_tipo,
            "tramite_code": tramite_code,
            "tipodecliente": self._clean(src.get("tipodecliente")),
            "nif": self._clean(src.get("nif")),
            "nifempresa": self._clean(src.get("nifempresa")),
            "nombre": nombre,
            "apellido1": apellido1,
            "apellido2": apellido2,
            "nombrefiscal": nombrefiscal,
            "conduc_nom": self._clean(src.get("conduc_nom") or src.get("ConducNom")),
            "conduc_dni": self._clean(src.get("conduc_dni") or src.get("Conducdni")),
            "conduc_codpost": self._clean(src.get("conduc_codpost") or src.get("ConducCodpost")),
            "conduc_adr": self._clean(src.get("conduc_adr") or src.get("ConducAdr")),
            "texp": self._to_int(src.get("texp") or src.get("TExp"), 0),
            "matricula": self._clean(src.get("matricula") or src.get("Matricula")),
            "matricula2": self._clean(src.get("matricula2") or src.get("Matricula2")),
            "matricula3": self._clean(src.get("matricula3") or src.get("Matricula3")),
            "expone": expone,
            "solicita": solicita,
            "archivos": list(src.get("archivos") or []),
            "headless": bool(src.get("headless", True)),
            "payload": dict(src),
        }

    def create_target(self, **kwargs: Any) -> ValenciaTarget:
        raw_payload = self._payload_dict(kwargs.get("payload"))
        merged = dict(raw_payload)
        merged.update(kwargs)
        id_recurso = kwargs.get("idRecurso") or raw_payload.get("idRecurso")
        id_exp = kwargs.get("idExp") or raw_payload.get("idExp")
        expediente = self._clean(kwargs.get("expediente") or raw_payload.get("expediente") or raw_payload.get("Expedient"))
        fase_procedimiento = self._clean(kwargs.get("fase_procedimiento") or raw_payload.get("fase_procedimiento") or raw_payload.get("FaseProcedimiento"))
        inferred_tipo, inferred_code = self._infer_tramite(fase_procedimiento)
        tramite_tipo = self._clean(kwargs.get("tramite_tipo") or raw_payload.get("tramite_tipo")) or inferred_tipo
        tramite_code = self._clean(kwargs.get("tramite_code") or raw_payload.get("tramite_code")) or inferred_code
        nombre = self._clean(kwargs.get("nombre") or raw_payload.get("nombre") or raw_payload.get("Nombre") or raw_payload.get("SujetoRecurso"))
        apellido1 = self._clean(kwargs.get("apellido1") or raw_payload.get("apellido1") or raw_payload.get("Apellido1"))
        apellido2 = self._clean(kwargs.get("apellido2") or raw_payload.get("apellido2") or raw_payload.get("Apellido2"))
        nombrefiscal = self._clean(kwargs.get("nombrefiscal") or raw_payload.get("nombrefiscal") or raw_payload.get("Nombrefiscal"))
        tipodecliente = self._clean(kwargs.get("tipodecliente") or raw_payload.get("tipodecliente"))
        nif = self._clean(kwargs.get("nif") or raw_payload.get("nif"))
        nifempresa = self._clean(kwargs.get("nifempresa") or raw_payload.get("nifempresa"))
        conduc_nom = self._clean(kwargs.get("conduc_nom") or raw_payload.get("conduc_nom") or raw_payload.get("ConducNom"))
        conduc_dni = self._clean(kwargs.get("conduc_dni") or raw_payload.get("conduc_dni") or raw_payload.get("Conducdni"))
        conduc_codpost = self._clean(kwargs.get("conduc_codpost") or raw_payload.get("conduc_codpost") or raw_payload.get("ConducCodpost"))
        conduc_adr = self._clean(kwargs.get("conduc_adr") or raw_payload.get("conduc_adr") or raw_payload.get("ConducAdr"))
        matricula = self._clean(kwargs.get("matricula") or raw_payload.get("matricula") or raw_payload.get("Matricula"))
        matricula2 = self._clean(kwargs.get("matricula2") or raw_payload.get("matricula2") or raw_payload.get("Matricula2"))
        matricula3 = self._clean(kwargs.get("matricula3") or raw_payload.get("matricula3") or raw_payload.get("Matricula3"))
        texp = self._to_int(kwargs.get("texp") or raw_payload.get("texp") or raw_payload.get("TExp"), 0)
        expone, solicita = self._resolve_expone_solicita(
            merged,
            expediente=expediente,
            fase_procedimiento=fase_procedimiento,
            nombre=nombre,
            apellido1=apellido1,
            apellido2=apellido2,
            nombrefiscal=nombrefiscal,
        )

        logger.info(
            "valencia.create_target idRecurso=%s idExp=%s expediente=%s tipodecliente=%s nif=%s conduc_dni=%s",
            id_recurso,
            id_exp,
            expediente,
            tipodecliente,
            nif,
            conduc_dni,
        )

        archivos_raw = kwargs.get("archivos")
        archivos_seq = archivos_raw if isinstance(archivos_raw, list) else []
        archivos = [Path(str(p)) for p in archivos_seq if str(p).strip()]
        return ValenciaTarget(
            idRecurso=id_recurso,
            idExp=id_exp,
            expediente=expediente,
            fase_procedimiento=fase_procedimiento,
            tramite_tipo=tramite_tipo,
            tramite_code=tramite_code,
            tipodecliente=tipodecliente,
            nif=nif,
            nifempresa=nifempresa,
            nombre=nombre,
            apellido1=apellido1,
            apellido2=apellido2,
            nombrefiscal=nombrefiscal,
            conduc_nom=conduc_nom,
            conduc_dni=conduc_dni,
            conduc_codpost=conduc_codpost,
            conduc_adr=conduc_adr,
            texp=texp,
            matricula=matricula,
            matricula2=matricula2,
            matricula3=matricula3,
            expone=expone,
            solicita=solicita,
            archivos_para_subir=archivos,
            payload=dict(merged),
            headless=bool(kwargs.get("headless", True)),
        )


def get_controller() -> ValenciaController:
    return ValenciaController()
