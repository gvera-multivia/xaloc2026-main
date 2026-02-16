from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineP2Data
from sites.base_online.flows.common import rellenar_contacto
from sites.base_online.flows.firma_y_justificante import firmar_presentar_y_descargar_justificante
from sites.base_online.flows.upload import subir_archivos_por_modal

DELAY_MS = 500


def _parse_expediente_parts(raw: str) -> tuple[str | None, str | None, str | None]:
    exp = str(raw or "").strip().upper()
    if not exp:
        return None, None, None

    m_gim = re.match(r"^(?P<id_ens>\d{5})-(?P<any>\d{4})/(?P<num>\d{4,5})-GIM$", exp)
    if m_gim:
        return m_gim.group("id_ens"), m_gim.group("any"), m_gim.group("num")

    m_exe = re.match(r"^(?P<id_ens>\d)-(?P<any>\d{4})[/\-](?P<num>\d{4,6})-(EXE|ECC)$", exp)
    if m_exe:
        return m_exe.group("id_ens"), m_exe.group("any"), m_exe.group("num")

    return None, None, None


async def _set_input_stable(page: Page, selector: str, value: str, *, label: str, retries: int = 3) -> None:
    expected = str(value or "").strip()
    locator = page.locator(selector).first
    await locator.wait_for(state="visible")

    for intento in range(1, retries + 1):
        await locator.fill(expected)
        await page.wait_for_timeout(120)
        ok = await page.evaluate(
            """([sel, val]) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                return String(el.value || '').trim() === String(val || '').trim();
            }""",
            [selector, expected],
        )
        if ok:
            return
        logging.warning("[P2] Reintento %s/%s al persistir %s", intento, retries, label)
        await page.wait_for_timeout(180)

    current = await locator.input_value()
    raise ValueError(f"[P2] No se pudo persistir {label}. esperado={expected!r} actual={current!r}")


async def ejecutar_p2(page: Page, data: BaseOnlineP2Data, *, payload: dict) -> None:
    logging.info("[P2] Rellenando formulario de alegaciones (paso 1)...")

    await page.locator("#form\\:nif").first.fill(data.nif)
    await page.wait_for_timeout(DELAY_MS)
    await page.locator("#form\\:rao_social").first.fill(data.rao_social)
    await page.wait_for_timeout(DELAY_MS)

    await rellenar_contacto(page, data.contacte)

    await page.locator("input[type='submit'][name='form:j_id20'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    logging.info("[P2] Aportando alegaciones (paso 2)...")
    exp_id_ens = (data.expedient_id_ens or "").strip() or None
    exp_any = (data.expedient_any or "").strip() or None
    exp_num = (data.expedient_num or "").strip() or None

    if not (exp_id_ens and exp_any and exp_num):
        payload_exp = (
            str(payload.get("expediente") or "").strip()
            or str(payload.get("num_butlleti") or "").strip()
            or str(payload.get("expediente_raw") or "").strip()
            or str(payload.get("expediente_base") or "").strip()
        )
        p_id_ens, p_any, p_num = _parse_expediente_parts(payload_exp)
        exp_id_ens = exp_id_ens or p_id_ens
        exp_any = exp_any or p_any
        exp_num = exp_num or p_num

    tiene_expediente = bool(exp_id_ens or exp_any or exp_num)
    butlleti_value = (
        (data.butlleti or "").strip()
        or str(payload.get("num_butlleti") or "").strip()
        or str(payload.get("expediente") or "").strip()
    )
    tiene_butlleti = bool(butlleti_value)
    if not (tiene_expediente or tiene_butlleti):
        raise ValueError("P2: es obligatorio indicar Num. Expedient o Num. Butlleti.")

    if tiene_expediente:
        logging.info("[P2] Expediente a informar: id_ens=%s any=%s num=%s", exp_id_ens, exp_any, exp_num)
        await _set_input_stable(
            page,
            "#form\\:clau_expedient_id_ens",
            exp_id_ens or "",
            label="expedient_id_ens",
        )
        await page.wait_for_timeout(DELAY_MS)
        await _set_input_stable(
            page,
            "#form\\:clau_expedient_any_exp",
            exp_any or "",
            label="expedient_any",
        )
        await page.wait_for_timeout(DELAY_MS)
        await _set_input_stable(
            page,
            "#form\\:clau_expedient_num_exp",
            exp_num or "",
            label="expedient_num",
        )
        await page.wait_for_timeout(DELAY_MS)
        await page.evaluate(
            "typeof actualitzarClauExpedientclau_expedient === 'function' && actualitzarClauExpedientclau_expedient()"
        )
        await page.wait_for_timeout(DELAY_MS)

    if tiene_butlleti:
        await _set_input_stable(page, "#form\\:butlleti", butlleti_value, label="butlleti")
        await page.wait_for_timeout(DELAY_MS)
        logging.info("[P2] Butlleti informado: %s", butlleti_value)

    await page.locator("#form\\:exposo").first.fill(data.exposo or "")
    await page.wait_for_timeout(DELAY_MS)
    await page.locator("#form\\:solicito").first.fill(data.solicito or "")
    await page.wait_for_timeout(DELAY_MS)

    await page.locator("input[type='submit'][name='form:j_id24'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    logging.info("[P2] Subiendo documentos (paso 3)...")
    archivos = list(data.archivos_adjuntos or [])
    if not archivos:
        raise ValueError("P2: falta 'archivos_adjuntos' (al menos 1 archivo).")
    await subir_archivos_por_modal(page, archivos)

    await page.locator("input[type='submit'][name='form:j_id29'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    logging.info("[P2] Preparando firma y presentacion...")
    await firmar_presentar_y_descargar_justificante(page, payload=payload)
