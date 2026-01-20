from __future__ import annotations

from playwright.async_api import Page
from sites.selva.data_models import DatosSolicitud


async def rellenar_formulario(page: Page, datos: DatosSolicitud):
    """
    Rellena el formulario de datos de contacto y solicitud.
    """

    # --- Contact Data ---
    await page.fill("#contact1", datos.contact_phone)
    await page.check("#info1") # Checkbox for phone

    await page.fill("#contact3", datos.contact_mobile)
    await page.check("#info3") # Checkbox for mobile

    await page.fill("#contact11", datos.contact_fax)
    await page.check("#info11") # Checkbox for fax

    await page.fill("#contact4", datos.contact_other_phone)
    await page.check("#info4") # Checkbox for other

    # --- Particular Data ---
    # Municipality
    # Using select_option by value if possible, otherwise by label
    try:
        await page.select_option("#Instancia_generica$IG_MUNICIPIO_ENTIDAD", value=datos.municipality)
    except:
        await page.select_option("#Instancia_generica$IG_MUNICIPIO_ENTIDAD", label=datos.municipality)

    # Theme
    await page.select_option("#Instancia_generica$TEMA", value=datos.theme)

    # Expose and Solicita
    await page.fill("#Instancia_generica$EXPONE", datos.expose_text)
    await page.fill("#Instancia_generica$SOLICITA", datos.request_text)

    # Checkboxes
    await page.check("#Instancia_generica$IG_OPOSICION_OBTENER_DATOS")
    await page.check("#Autorizacion_Notificacion_Electronica$AUTNOTELEC$AUTNOTELEC")

    # Click "Adjunta" to go to upload page
    # Selector: div#divBoton6261105284505789606120_2000405279801993506120 > a
    # This ID looks dynamic. Better use class or text.
    # Text "Adjunta" or class "boton-style tamano-defecto docs"

    await page.click("a.boton-style.tamano-defecto.docs")

    # Wait for upload page
    await page.wait_for_url("**/documentSignSend.jsp**")
