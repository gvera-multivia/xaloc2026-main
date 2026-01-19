from playwright.async_api import Page
import logging
import asyncio
from ..config import RedSaraConfig
from ..data_models import DatosRepresentante, DatosPresentador, DatosInteresado
from utils.validators import (
    validar_elemento_visible, 
    validar_valor_campo
)
# Nota: capturar_reconocimiento_formulario se omite si no es crítico, 
# o se adapta si se migra la carpeta utils de redsara.
# from ..utils.recon import capturar_reconocimiento_formulario

async def rellenar_seccion_direccion(page: Page, tipo_persona: str, datos_dir):
    """
    Rellena una sección de dirección (representante o presentador).
    tipo_persona: 'represented' o 'presentador'
    """
    prefix = f"{tipo_persona}" 
    logging.info(f"📍 Rellenando dirección para: {tipo_persona}")

    # 1. Tipo de vía (Autocomplete)
    selector_via = f'[id="{prefix}.streetType"] input[type="text"]'
    if not await page.locator(selector_via).count():
         selector_via = f'[id="{prefix}.streetType"] .dnt-select__input' 

    await page.locator(selector_via).first.click()
    await page.locator(selector_via).first.fill(datos_dir.tipo_via)
    
    opcion_via = page.get_by_role("option", name=datos_dir.tipo_via, exact=False).first
    await opcion_via.wait_for()
    await opcion_via.click()
    
    if tipo_persona == "represented":
        idx = 0 
    else:
        idx = 1
    
    # Input Dirección
    await page.get_by_label("Dirección").nth(idx).fill(datos_dir.direccion)
    
    # 3. Provincia (Autocomplete)
    selector_prov = f'[id="{prefix}.province"] input[type="text"]'
    await page.locator(selector_prov).first.click()
    await page.locator(selector_prov).first.fill(datos_dir.provincia)
    await page.get_by_role("option", name=datos_dir.provincia, exact=False).first.click()
    
    # 4. Ciudad (Autocomplete - Depende de provincia)
    await asyncio.sleep(1) 
    selector_city = f'[id="{prefix}.city"] input[type="text"]'
    
    try:
        await page.locator(selector_city).first.wait_for(state="visible", timeout=5000)
        await page.wait_for_function(f"document.querySelector('{selector_city}') && !document.querySelector('{selector_city}').disabled", timeout=5000)
    except Exception:
         logging.warning("El campo ciudad parece no estar habilitado o visible a tiempo.")

    await page.locator(selector_city).first.click()
    await page.locator(selector_city).first.fill(datos_dir.ciudad)
    
    opcion_ciudad = page.get_by_role("option", name=datos_dir.ciudad, exact=False).first
    try:
        await opcion_ciudad.wait_for(state="visible", timeout=5000)
        await opcion_ciudad.click(force=True)
    except Exception as e:
        logging.error(f"No se pudo seleccionar la ciudad '{datos_dir.ciudad}': {e}")
    
    # 5. Código Postal
    await page.get_by_role("textbox", name="Introduce C.P.").nth(idx).fill(datos_dir.codigo_postal)

async def _fill_dnt_textarea(page: Page, formcontrolname: str, value: str, label: str = None):
    """Helper para rellenar dnt-input type='textarea'"""
    if not value:
        return
    logging.info(f"Rellenando area de texto {formcontrolname} ({label})")
    selector = f'dnt-input[formcontrolname="{formcontrolname}"] textarea'
    try:
        if await page.locator(selector).count() > 0:
            await page.locator(selector).fill(value)
            return
        if label:
            lbl_loc = page.get_by_label(label, exact=False)
            if await lbl_loc.count() > 0 and await lbl_loc.first.is_visible():
                await lbl_loc.first.fill(value)
                return
        logging.warning(f"No se encontro textarea para {formcontrolname}")
    except Exception as e:
        logging.error(f"Error rellenando textarea {formcontrolname}: {e}")

async def rellenar_paso_2(page: Page, config: RedSaraConfig):
    """Rellena los campos del Paso 2: Datos de solicitud"""
    logging.info("📝 Rellenando Paso 2: Datos de solicitud")
    
    if config.organismo:
        logging.info(f"Seleccionando organismo: {config.organismo}")
        try:
            await page.locator('#destinationOrganism input[type="text"]').click()
            await asyncio.sleep(0.5)
            input_organismo = page.locator('#destinationOrganism input[type="text"]')
            await input_organismo.fill(config.organismo)
            await asyncio.sleep(0.5)
            await input_organismo.press("Space")
            await asyncio.sleep(1) 
            await page.get_by_role("option").first.click()
        except Exception as e:
             logging.error(f"Error seleccionando organismo: {e}")

    if config.asunto:
         await _fill_dnt_input(page, "subject", config.asunto, "Asunto")
    if config.expone:
        await _fill_dnt_textarea(page, "exposes", config.expone, "Expone")
    if config.solicita:
        await _fill_dnt_textarea(page, "solicit", config.solicita, "Solicita")
        
    logging.info("➡️ Avanzando al Paso 3: Documentación")
    boton_siguiente = page.get_by_role("button", name="Siguiente")
    await boton_siguiente.click()
    
    try:
        await page.wait_for_selector('text="Documentación"', timeout=10000)
    except:
        await asyncio.sleep(2)

async def _fill_dnt_input(page: Page, formcontrolname: str, value: str, label: str = None, group: str = None):
    """Helper robusto para rellenar dnt-input con soporte de agrupación"""
    if not value:
        return
    logging.info(f"Rellenando campo {formcontrolname} ({label}) [Group: {group}]")
    locators = []
    prefix = f'div[formgroupname="{group}"] ' if group else ""
    locators.append(page.locator(f'{prefix}dnt-input[formcontrolname="{formcontrolname}"] input:not([type="hidden"])'))
    if label:
        if group:
             locators.append(page.locator(f'div[formgroupname="{group}"]').get_by_label(label, exact=False))
        else:
             locators.append(page.get_by_label(label, exact=False))
    locators.append(page.locator(f'{prefix}input[formcontrolname="{formcontrolname}"]'))
    locators.append(page.locator(f'#{formcontrolname} input:not([type="hidden"])'))

    filled = False
    for loc in locators:
        try:
            if await loc.count() > 0:
                target = loc.first
                if await target.is_visible():
                    await target.fill(value)
                    filled = True
                    break
        except Exception:
            continue
    if not filled:
        logging.warning(f"No se pudo rellenar campo {formcontrolname} (Group: {group}).")

async def rellenar_formulario(
    page: Page, 
    datos_repre: DatosRepresentante, 
    datos_pres: DatosPresentador,
    datos_interesado: DatosInteresado,
    config: RedSaraConfig
) -> None:
    """Orquesta el rellenado de todo el formulario"""
    logging.info("📝 Iniciando rellenado de formulario")
    
    # 1. Selección inicial: ¿Es representante?
    if datos_repre.es_representante:
        logging.info("Seleccionando opcion 'Representante'")
        selector_repre = page.get_by_label("Representante", exact=False)
        if await selector_repre.count() > 0:
            await selector_repre.first.click(force=True)
            await asyncio.sleep(1) 
    
    # 2. Datos del Representante
    await _fill_dnt_input(page, "email", datos_repre.email, "Correo electrónico", group="represented")
    await _fill_dnt_input(page, "phone", datos_repre.telefono, "Teléfono", group="represented")
    await rellenar_seccion_direccion(page, "represented", datos_repre.direccion)
    
    check = page.get_by_label("Igual al representante")
    if await check.count() > 0 and await check.is_visible():
        if datos_pres.igual_que_representante:
            await check.check()
    else:
        logging.info("Checkbox 'Igual al representante' no encontrado. Rellenando Interesado manualmente.")
        await page.locator('#tipoDoc input[type="text"]').click()
        await page.get_by_role("option", name=datos_interesado.tipo_documento, exact=False).click()
        await _fill_dnt_input(page, "docNumber", datos_interesado.nif, "Número identificación", group="interested")
        await _fill_dnt_input(page, "name", datos_interesado.nombre, "Nombre", group="interested")
        await _fill_dnt_input(page, "surname", datos_interesado.apellido, "Primer apellido", group="interested")
        if datos_interesado.segundo_apellido:
             await _fill_dnt_input(page, "lastName", datos_interesado.segundo_apellido, "Segundo apellido", group="interested")

        dir_interesado = datos_interesado.direccion if datos_interesado.direccion else datos_repre.direccion
        await page.locator('#streetType input[type="text"]').click()
        await page.fill('#streetType input[type="text"]', dir_interesado.tipo_via)
        await page.get_by_role("option", name=dir_interesado.tipo_via, exact=False).first.click()
        await _fill_dnt_input(page, "streetName", dir_interesado.direccion, "Dirección", group="interested")
        
        await page.locator('#interested\\.province input[type="text"]').click() 
        await page.locator('#interested\\.province input[type="text"]').fill(dir_interesado.provincia)
        await page.get_by_role("option", name=dir_interesado.provincia, exact=False).first.click()
        
        await asyncio.sleep(1)
        await page.locator('#interested\\.city input[type="text"]').click()
        await page.locator('#interested\\.city input[type="text"]').fill(dir_interesado.ciudad)
        await page.get_by_role("option", name=dir_interesado.ciudad, exact=False).first.click()
        
        await _fill_dnt_input(page, "zipCode", dir_interesado.codigo_postal, "Código Postal", group="interested")

        if datos_interesado.telefono:
             await _fill_dnt_input(page, "phone", datos_interesado.telefono, "Teléfono", group="interested")
        if datos_interesado.email:
             await _fill_dnt_input(page, "email", datos_interesado.email, "Correo electrónico", group="interested")
             await page.locator('dnt-checkbox[formcontrolname="emailAlert"]').click()
             
    logging.info("➡️ Avanzando al Paso 2: Datos de solicitud")
    boton_siguiente = page.get_by_role("button", name="Siguiente")
    await boton_siguiente.click()
    
    try:
        await page.wait_for_selector('text="Datos de solicitud"', timeout=5000)
    except:
        await asyncio.sleep(3)

    await rellenar_paso_2(page, config)
