from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Frame, Page
    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget

from .form_scope import wait_form_scope
from .cookies import dismiss_cookie_banner_if_present
from core.redsara_upload_planner import (
    _compress_pdf_with_tier,
    _is_pdf_file,
    _rasterize_pdf_nuclear,
    _rasterize_pdf_ultra,
)


logger = logging.getLogger("xaloc_automation.servei_cat_trans")

MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB
MAX_DOC_SLOTS = 5  # Maximo de documentos permitidos por el formulario
UPLOAD_PREP_DIR = Path("tmp/servei_cat_trans_uploads")
_INVALID_BASE_CHARS_RE = re.compile(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿñÑçÇºª·._,'\-]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")
_MULTI_DOT_RE = re.compile(r"\.+")
_MAX_FILENAME_LEN = 96
_ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg"}


async def _file_input_ids(scope: "Page | Frame") -> list[str]:
    result = await scope.evaluate(
        """() => {
            return Array.from(document.querySelectorAll("input[type='file']"))
                .map((el) => el.id)
                .filter((id) => !!id);
        }"""
    )
    if not isinstance(result, list):
        return []
    return [str(item).strip() for item in result if str(item).strip()]


async def _wait_file_input_ids(scope: "Page | Frame", timeout_ms: int) -> list[str]:
    waited = 0
    step_ms = 1000
    last_ids: list[str] = []
    while waited <= timeout_ms:
        last_ids = await _file_input_ids(scope)
        if len(last_ids) >= 2:
            return last_ids
        await scope.wait_for_timeout(step_ms)
        waited += step_ms
    return last_ids


async def _find_special_upload_slot(
    scope: "Page | Frame",
    *,
    input_ids: list[str],
    label_tokens: list[str],
) -> str:
    if not input_ids:
        return ""
    try:
        result = await scope.evaluate(
            """({ inputIds, tokens }) => {
                const normalize = (txt) => String(txt || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();
                const wanted = (tokens || []).map((t) => normalize(t)).filter(Boolean);
                const includesWanted = (txt) => {
                    const n = normalize(txt);
                    return wanted.some((token) => n.includes(token));
                };
                for (const inputId of inputIds) {
                    const el = document.getElementById(inputId);
                    if (!el) continue;
                    let node = el;
                    for (let depth = 0; depth < 6 && node; depth += 1) {
                        const text = String(node.textContent || "");
                        const aria = String(node.getAttribute?.("aria-label") || "");
                        const title = String(node.getAttribute?.("title") || "");
                        if (includesWanted(text) || includesWanted(aria) || includesWanted(title)) {
                            return String(inputId);
                        }
                        node = node.parentElement;
                    }
                }
                return "";
            }""",
            {"inputIds": input_ids, "tokens": label_tokens},
        )
    except Exception:
        return ""
    return str(result or "").strip()


async def _upload_to_input(scope: "Page | Frame", input_id: str, file_path: Path) -> bool:
    await dismiss_cookie_banner_if_present(scope)
    selector = f'[id="{input_id}"]'
    await scope.locator(selector).set_input_files(str(file_path))
    await scope.wait_for_timeout(700)
    names = await _read_input_file_names(scope, input_id)
    if not names:
        return False
    expected = file_path.name.strip().lower()
    if expected and expected not in names:
        logger.warning(
            "servei_cat_trans.documentos: upload input=%s cargado con nombre distinto. expected=%s got=%s",
            input_id,
            expected,
            names,
        )
    return True


async def _read_input_file_names(scope: "Page | Frame", input_id: str) -> list[str]:
    try:
        state = await scope.evaluate(
            """(id) => {
                const el = document.getElementById(id);
                if (!el) return { exists: false, count: 0, names: [] };
                const names = Array.from(el.files || []).map((f) => String(f.name || ""));
                return { exists: true, count: names.length, names };
            }""",
            input_id,
        )
    except Exception:
        return []

    count = int((state or {}).get("count") or 0)
    if count <= 0:
        return []
    return [str(n or "").strip().lower() for n in (state or {}).get("names") or []]


async def _assert_expected_uploads_present(
    scope: "Page | Frame",
    *,
    expected_by_slot: dict[str, str],
) -> None:
    missing: list[str] = []
    mismatched: list[str] = []
    for input_id, expected_name in expected_by_slot.items():
        names = await _read_input_file_names(scope, input_id)
        if not names:
            missing.append(f"{input_id}:{expected_name}")
            continue
        if expected_name.strip().lower() not in names:
            mismatched.append(f"{input_id}:{expected_name}->{names}")
    if missing or mismatched:
        raise RuntimeError(
            "servei_cat_trans.documentos: verificacion final de adjuntos fallida. "
            f"missing={missing} mismatched={mismatched}"
        )


async def _upload_with_retry(scope: "Page | Frame", input_id: str, file_path: Path, *, attempts: int = 3) -> bool:
    for attempt in range(1, max(1, attempts) + 1):
        ok = await _upload_to_input(scope, input_id, file_path)
        if ok:
            return True
        if attempt < attempts:
            await scope.wait_for_timeout(900)
    return False


def _is_within_size_limit(file_path: Path) -> bool:
    try:
        return file_path.stat().st_size <= MAX_FILE_SIZE_BYTES
    except Exception:
        return False


def _norm_path(path: Path | str | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve()).lower()
    except Exception:
        return str(path).strip().lower()


def _sanitize_upload_filename(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "documento.pdf"

    normalized = unicodedata.normalize("NFC", Path(raw).name)
    normalized = re.sub(r",\s*(pdf|jpe?g)\s*$", r".\1", normalized, flags=re.IGNORECASE)

    m_ext = re.search(r"\.(pdf|jpe?g)\s*$", normalized, flags=re.IGNORECASE)
    if m_ext:
        suffix = f".{m_ext.group(1).lower()}"
        base = normalized[: m_ext.start()].strip()
    else:
        suffix = ".pdf"
        base = str(Path(normalized).stem or normalized).strip()

    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in _ALLOWED_EXTS:
        suffix = ".pdf"

    clean_base = base.replace(" ", "_")
    clean_base = _INVALID_BASE_CHARS_RE.sub("_", clean_base)
    clean_base = _MULTI_UNDERSCORE_RE.sub("_", clean_base)
    clean_base = _MULTI_DOT_RE.sub(".", clean_base)
    clean_base = clean_base.strip("._-,'") or "documento"

    max_base_len = max(12, _MAX_FILENAME_LEN - len(suffix))
    if len(clean_base) > max_base_len:
        clean_base = clean_base[:max_base_len].rstrip("._-,'") or "documento"

    clean_suffix = suffix
    return f"{clean_base}{clean_suffix}"


def _norm_name(name: str) -> str:
    txt = str(name or "").strip().lower()
    if not txt:
        return ""
    txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", txt).strip()


def _is_authorization_doc(path: Path | None) -> bool:
    if path is None:
        return False
    n = _norm_name(path.name)
    return any(token in n for token in ("autoriz", "autoriza", "acredit"))


def _is_optional_overflow_doc(path: Path | None) -> bool:
    if path is None:
        return False
    n = _norm_name(path.name)
    return "escritura" in n or "escriptura" in n


def _copy_with_safe_name(src: Path, *, output_dir: Path, prefix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_upload_filename(src.name)
    safe_prefix = _sanitize_upload_filename(prefix).rsplit(".", 1)[0]
    out = output_dir / f"{safe_prefix}_{safe_name}"
    if safe_name != src.name:
        logger.info(
            "servei_cat_trans.documentos: renombrado para upload regex-safe: %s -> %s",
            src.name,
            safe_name,
        )
    shutil.copy2(src, out)
    return out


def _compress_pdf_to_limit(src: Path, *, output_dir: Path) -> Path | None:
    if not _is_pdf_file(src):
        return None
    best = src
    best_size = src.stat().st_size
    if best_size <= MAX_FILE_SIZE_BYTES:
        return best

    candidates: list[Path] = []
    for tier in ("aggressive", "ultra"):
        candidate = _compress_pdf_with_tier(best, tier=tier, output_dir=output_dir / tier)
        if candidate and candidate.exists():
            candidates.append(candidate)
    nuclear = _rasterize_pdf_nuclear(best, output_dir=output_dir / "nuclear")
    if nuclear and nuclear.exists():
        candidates.append(nuclear)
    ultra = _rasterize_pdf_ultra(best, output_dir=output_dir / "ultra_raster")
    if ultra and ultra.exists():
        candidates.append(ultra)

    for candidate in candidates:
        size = candidate.stat().st_size
        if 0 < size < best_size:
            best = candidate
            best_size = size
        if size <= MAX_FILE_SIZE_BYTES:
            return candidate

    if best_size <= MAX_FILE_SIZE_BYTES:
        return best
    return None


def _select_files_by_origin(files: list[Path], payload: dict) -> tuple[Path | None, Path | None, list[Path]]:
    by_norm = {_norm_path(p): p for p in files}

    xvia_recurso = by_norm.get(_norm_path(payload.get("xvia_recurso_path")))
    xvia_adjuntos = {
        _norm_path(item)
        for item in (payload.get("xvia_attachment_paths") or [])
        if str(item or "").strip()
    }
    required_client_docs = [
        by_norm.get(_norm_path(item))
        for item in (payload.get("required_client_doc_paths") or [])
        if str(item or "").strip()
    ]
    required_client_docs = [p for p in required_client_docs if p is not None]

    acreditacion = by_norm.get(_norm_path(payload.get("acreditacion_path")))
    recurso = xvia_recurso or (files[0] if files else None)

    if not acreditacion and required_client_docs:
        auth_docs = [p for p in required_client_docs if _is_authorization_doc(p)]
        acreditacion = auth_docs[0] if auth_docs else required_client_docs[0]

    non_xvia_files = [
        p for p in files
        if _norm_path(p) != _norm_path(xvia_recurso) and _norm_path(p) not in xvia_adjuntos
    ]
    if not acreditacion:
        auth_docs = [p for p in non_xvia_files if p != recurso and _is_authorization_doc(p)]
        if auth_docs:
            acreditacion = auth_docs[0]
    if not acreditacion:
        for p in non_xvia_files:
            if p != recurso:
                acreditacion = p
                break

    rest = []
    for p in files:
        if p in {recurso, acreditacion}:
            continue
        if acreditacion and _is_authorization_doc(p):
            continue
        rest.append(p)
    return recurso, acreditacion, rest


def _build_slot_upload_plan(
    *,
    doc_slots: list[str],
    recurso: Path | None,
    middle_files: list[Path],
    autorizacion: Path | None,
) -> list[tuple[Path, str]]:
    """
    Regla critica del formulario:
    la autorizacion debe ir siempre en el ultimo slot de documentos, aunque
    queden slots previos sin usar.
    """
    if not doc_slots:
        return []

    plan: list[tuple[Path, str]] = []
    non_last_slots = doc_slots[:-1]
    last_slot = doc_slots[-1]

    if recurso and non_last_slots:
        plan.append((recurso, non_last_slots[0]))
    elif recurso and not non_last_slots and not autorizacion:
        plan.append((recurso, last_slot))

    middle_start = 1 if (recurso and non_last_slots) else 0
    for file_path, slot_id in zip(middle_files, non_last_slots[middle_start:]):
        plan.append((file_path, slot_id))

    if autorizacion:
        plan.append((autorizacion, last_slot))
    return plan


async def run_documentos(page: "Page", config: "ServeiCatTransConfig", datos: "ServeiCatTransTarget") -> "Page":
    await dismiss_cookie_banner_if_present(page)
    files = [Path(p) for p in (datos.archivos_para_subir or []) if Path(p).exists()]
    if not files:
        raise RuntimeError("servei_cat_trans.documentos: no hay archivos para subir.")

    payload = datos.payload if isinstance(datos.payload, dict) else {}
    recurso, autorizacion, rest = _select_files_by_origin(files, payload)
    logger.info(
        "servei_cat_trans.documentos: seleccion origen recurso=%s autorizacion=%s extras=%s",
        recurso.name if recurso else "N/A",
        autorizacion.name if autorizacion else "N/A",
        [p.name for p in rest],
    )

    run_dir = UPLOAD_PREP_DIR / str(datos.idRecurso or "unknown")
    prepared_recurso: Path | None = None
    prepared_autorizacion: Path | None = None

    if recurso and recurso.exists():
        recurso_comp = _compress_pdf_to_limit(recurso, output_dir=run_dir / "resource_compressed") or recurso
        if recurso_comp.exists() and _is_within_size_limit(recurso_comp):
            prepared_recurso = _copy_with_safe_name(recurso_comp, output_dir=run_dir, prefix="recurso")
        else:
            logger.error(
                "servei_cat_trans.documentos: recurso no apto para subida tras compresion (%s, %.2f MB).",
                recurso.name,
                recurso.stat().st_size / (1024 * 1024),
            )

    if autorizacion and autorizacion.exists():
        aut_comp = _compress_pdf_to_limit(autorizacion, output_dir=run_dir / "auth_compressed") or autorizacion
        if aut_comp.exists() and _is_within_size_limit(aut_comp):
            prepared_autorizacion = _copy_with_safe_name(aut_comp, output_dir=run_dir, prefix="autorizacion")
        else:
            logger.error(
                "servei_cat_trans.documentos: autorizacion no apta para subida tras compresion (%s, %.2f MB).",
                autorizacion.name,
                autorizacion.stat().st_size / (1024 * 1024),
            )

    if not prepared_recurso or not prepared_autorizacion:
        raise RuntimeError(
            "servei_cat_trans.documentos: faltan adjuntos obligatorios (recurso y/o autorizacion) "
            "o no cumplen limite de 1MB tras compresion."
        )

    max_middle = MAX_DOC_SLOTS - (1 if prepared_recurso else 0) - (1 if prepared_autorizacion else 0)
    overflow_files = [p for p in rest[max_middle:] if p.exists()]
    blocking_overflow = [p.name for p in overflow_files if not _is_optional_overflow_doc(p)]
    skipped_optional_overflow = [p.name for p in overflow_files if _is_optional_overflow_doc(p)]
    if skipped_optional_overflow:
        logger.warning(
            "servei_cat_trans.documentos: extras opcionales omitidos por limite de slots: %s",
            skipped_optional_overflow,
        )
    if blocking_overflow:
        raise RuntimeError(
            "servei_cat_trans.documentos: hay mas adjuntos que slots disponibles; "
            f"omitidos={blocking_overflow}"
        )

    form_scope = await wait_form_scope(page, timeout_ms=config.upload_inputs_timeout_ms)
    input_ids = await _wait_file_input_ids(form_scope, timeout_ms=config.upload_inputs_timeout_ms)
    if len(input_ids) < 2:
        raise RuntimeError(
            "servei_cat_trans.documentos: no se detectaron inputs file suficientes "
            f"tras espera ({config.upload_inputs_timeout_ms}ms)."
        )

    # Orden observado en este formulario:
    # [0]=uploader interno (no usar), [1..5]=docs opcionales, [6]=acreditacion.
    doc_slots = input_ids[1:6]  # 5 slots maximo
    acreditacion_slot = await _find_special_upload_slot(
        form_scope,
        input_ids=input_ids,
        label_tokens=["acredit", "represent", "autoriza"],
    )
    if not acreditacion_slot and len(input_ids) > 6:
        acreditacion_slot = input_ids[6]

    # Montar extras intermedios (la autorizacion SIEMPRE se asigna al ultimo slot).
    prepared_middle: list[Path] = []
    for idx, mid in enumerate(rest[:max_middle], start=1):
        if not mid.exists():
            continue
        mid_comp = _compress_pdf_to_limit(mid, output_dir=run_dir / "middle_compressed") or mid
        if not _is_within_size_limit(mid_comp):
            logger.warning(
                "servei_cat_trans.documentos: archivo intermedio omitido por tamano >1MB (%s).",
                mid.name,
            )
            continue
        prepared_middle.append(_copy_with_safe_name(mid_comp, output_dir=run_dir, prefix=f"extra_{idx}"))

    logger.info(
        "servei_cat_trans.documentos: subiendo %d archivos (max %d, max 1MB). Recurso=%s, Autorizacion=%s",
        (1 if prepared_recurso else 0) + len(prepared_middle) + (1 if prepared_autorizacion else 0),
        MAX_DOC_SLOTS,
        prepared_recurso.name if prepared_recurso else "N/A",
        prepared_autorizacion.name if prepared_autorizacion else "N/A",
    )

    upload_plan = _build_slot_upload_plan(
        doc_slots=doc_slots,
        recurso=prepared_recurso,
        middle_files=prepared_middle,
        autorizacion=prepared_autorizacion,
    )
    expected_by_slot: dict[str, str] = {}
    recurso_uploaded = False
    autorizacion_uploaded = False
    for file_path, slot_id in upload_plan:
        await dismiss_cookie_banner_if_present(form_scope)
        logger.info("  -> subiendo %s (%.2f KB)", file_path.name, file_path.stat().st_size / 1024)
        ok = await _upload_with_retry(form_scope, slot_id, file_path)
        if not ok:
            raise RuntimeError(
                f"servei_cat_trans.documentos: no se pudo confirmar upload en slot={slot_id} archivo={file_path.name}."
            )
        expected_by_slot[slot_id] = file_path.name
        if prepared_recurso and file_path == prepared_recurso:
            recurso_uploaded = True
        if prepared_autorizacion and file_path == prepared_autorizacion:
            autorizacion_uploaded = True

    # Acreditacion para persona juridica (slot especifico separado)
    if datos.tipo_persona == "juridica" and acreditacion_slot and prepared_autorizacion:
        await dismiss_cookie_banner_if_present(form_scope)
        logger.info("  -> subiendo acreditacion (slot especial): %s", prepared_autorizacion.name)
        ok = await _upload_with_retry(form_scope, acreditacion_slot, prepared_autorizacion)
        if not ok:
            raise RuntimeError(
                "servei_cat_trans.documentos: no se pudo confirmar upload de acreditacion en slot especial."
            )
        expected_by_slot[acreditacion_slot] = prepared_autorizacion.name
        autorizacion_uploaded = True

    if datos.tipo_persona == "juridica" and not acreditacion_slot:
        logger.warning(
            "servei_cat_trans.documentos: no se detecto slot especial de acreditacion para persona juridica; "
            "la autorizacion solo se sube en slots de documentos."
        )

    if not recurso_uploaded:
        raise RuntimeError("servei_cat_trans.documentos: el recurso obligatorio no quedo adjuntado.")
    if not autorizacion_uploaded:
        raise RuntimeError("servei_cat_trans.documentos: la autorizacion/acreditacion obligatoria no quedo adjuntada.")

    await _assert_expected_uploads_present(form_scope, expected_by_slot=expected_by_slot)

    return page
