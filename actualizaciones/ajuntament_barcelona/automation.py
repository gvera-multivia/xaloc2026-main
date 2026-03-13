from __future__ import annotations

import asyncio

from core.base_automation import BaseAutomation
from .config import AjuntamentBarcelonaConfig
from .data_models import AjuntamentBarcelonaTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion, run_multes


class AjuntamentBarcelonaAutomation(BaseAutomation):
    def __init__(self, config: AjuntamentBarcelonaConfig):
        super().__init__(config)
        self.config = config

    async def _pause_before_close(self) -> None:
        self.logger.info("ajuntament_barcelona.flujo pause END (pulsa Enter en consola para cerrar navegador)")
        await asyncio.to_thread(
            input, "Ajuntament Barcelona flujo finalizado. Pulsa Enter para cerrar el navegador..."
        )

    async def _reset_page_for_retry(self) -> None:
        """Cierra popups extra y deja self.page apuntando a la primera página viva."""
        if self.page is None:
            return
        try:
            pages = [p for p in self.page.context.pages if not p.is_closed()]
            if pages:
                self.page = pages[0]
                for extra in pages[1:]:
                    try:
                        await extra.close()
                    except Exception:
                        pass
        except Exception as err:
            self.logger.warning("ajuntament_barcelona.flujo reset_page error=%s", err)

    async def ejecutar_flujo_completo(self, datos: AjuntamentBarcelonaTarget, max_reintentos: int = 2) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        shot = self.config.dir_screenshots / "ajuntament_barcelona_standalone.png"
        total_intentos = max_reintentos + 1

        try:
            for intento in range(1, total_intentos + 1):
                if intento > 1:
                    self.logger.info(
                        "ajuntament_barcelona.flujo REINTENTO intento=%s/%s",
                        intento, total_intentos,
                    )
                    await self._reset_page_for_retry()

                current_page = self.page
                try:
                    self.logger.info(
                        "ajuntament_barcelona.flujo START intento=%s/%s numclient=%s expediente=%s",
                        intento, total_intentos,
                        datos.payload.get("numclient"),
                        datos.expediente,
                    )
                    current_page = await run_login(current_page, self.config, datos)
                    self.logger.info("ajuntament_barcelona.flujo login OK")
                    current_page = await run_formulario(current_page, self.config, datos)
                    self.logger.info("ajuntament_barcelona.flujo formulario OK")
                    current_page = await run_documentos(current_page, self.config, datos)
                    self.logger.info("ajuntament_barcelona.flujo documentos OK")
                    current_page = await run_confirmacion(current_page, self.config, datos)
                    self.logger.info("ajuntament_barcelona.flujo confirmacion OK")
                    current_page = await run_multes(current_page, self.config, datos)
                    self.logger.info("ajuntament_barcelona.flujo multes OK")

                    self.page = current_page
                    await current_page.screenshot(path=shot, full_page=True)
                    self.logger.info("ajuntament_barcelona.flujo END screenshot=%s intento=%s", shot, intento)
                    return str(shot)

                except Exception as exc:
                    self.page = current_page
                    try:
                        await current_page.screenshot(path=shot, full_page=True)
                        self.logger.info("ajuntament_barcelona.flujo ERROR screenshot=%s intento=%s", shot, intento)
                    except Exception:
                        pass
                    if intento < total_intentos:
                        self.logger.warning(
                            "ajuntament_barcelona.flujo ERROR intento=%s/%s err=%s — reintentando",
                            intento, total_intentos, exc,
                        )
                        continue
                    self.logger.error(
                        "ajuntament_barcelona.flujo FALLO_DEFINITIVO intento=%s/%s err=%s",
                        intento, total_intentos, exc,
                    )
                    raise
        finally:
            await self._pause_before_close()
        raise RuntimeError("ajuntament_barcelona: bucle de reintentos agotado sin resultado")
