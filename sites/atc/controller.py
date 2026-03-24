from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.contact_defaults import get_default_contact_email, get_default_contact_mobile

from .config import AtcConfig
from .data_models import AtcDocumento, AtcTarget


class AtcController:
    site_id = "atc"
    display_name = "ATC Gencat"

    _CLIENTES_BLOQUEADOS = {13607, 14274}
    _REA_RE = re.compile(r"(RECLAMACION\s+(ECONOMICO|ECO)[- ]*(ADMINISTRATIVA|ADVA)|(?<!\w)REA(?!\w))", re.IGNORECASE)
    _REPOS_RE = re.compile(r"(RECURSO\s+(EXTRAORDINARIO|REVISION|DE\s+REPOSICION)|(?<!\w)REPOSICION(?!\w))", re.IGNORECASE)
    _EXPEDIENT_PATTERNS = (
        re.compile(r"\b\d{14}\b"),                         # 20250001462212
        re.compile(r"\b\d{5,}-\d{4}/\d{1,10}-[A-Z]{2,5}\b", re.IGNORECASE),
        re.compile(r"\b\d-\d{4}/\d{1,10}-[A-Z]{2,5}\b", re.IGNORECASE),
        re.compile(r"\b\d{4}/\d{6,}\b"),
    )

    def create_config(self, *, headless: bool):
        cfg = AtcConfig()
        cfg.navegador.headless = bool(headless)
        return cfg

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _to_int(value: Any) -> int | None:
        try:
            return int(str(value or "").strip())
        except Exception:
            return None

    @classmethod
    def _norm(cls, value: Any) -> str:
        txt = cls._clean(value).lower()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return " ".join(txt.split())

    @classmethod
    def _sanitize_doc(cls, value: Any) -> str:
        return re.sub(r"[^A-Z0-9]+", "", cls._clean(value).upper())

    @classmethod
    def _is_empresa_tipodecliente(cls, value: Any) -> bool | None:
        raw = cls._clean(value)
        if raw == "2":
            return True
        if raw == "1":
            return False
        return None

    @classmethod
    def _normalize_expediente(cls, value: Any) -> str:
        raw = cls._clean(value)
        if not raw:
            return ""
        text = " ".join(raw.split())
        for rx in cls._EXPEDIENT_PATTERNS:
            m = rx.search(text)
            if m:
                return m.group(0).strip()
        # ATC: a veces llega "expediente + segunda parte", conservar solo la primera.
        return text.split(" ", 1)[0].strip()

    @classmethod
    def _infer_protocol(cls, *, csv_acto: str, procedim: str) -> str:
        if not csv_acto:
            return "registro_sin_csv"
        if cls._REA_RE.search(procedim or ""):
            return "rea"
        if cls._REPOS_RE.search(procedim or ""):
            return "reposicio"
        return "reposicio"

    @classmethod
    def _parse_date(cls, value: Any) -> date | None:
        raw = cls._clean(value)
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(raw.split("+")[0], fmt).date()
            except Exception:
                continue
        return None

    @classmethod
    def _build_nombre_representado(cls, src: dict[str, Any]) -> str:
        juridica = cls._clean(src.get("Nombrefiscal") or src.get("cliente_razon_social"))
        if juridica:
            return juridica
        nombre = cls._clean(src.get("Nombre") or src.get("cliente_nombre") or src.get("SujetoRecurso"))
        apellido1 = cls._clean(src.get("Apellido1") or src.get("cliente_apellido1"))
        apellido2 = cls._clean(src.get("Apellido2") or src.get("cliente_apellido2"))
        return " ".join([part for part in [nombre, apellido1, apellido2] if part]).strip()

    @classmethod
    def _build_documentos(cls, src: dict[str, Any], protocol: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        docs_raw = src.get("documentos")
        if isinstance(docs_raw, list):
            for item in docs_raw:
                if not isinstance(item, dict):
                    continue
                fitxer = cls._clean(item.get("fitxer") or item.get("path"))
                if not fitxer:
                    continue
                key = str(Path(fitxer))
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "fitxer": fitxer,
                        "tipus": cls._clean(item.get("tipus")),
                        "descripcio": cls._clean(item.get("descripcio")),
                    }
                )

        archivos = src.get("archivos") or []
        for file_path in archivos:
            p = cls._clean(file_path)
            if not p:
                continue
            key = str(Path(p))
            if key in seen:
                continue
            seen.add(key)
            idx = len(out)
            if protocol == "rea":
                default_tipus = "Al-legacions" if idx == 0 else "Documentacio acreditativa"
            elif protocol == "reposicio":
                default_tipus = "Documentacio acreditativa si escau"
            else:
                default_tipus = "Otros"
            out.append({"fitxer": p, "tipus": default_tipus, "descripcio": Path(p).stem[:80] or "Documento"})
        return out

    @classmethod
    def _default_alegaciones(cls, expediente: str) -> str:
        exp = expediente or "N/A"
        return f"Se formulan alegaciones en relacion con el expediente {exp} y se solicita su estimacion."

    @classmethod
    def _build_phase_text(cls, src: dict[str, Any], expediente: str) -> str:
        asunto = cls._clean(src.get("asunto"))
        expone = cls._clean(src.get("expone"))
        solicita = cls._clean(src.get("solicita"))

        if not asunto:
            asunto = f"Aportacion de documentacion expediente {expediente or 'N/A'}"
        if not expone:
            expone = f"Se formulan alegaciones en relacion con el expediente {expediente or 'N/A'}."
        if not solicita:
            solicita = "Se solicita la estimacion de las alegaciones y la admision de la documentacion aportada."

        parts = [
            f"ASUNTO: {asunto}",
            f"EXPONE: {expone}",
            f"SOLICITA: {solicita}",
        ]
        return "\n\n".join(parts).strip()

    @classmethod
    def _resolve_organo_from_phase(cls, src: dict[str, Any]) -> str:
        fase_raw = cls._clean(src.get("fase_procedimiento") or src.get("FaseProcedimiento"))
        fase = cls._norm(fase_raw)
        if not fase:
            return cls._clean(src.get("organo")) or "Oficina Central de Gestion Tributaria"
        if any(token in fase for token in ("apremio", "embargo", "recaudacion")):
            return "Oficina Central de Recaudacion"
        if "inspeccion" in fase:
            return "Oficina Central de Inspeccion"
        return "Oficina Central de Gestion Tributaria"

    def map_data(self, data: dict) -> dict:
        src = dict(data or {})
        expediente = self._normalize_expediente(src.get("expediente") or src.get("Expedient"))
        csv_acto = self._clean(src.get("csv_acto") or src.get("ExpedientePublicacion"))
        procedim = self._clean(src.get("procedim") or src.get("Procedim"))
        protocol = self._clean(src.get("protocol")) or self._infer_protocol(csv_acto=csv_acto, procedim=procedim)
        tipodecliente = self._clean(src.get("tipodecliente"))
        es_empresa = self._is_empresa_tipodecliente(tipodecliente)
        nombre_juridico = self._clean(src.get("Nombrefiscal") or src.get("cliente_razon_social"))
        nombre_persona = " ".join(
            [
                part
                for part in [
                    self._clean(src.get("Nombre") or src.get("cliente_nombre") or src.get("SujetoRecurso")),
                    self._clean(src.get("Apellido1") or src.get("cliente_apellido1")),
                    self._clean(src.get("Apellido2") or src.get("cliente_apellido2")),
                ]
                if part
            ]
        ).strip()
        nif_empresa = self._sanitize_doc(src.get("nifempresa") or src.get("cliente_nif_empresa"))
        nif_persona = self._sanitize_doc(src.get("nif") or src.get("cliente_nif"))
        if es_empresa is True:
            nombre_repr = nombre_juridico or nombre_persona
            nif_repr = nif_empresa or nif_persona
        elif es_empresa is False:
            nombre_repr = nombre_persona or nombre_juridico
            nif_repr = nif_persona or nif_empresa
        else:
            nombre_repr = self._build_nombre_representado(src)
            nif_repr = self._sanitize_doc(src.get("nifempresa") or src.get("nif") or src.get("cliente_nif_empresa") or src.get("cliente_nif"))
        phase_text = self._build_phase_text(src, expediente)
        alegaciones = phase_text or self._clean(src.get("alegaciones")) or self._default_alegaciones(expediente)
        email = self._clean(src.get("email")) or get_default_contact_email()
        telefono = self._clean(src.get("telefono")) or get_default_contact_mobile()
        organo = self._resolve_organo_from_phase(src)

        return {
            "idRecurso": src.get("idRecurso"),
            "idExp": src.get("idExp") or src.get("IdExp"),
            "numclient": self._to_int(src.get("numclient")),
            "expediente": expediente,
            "procedim": procedim,
            "protocol": protocol,
            "csv_acto": csv_acto,
            "representado_nif": nif_repr,
            "representado_nombre": nombre_repr,
            "alegaciones": alegaciones[:1000],
            "motivo_reposicion": self._clean(src.get("motivo_reposicion")) or "Altres motius diferents dels anteriors.",
            "block_until_date": self._parse_date(src.get("fecpres")),
            "tipo_tramite": self._clean(src.get("tipo_tramite")) or "Aporte de documentos",
            "tipo_documento": self._clean(src.get("tipo_documento")) or "Expediente",
            "impuesto": self._clean(src.get("impuesto")) or "Impuesto sobre sucesiones y donaciones",
            "num_documento": self._clean(src.get("num_documento")) or expediente,
            "email": email,
            "telefono": telefono,
            "nif_interesado": self._sanitize_doc(src.get("nif_interesado") or nif_repr),
            "nombre_interesado": self._clean(src.get("nombre_interesado")) or nombre_repr,
            "organo": organo,
            "asunto": self._clean(src.get("asunto")) or f"Aportacion de documentacion expediente {expediente or 'N/A'}",
            "documentos": self._build_documentos(src, protocol),
            "archivos": list(src.get("archivos") or []),
            "headless": bool(src.get("headless", True)),
            "payload": dict(src),
        }

    def create_target(self, **kwargs: Any) -> AtcTarget:
        numclient = self._to_int(kwargs.get("numclient"))
        block_until = kwargs.get("block_until_date")
        if (
            numclient in self._CLIENTES_BLOQUEADOS
            and isinstance(block_until, date)
            and date.today() < block_until
        ):
            raise ValueError(
                f"atc: recurso bloqueado por regla de cliente {numclient} hasta {block_until.isoformat()}."
            )

        archivos = kwargs.get("archivos") or []
        documentos_raw = kwargs.get("documentos") or []
        documentos: list[AtcDocumento] = []
        for doc in documentos_raw:
            if not isinstance(doc, dict):
                continue
            fitxer = self._clean(doc.get("fitxer"))
            if not fitxer:
                continue
            documentos.append(
                AtcDocumento(
                    fitxer=Path(fitxer),
                    tipus=self._clean(doc.get("tipus")),
                    descripcio=self._clean(doc.get("descripcio")),
                )
            )

        raw_payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
        merged_payload: dict[str, Any] = dict(raw_payload)
        for key, value in kwargs.items():
            if key == "payload":
                continue
            merged_payload[key] = value

        return AtcTarget(
            idRecurso=kwargs.get("idRecurso"),
            idExp=kwargs.get("idExp"),
            numclient=numclient,
            expediente=str(kwargs.get("expediente") or ""),
            procedim=self._clean(kwargs.get("procedim")),
            protocol=self._clean(kwargs.get("protocol")) or "reposicio",
            csv_acto=self._clean(kwargs.get("csv_acto")),
            representado_nif=self._sanitize_doc(kwargs.get("representado_nif")),
            representado_nombre=self._clean(kwargs.get("representado_nombre")),
            alegaciones=self._clean(kwargs.get("alegaciones"))[:1000],
            motivo_reposicion=self._clean(kwargs.get("motivo_reposicion")) or "Altres motius diferents dels anteriors.",
            block_until_date=block_until if isinstance(block_until, date) else None,
            tipo_tramite=self._clean(kwargs.get("tipo_tramite")) or "Aporte de documentos",
            tipo_documento=self._clean(kwargs.get("tipo_documento")) or "Expediente",
            impuesto=self._clean(kwargs.get("impuesto")) or "Impuesto sobre sucesiones y donaciones",
            num_documento=self._clean(kwargs.get("num_documento")) or self._clean(kwargs.get("expediente")),
            email=self._clean(kwargs.get("email")) or get_default_contact_email(),
            telefono=self._clean(kwargs.get("telefono")) or get_default_contact_mobile(),
            nif_interesado=self._sanitize_doc(kwargs.get("nif_interesado")),
            nombre_interesado=self._clean(kwargs.get("nombre_interesado")),
            organo=self._clean(kwargs.get("organo")) or "Oficina Central de Gestion Tributaria",
            asunto=self._clean(kwargs.get("asunto")) or f"Aportacion de documentacion expediente {self._clean(kwargs.get('expediente'))}",
            documentos=documentos,
            archivos_adjuntos=[Path(str(p)) for p in archivos],
            payload=merged_payload,
            headless=bool(kwargs.get("headless", True)),
        )


def get_controller() -> AtcController:
    return AtcController()
