from __future__ import annotations

from playwright.async_api import Page


async def navegar_a_formulario(page: Page, url_base: str):
    """
    Navega a la página de inicio y hace clic en 'Instància genèrica' con certificado.
    """
    await page.goto(url_base)

    # Click on "Instància genèrica" (Amb certificat digital)
    # The selector from recording: div#aazone.CATSERV > div > ul > li > div:nth-of-type(2) > ul > li > a
    # We can also use text.

    # Wait for the element to be visible
    selector = "div#aazone.CATSERV > div > ul > li > div:nth-of-type(2) > ul > li > a"
    # Alternative robust selector:
    # await page.get_by_role("link", name="Amb certificat digital").click()

    await page.click(selector)

    # Wait for navigation to the form (URL contains TramitaForm)
    await page.wait_for_url("**/TramitaForm**")
