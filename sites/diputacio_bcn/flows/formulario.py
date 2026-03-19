from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import DiputacioBcnConfig
    from ..data_models import DiputacioBcnTarget


def _pick_latest_open_page(page: "Page") -> "Page":
    if not page.is_closed():
        return page
    pages = [p for p in page.context.pages if not p.is_closed()]
    if not pages:
        raise RuntimeError("No hay pestañas activas tras la redirección de identificación.")
    return pages[-1]


async def _paso4_fisica(page: "Page", datos: "DiputacioBcnTarget") -> None:
    await page.get_by_role(
        "link",
        name="La entidad actúa en representación de una persona física",
    ).click()
    await page.locator("#nifcr4c").fill((datos.nif_interessat or "00000000T").upper())
    await page.locator("#nomcr4c").fill(datos.nom_cr4 or "Nom")
    await page.locator("#cognom1cr4c").fill(datos.cognom1 or "Cognom1")
    await page.locator("#cognom2cr4c").fill(datos.cognom2 or "Cognom2")
    await page.locator("#collapseFour").get_by_role("button", name="Continuar").click()


async def _paso4_juridica(page: "Page", datos: "DiputacioBcnTarget") -> None:
    await page.get_by_role(
        "link",
        name="La entidad actúa en representación de otra entidad",
    ).click()
    await page.locator("#identificadorInteressatCR5Rep").fill((datos.nif_interessat or "").upper())
    await page.locator("#nomInteressatCR5Rep").fill(datos.nom_juridica or "Empresa SL")
    await page.locator("#collapseFive").get_by_role("button", name="Continuar").click()


async def run_formulario(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = config
    page = _pick_latest_open_page(page)

    if "/Home/representacioPas1juridica" not in page.url:
        try:
            await page.wait_for_url("https://valid.aoc.cat/**", timeout=120000)
        except Exception:
            page = _pick_latest_open_page(page)
        if "/Home/representacioPas1juridica" not in page.url:
            btn_cert = page.locator("#btnContinuaCert")
            await btn_cert.wait_for(state="visible", timeout=60000)
            try:
                await btn_cert.click(force=True, timeout=10000)
            except Exception:
                await page.evaluate(
                    "() => { const b = document.querySelector('#btnContinuaCert'); if (b) b.click(); }"
                )
            await page.wait_for_url("**/Home/representacioPas1juridica**", timeout=180000)

    await page.get_by_role("radio", name="Representante legal").click()
    await page.get_by_role("button", name="La entidad es representante de otra persona interesada").click()

    await page.wait_for_url("**/Home/representacioPas2juridica**", timeout=120000)
    if (datos.tipo_representado or "fisica").strip().lower() == "juridica":
        await _paso4_juridica(page, datos)
    else:
        await _paso4_fisica(page, datos)

    # Dejamos la subida de documentos para run_documentos.
    await page.wait_for_url("**/Home/representacioPas3juridica**", timeout=120000)
    await page.wait_for_load_state("networkidle", timeout=15000)
    return _pick_latest_open_page(page)
