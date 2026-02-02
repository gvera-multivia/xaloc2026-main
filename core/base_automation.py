"""
BaseAutomation: orquestador reusable (Playwright + perfil persistente).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from core.base_config import BaseConfig


class BaseAutomation:
    _shared_playwright = None
    _shared_context: Optional[BrowserContext] = None
    _shared_fingerprint: Optional[tuple] = None
    _shared_home_page: Optional[Page] = None
    _shared_lock: Optional[asyncio.Lock] = None

    def __init__(self, config: BaseConfig):
        self.config = config
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.logger = self._create_logger()
        self._exit_has_nonfatal_issues: bool = False

    def _create_logger(self) -> logging.Logger:
        self.config.ensure_directories()
        logger = logging.getLogger(f"xaloc_automation.{self.config.site_id}")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            log_file = self.config.dir_logs / f"{self.config.site_id}.log"
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(formatter)

            sh = logging.StreamHandler()
            sh.setFormatter(formatter)

            logger.addHandler(fh)
            logger.addHandler(sh)

        return logger

    def _build_browser_args(self) -> list[str]:
        args = list(self.config.navegador.args)

        if self.config.auto_select_certificate:
            policy = f'{{"pattern":"{self.config.auto_select_certificate_pattern}","filter":{{}}}}'
            args.append(f"--auto-select-certificate-for-urls=[{policy}]")

        if self.config.lang:
            args.append(f"--lang={self.config.lang}")

        if self.config.disable_translate_ui:
            args.append("--disable-features=TranslateUI")

        return args

    async def __aenter__(self):
        await self._start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        success = (exc_type is None) and (not self._exit_has_nonfatal_issues)
        await self._stop_browser(success=success)

    def mark_nonfatal_issue(self) -> None:
        """
        Marca que la ejecución tuvo un problema no fatal (p.ej. fallo de descarga final),
        para que el cierre del navegador se comporte como un fallo cuando
        XALOC_KEEP_BROWSER_OPEN=1.
        """
        self._exit_has_nonfatal_issues = True

    async def _start_browser(self) -> None:
        user_data_dir = str(self.config.navegador.perfil_path.absolute())
        args = self._build_browser_args()
        fingerprint = (user_data_dir, self.config.navegador.canal, self.config.navegador.headless, tuple(args))

        keep_open = os.getenv("XALOC_KEEP_BROWSER_OPEN") == "1"
        if keep_open:
            if BaseAutomation._shared_lock is None:
                BaseAutomation._shared_lock = asyncio.Lock()

            async with BaseAutomation._shared_lock:
                if BaseAutomation._shared_context and BaseAutomation._shared_fingerprint == fingerprint:
                    self.playwright = BaseAutomation._shared_playwright
                    self.context = BaseAutomation._shared_context

                    if BaseAutomation._shared_home_page is None:
                        if self.context.pages:
                            BaseAutomation._shared_home_page = self.context.pages[0]
                        else:
                            BaseAutomation._shared_home_page = await self.context.new_page()

                    self.page = await self.context.new_page()
                    self.page.set_default_timeout(self.config.timeouts.general)
                    self.logger.info("Navegador reutilizado (XALOC_KEEP_BROWSER_OPEN=1)")
                    return

                if BaseAutomation._shared_context and BaseAutomation._shared_fingerprint != fingerprint:
                    self.logger.warning(
                        "Navegador compartido incompatible; reiniciando contexto persistente (XALOC_KEEP_BROWSER_OPEN=1)"
                    )
                    try:
                        await BaseAutomation._shared_context.close()
                    except Exception:
                        pass
                    try:
                        if BaseAutomation._shared_playwright:
                            await BaseAutomation._shared_playwright.stop()
                    except Exception:
                        pass
                    BaseAutomation._shared_context = None
                    BaseAutomation._shared_playwright = None
                    BaseAutomation._shared_fingerprint = None
                    BaseAutomation._shared_home_page = None

                self.logger.info("Iniciando navegador con perfil persistente (compartido)...")
                self.playwright = await async_playwright().start()
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel=self.config.navegador.canal,
                    headless=self.config.navegador.headless,
                    args=args,
                    ignore_https_errors=True,
                    accept_downloads=True,
                )

                BaseAutomation._shared_playwright = self.playwright
                BaseAutomation._shared_context = self.context
                BaseAutomation._shared_fingerprint = fingerprint

                if self.config.stealth_disable_webdriver:
                    try:
                        await self.context.add_init_script(
                            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                        )
                    except Exception:
                        pass

                # Mantener una pestaña "home" siempre abierta para que no se cierre la ventana.
                if self.context.pages:
                    BaseAutomation._shared_home_page = self.context.pages[0]
                else:
                    BaseAutomation._shared_home_page = await self.context.new_page()

                self.page = await self.context.new_page()
                self.page.set_default_timeout(self.config.timeouts.general)
                self.logger.info("Navegador listo (compartido)")
                return

        self.logger.info("Iniciando navegador con perfil persistente...")
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel=self.config.navegador.canal,
            headless=self.config.navegador.headless,
            args=args,
            ignore_https_errors=True,
            accept_downloads=True,
        )

        if self.config.stealth_disable_webdriver:
            try:
                await self.context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
            except Exception:
                pass

        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        self.page.set_default_timeout(self.config.timeouts.general)
        self.logger.info("Navegador listo")

    async def _stop_browser(self, *, success: bool) -> None:
        keep_open = os.getenv("XALOC_KEEP_BROWSER_OPEN") == "1"
        if keep_open:
            if os.getenv("XALOC_KEEP_TAB_OPEN") == "1":
                self.logger.info("PestaÃ±a y navegador mantenidos abiertos (XALOC_KEEP_TAB_OPEN=1)")
                return
            if not success:
                self.logger.info("Navegador NO cerrado (XALOC_KEEP_BROWSER_OPEN=1)")
                return

            # Éxito: cerrar solo la pestaña de trabajo. El contexto/playwright se
            # mantienen abiertos para reutilizar el navegador entre tareas.
            if self.page:
                try:
                    await self.page.close()
                except Exception:
                    pass
                finally:
                    self.page = None

            self.context = None
            self.playwright = None
            self._exit_has_nonfatal_issues = False
            self.logger.info("Pestaña cerrada; navegador mantenido abierto (XALOC_KEEP_BROWSER_OPEN=1)")
            return

        if self.context:
            try:
                await self.context.close()
            finally:
                self.context = None
                self.page = None
        if self.playwright:
            try:
                await self.playwright.stop()
            finally:
                self.playwright = None
        self.logger.info("Navegador cerrado")

    async def restart_browser(self) -> None:
        """
        Cierra por completo el navegador/contexto y lo vuelve a abrir con el mismo perfil.
        """
        # Forzar cierre real aunque XALOC_KEEP_BROWSER_OPEN=1
        prev = os.getenv("XALOC_KEEP_BROWSER_OPEN")
        try:
            os.environ["XALOC_KEEP_BROWSER_OPEN"] = "0"
            await self._stop_browser(success=False)
        finally:
            if prev is None:
                os.environ.pop("XALOC_KEEP_BROWSER_OPEN", None)
            else:
                os.environ["XALOC_KEEP_BROWSER_OPEN"] = prev
        await self._start_browser()

    async def capture_error_screenshot(self, filename: str = "error.png") -> Optional[Path]:
        if not self.page:
            return None
        path = self.config.dir_screenshots / filename
        try:
            await self.page.screenshot(path=path, full_page=True)
        except Exception:
            return None
        return path
