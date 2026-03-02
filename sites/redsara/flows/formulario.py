from __future__ import annotations

import asyncio
import re
import unicodedata

from playwright.async_api import Page

from sites.redsara.config import RedSaraConfig
from sites.redsara.data_models import RedSaraTarget


def _normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFD", (text or "").strip().lower())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", value)


def _normalize_phase(fase: str, file_name: str) -> str:
    f = _normalize_text(fase)
    fn = _normalize_text(file_name)

    if f.startswith("sanci"):
        f = "sancion"
    if f == "alegacion":
        f = "denuncia"
    if "prop" in fn and "res" in fn:
        f = "propuesta de resolucion"
    if "subsana" in fn:
        f = "subsanacion"
    if f in {"apremio", "embargo"} and "reclamac" in fn:
        f = "reclamaciones"
    if f == "embargo" and ("info" in fn or "requerim" in fn):
        f = "requerimiento embargo"
    if f in {"sancion", "apremio", "embargo"} and "extraord" in fn and "revis" in fn:
        f = "extraordinario de revision"
    return f


def _build_texts_for_phase(fase: str, expediente: str) -> tuple[str, str, str]:
    f = fase
    exp = (expediente or "").strip()
    mapping = {
        "identificacion": (
            "Identificacion de conductor",
            "Se presenta identificacion de conductor responsable.",
            f"Se tenga por presentada la identificacion adjunta. Expediente: {exp}",
        ),
        "denuncia": (
            "Escrito de alegaciones frente a denuncia",
            "Se presenta escrito de alegaciones frente a denuncia.",
            f"Se tenga por presentado el escrito de alegaciones. Expediente: {exp}",
        ),
        "propuesta de resolucion": (
            "Alegaciones frente a propuesta de resolucion",
            "Se presenta escrito de alegaciones frente a propuesta de resolucion.",
            f"Se tenga por presentado el escrito de alegaciones. Expediente: {exp}",
        ),
        "extraordinario de revision": (
            "Recurso extraordinario de revision",
            "Se presenta recurso extraordinario de revision.",
            f"Se tenga por presentado el recurso extraordinario de revision. Expediente: {exp}",
        ),
        "subsanacion": (
            "Escrito de subsanacion",
            "Se presenta escrito de subsanacion para el expediente indicado.",
            f"Se tenga por presentado el escrito de subsanacion. Expediente: {exp}",
        ),
        "reclamaciones": (
            "Reclamacion economico-administrativa",
            "Se presenta reclamacion economico-administrativa.",
            f"Se tenga por presentada la reclamacion economico-administrativa. Expediente: {exp}",
        ),
        "requerimiento embargo": (
            "Solicitud de prescripcion frente a requerimiento de embargo",
            "Se presenta solicitud de prescripcion frente al requerimiento de embargo.",
            f"Se tenga por presentada la solicitud de prescripcion. Expediente: {exp}",
        ),
        "sancion": (
            "Recurso de reposicion frente a sancion",
            "Se presenta recurso de reposicion frente a sancion.",
            f"Se tenga por presentado el recurso de reposicion. Expediente: {exp}",
        ),
        "apremio": (
            "Recurso de reposicion frente a apremio",
            "Se presenta recurso de reposicion frente a apremio.",
            f"Se tenga por presentado el recurso de reposicion. Expediente: {exp}",
        ),
        "embargo": (
            "Recurso de reposicion frente a embargo",
            "Se presenta recurso de reposicion frente a embargo.",
            f"Se tenga por presentado el recurso de reposicion. Expediente: {exp}",
        ),
    }
    if f not in mapping:
        raise ValueError(f"redsara: fase no soportada '{f}'")
    return mapping[f]


async def _fill_input(page: Page, selector: str, value: str) -> None:
    loc = page.locator(selector).first
    await loc.wait_for(state="visible")
    await loc.scroll_into_view_if_needed()
    await loc.click()
    await loc.fill(value)


async def _fill_first_visible(locator, value: str) -> bool:
    count = await locator.count()
    for i in range(count):
        candidate = locator.nth(i)
        try:
            if not await candidate.is_visible():
                continue
            await candidate.scroll_into_view_if_needed()
            await candidate.fill(value)
            return True
        except Exception:
            continue
    return False


async def _fill_dnt_input(page: Page, formcontrolname: str, value: str, group: str | None = None) -> None:
    if not value:
        return
    prefix = f'div[formgroupname="{group}"] ' if group else ""
    locator = page.locator(f'{prefix}dnt-input[formcontrolname="{formcontrolname}"] input:not([type="hidden"])')
    if await locator.count() > 0 and await _fill_first_visible(locator, value):
        return
    fallback = page.locator(f'{prefix}input[formcontrolname="{formcontrolname}"]')
    if await fallback.count() > 0 and await _fill_first_visible(fallback, value):
        return
    raise RuntimeError(f"redsara: no se pudo rellenar campo '{formcontrolname}' (group={group}).")


async def _select_representante(page: Page) -> None:
    # 1) Intento por texto visible
    try:
        text_target = page.get_by_text("Representante", exact=False).first
        if await text_target.is_visible():
            await text_target.click(force=True)
            return
    except Exception:
        pass

    # 2) Fallback por radios custom (segunda opcion)
    radios = page.locator(".dnt-radio__inner")
    if await radios.count() >= 2:
        await radios.nth(1).click(force=True)
        return

    # 3) Ultimo intento por label
    radio = page.get_by_label("Representante", exact=False)
    if await radio.count() > 0:
        await radio.first.click(force=True)
        return

    raise RuntimeError("redsara: no se pudo seleccionar el tipo 'Representante'.")


async def _select_option_after_fill(page: Page, selector: str, value: str) -> None:
    await _fill_input(page, selector, value)
    await page.locator(selector).first.press("Space")
    await page.get_by_role("option", name=value, exact=False).first.click()


async def rellenar_formulario_redsara(page: Page, config: RedSaraConfig, datos: RedSaraTarget) -> Page:
    await page.get_by_text("Datos del interesado").wait_for(timeout=config.flow_timeouts.medium_wait)

    if datos.representante.es_representante:
        await _select_representante(page)
        represented_group = page.locator('div[formgroupname="represented"]')
        await represented_group.first.wait_for(state="visible", timeout=config.flow_timeouts.medium_wait)

    await _fill_dnt_input(page, "email", datos.representante.email, group="represented")
    await _fill_dnt_input(page, "phone", datos.representante.telefono, group="represented")

    rep_dir = datos.representante.direccion
    if rep_dir:
        await _select_option_after_fill(page, '#represented\\.streetType input[type="text"]', rep_dir.tipo_via)
        await _fill_dnt_input(page, "streetName", rep_dir.direccion, group="represented")
        await _select_option_after_fill(page, '#represented\\.province input[type="text"]', rep_dir.provincia)
        await asyncio.sleep(0.7)
        await _select_option_after_fill(page, '#represented\\.city input[type="text"]', rep_dir.ciudad)
        await _fill_dnt_input(page, "zipCode", rep_dir.codigo_postal, group="represented")

    interested_same = page.get_by_label("Igual al representante", exact=False)
    if await interested_same.count() > 0 and datos.presentador.igual_que_representante:
        await interested_same.first.check()
    else:
        interes = datos.interesado
        if interes.es_empresa:
            await _fill_input(page, '#tipoDoc input[type="text"]', "CIF")
            await page.get_by_role("option", name="CIF", exact=False).first.click()
            await _fill_dnt_input(page, "numeroDoc", interes.cif, group="interested")
            await _fill_dnt_input(page, "razonSocial", interes.empresa, group="interested")
        else:
            await _fill_input(page, '#tipoDoc input[type="text"]', "NIF")
            if re.match(r"^[0-9]{8}[A-Za-z]$", interes.nif or ""):
                await page.get_by_role("option", name="NIF", exact=False).first.click()
            elif re.match(r"^[XYZ][0-9]{7}[A-Za-z]$", interes.nif or ""):
                await page.get_by_role("option", name="NIE", exact=False).first.click()
            else:
                await page.get_by_role("option", name="PASAPORTE", exact=False).first.click()
            await _fill_dnt_input(page, "docNumber", interes.nif, group="interested")
            await _fill_dnt_input(page, "name", interes.nombre.replace("Mª", "Maria"), group="interested")
            await _fill_dnt_input(page, "surname", interes.apellido1, group="interested")
            await _fill_dnt_input(page, "lastName", interes.apellido2, group="interested")

        if interes.direccion:
            d = interes.direccion
            await _select_option_after_fill(page, '#streetType input[type="text"]', d.tipo_via)
            await _fill_dnt_input(page, "streetName", d.direccion, group="interested")
            await _select_option_after_fill(page, '#interested\\.province input[type="text"]', d.provincia)
            await asyncio.sleep(0.7)
            ciudad = d.gerent_pobl if d.gerent_pobl and d.gerent_pobl != "None" else d.ciudad
            await _select_option_after_fill(page, '#interested\\.city input[type="text"]', ciudad)
            await _fill_dnt_input(page, "zipCode", d.codigo_postal, group="interested")

        await _fill_dnt_input(page, "phone", interes.telefono or "", group="interested")
        await _fill_dnt_input(page, "email", interes.email or "", group="interested")
        if interes.email:
            email_alert = page.locator('dnt-checkbox[formcontrolname="emailAlert"]')
            if await email_alert.count() > 0:
                await email_alert.first.click(force=True)

    await page.get_by_role("button", name="Siguiente").click()
    await page.wait_for_selector('text="Datos de solicitud"', timeout=config.flow_timeouts.medium_wait)

    organismo = (datos.recurso.organismo or "").strip()
    if organismo:
        org = organismo
        if org in {"AJUNTAMENT DE BARCELONA", "AYUNTAMIENTO DE BARCELONA"}:
            org = "INSTITUTO MUNICIPAL DE HACIENDA"
        if org == "CENTRO DE TRATAMIENTO DE DENUNCIAS AUTOMATIZADAS DE LEON":
            org = "E00130201"
        if org == "AYUNTAMIENTO DE PALMA":
            org = "L01070407"
        await _select_option_after_fill(page, config.selectors.destination_organism_input, org.lower())

    file_name = ""
    if datos.recurso.recent_pdf:
        file_name = str(datos.recurso.recent_pdf.get("name", ""))
    fase = _normalize_phase(datos.recurso.fase, file_name)
    asunto, expone, solicita = _build_texts_for_phase(fase, datos.recurso.expediente)

    await _fill_dnt_input(page, "subject", asunto)
    await page.locator('dnt-input[formcontrolname="exposes"] textarea').fill(expone)
    await page.locator('dnt-input[formcontrolname="solicit"] textarea').fill(solicita)

    await page.get_by_role("button", name="Siguiente").click()
    await page.locator(config.selectors.attachments_input).wait_for(
        state="attached",
        timeout=config.flow_timeouts.long_wait,
    )
    return page
