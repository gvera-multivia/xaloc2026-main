from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget


async def run_formulario(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    await page.locator(f"a[href='{config.href_actuar_representant}']").first.click()
    await page.wait_for_load_state("domcontentloaded")

    await page.select_option("select#IDPersona_TD", value=str(datos.document_type_value or "1"))
    await page.fill("input#IDPersona_ND", datos.document_number)
    await page.evaluate("document.getElementById('IDPersona_ND').blur()")

    await page.fill("input#nom", datos.nombre)
    await page.evaluate("document.getElementById('nom').blur()")

    if not datos.is_company:
        await page.fill("input#cognom1", datos.apellido1)
        await page.evaluate("document.getElementById('cognom1').blur()")
        if datos.apellido2:
            await page.fill("input#cognom2", datos.apellido2)
            await page.evaluate("document.getElementById('cognom2').blur()")

    await page.fill("input#_NUM_EXPEDIENT", datos.expediente)
    await page.evaluate("document.getElementById('_NUM_EXPEDIENT').blur()")
    await page.fill("input#_DATA_FET", datos.fecha_infraccion)
    await page.evaluate("document.getElementById('_DATA_FET').blur()")
    await page.fill("input#_MATRICULA", datos.matricula)
    await page.evaluate("document.getElementById('_MATRICULA').blur()")
    await page.fill("input#_MARCA", datos.marca)
    await page.evaluate("document.getElementById('_MARCA').blur()")

    await page.fill("textarea#_MOTIUS", datos.alegaciones)
    await page.fill("textarea#_OBSERV", datos.observaciones)
    return page
