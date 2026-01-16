from __future__ import annotations

import logging

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineAddressData, BaseOnlineP1Data
from sites.base_online.flows.common import rellenar_contacto


_SIGLES_PERMESES = {
    "AG",
    "AL",
    "AP",
    "AR",
    "AU",
    "AV",
    "AY",
    "BJ",
    "BO",
    "BR",
    "CA",
    "CG",
    "CH",
    "CI",
    "CJ",
    "CL",
    "CM",
    "CN",
    "CO",
    "CP",
    "CR",
    "CS",
    "CT",
    "CU",
    "DE",
    "DP",
    "DS",
    "ED",
    "EM",
    "EN",
    "ER",
    "ES",
    "EX",
    "FC",
    "FN",
    "GL",
    "GR",
    "GV",
    "HT",
    "JR",
    "LD",
    "LG",
    "MC",
    "ML",
    "MN",
    "MS",
    "MT",
    "MZ",
    "PB",
    "PD",
    "PJ",
    "PQ",
    "PR",
    "PS",
    "PT",
    "PZ",
    "QT",
    "RB",
    "RC",
    "RD",
    "RM",
    "RP",
    "RR",
    "RU",
    "SA",
    "SD",
    "SL",
    "SN",
    "SU",
    "TN",
    "TO",
    "TR",
    "UR",
    "VR",
    "ZN",
}


def _upper_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value.upper() if value else None


def _formatear_adreca(detall: BaseOnlineAddressData) -> str:
    sigla = (detall.sigla or "").strip().upper()
    if sigla not in _SIGLES_PERMESES:
        raise ValueError(f"P1: 'sigla' inválida: {detall.sigla}")

    calle = (detall.calle or "").strip()
    numero = (detall.numero or "").strip()
    if not calle or not numero:
        raise ValueError("P1: 'calle' y 'numero' son obligatorios.")

    cp = (detall.codigo_postal or "").strip()
    if not cp:
        raise ValueError("P1: 'codigo_postal' es obligatorio.")

    municipio = _upper_or_none(detall.municipio)
    ampliacion_municipio = _upper_or_none(detall.ampliacion_municipio)
    provincia = _upper_or_none(detall.provincia)
    pais = _upper_or_none(detall.pais)

    es_espana = pais is None or pais in {"ESPAÑA", "ESPANA"}
    if es_espana:
        if not municipio:
            raise ValueError("P1: 'municipio' es obligatorio para España.")
        if not provincia:
            raise ValueError("P1: 'provincia' es obligatoria para España.")
    else:
        if not ampliacion_municipio:
            raise ValueError("P1: 'ampliacion_municipio' es obligatorio fuera de España.")

    calle_line = f"{sigla} {calle}, {numero}"
    extra1 = [detall.letra, detall.escala, detall.piso, detall.puerta]
    extra1 = [x.strip() for x in extra1 if x and x.strip()]
    if extra1:
        calle_line += ", " + ", ".join(extra1)
    if detall.ampliacion_calle and detall.ampliacion_calle.strip():
        calle_line += f" {detall.ampliacion_calle.strip()}"

    linea_cp = f"{cp} "
    if es_espana:
        linea_cp += municipio
        if ampliacion_municipio:
            linea_cp += f" {ampliacion_municipio}"
        linea_prov = provincia
    else:
        linea_cp += ampliacion_municipio
        linea_prov = pais

    return f"{calle_line}\n{linea_cp}\n{linea_prov}"


async def _rellenar_contacto(page: Page, data: BaseOnlineP1Data) -> None:
    await rellenar_contacto(page, data.contacte)

    await page.locator("input[type='submit'][name='form:j_id20'][value='Continuar']").first.click()
    await page.wait_for_load_state("domcontentloaded")


async def _rellenar_identificacion_conductor(page: Page, data: BaseOnlineP1Data) -> None:
    info = data.identificacio

    await page.locator("#form\\:clau_expedient_id_ens").first.fill(info.expedient_id_ens)
    await page.locator("#form\\:clau_expedient_any_exp").first.fill(info.expedient_any)
    await page.locator("#form\\:clau_expedient_num_exp").first.fill(info.expedient_num)

    await page.evaluate(
        "typeof actualitzarClauExpedientclau_expedient === 'function' && actualitzarClauExpedientclau_expedient()"
    )

    await page.locator("#form\\:num_butlleti").first.fill(info.num_butlleti)
    await page.locator("#form\\:data_denuncia").first.fill(info.data_denuncia)
    await page.locator("#form\\:matricula").first.fill(info.matricula)
    await page.locator("#form\\:identificacio").first.fill(info.identificacio)
    await page.locator("#form\\:llicencia_conduccio").first.fill(info.llicencia_conduccio)
    await page.locator("#form\\:nom_complet").first.fill(info.nom_complet)

    adreca_text = info.adreca
    if not adreca_text and info.adreca_detall:
        adreca_text = _formatear_adreca(info.adreca_detall)
    if not adreca_text:
        raise ValueError("P1: falta dirección (adreca o adreca_detall).")

    # La "adreça" tiene ID duplicado (textarea readonly + input hidden). Seteamos ambos por JS.
    await page.evaluate(
        """(value) => {
          const nodes = document.querySelectorAll('#form\\\\:adreca');
          for (const el of nodes) {
            try { el.removeAttribute('readonly'); } catch (e) {}
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }""",
        adreca_text,
    )

    logging.info("[P1] Formulario 2 rellenado; avanzando al siguiente paso...")
    await page.locator("input[type='submit'][name='form:j_id24'][value='Continuar']").first.click()
    await page.wait_for_load_state("domcontentloaded")


async def ejecutar_p1(page: Page, data: BaseOnlineP1Data) -> None:
    logging.info("[P1] Rellenando pantalla 1 (contacto)...")
    await _rellenar_contacto(page, data)
    logging.info("[P1] Rellenando pantalla 2 (identificación conductor)...")
    await _rellenar_identificacion_conductor(page, data)
