"""
BaseAutomation: orquestador reusable (Playwright + perfil persistente).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from core.base_config import BaseConfig


class BaseAutomation:
    def __init__(self, config: BaseConfig):
        self.config = config
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.logger = self._create_logger()

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
        await self._stop_browser()

    async def _start_browser(self) -> None:
        self.logger.info("Iniciando navegador con perfil persistente...")
        self.playwright = await async_playwright().start()

        user_data_dir = str(self.config.navegador.perfil_path.absolute())
        args = self._build_browser_args()

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

    async def _stop_browser(self) -> None:
        # Debug: permitir dejar el navegador abierto al finalizar la ejecución.
        # Uso: `set XALOC_KEEP_BROWSER_OPEN=1` (cmd) / `$env:XALOC_KEEP_BROWSER_OPEN='1'` (PowerShell)
        if os.getenv("XALOC_KEEP_BROWSER_OPEN") == "1":
            self.logger.info("Navegador NO cerrado (XALOC_KEEP_BROWSER_OPEN=1)")
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
        await self._stop_browser()
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
