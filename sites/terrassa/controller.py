from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import TerrassaConfig
from .data_models import TerrassaTarget


class TerrassaController:
    site_id = "terrassa"
    display_name = "Terrassa Ayuntamiento"

    _GENERIC_DESC = {"", "documento", "document"}
    _GENERIC_TIPUS = {"", "al legacio", "allegacio", "allegacio"}

    def create_config(self, *, headless: bool):
        cfg = TerrassaConfig()
        cfg.navegador.headless = bool(headless)
        return cfg

    @staticmethod
    def _clean(v: object) -> str:
        return str(v or "").strip()

    @classmethod
    def _norm(cls, v: object) -> str:
        txt = cls._clean(v).lower()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return re.sub(r"[^a-z0-9]+", " ", txt).strip()

    @classmethod
    def _infer_tipus_and_desc(cls, file_path: Path) -> tuple[str, str]:
        name = cls._norm(file_path.name)

        # Prioridad absoluta: el recurso principal de XVIA debe ir como alegacion.
        if "recurso exp" in name or "recurso" in name:
            return "Al-legacio", "Recurso"

        rules = [
            (("autoriz", "autoriza"), ("Autoritzacio", "Autorizacion")),
            (("dni", "nif", "document nacional"), ("Document Nacional Identitat - NIF", "Documento identidad")),
            (("nie", "identitat estranger"), ("Document Identitat Estranger - NIE", "Documento NIE")),
            (("carnet", "permiso conducir", "carnet conducir", "licencia conducir"), ("Carnet", "Carnet conducir")),
            (("escritura",), ("Escriptura", "Escritura")),
            (("certificat", "certificado"), ("Certificat", "Certificado")),
            (("contracte", "contrato"), ("Contracte", "Contrato")),
            (("conveni", "convenio"), ("Conveni", "Convenio")),
            (("factura",), ("Factura", "Factura")),
            (("justificant", "justificante"), ("Justificant", "Justificante")),
            (("memoria",), ("Memoria", "Memoria")),
            (("notificacio", "notificacion"), ("Notificacio", "Notificacion")),
            (("plano", "planol"), ("Planol", "Plano")),
            (("poder notarial", "poderes notariales", "poders notarials"), ("Poders notarials", "Poderes notariales")),
            (("pressupost", "presupuesto"), ("Pressupost", "Presupuesto")),
            (("projecte", "proyecto"), ("Projecte", "Proyecto")),
            (("resolucio", "resolucion"), ("Resolucio", "Resolucion")),
            (("sentencia",), ("Sentencia", "Sentencia")),
            (("informe",), ("Informe", "Informe")),
            (("fotografia", "foto"), ("Fotografia", "Fotografia")),
            (("curriculum",), ("Curriculum", "Curriculum")),
        ]

        for needles, mapped in rules:
            if any(n in name for n in needles):
                return mapped[0], mapped[1]

        return "Al-legacio", (file_path.stem[:70] or "Documento")

    def map_data(self, data: dict) -> dict:
        src = dict(data or {})
        return {
            "idRecurso": src.get("idRecurso"),
            "idExp": src.get("idExp"),
            "numclient": src.get("numclient"),
            "expediente": src.get("expediente") or src.get("Expedient"),
            "is_company": bool(src.get("is_company")),
            "document_type_value": src.get("document_type_value") or src.get("tipus_document_value"),
            "document_number": src.get("document_number") or src.get("nif"),
            "nombre": src.get("nombre") or src.get("name") or src.get("sujeto_recurso"),
            "apellido1": src.get("apellido1"),
            "apellido2": src.get("apellido2"),
            "fecha_infraccion": src.get("fecha_infraccion") or src.get("data_infraccion") or src.get("FAlta"),
            "matricula": src.get("matricula") or src.get("plate_number"),
            "marca": src.get("marca") or "Otros",
            "alegaciones": src.get("alegaciones") or src.get("motivos") or src.get("expone"),
            "observaciones": src.get("observaciones") or src.get("solicita"),
            "documentos": src.get("documentos") or [],
            "archivos": src.get("archivos") or src.get("archivos_adjuntos") or [],
            "headless": src.get("headless", True),
            "fase_procedimiento": src.get("fase_procedimiento") or "",
            "sujeto_recurso": src.get("sujeto_recurso") or src.get("SujetoRecurso") or "",
        }

    def create_target(
        self,
        *,
        idRecurso: int | None = None,
        idExp: int | None = None,
        numclient: int | None = None,
        expediente: str | None = None,
        is_company: bool = False,
        document_type_value: str | None = None,
        document_number: str | None = None,
        nombre: str | None = None,
        apellido1: str | None = None,
        apellido2: str | None = None,
        fecha_infraccion: str | None = None,
        matricula: str | None = None,
        marca: str | None = None,
        alegaciones: str | None = None,
        observaciones: str | None = None,
        documentos: list[dict] | None = None,
        archivos: list[Path] | list[str] | None = None,
        headless: bool = True,
        fase_procedimiento: str | None = None,
        sujeto_recurso: str | None = None,
        **kwargs,
    ) -> TerrassaTarget:
        def _req(name: str, value: str | None) -> str:
            text = str(value or "").strip()
            if not text:
                raise ValueError(f"terrassa: falta '{name}'.")
            return text

        archivos_raw = archivos or kwargs.get("archivos") or []
        archivos_norm = [Path(str(p)) for p in archivos_raw if str(p).strip()]
        if not archivos_norm:
            raise ValueError("terrassa: falta el recurso principal de XVIA (obligatorio).")

        documentos_raw = documentos or kwargs.get("documentos") or []
        provided_docs: dict[str, dict[str, str]] = {}
        for item in documentos_raw:
            if not isinstance(item, dict):
                continue
            fitxer = str(item.get("fitxer") or "").strip()
            if not fitxer:
                continue
            key = str(Path(fitxer))
            provided_docs[key] = {
                "descripcio": str(item.get("descripcio") or "").strip(),
                "tipus": str(item.get("tipus") or "").strip(),
            }

        # Merge obligatorio: recurso XVIA + adjuntos + documentacion cliente.
        merged_paths: list[Path] = []
        seen: set[str] = set()
        for p in archivos_norm:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            merged_paths.append(p)
        for key in provided_docs.keys():
            p = Path(key)
            if key in seen:
                continue
            if not p.exists():
                continue
            seen.add(key)
            merged_paths.append(p)

        documentos_final: list[dict[str, str]] = []
        resource_main_key = str(archivos_norm[0]) if archivos_norm else ""
        for p in merged_paths:
            key = str(p)
            provided = provided_docs.get(key, {})
            p_desc = str(provided.get("descripcio") or "").strip()
            p_tipus = str(provided.get("tipus") or "").strip()

            if key == resource_main_key:
                # Regla de negocio: el recurso principal SIEMPRE se sube como alegacion.
                final_tipus = "Al-legacio"
                final_desc = "Recurso"
            else:
                infer_tipus, infer_desc = self._infer_tipus_and_desc(p)
                final_tipus = infer_tipus if self._norm(p_tipus) in self._GENERIC_TIPUS else (p_tipus or infer_tipus)
                final_desc = infer_desc if self._norm(p_desc) in self._GENERIC_DESC else (p_desc or infer_desc)

            documentos_final.append(
                {
                    "fitxer": str(p),
                    "descripcio": final_desc[:70] or "Documento",
                    "tipus": final_tipus or "Al-legacio",
                }
            )

        return TerrassaTarget(
            idRecurso=idRecurso,
            idExp=idExp,
            numclient=numclient,
            expediente=_req("expediente", expediente),
            is_company=bool(is_company),
            document_type_value=str(document_type_value or "1"),
            document_number=_req("document_number", document_number),
            nombre=_req("nombre", nombre),
            apellido1=str(apellido1 or "").strip(),
            apellido2=str(apellido2 or "").strip(),
            fecha_infraccion=_req("fecha_infraccion", fecha_infraccion),
            matricula=_req("matricula", matricula),
            marca=str(marca or "Otros").strip() or "Otros",
            alegaciones=_req("alegaciones", alegaciones),
            observaciones=_req("observaciones", observaciones),
            documentos=documentos_final,
            archivos_para_subir=merged_paths,
            payload={
                "idRecurso": idRecurso,
                "idExp": idExp,
                "numclient": numclient,
                "expediente": expediente,
                "is_company": is_company,
                "document_type_value": document_type_value,
                "document_number": document_number,
                "nombre": nombre,
                "apellido1": apellido1,
                "apellido2": apellido2,
                "fecha_infraccion": fecha_infraccion,
                "matricula": matricula,
                "marca": marca,
                "alegaciones": alegaciones,
                "observaciones": observaciones,
                "documentos": documentos_final,
                "archivos": [str(p) for p in merged_paths],
                "headless": headless,
                "fase_procedimiento": fase_procedimiento or "",
                "sujeto_recurso": sujeto_recurso or "",
                **kwargs,
            },
            headless=bool(headless),
            fase_procedimiento=str(fase_procedimiento or "").strip(),
            sujeto_recurso=str(sujeto_recurso or "").strip(),
        )


def get_controller() -> TerrassaController:
    return TerrassaController()
