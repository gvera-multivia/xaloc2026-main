"""
Flujo de navegaciÃ³n para Madrid Ayuntamiento.
Implementa los 11 pasos documentados en explore-html/madrid-guide.md
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from core.errors import RestartWithProfileResetError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)

async def _esta_en_servcla(page: Page, config: "MadridConfig") -> bool:
    url = (page.url or "").lower()
    return (config.url_servcla_inicial_contains.lower() in url) or (
        config.url_servcla_formulario_contains.lower() in url
    )


async def _btn_continuar_post_auth_visible(page: Page, config: "MadridConfig") -> bool:
    try:
        return await page.locator(config.selectors_login.continuar_post_auth).first.is_visible(timeout=500)
    except Exception:
        return False


async def _esperar_auth_o_servcla(page: Page, config: "MadridConfig", *, timeout_ms: int) -> None:
    """
    Espera a que la autenticaciÃ³n por certificado haya terminado.

    Casos vÃ¡lidos:
    - Aparece el botÃ³n 'Continuar' post-auth (flujo clÃ¡sico).
    - Se navega directamente a servcla (cuando la sesiÃ³n ya estaba guardada).
    """
    deadline = (time.monotonic() + (timeout_ms / 1000.0)) if timeout_ms > 0 else None

    while True:
        if await _esta_en_servcla(page, config):
            return
        if await _btn_continuar_post_auth_visible(page, config):
            return
        if deadline is not None and time.monotonic() > deadline:
            raise PlaywrightTimeoutError("Timeout esperando auth (btnContinuar o servcla).")
        await page.wait_for_timeout(250)


async def _detectar_tramite_en_curso(page: Page) -> bool:
    try:
        modal = page.locator("div.modal-alert.modal-warning:visible").first
        if await modal.count() == 0:
            return False

        raw_text = (await modal.inner_text()) or ""
        text = "".join(
            c for c in unicodedata.normalize("NFD", raw_text.lower())
            if unicodedata.category(c) != "Mn"
        )
        tokens = (
            "ya esta realizando un tramite",
            "ya esta realizando",
            "tramite en curso",
            "tramite abierto",
        )
        return any(t in text for t in tokens)
    except Exception:
        return False


async def _asegurar_no_tramite_en_curso(page: Page, *, por_timeout: bool = False, paso: str = "") -> None:
    if not por_timeout:
        return
    if await _detectar_tramite_en_curso(page):
        raise RestartWithProfileResetError(
            (
                "Se ha detectado mensaje de 'tramite en curso' tras timeout "
                f"antes de formulario (paso: {paso or 'desconocido'}); reiniciar con perfil limpio."
            )
        )


async def _detectar_problema_autenticacion(page: Page) -> str | None:
    """
    Detecta problemas conocidos en el flujo de autenticaciÃ³n.

    Triggers:
    - ssl: mensajes de SSL handshake / ERR_SSL / SSL en tÃ­tulo o DOM.
    - acceso: "no se puede obtener acceso a esta pÃ¡gina".
    - redirigiendo: cas.madrid.es/commonauth con "Redirigiendo a Cl@ve..." que no avanza.
    """
    # Si el popup de certificado ya estÃ¡ presente, no disparar recovery.
    url = (page.url or "").lower()

    try:
        titulo = (await page.title()).lower()
    except Exception:
        titulo = ""

    if "ssl" in titulo or "err_ssl" in titulo:
        return "ssl"

    ssl_text = page.locator("text=/ssl\\s*(handshake|protocol|error)|err_ssl/i")
    try:
        if await ssl_text.first.is_visible(timeout=500):
            return "ssl"
    except Exception:
        pass

    acceso_text = page.locator("text=/no se puede obtener acceso/i")
    try:
        if "no se puede obtener acceso" in titulo or await acceso_text.first.is_visible(timeout=500):
            return "acceso"
    except Exception:
        pass

    if "cas.madrid.es" in url and "commonauth" in url:
        redir = page.locator("text=/Redirigiendo a Cl@ve/i")
        try:
            if await redir.first.is_visible(timeout=500):
                return "redirigiendo"
        except Exception:
            pass

    return None


async def _recuperar_problema_autenticacion(page: Page, config: "MadridConfig", problema: str) -> bool:
    """
    Protocolo de recuperaciÃ³n:
    - Espera pasiva 3s.
    - Si persiste, refresh.
    - Si tras refresh aparece "Confirmar reenvÃ­o de formulario", TAB->ENTER (PyAutoGUI).
    """
    logger.warning(f"RecuperaciÃ³n auth: detectado problema '{problema}' (URL: {page.url})")

    await page.wait_for_timeout(3000)
    if await _detectar_problema_autenticacion(page) is None:
        logger.info("RecuperaciÃ³n auth: el problema desapareciÃ³ tras espera pasiva")
        return True

    try:
        await page.reload(wait_until="domcontentloaded", timeout=config.navigation_timeout)
    except Exception:
        # Fallback: F5 equivalente
        try:
            await page.keyboard.press("F5")
        except Exception:
            pass

    return True


async def _click_certificado_y_aceptar_popup(page: Page, config: "MadridConfig") -> None:
    """
    Click en 'DNIe / Certificado'.
    El certificado se asume pre-inyectado en el navegador.
    """
    await page.click(config.selectors_login.certificado_login, timeout=config.navigation_timeout, force=True)
    logger.info("  -> Click en 'DNIe / Certificado'")



    # Durante ese intervalo, monitorizar errores para recovery.


async def _seleccionar_radio_por_texto(page: Page, texto: str) -> None:
    """
    Selecciona un radio cuyo label contiene el texto indicado.
    Ãštil cuando los IDs internos varÃ­an entre sesiones.
    """
    label = page.locator("label", has_text=re.compile(texto, re.IGNORECASE))
    radio = label.locator("input[type='radio']")
    if await radio.count() > 0:
        await radio.first.check()
        return


async def _manejar_pantalla_servcla_inicial(page: Page, config: "MadridConfig") -> bool:
    """
    Maneja la pantalla intermedia de 'Acceso al formulario' en servcla:
    https://servcla.madrid.es/WFORS_WBWFORS/servlet?action=inicial&fromLogin=true

    Devuelve True si la pantalla se gestionÃ³ (y se navegÃ³ a la siguiente).
    """
    if config.url_servcla_inicial_contains not in page.url:
        return False

    logger.info("PASO 8: Pantalla 'Acceso al formulario' (servcla) detectada")
    logger.info(f"  â†’ URL: {page.url}")

    # 1) Seleccionar "Tramitar una nueva solicitud" (checkboxNuevoTramite)
    # Esto dispara cargarOpciones() y el DOM se actualiza.
    await page.wait_for_selector(config.selectors_navegacion.radio_nuevo_tramite, state="visible", timeout=config.default_timeout)
    
    await page.wait_for_timeout(500) # Delay
    await page.click(config.selectors_navegacion.radio_nuevo_tramite)
    await _asegurar_no_tramite_en_curso(page)

    # 2) Tras el refresh, aparece el radio de rol (checkboxInteresado)
    await page.wait_for_selector(config.selectors_navegacion.radio_interesado, state="visible", timeout=config.default_timeout)
    
    await page.wait_for_timeout(500) # Delay
    await page.click(config.selectors_navegacion.radio_interesado)
    await _asegurar_no_tramite_en_curso(page)

    # 3) Continuar
    await page.wait_for_selector(config.selectors_navegacion.continuar_interesado, state="visible", timeout=config.default_timeout)
    
    await page.wait_for_timeout(500) # Delay
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.selectors_navegacion.continuar_interesado)

    logger.info(f"  â†’ Navegado a: {page.url}")
    return True


async def _aceptar_cookies_si_aparece(page: Page) -> None:
    """
    Intenta aceptar el banner de cookies si aparece.
    Busca mÃºltiples variantes de textos de botones de aceptaciÃ³n.
    """
    posibles = [
        r"Aceptar",
        r"Acceptar",
        r"Aceptar todo",
        r"Aceptar todas",
        r"Accept all",
        r"Accept",
        r"Acepto",
        r"Permitir todo",
        r"Permitir todas",
        r"OK",
    ]
    
    for patron in posibles:
        try:
            boton = page.get_by_role("button", name=re.compile(patron, re.IGNORECASE))
            if await boton.count() > 0:
                await boton.first.click(timeout=1500)
                logger.info(f"  â†’ Cookies aceptadas (botÃ³n: {patron})")
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue
    
    # TambiÃ©n intentar con enlaces (algunos sitios usan <a> en lugar de <button>)
    for patron in posibles:
        try:
            enlace = page.get_by_role("link", name=re.compile(patron, re.IGNORECASE))
            if await enlace.count() > 0:
                await enlace.first.click(timeout=1500)
                logger.info(f"  â†’ Cookies aceptadas (enlace: {patron})")
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue
    
    logger.debug("  â†’ No se detectÃ³ banner de cookies o ya estaba aceptado")


async def _esperar_dom_estable(page: Page, timeout_ms: int = 2000) -> None:
    """
    Espera a que el DOM estÃ© estable.
    
    NOTA: No usamos 'networkidle' porque puede haber scripts que hacen
    peticiones constantes y nunca se alcanza el estado idle.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=6000)
    except PlaywrightTimeoutError:
        logger.warning("Timeout esperando domcontentloaded, continuando...")
    
    try:
        await page.wait_for_load_state("load", timeout=10000)
    except PlaywrightTimeoutError:
        logger.warning("Timeout esperando load completo, continuando...")
    
    # Espera adicional para scripts dinÃ¡micos
    await page.wait_for_timeout(timeout_ms)


async def _cerrar_pestanas_extra(page: Page) -> None:
    """
    Cierra todas las pestaÃ±as/popups excepto la pÃ¡gina principal.
    Ãštil para eliminar pestaÃ±as abiertas por widgets sociales (Facebook, Twitter, etc.).
    """
    context = page.context
    pages = context.pages
    
    if len(pages) > 1:
        logger.info(f"  â†’ Detectadas {len(pages)} pestaÃ±as, cerrando las extras...")
        for p in pages:
            if p != page:
                try:
                    url = p.url
                    await p.close()
                    logger.info(f"  â†’ PestaÃ±a cerrada: {url[:50]}...")
                except Exception as e:
                    logger.warning(f"  â†’ Error al cerrar pestaÃ±a: {e}")


def _configurar_bloqueo_popups(page: Page) -> None:
    """
    Configura un handler para cerrar automÃ¡ticamente cualquier popup
    que se abra durante la navegaciÃ³n (redes sociales, anuncios, etc.).
    """
    context = page.context
    
    def on_page_opened(new_page):
        """Handler que cierra popups no deseados automÃ¡ticamente."""
        async def cerrar_popup():
            try:
                url = new_page.url
                # Lista de dominios a bloquear
                dominios_bloqueados = [
                    "facebook.com",
                    "twitter.com",
                    "x.com",
                    "instagram.com",
                    "linkedin.com",
                    "youtube.com",
                    "whatsapp.com",
                    "telegram.org",
                    "pinterest.com",
                    "tiktok.com",
                ]
                
                # Verificar si es un popup de redes sociales
                for dominio in dominios_bloqueados:
                    if dominio in url:
                        logger.info(f"  â†’ Bloqueando popup de {dominio}: {url[:50]}...")
                        await new_page.close()
                        return
                
                # Si es about:blank, esperar un momento y verificar de nuevo
                if url == "about:blank":
                    await new_page.wait_for_timeout(1000)
                    url = new_page.url
                    for dominio in dominios_bloqueados:
                        if dominio in url:
                            logger.info(f"  â†’ Bloqueando popup de {dominio}: {url[:50]}...")
                            await new_page.close()
                            return
                
                logger.warning(f"  â†’ Popup inesperado abierto: {url[:80]}")
            except Exception as e:
                logger.debug(f"  â†’ Error procesando popup: {e}")
        
        # Ejecutar el cierre de forma asÃ­ncrona
        asyncio.create_task(cerrar_popup())
    
    # Registrar el handler
    context.on("page", on_page_opened)
    logger.debug("  â†’ Handler de bloqueo de popups configurado")


async def ejecutar_navegacion_madrid(page: Page, config: MadridConfig) -> Page:
    """
    Ejecuta la navegaciÃ³n completa desde la pÃ¡gina base hasta el formulario.
    
    Pasos implementados (segÃºn madrid-guide.md):
    1. Click "Tramitar en lÃ­nea"
    2. Click "Registro ElectrÃ³nico"
    3. Click primer "Continuar"
    4. Click "Iniciar tramitaciÃ³n"
    5. Click "DNIe / Certificado"
    6. Manejar popup de certificado Windows
    7. Click "Continuar" post-autenticaciÃ³n
    8. Seleccionar "Tramitar nueva solicitud"
    9. Seleccionar "Persona o Entidad interesada" + Continuar
    10. Condicional: Click "Nuevo trÃ¡mite" si existe
    11. Verificar llegada al formulario
    
    Args:
        page: PÃ¡gina de Playwright
        config: ConfiguraciÃ³n del sitio Madrid
        
    Returns:
        Page: PÃ¡gina de Playwright en el formulario final
    """
    
    # Delay entre pasos de navegaciÃ³n (demo)
    DELAY_ENTRE_PASOS = int(config.delay_ms or config.flow_timeouts.short_delay)
    
    # ========================================================================
    # CONFIGURACIÃ“N INICIAL: Bloqueo de popups de redes sociales
    # ========================================================================
    # Configurar handler para cerrar automÃ¡ticamente popups de Facebook, etc.
    _configurar_bloqueo_popups(page)
    logger.info("  â†’ Bloqueo de popups de redes sociales activado")
    
    # Cerrar cualquier pestaÃ±a extra que pueda haber quedado de ejecuciones anteriores
    await _cerrar_pestanas_extra(page)
    
    # ========================================================================
    # DETECCIÃ“N DE SESIÃ“N: Â¿Ya estamos dentro o autenticados?
    # ========================================================================
    url_actual = page.url or ""
    if config.url_servcla_inicial_contains in url_actual or config.url_servcla_formulario_contains in url_actual:
        logger.info("  â†’ SesiÃ³n ya activa detectada por URL. Saltando a selecciÃ³n de formulario.")
        goto_servcla = True
    else:
        # Verificar si por algÃºn motivo ya estamos autenticados aunque no estemos en la URL final
        # (ej: si aparece el botÃ³n 'Continuar' post-auth en lugar de login)
        boton_continuar = page.locator(config.selectors_login.continuar_post_auth)
        try:
            if await boton_continuar.is_visible(timeout=2000):
                logger.info("  â†’ Detectado botÃ³n post-auth. SesiÃ³n probablemente activa.")
                goto_servcla = True
            else:
                goto_servcla = False
        except Exception:
            goto_servcla = False

    if not goto_servcla:
        # ========================================================================
        # PASO 1: Navegar a URL base y click "Tramitar en lÃ­nea"
        # ========================================================================
        logger.info("PASO 1: Navegando a pÃ¡gina base y clickando 'Tramitar en lÃ­nea'")
        await page.goto(config.url_base, wait_until="domcontentloaded", timeout=config.navigation_timeout)
        await _asegurar_no_tramite_en_curso(page)
        logger.info(f"  â†’ URL cargada: {page.url}")
        
        # Esperar estabilizaciÃ³n del DOM (mÃ¡s tiempo)
        await _esperar_dom_estable(page, timeout_ms=config.flow_timeouts.dom_stable)
        
        # Aceptar cookies si aparecen
        await _aceptar_cookies_si_aparece(page)
        
        # Delay adicional para parecer mÃ¡s humano
        await page.wait_for_timeout(DELAY_ENTRE_PASOS)
        
        # Esperar y clickar el botÃ³n "Tramitar en lÃ­nea"
        await page.wait_for_selector(config.selectors_navegacion.boton_tramitar, state="visible", timeout=config.default_timeout)
        await page.click(config.selectors_navegacion.boton_tramitar)
        logger.info(f"  â†’ Click en botÃ³n 'Tramitar en lÃ­nea' ({config.selectors_navegacion.boton_tramitar})")
        
        # Esperar a que aparezca el bloque #verTodas
        await page.wait_for_selector(config.selectors_navegacion.bloque_tramitar, state="visible", timeout=config.default_timeout)
        logger.info(f"  â†’ Bloque de tramitaciÃ³n visible ({config.selectors_navegacion.bloque_tramitar})")
        
        # Delay antes del siguiente paso
        await page.wait_for_timeout(DELAY_ENTRE_PASOS)
        
        # ========================================================================
        # PASO 2: Click "Registro ElectrÃ³nico"
        # ========================================================================
        logger.info("PASO 2: Clickando 'Registro ElectrÃ³nico'")
        await page.wait_for_selector(config.selectors_navegacion.registro_electronico, state="visible", timeout=config.default_timeout)
        
        # Click y esperar navegaciÃ³n a servpub.madrid.es
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
            await page.click(config.selectors_navegacion.registro_electronico)
        await _asegurar_no_tramite_en_curso(page)
        
        logger.info(f"  â†’ Navegado a: {page.url}")
        
        # Esperar estabilizaciÃ³n despuÃ©s de cambio de dominio
        await _esperar_dom_estable(page, timeout_ms=config.flow_timeouts.dom_stable)
        
        # Aceptar cookies en nuevo dominio si aparecen
        await _aceptar_cookies_si_aparece(page)
        
        # Delay antes del siguiente paso
        await page.wait_for_timeout(DELAY_ENTRE_PASOS)
        
        # ========================================================================
        # PASO 3: Click primer "Continuar"
        # ========================================================================
        logger.info("PASO 3: Clickando primer botÃ³n 'Continuar'")
        try:
            await page.wait_for_selector(config.selectors_navegacion.continuar_1, state="visible", timeout=config.default_timeout)
        except PlaywrightTimeoutError:
            # Comprobar si es la pantalla de "trÃ¡mite en curso" â†’ reinicio del navegador
            if await _detectar_tramite_en_curso(page):
                logger.warning("  ! Detectada pantalla 'trÃ¡mite en curso' en PASO 3")
                raise RestartWithProfileResetError(
                    "Pantalla 'trÃ¡mite en curso' detectada en PASO 3; reiniciar con perfil limpio."
                )
            raise
        
        try:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
                await page.click(config.selectors_navegacion.continuar_1)
        except PlaywrightTimeoutError:
            await _asegurar_no_tramite_en_curso(page, por_timeout=True, paso="PASO 3")
            raise
        
        logger.info(f"  â†’ Navegado a: {page.url}")
        
        # Esperar estabilizaciÃ³n
        await _esperar_dom_estable(page, timeout_ms=config.flow_timeouts.dom_stable)
        
        # Delay antes del siguiente paso
        await page.wait_for_timeout(DELAY_ENTRE_PASOS)
        
        # ========================================================================
        # PASO 4: Click "Iniciar tramitaciÃ³n"
        # ========================================================================
        logger.info("PASO 4: Clickando 'Iniciar tramitaciÃ³n'")
        await page.wait_for_selector(config.selectors_login.iniciar_tramitacion, state="visible", timeout=config.default_timeout)
        
        # Delay antes de la acciÃ³n que llevarÃ¡ a la pasarela de certificados
        await page.wait_for_timeout(DELAY_ENTRE_PASOS)
        
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
            await page.click(config.selectors_login.iniciar_tramitacion)
        await _asegurar_no_tramite_en_curso(page)
        
        logger.info(f"  â†’ Navegado a pantalla de login: {page.url}")
        
        # Esperar estabilizaciÃ³n despuÃ©s de llegar a la pasarela
        await _esperar_dom_estable(page, timeout_ms=config.flow_timeouts.dom_stable)
        
        # Aceptar cookies en dominio de login si aparecen
        await _aceptar_cookies_si_aparece(page)
        
        # Delay extra antes del paso de certificado (demo)
        await page.wait_for_timeout(int(getattr(config, "delay_ms", 500)))
        
        # ========================================================================
        # PASO 5: Click "DNIe / Certificado"
        # ========================================================================
        logger.info("PASO 5: Seleccionando mÃ©todo de acceso 'DNIe / Certificado'")
        # Nota: cuando la sesiÃ³n ya estÃ¡ guardada (trÃ¡mite anterior), Madrid puede saltarse
        # la pantalla de DNIe/certificado y navegar directo a servcla. Evitamos timeouts.
        if await _esta_en_servcla(page, config):
            logger.info("  â†’ SesiÃ³n activa: ya estamos en servcla; saltando DNIe/certificado")
        elif await _btn_continuar_post_auth_visible(page, config):
            logger.info("  â†’ SesiÃ³n activa: botÃ³n 'Continuar' post-auth ya visible; saltando DNIe/certificado")
        else:
            # Puede ocurrir que Madrid navegue automÃ¡ticamente a servcla (sesiÃ³n guardada)
            # y el selector de certificado nunca llegue a aparecer. Esperamos de forma
            # robusta a uno de: certificado, btnContinuar, o servcla.
            deadline = time.monotonic() + (config.default_timeout / 1000.0)
            while True:
                if await _esta_en_servcla(page, config) or await _btn_continuar_post_auth_visible(page, config):
                    logger.info("  â†’ SesiÃ³n activa detectada durante la espera; saltando click certificado")
                    break
                try:
                    await page.wait_for_selector(config.selectors_login.certificado_login, state="attached", timeout=500)
                    break
                except PlaywrightTimeoutError:
                    if time.monotonic() > deadline:
                        raise

            if await _esta_en_servcla(page, config) or await _btn_continuar_post_auth_visible(page, config):
                # Ya estamos autenticados o hemos saltado a servcla.
                pass
            else:
                # Delay antes de hacer click en certificado
                await page.wait_for_timeout(DELAY_ENTRE_PASOS)

                # ========================================================================
                # PASO 6: Manejar popup de certificado Windows
                # ========================================================================
                logger.info("PASO 6: Preparando manejo de popup de certificado Windows")

                # Click + monitorizaciÃ³n previa
                await _click_certificado_y_aceptar_popup(page, config)

                # Esperar a que la autenticaciÃ³n complete:
                # - aparece btnContinuar, o
                # - se navega directamente a servcla (sesiÃ³n ya guardada)
                try:
                    await _esperar_auth_o_servcla(page, config, timeout_ms=config.flow_timeouts.auth_wait)
                    logger.info("  -> Autenticacion completada (btnContinuar o servcla)")
                except PlaywrightTimeoutError:
                    if getattr(config.navegador, "headless", False):
                        raise RuntimeError("Madrid: timeout esperando autenticaciÃ³n post-certificado.")
                    logger.warning("  ! Timeout de automatizaciÃ³n (15s). Esperando intervenciÃ³n manual...")
                    await _esperar_auth_o_servcla(page, config, timeout_ms=0)

                problema = await _detectar_problema_autenticacion(page)
                if problema:
                    await _recuperar_problema_autenticacion(page, config, problema)
        
        # ========================================================================
        # PASO 7: Click "Continuar" post-autenticaciÃ³n
        # ========================================================================
        logger.info("PASO 7: Clickando 'Continuar' tras autenticaciÃ³n")
        if await _esta_en_servcla(page, config):
            logger.info("  â†’ Ya estamos en servcla; no existe 'Continuar' post-auth. Saltando PASO 7.")
        else:
            await page.wait_for_timeout(DELAY_ENTRE_PASOS)

            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
                    await page.click(config.selectors_login.continuar_post_auth)
            except PlaywrightTimeoutError:
                await _asegurar_no_tramite_en_curso(page, por_timeout=True, paso="PASO 7")
                raise

            logger.info(f"  â†’ Navegado a: {page.url}")
    
    # ========================================================================
    # PASO 8-9: Acceso al formulario (pantalla intermedia servcla o flujo antiguo)
    # ========================================================================
    if config.url_servcla_formulario_contains in page.url:
        logger.info("PASO 8-9: Ya estamos en el formulario (action=opcion), saltando selecciÃ³n de acceso")
    else:
    # Si estamos en la pantalla action=inicial, gestionarla por texto (mÃ¡s robusto).
        handled = await _manejar_pantalla_servcla_inicial(page, config)
        if not handled:
            # Fallback a la ruta antigua basada en IDs (por si cambia el flujo en el futuro)
            logger.info("PASO 8: Seleccionando 'Tramitar nueva solicitud'")
            await page.wait_for_selector(config.selectors_navegacion.radio_nuevo_tramite, state="visible", timeout=config.default_timeout)
            
            # Delay
            await page.wait_for_timeout(DELAY_ENTRE_PASOS)
            await page.click(config.selectors_navegacion.radio_nuevo_tramite)
            logger.info(f"  â†’ Radio seleccionado ({config.selectors_navegacion.radio_nuevo_tramite})")
            
            # Esperar a que cargarOpciones() actualice el DOM
            await page.wait_for_selector(config.selectors_navegacion.radio_interesado, state="visible", timeout=config.default_timeout)
            logger.info("  â†’ DOM actualizado, opciones cargadas")
            
            logger.info("PASO 9: Seleccionando 'Persona o Entidad interesada'")
            
            # Delay
            await page.wait_for_timeout(DELAY_ENTRE_PASOS)
            await page.click(config.selectors_navegacion.radio_interesado)
            logger.info(f"  â†’ Radio seleccionado ({config.selectors_navegacion.radio_interesado})")
            
            await page.wait_for_selector(config.selectors_navegacion.continuar_interesado, state="visible", timeout=config.default_timeout)
            
            # Delay
            await page.wait_for_timeout(DELAY_ENTRE_PASOS)
            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
                    await page.click(config.selectors_navegacion.continuar_interesado)
            except PlaywrightTimeoutError:
                await _asegurar_no_tramite_en_curso(page, por_timeout=True, paso="PASO 9")
                raise
            logger.info(f"  â†’ Navegado a: {page.url}")
    
    # ========================================================================
    # PASO 10: Condicional - Manejar "Nuevo trÃ¡mite" si existe
    # ========================================================================
    logger.info("PASO 10: Verificando si existe trÃ¡mite a medias...")
    
    try:
        # Intentar encontrar el botÃ³n "Nuevo trÃ¡mite" (timeout corto)
        await page.wait_for_selector(
            config.selectors_navegacion.boton_nuevo_tramite_condicional,
            state="visible",
            timeout=config.flow_timeouts.short_interaction
        )
        
        logger.info("  â†’ Detectado trÃ¡mite a medias, clickando 'Nuevo trÃ¡mite'")
        
        # Delay
        await page.wait_for_timeout(DELAY_ENTRE_PASOS)
        
        try:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
                await page.click(config.selectors_navegacion.boton_nuevo_tramite_condicional)
        except PlaywrightTimeoutError:
            await _asegurar_no_tramite_en_curso(page, por_timeout=True, paso="PASO 10")
            raise
        
        logger.info(f"  â†’ Navegado a nuevo trÃ¡mite: {page.url}")
        
    except PlaywrightTimeoutError:
        logger.info("  â†’ No hay trÃ¡mite a medias, continuando normalmente")
    
    # ========================================================================
    # PASO 11: Verificar llegada al formulario
    # ========================================================================
    logger.info("PASO 11: Verificando llegada al formulario")
    
    if config.url_servcla_formulario_contains not in page.url:
        logger.info(f"  â†’ Aviso: URL no contiene action=opcion todavÃ­a: {page.url}")
    
    # Esperar a que exista un formulario (criterio genÃ©rico por ahora)
    await page.wait_for_selector(config.selectors_navegacion.formulario_llegada, state="attached", timeout=config.default_timeout)
    
    logger.info("  âœ“ Formulario detectado")
    logger.info(f"  âœ“ URL final: {page.url}")
    logger.info("=" * 80)
    logger.info("NAVEGACIÃ“N COMPLETADA EXITOSAMENTE")
    logger.info("=" * 80)
    
    return page

