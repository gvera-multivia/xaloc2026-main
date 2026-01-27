from __future__ import annotations

import logging
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


class RequiredClientDocumentsError(RuntimeError):
    """No se han podido localizar/adjuntar los documentos obligatorios del cliente."""


@dataclass(frozen=True)
class ClientIdentity:
    is_company: bool
    empresa: str | None = None
    nombre: str | None = None
    apellido1: str | None = None
    apellido2: str | None = None


def client_identity_from_payload(payload: dict) -> ClientIdentity:
    """
    Intenta construir la identidad del cliente a partir del payload del worker.

    Soporta principalmente el formato actual de `xaloc_task.py`:
      payload["mandatario"] = { tipo_persona, razon_social | nombre/apellidos, ... }
    """
    mandatario = payload.get("mandatario") or {}
    if isinstance(mandatario, dict) and (mandatario.get("tipo_persona") or "").strip():
        tipo = str(mandatario.get("tipo_persona")).strip().upper()
        if tipo == "JURIDICA":
            empresa = (mandatario.get("razon_social") or "").strip()
            if not empresa:
                raise RequiredClientDocumentsError("mandatario.tipo_persona=JURIDICA pero falta mandatario.razon_social.")
            return ClientIdentity(is_company=True, empresa=empresa)
        if tipo == "FISICA":
            nombre = (mandatario.get("nombre") or "").strip()
            ap1 = (mandatario.get("apellido1") or "").strip()
            ap2 = (mandatario.get("apellido2") or "").strip()
            if not (nombre and ap1 and ap2):
                raise RequiredClientDocumentsError(
                    "mandatario.tipo_persona=FISICA pero falta mandatario.nombre/apellido1/apellido2."
                )
            return ClientIdentity(is_company=False, nombre=nombre, apellido1=ap1, apellido2=ap2)

    # Fallbacks (formatos alternativos). Si faltan, forzamos error para mantener "obligatorio".
    empresa = (payload.get("empresa") or payload.get("Empresa") or payload.get("company_name") or "").strip()
    if empresa:
        return ClientIdentity(is_company=True, empresa=empresa)

    # También puede venir como "rao_social"/"razon_social" en otros sites/controladores
    empresa_alt = (
        payload.get("rao_social")
        or payload.get("razon_social")
        or payload.get("p2_rao_social")
        or payload.get("notif_razon_social")
        or ""
    )
    if str(empresa_alt).strip():
        return ClientIdentity(is_company=True, empresa=str(empresa_alt).strip())

    nombre = (payload.get("cliente_nombre") or "").strip()
    ap1 = (payload.get("cliente_apellido1") or payload.get("surname1") or payload.get("apellido1") or "").strip()
    ap2 = (payload.get("cliente_apellido2") or payload.get("surname2") or payload.get("apellido2") or "").strip()
    if nombre and ap1 and ap2:
        return ClientIdentity(is_company=False, nombre=nombre, apellido1=ap1, apellido2=ap2)

    # Último fallback: nombre completo en un único campo (p.ej. "NOMBRE APELLIDO1 APELLIDO2")
    full_name = (payload.get("name") or payload.get("p1_nom_complet") or payload.get("nom_complet") or "").strip()
    if full_name:
        parts = [p for p in full_name.split() if p.strip()]
        if len(parts) >= 3:
            nombre = " ".join(parts[:-2])
            ap1 = parts[-2]
            ap2 = parts[-1]
            return ClientIdentity(is_company=False, nombre=nombre, apellido1=ap1, apellido2=ap2)

    raise RequiredClientDocumentsError(
        "No se pudo inferir identidad del cliente para buscar documentación (esperaba payload.mandatario o campos cliente_*)."
    )


def _obtener_carpeta_correspondiente(inicial: str) -> str:
    if inicial in "0123456789":
        return "0-9 (NUMEROS)"
    if inicial in "ABC":
        return "A-C"
    if inicial in "DE":
        return "D-E"
    if inicial in "FGHIJ":
        return "F-J"
    if inicial in "KL":
        return "K-L"
    if inicial in "MNO":
        return "M-O"
    if inicial in "PQRSTU":
        return "P-U"
    if inicial in "VWXYZ":
        return "V-Z"
    return "Desconocido"


def get_ruta_cliente_documentacion(
    client: ClientIdentity,
    *,
    base_path: str | Path = r"\\SERVER-DOC\clientes",
) -> Path:
    base = Path(base_path)

    if client.is_company:
        empresa = (client.empresa or "").strip()
        if not empresa:
            raise RequiredClientDocumentsError("Cliente empresa sin nombre de empresa.")

        # Quitar puntuación final
        if empresa[-1] in "!.,?;:":
            empresa = empresa[:-1]

        inicial = empresa[0].upper()
        carpeta = _obtener_carpeta_correspondiente(inicial)
        ruta_cliente = base / carpeta / empresa.strip()
    else:
        nombre = (client.nombre or "").strip()
        ap1 = (client.apellido1 or "").strip()
        ap2 = (client.apellido2 or "").strip()
        if not (nombre and ap1 and ap2):
            raise RequiredClientDocumentsError("Cliente particular sin nombre/apellidos completos.")

        inicial = nombre[0].upper()
        carpeta = _obtener_carpeta_correspondiente(inicial)
        nombre_completo = f"{nombre} {ap1.upper()} {ap2.upper()}".strip()
        ruta_cliente = base / carpeta / nombre_completo

    # Carpetas candidatas
    dir_documentacion1 = ruta_cliente / "DOCUMENTACION"
    dir_documentacion2 = ruta_cliente / "DOCUMENTACIÓN"
    dir_documentacion3 = ruta_cliente / "DOCUMENTACION RECURSOS"

    if dir_documentacion3.exists():
        return dir_documentacion3
    if dir_documentacion1.exists():
        return dir_documentacion1
    if dir_documentacion2.exists():
        return dir_documentacion2

    # Si no existe la carpeta estándar, devolvemos la ruta del cliente para intentar localizar docs dentro.
    return ruta_cliente


@dataclass(frozen=True)
class SelectedClientDocuments:
    files_to_upload: list[Path]
    covered_terms: list[str]
    missing_terms: list[str]


def _pick_newer(existing: dict | None, candidate: dict) -> dict:
    if not existing:
        return candidate
    if candidate.get("last_modified", 0) > existing.get("last_modified", 0):
        return candidate
    return existing


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            yield Path(dirpath) / filename


def select_required_client_documents(
    *,
    ruta_docu: Path,
    is_company: bool,
    strict: bool = True,
    merge_if_multiple: bool = True,
    pdftk_path: str | Path = r"C:\Program Files (x86)\PDFtk\bin\pdftk.exe",
    output_dir: Path = Path("tmp/client_docs"),
    output_label: str = "client",
) -> SelectedClientDocuments:
    """
    Busca los documentos obligatorios dentro de `ruta_docu` usando heurísticas de nombre.

    - Si encuentra un PDF "principal" (AUT + termina en *comp.pdf o *cmp.pdf), lo usa directamente.
    - Si no, compone una lista en base a términos requeridos.
    - Si faltan términos, lanza RequiredClientDocumentsError (si strict=True).
    - Si hay múltiples ficheros y merge_if_multiple=True, intenta fusionarlos con PDFtk si existe.
    """
    terminos_requeridos = ["AUT", "CIF", "DNI", "NIF", "ESCR"] if is_company else ["AUT", "DNI", "NIE"]

    archivos_encontrados: dict[str, dict | None] = defaultdict(lambda: None)
    archivo_principal: dict | None = None

    max_file_size = 7 * 1024 * 1024

    if not ruta_docu.exists():
        raise RequiredClientDocumentsError(f"No existe la ruta de documentación: {ruta_docu}")

    for file_path in _iter_files(ruta_docu):
        try:
            stat = file_path.stat()
        except OSError:
            continue

        file_name_lower = file_path.name.lower()
        last_modified = int(stat.st_mtime * 1000)
        file_size = int(stat.st_size)

        # CRITERIO PRINCIPAL: AUT + termina en COMP o CMP (PDF)
        if "aut" in file_name_lower and (file_name_lower.endswith("comp.pdf") or file_name_lower.endswith("cmp.pdf")):
            archivo_principal = {"path": file_path, "last_modified": last_modified, "terminos": ["AUT"]}
            break

        encontrado_terminos = [t for t in terminos_requeridos if t.lower() in file_name_lower]

        # Si contiene múltiples términos, preferimos ese como principal
        if len(encontrado_terminos) > 1:
            candidate = {"path": file_path, "last_modified": last_modified, "terminos": encontrado_terminos}
            if (not archivo_principal) or (len(encontrado_terminos) > len(archivo_principal.get("terminos", []))):
                archivo_principal = candidate
                for term in encontrado_terminos:
                    archivos_encontrados.pop(term, None)
            elif archivo_principal and len(encontrado_terminos) == len(archivo_principal.get("terminos", [])):
                archivo_principal = _pick_newer(archivo_principal, candidate)
            continue

        # Selección por término (uno a uno)
        if file_size > max_file_size:
            continue

        if "aut" in file_name_lower:
            if (is_company and "part" not in file_name_lower) or (not is_company and "empr" not in file_name_lower):
                archivos_encontrados["AUT"] = _pick_newer(
                    archivos_encontrados.get("AUT"),
                    {"path": file_path, "last_modified": last_modified},
                )
        elif is_company and ("cif" in file_name_lower or "nif" in file_name_lower):
            archivos_encontrados["CIF"] = _pick_newer(
                archivos_encontrados.get("CIF"),
                {"path": file_path, "last_modified": last_modified},
            )
        elif "dni" in file_name_lower:
            archivos_encontrados["DNI"] = _pick_newer(
                archivos_encontrados.get("DNI"),
                {"path": file_path, "last_modified": last_modified},
            )
        elif "nie" in file_name_lower and "daniel" not in file_name_lower:
            archivos_encontrados["NIE"] = _pick_newer(
                archivos_encontrados.get("NIE"),
                {"path": file_path, "last_modified": last_modified},
            )
        elif is_company and "escr" in file_name_lower:
            archivos_encontrados["ESCR"] = _pick_newer(
                archivos_encontrados.get("ESCR"),
                {"path": file_path, "last_modified": last_modified},
            )

    covered_terms: list[str] = []
    archivos_para_subir: list[Path] = []

    if archivo_principal:
        archivos_para_subir = [Path(archivo_principal["path"])]
        covered_terms = [t.upper() for t in (archivo_principal.get("terminos") or [])]
    else:
        for term in terminos_requeridos:
            item = archivos_encontrados.get(term)
            if item and item.get("path"):
                archivos_para_subir.append(Path(item["path"]))
                covered_terms.append(term)

    missing_terms = [t for t in terminos_requeridos if t not in set(covered_terms)]
    if missing_terms and strict:
        raise RequiredClientDocumentsError(
            f"Faltan documentos obligatorios ({', '.join(missing_terms)}) en {ruta_docu}."
        )

    # Fusionar si procede (mejor subir 1 PDF que varios, si el entorno lo permite)
    if merge_if_multiple and len(archivos_para_subir) > 1:
        pdftk_exe = Path(pdftk_path)
        if pdftk_exe.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            terms_token = "".join([t.upper() for t in covered_terms]) or "DOCS"
            out_path = output_dir / f"{output_label}_{terms_token}.pdf"
            cmd = [str(pdftk_exe), *[str(p) for p in archivos_para_subir], "cat", "output", str(out_path)]
            logger.info(f"Fusionando {len(archivos_para_subir)} doc(s) con PDFtk → {out_path}")
            subprocess.run(cmd, check=True)
            archivos_para_subir = [out_path]
        else:
            logger.warning(f"PDFtk no encontrado en {pdftk_exe}; se suben documentos por separado.")

    return SelectedClientDocuments(
        files_to_upload=archivos_para_subir,
        covered_terms=covered_terms,
        missing_terms=missing_terms,
    )


def build_required_client_documents_for_payload(
    payload: dict,
    *,
    strict: bool = True,
    merge_if_multiple: bool = True,
) -> list[Path]:
    """
    API de alto nivel: a partir del payload, localiza y devuelve los doc: obligatorios del cliente.
    """
    client = client_identity_from_payload(payload)
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    pdftk_path = os.getenv("PDFTK_PATH") or r"C:\Program Files (x86)\PDFtk\bin\pdftk.exe"
    output_dir = Path(os.getenv("CLIENT_DOCS_OUTPUT_DIR") or "tmp/client_docs")
    id_recurso = str(payload.get("idRecurso") or "client").strip() or "client"

    ruta = get_ruta_cliente_documentacion(client, base_path=base_path)
    selected = select_required_client_documents(
        ruta_docu=ruta,
        is_company=client.is_company,
        strict=strict,
        merge_if_multiple=merge_if_multiple,
        pdftk_path=pdftk_path,
        output_dir=output_dir,
        output_label=id_recurso,
    )
    return selected.files_to_upload
