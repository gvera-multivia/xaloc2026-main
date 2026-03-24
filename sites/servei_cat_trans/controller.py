from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from .config import ServeiCatTransConfig
from .data_models import ServeiCatTransTarget


class ServeiCatTransController:
    site_id = "servei_cat_trans"
    display_name = "Servei Cat Trans"

    def create_config(self, *, headless: bool):
        cfg = ServeiCatTransConfig()
        cfg.navegador.headless = bool(headless)
        return cfg

    @staticmethod
    def _clean(v: Any) -> str:
        return str(v or "").strip()

    @classmethod
    def _norm(cls, v: Any) -> str:
        txt = cls._clean(v).lower()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return re.sub(r"[^a-z0-9]+", " ", txt).strip()

    @classmethod
    def _sanitize_document(cls, v: Any) -> str:
        return re.sub(r"[^A-Z0-9]+", "", cls._clean(v).upper())

    @classmethod
    def _infer_tipo_escrito(cls, fase: str) -> str:
        norm = cls._norm(fase)
        if "extraordin" in norm and "revis" in norm:
            return "revision"
        if "reposicion" in norm:
            return "reposicion"
        return "alegaciones"

    @classmethod
    def _split_expediente(cls, expediente: str) -> tuple[str, str, str]:
        raw = cls._clean(expediente)
        if not raw:
            return "", "", ""

        match = re.search(r"(\d{2})[/-](\d{7,10})-(\d{1,2})", raw)
        if match:
            return match.group(1), match.group(2), match.group(3)

        digits = re.findall(r"\d+", raw)
        if len(digits) >= 3:
            return digits[0][-2:], digits[1], digits[2]
        return "", "", ""

    @classmethod
    def _infer_document_type_persona(cls, document: str) -> str:
        doc = cls._sanitize_document(document)
        if re.fullmatch(r"\d{8}[A-Z]", doc):
            return "DNI"
        if re.fullmatch(r"[XYZ]\d{7}[A-Z]", doc):
            return "NIE"
        if doc:
            return "Pasaporte"
        return "DNI"

    @classmethod
    def _infer_document_type_empresa(cls, document: str) -> str:
        doc = cls._sanitize_document(document)
        if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", doc):
            return "NIF de empresa"
        if doc:
            return "Documento de identidad extranjero"
        return "NIF de empresa"

    @classmethod
    def _fallback_expone(cls, expediente: str) -> str:
        return f"Se presenta escrito relacionado con el expediente {expediente}."

    @classmethod
    def _fallback_solicita(cls, expediente: str) -> str:
        return f"Se solicita la admision y tramitacion del expediente {expediente}."

    def map_data(self, data: dict) -> dict:
        src = dict(data or {})
        expediente = self._clean(src.get("expediente") or src.get("Expedient"))
        servicio, expediente_num, digito = self._split_expediente(expediente)

        tipodecliente = self._clean(src.get("tipodecliente"))
        is_company = tipodecliente == "2" or bool(self._clean(src.get("nifempresa")))
        tipo_persona = "juridica" if is_company else "fisica"

        nombre = self._clean(src.get("nombre") or src.get("Nombre") or src.get("SujetoRecurso"))
        apellido1 = self._clean(src.get("apellido1") or src.get("Apellido1"))
        apellido2 = self._clean(src.get("apellido2") or src.get("Apellido2"))
        nif_persona = self._sanitize_document(src.get("nif"))
        razon_social = self._clean(src.get("razon_social") or src.get("Nombrefiscal") or src.get("SujetoRecurso"))
        nif_empresa = self._sanitize_document(src.get("nifempresa"))

        fase = self._clean(src.get("fase_procedimiento") or src.get("FaseProcedimiento"))
        tipo_escrito = self._clean(src.get("tipo_escrito")) or self._infer_tipo_escrito(fase)
        expongo = self._clean(src.get("expongo")) or self._fallback_expone(expediente)
        solicita = self._clean(src.get("solicito")) or self._fallback_solicita(expediente)
        email = self._clean(src.get("email")) or get_default_contact_email()
        telefono = self._clean(src.get("telefono_movil") or src.get("telefono")) or get_default_contact_mobile()

        direccion = self._clean(src.get("direccion") or src.get("ConducAdr"))
        cp = self._clean(src.get("direccion_cp") or src.get("ConducCodpost"))
        numero = self._clean(src.get("direccion_numero"))
        if not numero and direccion:
            num_match = re.search(r"\d+", direccion)
            if num_match:
                numero = num_match.group(0)

        archivos = src.get("archivos") or src.get("archivos_adjuntos") or []
        if isinstance(archivos, str):
            archivos = [archivos]

        return {
            "idRecurso": src.get("idRecurso"),
            "idExp": src.get("idExp") or src.get("IdExp"),
            "numclient": src.get("numclient"),
            "expediente": expediente,
            "servicio_territorial": servicio,
            "expediente_numero": expediente_num,
            "digito_control": digito,
            "codigo_personal": self._clean(src.get("codigo_personal")) or self._clean(src.get("idRecurso")),
            "tipo_persona": tipo_persona,
            "nombre": nombre,
            "apellido1": apellido1,
            "apellido2": apellido2,
            "nif": nif_persona,
            "razon_social": razon_social,
            "nif_empresa": nif_empresa,
            "documento_solicitante_tipo": self._infer_document_type_persona(nif_persona),
            "documento_empresa_tipo": self._infer_document_type_empresa(nif_empresa),
            "email": email,
            "telefono_movil": telefono,
            "direccion_tipo_via": self._clean(src.get("direccion_tipo_via")),
            "direccion_nombre_via": self._clean(src.get("direccion_nombre_via")) or direccion,
            "direccion_numero": numero,
            "direccion_cp": cp,
            "direccion_provincia": self._clean(src.get("direccion_provincia") or "Barcelona"),
            "direccion_comarca": self._clean(src.get("direccion_comarca")),
            "direccion_municipio": self._clean(src.get("direccion_municipio")),
            "representado_tipo_via": self._clean(src.get("representado_tipo_via")),
            "representado_nombre_via": self._clean(src.get("representado_calle") or src.get("representado_calle_raw")),
            "representado_numero": self._clean(src.get("representado_numero") or src.get("representado_numero_raw")),
            "representado_cp": self._clean(src.get("representado_cp")),
            "representado_provincia": self._clean(src.get("representado_provincia")),
            "representado_comarca": self._clean(src.get("representado_comarca")),
            "representado_municipio": self._clean(src.get("representado_municipio") or src.get("representado_poblacion")),
            "tipo_escrito": tipo_escrito,
            "expongo": expongo,
            "solicito": solicita,
            "archivos": list(archivos),
            "acreditacion_path": self._clean(src.get("acreditacion_path")),
            "headless": bool(src.get("headless", True)),
            "payload": dict(src),
        }

    def create_target(self, **kwargs) -> ServeiCatTransTarget:
        archivos = kwargs.get("archivos") or []
        if isinstance(archivos, str):
            archivos = [archivos]

        payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
        merged_payload = dict(payload)
        for key, value in kwargs.items():
            if key == "payload":
                continue
            merged_payload[key] = value

        direccion_tipo_via = self._clean(kwargs.get("direccion_tipo_via")) or "Ronda"
        direccion_nombre_via = self._clean(kwargs.get("direccion_nombre_via")) or "DEL GENERAL MITRE"
        direccion_numero = self._clean(kwargs.get("direccion_numero")) or "169"
        direccion_cp = self._clean(kwargs.get("direccion_cp")) or "08022"
        direccion_provincia = self._clean(kwargs.get("direccion_provincia")) or "Barcelona"
        direccion_comarca = self._clean(kwargs.get("direccion_comarca")) or "Barcelon\u00e8s"
        direccion_municipio = self._clean(kwargs.get("direccion_municipio")) or "BARCELONA"

        return ServeiCatTransTarget(
            idRecurso=kwargs.get("idRecurso"),
            idExp=kwargs.get("idExp"),
            numclient=kwargs.get("numclient"),
            expediente=str(kwargs.get("expediente") or ""),
            servicio_territorial=self._clean(kwargs.get("servicio_territorial")),
            expediente_numero=self._clean(kwargs.get("expediente_numero")),
            digito_control=self._clean(kwargs.get("digito_control")),
            codigo_personal=self._clean(kwargs.get("codigo_personal")),
            tipo_persona=self._clean(kwargs.get("tipo_persona")) or "fisica",
            nombre=self._clean(kwargs.get("nombre")),
            apellido1=self._clean(kwargs.get("apellido1")),
            apellido2=self._clean(kwargs.get("apellido2")),
            nif=self._sanitize_document(kwargs.get("nif")),
            razon_social=self._clean(kwargs.get("razon_social")),
            nif_empresa=self._sanitize_document(kwargs.get("nif_empresa")),
            email=self._clean(kwargs.get("email")) or get_default_contact_email(),
            telefono_movil=self._clean(kwargs.get("telefono_movil")) or get_default_contact_mobile(),
            direccion_tipo_via=direccion_tipo_via,
            direccion_nombre_via=direccion_nombre_via,
            direccion_numero=direccion_numero,
            direccion_cp=direccion_cp,
            direccion_provincia=direccion_provincia,
            direccion_comarca=direccion_comarca,
            direccion_municipio=direccion_municipio,
            representado_tipo_via=self._clean(kwargs.get("representado_tipo_via")),
            representado_nombre_via=self._clean(kwargs.get("representado_nombre_via")),
            representado_numero=self._clean(kwargs.get("representado_numero")),
            representado_cp=self._clean(kwargs.get("representado_cp")),
            representado_provincia=self._clean(kwargs.get("representado_provincia")),
            representado_comarca=self._clean(kwargs.get("representado_comarca")),
            representado_municipio=self._clean(kwargs.get("representado_municipio")),
            tipo_escrito=self._clean(kwargs.get("tipo_escrito")) or "alegaciones",
            expongo=self._clean(kwargs.get("expongo")),
            solicito=self._clean(kwargs.get("solicito")),
            archivos_para_subir=[Path(str(p)) for p in archivos if str(p).strip()],
            payload=merged_payload,
            headless=bool(kwargs.get("headless", True)),
        )


def get_controller() -> ServeiCatTransController:
    return ServeiCatTransController()
