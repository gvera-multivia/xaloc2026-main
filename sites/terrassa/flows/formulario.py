from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ._page_eval import evaluate_with_nav_retry

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget


async def _blur_field(page: "Page", field: "Locator") -> None:
    try:
        await field.press("Tab", timeout=1000)
        return
    except PlaywrightTimeoutError:
        pass
    except Exception:
        pass

    try:
        await field.evaluate(
            """(el) => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (typeof el.blur === 'function') el.blur();
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }"""
        )
        return
    except Exception:
        pass

    try:
        field_id = await field.get_attribute("id")
        if not field_id:
            return
        await evaluate_with_nav_retry(
            page,
            """(selector) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (typeof el.blur === 'function') el.blur();
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                return true;
            }""",
            f"#{field_id}",
        )
    except Exception:
        pass


async def _fill_and_blur(page: "Page", selector: str, value: str) -> None:
    field = page.locator(selector).first
    await field.fill(value)
    await _blur_field(page, field)


async def run_formulario(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    await page.locator(f"a[href='{config.href_actuar_representant}']").first.click()
    await page.wait_for_load_state("domcontentloaded")

    await page.select_option("select#IDPersona_TD", value=str(datos.document_type_value or "1"))
    await _fill_and_blur(page, "input#IDPersona_ND", datos.document_number)

    await _fill_and_blur(page, "input#nom", datos.nombre)

    if not datos.is_company:
        await _fill_and_blur(page, "input#cognom1", datos.apellido1)
        if datos.apellido2:
            await _fill_and_blur(page, "input#cognom2", datos.apellido2)

    await _fill_and_blur(page, "input#_NUM_EXPEDIENT", datos.expediente)
    await _fill_and_blur(page, "input#_DATA_FET", datos.fecha_infraccion)
    await _fill_and_blur(page, "input#_MATRICULA", datos.matricula)
    await _fill_and_blur(page, "input#_MARCA", datos.marca)

    await page.fill("textarea#_MOTIUS", datos.alegaciones)
    await page.fill("textarea#_OBSERV", datos.observaciones)
    return page
