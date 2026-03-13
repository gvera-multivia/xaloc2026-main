from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page
    from ..config import AjuntamentBarcelonaConfig
    from ..data_models import AjuntamentBarcelonaTarget


logger = logging.getLogger("xaloc_automation.ajuntament_barcelona")


DOWNLOAD_DIR = "actualizaciones/ajuntament_barcelona/downloads/documentos_multas"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def descargar_documentos(page: "Page", context: "BrowserContext") -> None:

    # Recoger identificadores antes de navegar
    idents = await page.evaluate(
        """() => Array.from(document.querySelectorAll("a[title='Documents Associats']"))
               .map(a => a.innerText.trim())"""
    )

    logger.info(
        "ajuntament_barcelona.descargar_documentos multas_encontradas=%d", len(idents)
    )

    for i, ident in enumerate(idents):

        logger.info(
            "ajuntament_barcelona.descargar_documentos multa=%d ident=%s", i, ident
        )

        try:
            # Navegar a la página de detalle
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                await page.evaluate(f"document.getElementById('form{i}').submit()")

            logger.info(
                "ajuntament_barcelona.descargar_documentos multa=%d detail_url=%s",
                i,
                page.url,
            )

            # Contar formularios de descarga (action=detalleMulteAc.do?do=getDocument)
            num_doc_forms = await page.evaluate(
                """() => document.querySelectorAll("form[action*='getDocument']").length"""
            )
            logger.info(
                "ajuntament_barcelona.descargar_documentos multa=%d doc_forms=%d",
                i,
                num_doc_forms,
            )

            for j in range(num_doc_forms):
                try:
                    async with page.expect_download(timeout=15000) as dl_info:
                        await page.evaluate(
                            f"document.querySelectorAll(\"form[action*='getDocument']\")[{j}].submit()"
                        )
                    download = await dl_info.value
                    filename = f"{ident}_{j}_{download.suggested_filename or 'document.pdf'}"
                    path = os.path.join(DOWNLOAD_DIR, filename)
                    await download.save_as(path)
                    logger.info(
                        "ajuntament_barcelona.descargar_documentos multa=%d doc=%d saved=%s",
                        i,
                        j,
                        path,
                    )
                except Exception as e:
                    logger.warning(
                        "ajuntament_barcelona.descargar_documentos multa=%d doc=%d error=%s",
                        i,
                        j,
                        e,
                    )

            # Volver al listado
            await page.go_back(wait_until="domcontentloaded")

        except Exception as e:
            logger.warning(
                "ajuntament_barcelona.descargar_documentos multa=%d error=%s",
                i,
                e,
            )
            try:
                await page.go_back(wait_until="domcontentloaded")
            except Exception:
                pass


async def run_multes(
    page: "Page",
    config: "AjuntamentBarcelonaConfig",
    datos: "AjuntamentBarcelonaTarget",
) -> "Page":
    _ = config
    multes_url = "https://ajuntament.barcelona.cat/hisenda/ca/tramits-gestions/multes-de-transit?profile=1#procedures"
    logger.info("ajuntament_barcelona.multes START url=%s", multes_url)
    await page.goto(multes_url, wait_until="domcontentloaded")
    await page.wait_for_load_state("networkidle")
    logger.info("ajuntament_barcelona.multes page url=%s", page.url)

    # Suele ser un acordeon/fieldset previo al enlace de consulta.
    try:
        await page.locator(".field > div:nth-child(5)").first.click(timeout=5000)
        logger.info("ajuntament_barcelona.multes accordion clicked")
    except Exception:
        logger.info("ajuntament_barcelona.multes accordion not clicked (continuing)")

    link_consulta = (
        page.locator("a[href*='ptbportal/login.do'][target='_blank']")
        .filter(
            has_text=re.compile(
                r"Consulta multes pagades i/o pendents|Consulta multes pagades i/o",
                re.IGNORECASE,
            )
        )
        .first
    )
    if await link_consulta.count() == 0:
        link_consulta = page.get_by_role(
            "link",
            name=re.compile(
                r"Consulta multes pagades i/o pendents|Consulta multes pagades i/o",
                re.IGNORECASE,
            ),
        ).first

    logger.info(
        "ajuntament_barcelona.multes link_consulta count=%s",
        await link_consulta.count(),
    )
    await link_consulta.wait_for(state="visible", timeout=15000)
    await link_consulta.scroll_into_view_if_needed()
    async with page.expect_popup(timeout=15000) as p1_info:
        await link_consulta.click(force=True)
    page1 = await p1_info.value
    await page1.wait_for_load_state("domcontentloaded")
    await page1.wait_for_load_state("networkidle")
    logger.info("ajuntament_barcelona.multes popup1 url=%s", page1.url)

    # Inicio con certificado si aplica.
    cert_btn = page1.get_by_test_id("certificate-btn")
    logger.info(
        "ajuntament_barcelona.multes cert_btn count=%s",
        await cert_btn.count(),
    )
    if await cert_btn.count():
        await cert_btn.first.click()
        await page1.wait_for_load_state("domcontentloaded")
        await page1.wait_for_load_state("networkidle")
        logger.info("ajuntament_barcelona.multes cert_btn clicked")

    # Prioridad: "Accedir a la meva carpeta"; fallback: "Accedir".
    try:
        primary_access = page1.locator(
            "input[type='submit'][value='Accedir a la meva carpeta']"
        ).first
        logger.info(
            "ajuntament_barcelona.multes primary_access count=%s",
            await primary_access.count(),
        )
        await primary_access.wait_for(state="visible", timeout=10000)
        await primary_access.click()
        logger.info("ajuntament_barcelona.multes primary_access clicked")
    except Exception:
        fallback_access = page1.locator("input[type='submit'][value='Accedir']").first
        logger.info(
            "ajuntament_barcelona.multes fallback_access count=%s",
            await fallback_access.count(),
        )
        await fallback_access.wait_for(state="visible", timeout=10000)
        await fallback_access.click()
        logger.info("ajuntament_barcelona.multes fallback_access clicked")

    try:
        await page1.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        await page1.wait_for_load_state("domcontentloaded", timeout=15000)
    logger.info("ajuntament_barcelona.multes post_access url=%s", page1.url)

    tab_multes = page1.locator("a#contact-tab")
    try:
        await page1.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    logger.info(
        "ajuntament_barcelona.multes tab_multes count=%s",
        await tab_multes.count(),
    )
    try:
        await tab_multes.first.wait_for(state="visible", timeout=10000)
        try:
            tab_class = await tab_multes.first.get_attribute("class")
        except Exception:
            tab_class = None
        logger.info(
            "ajuntament_barcelona.multes tab_multes visible=1 class=%s",
            tab_class,
        )
        await tab_multes.first.click()
        logger.info("ajuntament_barcelona.multes tab_multes clicked via #contact-tab")
    except Exception:
        logger.info("ajuntament_barcelona.multes tab_multes fallback via role=tab")
        await page1.get_by_role(
            "tab", name=re.compile(r"Multes", re.IGNORECASE)
        ).first.click()
        logger.info("ajuntament_barcelona.multes tab_multes clicked via role")
    try:
        await page1.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    logger.info("ajuntament_barcelona.multes post_tab url=%s", page1.url)

    card_multes_pendents = (
        page1.locator(".card-result.object-tramit")
        .filter(has_text=re.compile(r"Multes pendents", re.IGNORECASE))
        .first
    )
    card_emultes = (
        page1.locator(".card-result.object-tramit")
        .filter(has_text=re.compile(r"eMultes", re.IGNORECASE))
        .first
    )
    logger.info(
        "ajuntament_barcelona.multes cards counts multes_pendents=%s emultes=%s",
        await card_multes_pendents.count(),
        await card_emultes.count(),
    )

    async with page1.expect_popup() as p2_info:
        try:
            await card_multes_pendents.wait_for(state="visible", timeout=8000)
            await card_multes_pendents.click()
            logger.info("ajuntament_barcelona.multes card clicked=Multes pendents")
        except Exception:
            await card_emultes.wait_for(state="visible", timeout=8000)
            await card_emultes.click()
            logger.info("ajuntament_barcelona.multes card clicked=eMultes")
    page2 = await p2_info.value
    await page2.wait_for_load_state("domcontentloaded")
    await page2.wait_for_load_state("networkidle")
    logger.info("ajuntament_barcelona.multes popup2 url=%s", page2.url)

    try:
        select_any = page2.locator("select[name='anySeleccio']")
        await select_any.first.wait_for(state="visible", timeout=5000)
        await select_any.first.select_option("TOTS")
        cercar_btn = page2.locator('[id="cercar"]')
        await cercar_btn.first.wait_for(state="visible", timeout=5000)
        await cercar_btn.first.click()
        await page2.wait_for_load_state("networkidle", timeout=10000)
        logger.info("ajuntament_barcelona.multes anySeleccio selected=TOTS cercar clicked")
    except Exception:
        logger.info("ajuntament_barcelona.multes anySeleccio not found (continuing)")

    no_remeses_cell = page2.get_by_role(
        "cell", name=re.compile(r"No s'han trobat remeses", re.IGNORECASE)
    )
    no_dades_text = page2.get_by_text(
        re.compile(
            r"no consten dades de la vostra empresa o entitat",
            re.IGNORECASE,
        )
    )
    exists_no_remeses = await no_remeses_cell.count() > 0 or await no_dades_text.count() > 0
    logger.info(
        "ajuntament_barcelona.multes no_remeses_exists=%d", int(exists_no_remeses)
    )

    if not exists_no_remeses:
        data = await page2.evaluate(
            """
        () => {
            const forms = document.querySelectorAll("form[id^='form']");

            return Array.from(forms).map(f => ({
                identif: f.querySelector("input[name='identificacio']")?.value || "",
                fet: f.querySelector("input[name='fetDenunciat']")?.value || "",
                adreca: f.querySelector("input[name='adreca']")?.value || "",
                data: f.querySelector("input[name='data']")?.value || "",
                situacio: "VOLUNTÀRIA", 
                expedient: f.querySelector("input[name='numExpediente']")?.value || "",
                import: f.querySelector("input[name='importe']")?.value || ""
            }));
        }
        """
        )

        df = pd.DataFrame(data)

        df = df.rename(
            columns={
                "identif": "Identif",
                "fet": "Fet denunciat",
                "adreca": "Adreça",
                "data": "Data",
                "situacio": "Situació",
                "expedient": "Expedient",
                "import": "Import",
            }
        )

        logger.info("ajuntament_barcelona.multes multes_df rows=%d\n%s", len(df), df.to_string())
        await descargar_documentos(page2, page2.context)

    if isinstance(datos.payload, dict):
        datos.payload["ajuntament_barcelona_multes_no_trobat_remeses_exists"] = bool(
            exists_no_remeses
        )

    logger.info("ajuntament_barcelona.multes done")
    return page2
