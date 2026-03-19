from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.client_documentation import client_identity_from_payload
from core.client_paths import (
    get_ruta_recursos_telematicos,
    resolve_client_docs_base_path,
)

from ..texts import build_fets_solicitud

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import DiputacioBcnConfig
    from ..data_models import DiputacioBcnTarget


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


async def run_presentmul_pas2(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = config
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
    continue_btn = page.locator("input[type='submit'][value='Continuar']").first
    if await continue_btn.count() == 0:
        raise RuntimeError("No se encontró el botón 'Continuar' en presentmulPas2.")
    await continue_btn.scroll_into_view_if_needed()
    await continue_btn.click()
    await page.wait_for_url("**/TramitsPagaments/Presentmul/presentmulPresentacio**", timeout=30000)
    signature_checkbox = page.locator("#SignaturaDocument").first
    if await signature_checkbox.count() > 0:
        await signature_checkbox.wait_for(state="visible", timeout=15000)
        await signature_checkbox.check(force=True)
    firmar_btn = page.locator("input.btn.btn-info.pull-left[name='accio'][value='Firmar y Presentar']").first
    if await firmar_btn.count() > 0:
        await firmar_btn.wait_for(state="visible", timeout=15000)
        await firmar_btn.click()
    recibo_btn = page.locator("button.btn.btn-info.pull-left:has-text('Recibo de presentación')").first
    if await recibo_btn.count() > 0:
        await recibo_btn.wait_for(state="visible", timeout=15000)
        async with page.expect_download(timeout=60000) as dl_info:
            await recibo_btn.click()
        download = await dl_info.value
        # Determine client folder for telematic resources
        identity = client_identity_from_payload(datos.payload or {})
        base_path = resolve_client_docs_base_path()
        target_dir = get_ruta_recursos_telematicos(
            client=identity,
            base_path=base_path,
            fase_procedimiento=datos.fase_procedimiento,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = download.suggested_filename or "recibo.pdf"
        # Keep unique naming by timestamp
        dest = target_dir / f"recibo_presentacion_{datos.expediente or 'sinexp'}_{filename}"
        await download.save_as(dest)
    return page
