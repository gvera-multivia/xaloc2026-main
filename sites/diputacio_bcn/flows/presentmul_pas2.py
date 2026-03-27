from __future__ import annotations

import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from core.justificantes_storage import (
    build_receipt_filename,
    resolve_receipt_dir_from_payload,
    save_receipt_from_tmp,
)
from .confirmacion import _resolve_preselector_screen

from ..texts import build_fets_solicitud

logger = logging.getLogger("sites.diputacio_bcn.presentmul_pas2")

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import DiputacioBcnConfig
    from ..data_models import DiputacioBcnTarget


def _norm(value: str) -> str:
    txt = unicodedata.normalize("NFD", str(value or ""))
    txt = "".join(ch for ch in txt if unicodedata.category(ch) != "Mn")
    txt = txt.upper().strip()
    txt = re.sub(r"\s+", " ", txt)
    return txt


def _is_orgt_diba_alias(value: str) -> bool:
    norm = _norm(value)
    if not norm:
        return False
    has_orgt = "ORGT" in norm or "GESTION TRIBUTA" in norm or "GESTIO TRIBUTA" in norm
    has_diba = "DIPUTAC" in norm or "DIBA" in norm
    has_bcn_hint = "BARCELONA" in norm or "OFICINA DE MULTES" in norm
    return bool(has_orgt and has_diba and has_bcn_hint)


def _extract_municipio_from_organismo(organismo_raw: str) -> str:
    norm = _norm(organismo_raw)
    if not norm:
        return ""
    if _is_orgt_diba_alias(norm):
        return ""
    patterns = (
        r"\b(?:AJUNTAMENT|AYUNTAMENT|AYUNTAMIENTO|AYTO\.?)\s+(?:DE|DEL|DE LA|DE LES|DE LOS|DE LAS)\s+(.+)",
        r"\b(?:AJUNTAMENT|AYUNTAMENT|AYUNTAMIENTO|AYTO\.?)\s+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, norm)
        if not match:
            continue
        candidate = re.split(r"\s+-\s+|\s+\|\s+|;|,", match.group(1), maxsplit=1)[0]
        candidate = re.sub(r"\s+", " ", candidate).strip(" -'")
        if candidate:
            return candidate
    return ""


def _municipio_candidates(municipio_raw: str, organismo_raw: str) -> list[str]:
    out: list[str] = []
    from_organismo = _extract_municipio_from_organismo(organismo_raw)
    if from_organismo:
        out.append(from_organismo)
    if municipio_raw:
        out.append(str(municipio_raw).strip())
    unique: list[str] = []
    seen: set[str] = set()
    for item in out:
        key = _norm(item)
        if not key or key in seen:
            continue
        unique.append(item)
        seen.add(key)
    return unique


def _payload_codmuni(datos: "DiputacioBcnTarget") -> str:
    raw = str(
        datos.payload.get("codmuni")
        or datos.payload.get("municipio_code")
        or datos.payload.get("municipio_codigo")
        or ""
    ).strip()
    if not raw:
        return ""
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 5 and digits.startswith("08"):
        digits = digits[-3:]
    if len(digits) == 3:
        return digits
    return ""


async def _pick_municipio_value(page: "Page", candidates: list[str]) -> str:
    options = await page.eval_on_selector_all(
        "#MunicipisList option",
        """(els) => els.map((o) => ({ value: (o.value || "").trim(), label: (o.textContent || "").trim() }))""",
    )
    if not options:
        return ""
    by_value = {str(o.get("value") or "").strip(): str(o.get("label") or "").strip() for o in options}
    value_keys = set(by_value.keys())

    for candidate in candidates:
        raw = str(candidate or "").strip()
        if not raw:
            continue

        if raw in value_keys and raw != "000":
            return raw

        digits = re.sub(r"\D+", "", raw)
        if len(digits) == 5 and digits.startswith("08"):
            cand = digits[-3:]
            if cand in value_keys and cand != "000":
                return cand
        if len(digits) == 3 and digits in value_keys and digits != "000":
            return digits

        target = _norm(raw)
        for value, label in by_value.items():
            if value == "000":
                continue
            if _norm(label) == target:
                return value
        for value, label in by_value.items():
            if value == "000":
                continue
            if target and target in _norm(label):
                return value

        for value, label in by_value.items():
            if value == "000":
                continue
            label_norm = _norm(label)
            if target and label_norm and label_norm in target:
                return value
    return ""


async def _read_select_state(page: "Page", select_id: str) -> dict:
    return await page.evaluate(
        """(sid) => {
            const sel = document.getElementById(sid);
            if (!sel) return { found: false, value: "", label: "", options: 0 };
            const idx = sel.selectedIndex;
            const opt = idx >= 0 ? sel.options[idx] : null;
            return {
                found: true,
                value: String(sel.value || "").trim(),
                label: opt ? String(opt.textContent || "").trim() : "",
                options: sel.options ? sel.options.length : 0,
            };
        }""",
        select_id,
    )


async def _force_select_and_trigger_change(page: "Page", select_id: str, value: str) -> dict:
    return await page.evaluate(
        """({ sid, val }) => {
            const sel = document.getElementById(sid);
            if (!sel) return { applied: false, value: "", onchangeCalled: false };
            sel.value = val;
            sel.dispatchEvent(new Event("input", { bubbles: true }));
            sel.dispatchEvent(new Event("change", { bubbles: true }));
            let onchangeCalled = false;
            try {
                if (typeof window.CallChangefuncMuni === "function") {
                    window.CallChangefuncMuni(sel);
                    onchangeCalled = true;
                }
            } catch (_) {}
            return {
                applied: String(sel.value || "").trim() === String(val || "").trim(),
                value: String(sel.value || "").trim(),
                onchangeCalled,
            };
        }""",
        {"sid": select_id, "val": value},
    )


async def _wait_select_options_ready(
    page: "Page",
    select_id: str,
    *,
    min_options: int = 2,
    timeout_ms: int = 12000,
) -> dict:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_state: dict = {"found": False, "value": "", "label": "", "options": 0}
    while time.monotonic() < deadline:
        last_state = await _read_select_state(page, select_id)
        try:
            options = int(last_state.get("options") or 0)
        except Exception:
            options = 0
        if bool(last_state.get("found")) and options >= min_options:
            return last_state
        await page.wait_for_timeout(250)
    return last_state


async def _select_municipio_if_present(page: "Page", datos: "DiputacioBcnTarget") -> None:
    municipio_select = page.locator("#MunicipisList").first
    if await municipio_select.count() == 0:
        return
    codmuni = _payload_codmuni(datos)
    if not codmuni:
        raise RuntimeError(
            "diputacio_bcn: falta 'codmuni' en payload para seleccionar municipio "
            f"(municipio={str(datos.payload.get('municipio') or datos.municipio or '').strip()!r}, "
            f"organismo={str(datos.payload.get('organismo') or datos.payload.get('Organisme') or '').strip()!r})."
        )
    await municipio_select.wait_for(state="visible", timeout=15000)
    ready_state = await _wait_select_options_ready(page, "MunicipisList", timeout_ms=12000)
    logger.info(
        "diputacio_bcn municipio-select options_ready found=%s options=%s value=%s",
        ready_state.get("found"),
        ready_state.get("options"),
        ready_state.get("value"),
    )
    state_before = await _read_select_state(page, "MunicipisList")
    logger.info(
        "diputacio_bcn municipio-select before value=%s label=%s options=%s codmuni=%s",
        state_before.get("value"),
        state_before.get("label"),
        state_before.get("options"),
        codmuni,
    )
    await municipio_select.select_option(value=codmuni)
    state_after = await _read_select_state(page, "MunicipisList")
    if str(state_after.get("value") or "").strip() != codmuni:
        forced = await _force_select_and_trigger_change(page, "MunicipisList", codmuni)
        logger.warning(
            "diputacio_bcn municipio-select fallback aplicado value=%s after=%s onchange=%s",
            codmuni,
            forced.get("value"),
            forced.get("onchangeCalled"),
        )
        state_after = await _read_select_state(page, "MunicipisList")

    logger.info(
        "diputacio_bcn municipio-select after value=%s label=%s",
        state_after.get("value"),
        state_after.get("label"),
    )
    if str(state_after.get("value") or "").strip() != codmuni:
        raise RuntimeError(
            "diputacio_bcn: no se pudo fijar MunicipioSeleccionat.codiOficina "
            f"(wanted={codmuni}, got={state_after.get('value')})."
        )


async def _set_fets_solicitud(page: "Page", text: str) -> None:
    value = str(text or "").strip()
    if not value:
        return

    field = page.locator("#FetsSolicitud, textarea[name='FetsSolicitud']").first
    await field.wait_for(state="visible", timeout=15000)

    try:
        await field.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        await field.fill(value)
    except Exception:
        pass

    confirmed = await page.evaluate(
        """() => {
            const el = document.querySelector("#FetsSolicitud") || document.querySelector("textarea[name='FetsSolicitud']");
            return el ? (el.value || "") : "";
        }"""
    )
    if str(confirmed or "").strip() == value:
        return

    await page.evaluate(
        """(txt) => {
            const el = document.querySelector("#FetsSolicitud") || document.querySelector("textarea[name='FetsSolicitud']");
            if (!el) return;
            const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
            setter.call(el, txt);
            for (const eventName of ["input", "change", "keyup", "blur"]) {
                el.dispatchEvent(new Event(eventName, { bubbles: true }));
            }
        }""",
        value,
    )

    confirmed = await page.evaluate(
        """() => {
            const el = document.querySelector("#FetsSolicitud") || document.querySelector("textarea[name='FetsSolicitud']");
            return el ? (el.value || "") : "";
        }"""
    )
    if str(confirmed or "").strip() != value:
        raise RuntimeError("No se ha podido rellenar correctamente el campo '#FetsSolicitud'.")


async def _ensure_checked(page: "Page", locator, *, label: str) -> None:
    await locator.wait_for(state="visible", timeout=15000)
    await page.wait_for_timeout(3000)

    for attempt in range(1, 5):
        try:
            if await locator.is_checked():
                return
        except Exception:
            pass

        try:
            await locator.check(force=True, timeout=4000)
        except Exception as exc:
            logger.warning("diputacio_bcn %s check intento=%s fallo: %s", label, attempt, exc)

        try:
            if await locator.is_checked():
                return
        except Exception:
            pass

        try:
            await locator.click(force=True, timeout=3000)
        except Exception:
            pass

        try:
            if await locator.is_checked():
                return
        except Exception:
            pass

        try:
            await locator.evaluate(
                """(el) => {
                    if (!el) return false;
                    el.checked = true;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('click', { bubbles: true }));
                    return !!el.checked;
                }"""
            )
        except Exception:
            pass

        try:
            if await locator.is_checked():
                return
        except Exception:
            pass

        await page.wait_for_timeout(700)

    raise RuntimeError(f"Diputacio BCN: no se pudo marcar el checkbox '{label}' tras reintentos.")


def _is_multas_phase(fase: str) -> bool:
    txt = str(fase or "").strip().upper()
    if not txt:
        return False
    txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
    return any(token in txt for token in ("APREMIO", "EMBARGO"))


async def run_presentmul_pas2(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = config
    datos.payload["diputacio_justificante_descargado"] = False
    datos.payload.pop("diputacio_justificante_path", None)
    datos.payload.pop("diputacio_justificante_artifact_path", None)
    fase_raw = str(datos.fase_procedimiento or datos.payload.get("fase_procedimiento") or "").strip()
    is_multas = _is_multas_phase(fase_raw)

    if is_multas:
        # Para apremio/embargo ORGT puede intercalar la pantalla
        # "Seleccione un municipio o bien un ente..." antes de presgenmul.
        for _ in range(3):
            resolved = await _resolve_preselector_screen(page, datos)
            if not resolved:
                break
        await page.wait_for_url(
            re.compile(r".*/RegistreElectronicMultes/presgenmul(\?|$)"),
            timeout=30000,
        )
        await _select_municipio_if_present(page, datos)
    else:
        await page.wait_for_url("**/TramitsPagaments/Presentmul/presentmulPas2**", timeout=30000)

    fets_text = build_fets_solicitud(
        fase_procedimiento=datos.fase_procedimiento or datos.payload.get("fase_procedimiento"),
        expediente=datos.expediente or datos.payload.get("expediente"),
        sujeto_recurso=datos.payload.get("sujeto_recurso") or datos.nom_juridica,
        asunto=datos.payload.get("asunto"),
        expone=datos.payload.get("expone"),
        solicita=datos.payload.get("solicita"),
    )
    await _set_fets_solicitud(page, fets_text)

    if is_multas:
        submit_btn = page.locator("input[type='submit'][value='Siguiente']").first
        if await submit_btn.count() == 0:
            raise RuntimeError("No se encontro el boton 'Siguiente' en presgenmul.")
        await submit_btn.scroll_into_view_if_needed()
        await submit_btn.click()
        await page.wait_for_url(
            "**/TramitsPagaments/RegistreElectronicMultes/presgenmulPresentacio**",
            timeout=30000,
        )
    else:
        continue_btn = page.locator("input[type='submit'][value='Continuar']").first
        if await continue_btn.count() == 0:
            raise RuntimeError("No se encontro el boton 'Continuar' en presentmulPas2.")
        await continue_btn.scroll_into_view_if_needed()
        await continue_btn.click()
        await page.wait_for_url(
            "**/TramitsPagaments/Presentmul/presentmulPresentacio**",
            timeout=30000,
        )

    signature_checkbox = page.locator("#SignaturaDocument").first
    if await signature_checkbox.count() > 0:
        await _ensure_checked(page, signature_checkbox, label="SignaturaDocument")
    firmar_btn = page.locator("input.btn.btn-info[type='submit'][value*='Firmar y']").first
    if await firmar_btn.count() > 0:
        await firmar_btn.wait_for(state="visible", timeout=30000)
        await firmar_btn.click(timeout=90000)
    recibo_btn = page.locator("button.btn.btn-info.pull-left:has-text('Recibo de presentación')").first
    if await recibo_btn.count() > 0:
        await recibo_btn.wait_for(state="visible", timeout=15000)
        async with page.expect_download(timeout=60000) as dl_info:
            await recibo_btn.click()
        download = await dl_info.value
        await page.wait_for_timeout(2000)

        rid = str(datos.payload.get("idRecurso") or "unknown")
        tmp_dir = Path("tmp") / "diputacio_bcn" / "justificantes" / rid
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_name = (download.suggested_filename or "recibo.pdf").strip() or "recibo.pdf"
        tmp_path = tmp_dir / tmp_name
        await download.save_as(str(tmp_path))

        expediente = str(datos.expediente or datos.payload.get("expediente") or "SINEXP")
        final_filename = build_receipt_filename(
            expediente=expediente,
            template="JUSTIFICANTE - {expediente}.pdf",
        )
        destino_dir = resolve_receipt_dir_from_payload(
            payload=datos.payload or {},
            fase_procedimiento=datos.fase_procedimiento,
        )
        final_path = save_receipt_from_tmp(
            tmp_path=tmp_path,
            destino_dir=destino_dir,
            filename=final_filename,
        )
        datos.payload["diputacio_justificante_descargado"] = True
        datos.payload["diputacio_justificante_artifact_path"] = str(tmp_path)
        datos.payload["diputacio_justificante_path"] = str(final_path)
    return page
