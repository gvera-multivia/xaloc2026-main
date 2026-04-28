from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import TYPE_CHECKING

from ._sync import click_and_wait

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import DiputacioBcnConfig
    from ..data_models import DiputacioBcnTarget

logger = logging.getLogger("sites.diputacio_bcn.confirmacion")


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


def _is_alegaciones_phase(value: str) -> bool:
    fase = _norm(value)
    if not fase:
        return False
    return any(
        token in fase
        for token in (
            "DENUNCIA",
            "PROPUESTA DE RESOLUCION",
            "PROPOSTA DE RESOLUCIO",
            "SANCION",
            "SUBSANACION",
            "SUBSANACIO",
        )
    )


def _is_apremio_embargo_phase(value: str) -> bool:
    fase = _norm(value)
    if not fase:
        return False
    return any(token in fase for token in ("APREMIO", "EMBARGO"))


def _is_identificacion_phase(value: str) -> bool:
    fase = _norm(value)
    if not fase:
        return False
    return "IDENTIFIC" in fase


def _format_matricula_for_diputacio(value: str) -> str:
    raw = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if not raw or raw == ".":
        return ""
    patterns = [
        (r"^(\d{4})([A-Z]{3})$", r"\1-\2"),
        (r"^([A-Z]{2})(\d{4})([A-Z]{2})$", r"\1-\2-\3"),
        (r"^([A-Z]{2})(\d{4})([A-Z]{1})$", r"\1-\2-\3"),
        (r"^([A-Z]{1})(\d{5})([A-Z]{2})$", r"\1-\2-\3"),
        (r"^([A-Z]{1})(\d{4})([A-Z]{2})$", r"\1-\2-\3"),
        (r"^([A-Z]{1})(\d{4})([A-Z]{1})$", r"\1-\2-\3"),
        (r"^([A-Z]{1})(\d{4})([A-Z]{3})$", r"\1-\2-\3"),
        (r"^([A-Z]{2})(\d{6})$", r"\1-\2"),
        (r"^([A-Z]{1})(\d{6})$", r"\1-\2"),
        (r"^([A-Z]{2})(\d{4})$", r"\1-\2"),
    ]
    for pattern, replacement in patterns:
        if re.match(pattern, raw):
            return re.sub(pattern, replacement, raw)
    return raw


def _resolve_matricula_value(datos: "DiputacioBcnTarget") -> tuple[str, dict[str, str]]:
    raw_sources = {
        "datos.matricula": str(getattr(datos, "matricula", "") or "").strip(),
        "payload.matricula": str(datos.payload.get("matricula") or "").strip(),
        "payload.Matricula": str(datos.payload.get("Matricula") or "").strip(),
        "payload.rs_matricula": str(datos.payload.get("rs_matricula") or "").strip(),
        "payload.exp_matricula": str(datos.payload.get("exp_matricula") or "").strip(),
        "payload.pub_matricula": str(datos.payload.get("pub_matricula") or "").strip(),
    }
    raw_value = next((value for value in raw_sources.values() if value and value != "."), "")
    return _format_matricula_for_diputacio(raw_value.upper()), raw_sources


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


def _ens_candidates(organismo_raw: str) -> list[str]:
    norm = _norm(organismo_raw)
    out: list[str] = []
    if organismo_raw:
        out.append(str(organismo_raw).strip())
    if "ORGT" in norm or "GESTIO TRIBUT" in norm or "GESTION TRIBUT" in norm:
        out.append("ORG.DE GESTIO TRIBUTARIA")
        out.append("ORGANISMO DE GESTION TRIBUTARIA")
    if "DIPUTAC" in norm or "DIBA" in norm:
        out.append("DIPUTACIO DE BARCELONA")
    unique: list[str] = []
    seen: set[str] = set()
    for item in out:
        key = _norm(item)
        if not key or key in seen:
            continue
        unique.append(item)
        seen.add(key)
    return unique


async def _pick_select_value(page: "Page", select_id: str, candidates: list[str]) -> str:
    options = await page.eval_on_selector_all(
        f"#{select_id} option",
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


async def _resolve_preselector_screen(page: "Page", datos: "DiputacioBcnTarget") -> bool:
    submit_btn = page.locator("input[type='submit'].btn.btn-blue-left[value='Continuar']").first
    municipio_select = page.locator("#MunicipisList").first
    ens_select = page.locator("#EnsList").first
    if await submit_btn.count() == 0 or (await municipio_select.count() == 0 and await ens_select.count() == 0):
        return False

    organismo_raw = str(datos.payload.get("organismo") or datos.payload.get("Organisme") or "").strip()
    municipio_raw = str(datos.municipio or datos.payload.get("municipio") or "").strip()

    selected = False
    if await municipio_select.count() > 0:
        codmuni = _payload_codmuni(datos)
        if not codmuni:
            raise RuntimeError(
                "diputacio_bcn: falta 'codmuni' en payload para seleccionar municipio "
                f"(organismo={organismo_raw!r}, municipio={municipio_raw!r})."
            )
        await municipio_select.wait_for(state="visible", timeout=15000)
        ready_state = await _wait_select_options_ready(page, "MunicipisList", timeout_ms=12000)
        logger.info(
            "diputacio_bcn preselector municipio options_ready found=%s options=%s value=%s",
            ready_state.get("found"),
            ready_state.get("options"),
            ready_state.get("value"),
        )
        state_before = await _read_select_state(page, "MunicipisList")
        logger.info(
            "diputacio_bcn preselector municipio before value=%s label=%s options=%s codmuni=%s",
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
                "diputacio_bcn preselector municipio fallback value=%s after=%s onchange=%s",
                codmuni,
                forced.get("value"),
                forced.get("onchangeCalled"),
            )
            state_after = await _read_select_state(page, "MunicipisList")
        if str(state_after.get("value") or "").strip() != codmuni:
            raise RuntimeError(
                "diputacio_bcn: no se pudo fijar codmuni en preselector "
                f"(wanted={codmuni}, got={state_after.get('value')})."
            )
        selected = True

    if not selected and await ens_select.count() > 0:
        await ens_select.wait_for(state="visible", timeout=15000)
        ready_state = await _wait_select_options_ready(page, "EnsList", timeout_ms=12000)
        logger.info(
            "diputacio_bcn preselector ens options_ready found=%s options=%s value=%s",
            ready_state.get("found"),
            ready_state.get("options"),
            ready_state.get("value"),
        )
        ens_value = await _pick_select_value(page, "EnsList", _ens_candidates(organismo_raw))
        if ens_value:
            await ens_select.select_option(value=ens_value)
            selected = True

    if not selected:
        state_muni = await _read_select_state(page, "MunicipisList")
        state_ens = await _read_select_state(page, "EnsList")
        raise RuntimeError(
            "diputacio_bcn: no se pudo resolver el preselector de municipio/ente. "
            f"organismo={organismo_raw!r} municipio={municipio_raw!r} "
            f"MunicipisList={state_muni} EnsList={state_ens} url={page.url}"
        )

    await click_and_wait(
        page,
        submit_btn,
        url_patterns=[
            "**/TramitsPagaments/Presentmul/presentmul**",
            "**/RegistreElectronicMultes/presgenmul**",
            "**/Home/Seleccio/Seleccio**",
        ],
        visible_selectors=["#ExpSancionador", "#MunicipisList", "#EnsList", "#FetsSolicitud"],
    )
    return True


async def run_confirmacion(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = (config, datos)
    for _ in range(2):
        resolved = await _resolve_preselector_screen(page, datos)
        if not resolved:
            break

    await page.wait_for_url("**/TramitsPagaments/Presentmul/presentmul**", timeout=30000)
    municipio_select = page.locator("#MunicipisList").first
    if await municipio_select.count() > 0:
        codmuni = _payload_codmuni(datos)
        if not codmuni:
            raise RuntimeError(
                "diputacio_bcn: falta 'codmuni' en payload para pantalla de confirmacion "
                f"(organismo={str(datos.payload.get('organismo') or datos.payload.get('Organisme') or '').strip()!r})."
            )
        await municipio_select.wait_for(state="visible", timeout=15000)
        ready_state = await _wait_select_options_ready(page, "MunicipisList", timeout_ms=12000)
        logger.info(
            "diputacio_bcn confirmacion municipio options_ready found=%s options=%s value=%s",
            ready_state.get("found"),
            ready_state.get("options"),
            ready_state.get("value"),
        )
        state_before = await _read_select_state(page, "MunicipisList")
        logger.info(
            "diputacio_bcn confirmacion municipio before value=%s label=%s options=%s codmuni=%s",
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
                "diputacio_bcn confirmacion municipio fallback value=%s after=%s onchange=%s",
                codmuni,
                forced.get("value"),
                forced.get("onchangeCalled"),
            )
            state_after = await _read_select_state(page, "MunicipisList")
        logger.info(
            "diputacio_bcn confirmacion municipio after value=%s label=%s",
            state_after.get("value"),
            state_after.get("label"),
        )
        if str(state_after.get("value") or "").strip() != codmuni:
            raise RuntimeError(
                "diputacio_bcn: no se pudo fijar MunicipioSeleccionat.codiOficina "
                f"(wanted={codmuni}, got={state_after.get('value')})."
            )

    exp_field = page.locator("#ExpSancionador, input[name='ExpSancionador']").first
    if await exp_field.count() > 0:
        await exp_field.wait_for(state="visible", timeout=15000)
        exp_value = str(datos.payload.get("exp_sancionador") or datos.expediente or "").strip()
        await exp_field.fill(exp_value)

    matricula_field = page.locator(
        "#Matricula, input[name='Matricula'], input[id*='Matric'], input[name*='Matric']"
    ).first
    if await matricula_field.count() > 0:
        await matricula_field.wait_for(state="visible", timeout=15000)
        matricula_value, matricula_sources = _resolve_matricula_value(datos)
        logger.info(
            "[diputacio_bcn] matricula resolution idRecurso=%s expediente=%s resolved=%r sources=%s",
            getattr(datos, "idRecurso", None),
            getattr(datos, "expediente", None),
            matricula_value,
            matricula_sources,
        )
        if not matricula_value:
            raise RuntimeError(
                "diputacio_bcn: matricula ausente en payload antes de rellenar confirmacion "
                f"(idRecurso={getattr(datos, 'idRecurso', None)} expediente={getattr(datos, 'expediente', None)})"
            )
        await matricula_field.fill(matricula_value)
        filled_matricula_value = str(await matricula_field.input_value()).strip()
        if not filled_matricula_value:
            raise RuntimeError(
                "diputacio_bcn: no se pudo rellenar el campo Matricula en confirmacion "
                f"(idRecurso={getattr(datos, 'idRecurso', None)} expediente={getattr(datos, 'expediente', None)} "
                f"resolved={matricula_value!r})"
            )

    fase_raw = str(datos.fase_procedimiento or datos.payload.get("fase_procedimiento") or "").strip()
    if _is_identificacion_phase(fase_raw):
        identificacion_button = page.locator(
            "input[type='submit'][name='idcondBtn'][value='Identificar conductor o poseedor del vehículo']"
        ).first
        if await identificacion_button.count() > 0:
            await click_and_wait(
                page,
                identificacion_button,
                url_patterns=["**/TramitsPagaments/Presentmul/presentmulPas2**"],
                visible_selectors=["#FetsSolicitud"],
            )
    elif _is_apremio_embargo_phase(fase_raw):
        multas_link = page.locator(
            "a[href*='RegistreElectronicMultes'][href*='presgenmul']"
        ).first
        if await multas_link.count() > 0:
            await click_and_wait(
                page,
                multas_link,
                url_patterns=["**/RegistreElectronicMultes/presgenmul**"],
                visible_selectors=["#FetsSolicitud", "#MunicipisList"],
            )
    elif _is_alegaciones_phase(fase_raw):
        alegaciones_button = page.locator("input[type='submit'][value='Presentar alegaciones o recurso']").first
        if await alegaciones_button.count() > 0:
            await click_and_wait(
                page,
                alegaciones_button,
                url_patterns=["**/TramitsPagaments/Presentmul/presentmulPas2**"],
                visible_selectors=["#FetsSolicitud"],
            )

    return page
