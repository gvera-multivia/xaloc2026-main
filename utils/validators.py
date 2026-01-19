from playwright.async_api import Page, Locator
import logging

class ValidationError(Exception):
    """Excepción específica para fallos de validación de estado"""
    pass

async def validar_elemento_visible(
    page: Page, 
    selector: str, 
    timeout: int = 5000, 
    descripcion: str = "Elemento"
) -> bool:
    """
    Verifica que un elemento esté visible en la página.
    Lanza ValidationError si no aparece en el tiempo estipulado.
    """
    try:
        await page.wait_for_selector(selector, state="visible", timeout=timeout)
        logging.info(f"Validacion exitosa: {descripcion} es visible")
        return True
    except Exception as e:
        msg = f"Validacion fallida: {descripcion} no aparecio tras {timeout}ms"
        logging.error(msg)
        raise ValidationError(msg) from e

async def validar_texto_en_pagina(
    page: Page, 
    texto: str, 
    timeout: int = 5000
) -> bool:
    """Valida que un texto específico esté presente en el body visible"""
    try:
        # Usamos locator con has-text para buscar texto visible
        await page.wait_for_selector(f"text={texto}", timeout=timeout)
        logging.info(f"Texto encontrado: '{texto}'")
        return True
    except Exception:
        raise ValidationError(f"El texto '{texto}' no se encontro en la pagina")

async def validar_valor_campo(
    locator: Locator, 
    valor_esperado: str
) -> bool:
    """Valida que un campo de input tenga el valor correcto"""
    valor_actual = await locator.input_value()
    if valor_actual != valor_esperado:
        raise ValidationError(
            f"Campo incorrecto. Esperado: '{valor_esperado}', Actual: '{valor_actual}'"
        )
    return True

async def validar_archivo_subido(
    page: Page, 
    nombre_archivo: str,
    timeout: int = 5000
) -> bool:
    """
    Verifica visualmente que el archivo aparece en la lista de adjuntos.
    Busca el nombre del archivo en el DOM.
    """
    try:
        # Buscamos el texto del nombre del archivo en alguna parte de la UI
        await page.wait_for_selector(f"text={nombre_archivo}", timeout=timeout)
        logging.info(f"Archivo validado en UI: {nombre_archivo}")
        return True
    except Exception:
        raise ValidationError(f"No se detecto confirmacion de subida para: {nombre_archivo}")
