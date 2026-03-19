from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from typing import TYPE_CHECKING

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


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a, b=b).ratio()


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


async def _pick_municipio_value(page: "Page", municipio_raw: str) -> str:
    options = await page.eval_on_selector_all(
        "#MunicipisList option",
        """(els) => els.map((o) => ({ value: (o.value || "").trim(), label: (o.textContent || "").trim() }))""",
    )
    if not options:
        return ""

    by_value = {str(o.get("value") or "").strip(): str(o.get("label") or "").strip() for o in options}
    value_keys = set(by_value.keys())

    raw = str(municipio_raw or "").strip()
    if not raw:
        return ""

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
    best_value = ""
    best_score = 0.0
    for value, label in by_value.items():
        if value == "000":
            continue
        score = _similarity(target, _norm(label))
        if score > best_score:
            best_score = score
            best_value = value
    if best_score >= 0.86:
        return best_value
    return ""


async def run_confirmacion(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = (config, datos)
    await page.wait_for_url("**/TramitsPagaments/Presentmul/presentmul**", timeout=30000)
    municipio_select = page.locator("#MunicipisList").first
    if await municipio_select.count() > 0:
        await municipio_select.wait_for(state="visible", timeout=15000)
        municipio_raw = str(datos.municipio or datos.payload.get("municipio") or "").strip()
        selected_value = await _pick_municipio_value(page, municipio_raw)
        if selected_value:
            await municipio_select.select_option(value=selected_value)

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
        matricula_value = _format_matricula_for_diputacio(
            str(datos.matricula or datos.payload.get("matricula") or "").strip().upper()
        )
        await matricula_field.fill(matricula_value)

    fase_raw = str(datos.fase_procedimiento or datos.payload.get("fase_procedimiento") or "").strip()
    if _is_identificacion_phase(fase_raw):
        identificacion_button = page.locator(
            "input[type='submit'][name='idcondBtn'][value='Identificar conductor o poseedor del vehículo']"
        ).first
        if await identificacion_button.count() > 0:
            await identificacion_button.wait_for(state="visible", timeout=15000)
            await identificacion_button.click()
    elif _is_alegaciones_phase(fase_raw):
        alegaciones_button = page.locator("input[type='submit'][value='Presentar alegaciones o recurso']").first
        if await alegaciones_button.count() > 0:
            await alegaciones_button.wait_for(state="visible", timeout=15000)
            await alegaciones_button.click()

    return page
