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
    MISSING_PLATE_PLACEHOLDER = "."
    _motivos_cache: dict[str, dict[str, Any]] | None = None

    def create_config(self, *, headless: bool) -> ValenciaConfig:
        cfg = ValenciaConfig()
        cfg.navegador.headless = headless
        # Valencia firma in-process; dejar el auto-open activo fuerza a Chromium
        # a lanzar afirma:// y compite con el bridge programatico.
        cfg.autofirma_auto_open = False
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
    def _enrich_from_nested_and_canonical(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Ruta orquestada defensiva:
        - Promueve campos desde payload anidado (`payload`)
        - Promueve campos desde canonical (`__canonical_v1`) si faltan en raíz
        """
        src = dict(data or {})
        nested = src.get("payload")
        if isinstance(nested, dict):
            for key, value in nested.items():
                if src.get(key) in (None, "", []):
                    src[key] = value

        canonical = src.get("__canonical_v1")
        if not isinstance(canonical, dict):
            return src

        resource = canonical.get("resource") or {}
        client = canonical.get("client") or {}
        vehicle = canonical.get("vehicle") or {}
        client_doc = client.get("document") or {}
        client_name = client.get("name") or {}
        plate = (vehicle.get("plate") or {}).get("value")

        defaults = {
            "idRecurso": resource.get("id"),
            "idExp": resource.get("exp_id"),
            "expediente": resource.get("expedient"),
            "Expedient": resource.get("expedient"),
            "expediente_num": resource.get("expedient"),
            "num_expediente": resource.get("expedient"),
            "denuncia_num": resource.get("expedient"),
            "num_denuncia": resource.get("expedient"),
            "fase_procedimiento": resource.get("phase"),
            "FaseProcedimiento": resource.get("phase"),
            "sujeto_recurso": resource.get("subject_name"),
            "SujetoRecurso": resource.get("subject_name"),
            "tipodecliente": client.get("type"),
            "cliente_tipo": client.get("type"),
            "nif": client_doc.get("nif"),
            "nifempresa": client_doc.get("cif"),
            "cliente_nif": client_doc.get("nif"),
            "cliente_nif_empresa": client_doc.get("cif"),
            "nombre": client_name.get("first"),
            "apellido1": client_name.get("last1"),
            "apellido2": client_name.get("last2"),
            "nombrefiscal": client_name.get("business"),
            "nombrefiscal": client_name.get("business"),
            "matricula": plate,
            "plate_number": plate,
        }
        for key, value in defaults.items():
            if src.get(key) in (None, "", []):
                src[key] = value

        return src

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
    def _resolve_matricula(cls, *candidates: object) -> str:
        for raw in candidates:
            value = "".join(cls._clean(raw).upper().split())
            if value and len(value) <= 15 and value.isalnum():
                return value
        return cls.MISSING_PLATE_PLACEHOLDER

    @classmethod
    def _sync_payload_matricula(cls, payload: dict[str, Any], matricula: str) -> dict[str, Any]:
        synced = dict(payload or {})
        synced["matricula"] = matricula
        synced["plate_number"] = matricula
        return synced

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
            fallback_expediente = expediente or "N/A"
            if not expone:
                expone = (
                    f"Se presenta escrito en relacion con el expediente {fallback_expediente} "
                    "y se exponen los hechos para su valoracion."
                )
            if not solicita:
                solicita = (
                    f"Se solicita la admision y tramitacion del presente escrito "
                    f"relativo al expediente {fallback_expediente}."
                )
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
        # Blindaje final: si la plantilla no resolvio algun bloque, completar con texto base.
        fallback_expediente = expediente or "N/A"
        if not expone:
            expone = (
                f"Se presenta escrito en relacion con el expediente {fallback_expediente} "
                "y se exponen los hechos para su valoracion."
            )
        if not solicita:
            solicita = (
                f"Se solicita la admision y tramitacion del presente escrito "
                f"relativo al expediente {fallback_expediente}."
            )
        return expone, solicita

    def map_data(self, data: dict[str, Any]) -> dict[str, Any]:
        src = self._enrich_from_nested_and_canonical(dict(data or {}))
        expediente = self._clean(
            src.get("expediente")
            or src.get("Expedient")
            or src.get("expediente_num")
            or src.get("num_expediente")
            or src.get("denuncia_num")
            or src.get("num_denuncia")
            or src.get("nExp")
        )
        fase_procedimiento = self._clean(src.get("fase_procedimiento") or src.get("FaseProcedimiento"))
        inferred_tipo, inferred_code = self._infer_tramite(fase_procedimiento)
        tramite_tipo = self._clean(src.get("tramite_tipo")) or inferred_tipo
        tramite_code = self._clean(src.get("tramite_code")) or inferred_code
        nombre = self._clean(
            src.get("nombre") or src.get("Nombre") or src.get("cliente_nombre") or src.get("name") or src.get("SujetoRecurso")
        )
        apellido1 = self._clean(src.get("apellido1") or src.get("Apellido1") or src.get("cliente_apellido1"))
        apellido2 = self._clean(src.get("apellido2") or src.get("Apellido2") or src.get("cliente_apellido2"))
        nombrefiscal = self._clean(src.get("nombrefiscal") or src.get("Nombrefiscal") or src.get("cliente_razon_social"))
        matricula = self._resolve_matricula(
            src.get("matricula"),
            src.get("Matricula"),
            src.get("plate_number"),
            src.get("matricula2"),
            src.get("Matricula2"),
            src.get("matricula3"),
            src.get("Matricula3"),
        )
        payload = self._sync_payload_matricula(src, matricula)
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
            "tipodecliente": self._clean(src.get("tipodecliente") or src.get("cliente_tipo")),
            "nif": self._clean(src.get("nif") or src.get("cliente_nif")),
            "nifempresa": self._clean(src.get("nifempresa") or src.get("cliente_nif_empresa")),
            "nombre": nombre,
            "apellido1": apellido1,
            "apellido2": apellido2,
            "nombrefiscal": nombrefiscal,
            "conduc_nom": self._clean(src.get("conduc_nom") or src.get("ConducNom")),
            "conduc_dni": self._clean(src.get("conduc_dni") or src.get("Conducdni")),
            "conduc_codpost": self._clean(src.get("conduc_codpost") or src.get("ConducCodpost")),
            "conduc_adr": self._clean(src.get("conduc_adr") or src.get("ConducAdr")),
            "texp": self._to_int(src.get("texp") or src.get("TExp"), 0),
            "matricula": matricula,
            "matricula2": self._clean(src.get("matricula2") or src.get("Matricula2")),
            "matricula3": self._clean(src.get("matricula3") or src.get("Matricula3")),
            "expone": expone,
            "solicita": solicita,
            "archivos": list(src.get("archivos") or []),
            "headless": bool(src.get("headless", True)),
            "payload": payload,
        }

    def create_target(self, **kwargs: Any) -> ValenciaTarget:
        raw_payload = self._enrich_from_nested_and_canonical(self._payload_dict(kwargs.get("payload")))
        merged = dict(raw_payload)
        merged.update(kwargs)
        merged = self._enrich_from_nested_and_canonical(merged)
        id_recurso = kwargs.get("idRecurso") or raw_payload.get("idRecurso")
        id_exp = kwargs.get("idExp") or raw_payload.get("idExp")
        expediente = self._clean(
            kwargs.get("expediente")
            or raw_payload.get("expediente")
            or raw_payload.get("Expedient")
            or kwargs.get("expediente_num")
            or raw_payload.get("expediente_num")
            or kwargs.get("num_expediente")
            or raw_payload.get("num_expediente")
            or kwargs.get("denuncia_num")
            or raw_payload.get("denuncia_num")
            or kwargs.get("num_denuncia")
            or raw_payload.get("num_denuncia")
            or kwargs.get("nExp")
            or raw_payload.get("nExp")
        )
        fase_procedimiento = self._clean(kwargs.get("fase_procedimiento") or raw_payload.get("fase_procedimiento") or raw_payload.get("FaseProcedimiento"))
        inferred_tipo, inferred_code = self._infer_tramite(fase_procedimiento)
        tramite_tipo = self._clean(kwargs.get("tramite_tipo") or raw_payload.get("tramite_tipo")) or inferred_tipo
        tramite_code = self._clean(kwargs.get("tramite_code") or raw_payload.get("tramite_code")) or inferred_code
        nombre = self._clean(
            kwargs.get("nombre")
            or raw_payload.get("nombre")
            or raw_payload.get("Nombre")
            or raw_payload.get("cliente_nombre")
            or raw_payload.get("name")
            or raw_payload.get("SujetoRecurso")
        )
        apellido1 = self._clean(kwargs.get("apellido1") or raw_payload.get("apellido1") or raw_payload.get("Apellido1") or raw_payload.get("cliente_apellido1"))
        apellido2 = self._clean(kwargs.get("apellido2") or raw_payload.get("apellido2") or raw_payload.get("Apellido2") or raw_payload.get("cliente_apellido2"))
        nombrefiscal = self._clean(kwargs.get("nombrefiscal") or raw_payload.get("nombrefiscal") or raw_payload.get("Nombrefiscal") or raw_payload.get("cliente_razon_social"))
        tipodecliente = self._clean(kwargs.get("tipodecliente") or raw_payload.get("tipodecliente") or raw_payload.get("cliente_tipo"))
        nif = self._clean(kwargs.get("nif") or raw_payload.get("nif") or raw_payload.get("cliente_nif"))
        nifempresa = self._clean(kwargs.get("nifempresa") or raw_payload.get("nifempresa") or raw_payload.get("cliente_nif_empresa"))
        conduc_nom = self._clean(kwargs.get("conduc_nom") or raw_payload.get("conduc_nom") or raw_payload.get("ConducNom"))
        conduc_dni = self._clean(kwargs.get("conduc_dni") or raw_payload.get("conduc_dni") or raw_payload.get("Conducdni"))
        conduc_codpost = self._clean(kwargs.get("conduc_codpost") or raw_payload.get("conduc_codpost") or raw_payload.get("ConducCodpost"))
        conduc_adr = self._clean(kwargs.get("conduc_adr") or raw_payload.get("conduc_adr") or raw_payload.get("ConducAdr"))
        matricula = self._resolve_matricula(
            kwargs.get("matricula"),
            raw_payload.get("matricula"),
            raw_payload.get("Matricula"),
            raw_payload.get("plate_number"),
            kwargs.get("matricula2"),
            raw_payload.get("matricula2"),
            raw_payload.get("Matricula2"),
            kwargs.get("matricula3"),
            raw_payload.get("matricula3"),
            raw_payload.get("Matricula3"),
        )
        matricula2 = self._clean(kwargs.get("matricula2") or raw_payload.get("matricula2") or raw_payload.get("Matricula2"))
        matricula3 = self._clean(kwargs.get("matricula3") or raw_payload.get("matricula3") or raw_payload.get("Matricula3"))
        merged = self._sync_payload_matricula(merged, matricula)
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
