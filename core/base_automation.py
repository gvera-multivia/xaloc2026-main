"""
BaseAutomation: orquestador reusable (Playwright + perfil persistente).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from core.base_config import BaseConfig


# Ruta por defecto donde se escribe el frame en vivo del screencast.
_LIVE_FRAME_DIR = Path(__file__).parent.parent.absolute() / "screenshots"
_LIVE_FRAME_FILENAME = "live_frame.jpg"


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
        self._cdp_session = None
        self._screencast_active: bool = False
        self._screencast_path: Path = _LIVE_FRAME_DIR / _LIVE_FRAME_FILENAME
        self._screencast_page: Optional[Page] = None
        self._screencast_watch_task: Optional[asyncio.Task] = None
        self._screencast_switch_lock = asyncio.Lock()

    def _create_logger(self) -> logging.Logger:
        self.config.ensure_directories()
        logger = logging.getLogger(f"xaloc_automation.{self.config.site_id}")
        logger.setLevel(logging.INFO)
        logger.propagate = False

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

        # En modo headless, --start-maximized no tiene efecto; usar --window-size explÃ­cito.
        if self.config.navegador.headless:
            args = [a for a in args if a != "--start-maximized"]
            args.append("--window-size=1920,1080")

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
        Marca que la ejecuciÃ³n tuvo un problema no fatal (p.ej. fallo de descarga final),
        para que el cierre del navegador se comporte como un fallo cuando
        XALOC_KEEP_BROWSER_OPEN=1.
        """
        self._exit_has_nonfatal_issues = True

    async def _start_browser(self) -> None:
        user_data_dir = str(self.config.navegador.perfil_path.absolute())
        args = self._build_browser_args()

        # Viewport: en headless, forzar 1920x1080; en headed, dejar que siga el tamaÃ±o de ventana.
        if self.config.navegador.headless:
            viewport_kwargs = {"viewport": {"width": 1920, "height": 1080}}
        else:
            viewport_kwargs = {"no_viewport": True}

        fingerprint = (user_data_dir, self.config.navegador.canal, self.config.navegador.headless, tuple(args))

        keep_open = os.getenv("XALOC_KEEP_BROWSER_OPEN") == "1"
        if keep_open:
            if BaseAutomation._shared_lock is None:
                BaseAutomation._shared_lock = asyncio.Lock()

            async with BaseAutomation._shared_lock:
                if BaseAutomation._shared_context and BaseAutomation._shared_fingerprint == fingerprint:
                	try:
                		self.playwright = BaseAutomation._shared_playwright
                		self.context = BaseAutomation._shared_context

                		if BaseAutomation._shared_home_page is None:
                			if self.context.pages:
                				BaseAutomation._shared_home_page = self.context.pages[0]
                			else:
                				BaseAutomation._shared_home_page = await self.context.new_page()
                		elif BaseAutomation._shared_home_page.is_closed():
                			BaseAutomation._shared_home_page = await self.context.new_page()

                		# ReutilizaciÃ³n de pestaÃ±a (XALOC_KEEP_TAB_OPEN=1)
                		if os.getenv("XALOC_KEEP_TAB_OPEN") == "1":
                			self.page = BaseAutomation._shared_home_page
                			self.logger.info("PestaÃ±a reutilizada de sesiÃ³n compartida (XALOC_KEEP_TAB_OPEN=1)")
                		else:
                			self.page = await self.context.new_page()
                			self.logger.info("Contexto compartido, pero nueva pestaÃ±a creada")

                		self.page.set_default_timeout(self.config.timeouts.general)
                		self.logger.info("Navegador reutilizado (XALOC_KEEP_BROWSER_OPEN=1)")
                		return
                	except Exception as e:
                		self.logger.warning(f"Fallo al reutilizar contexto compartido ({e}). Limpiando estado...")
                		BaseAutomation._shared_context = None
                		BaseAutomation._shared_playwright = None
                		BaseAutomation._shared_home_page = None
                		BaseAutomation._shared_fingerprint = None

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
                    **viewport_kwargs,
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

                # Mantener una pestaÃ±a "home" siempre abierta para que no se cierre la ventana.
                if self.context.pages:
                    BaseAutomation._shared_home_page = self.context.pages[0]
                else:
                    BaseAutomation._shared_home_page = await self.context.new_page()

                # ReutilizaciÃ³n de pestaÃ±a (XALOC_KEEP_TAB_OPEN=1)
                if os.getenv("XALOC_KEEP_TAB_OPEN") == "1":
                    # Usar la pestaÃ±a home como la pestaÃ±a de trabajo
                    self.page = BaseAutomation._shared_home_page
                    self.logger.info("PestaÃ±a reutilizada (XALOC_KEEP_TAB_OPEN=1)")
                else:
                    self.page = await self.context.new_page()
                    self.logger.info("Nueva pestaÃ±a creada")

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
            **viewport_kwargs,
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

            # Ã‰xito: cerrar solo la pestaÃ±a de trabajo. El contexto/playwright se
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
            self.logger.info("PestaÃ±a cerrada; navegador mantenido abierto (XALOC_KEEP_BROWSER_OPEN=1)")
            return

        if self.context:
        	try:
        		await self.context.close()
        	except Exception:
        		pass
        	finally:
        		self.context = None
        		self.page = None
        		# Si era el contexto compartido, limpiar punteros de clase
        		BaseAutomation._shared_context = None
        		BaseAutomation._shared_home_page = None

        if self.playwright:
        	try:
        		await self.playwright.stop()
        	except Exception:
        		pass
        	finally:
        		self.playwright = None
        		BaseAutomation._shared_playwright = None
        		BaseAutomation._shared_fingerprint = None
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

    async def restart_browser_with_clean_profile(self) -> None:
        """
        Reinicia el navegador eliminando antes el perfil persistente.
        """
        perfil_path = Path(self.config.navegador.perfil_path)
        prev = os.getenv("XALOC_KEEP_BROWSER_OPEN")
        try:
            os.environ["XALOC_KEEP_BROWSER_OPEN"] = "0"
            await self._stop_browser(success=False)
        finally:
            if prev is None:
                os.environ.pop("XALOC_KEEP_BROWSER_OPEN", None)
            else:
                os.environ["XALOC_KEEP_BROWSER_OPEN"] = prev

        try:
            if perfil_path.exists():
                shutil.rmtree(perfil_path, ignore_errors=True)
            perfil_path.mkdir(parents=True, exist_ok=True)
            self.logger.info("Perfil de navegador limpiado: %s", perfil_path)
        except Exception as e:
            self.logger.warning("No se pudo limpiar el perfil %s: %s", perfil_path, e)
        await self._start_browser()

    # ------------------------------------------------------------------ #
    #  CDP Screencast â€“ streaming en vivo del navegador                   #
    # ------------------------------------------------------------------ #

    async def start_screencast(self, target_page: Optional[Page] = None) -> None:
        """Inicia el CDP Screencast y escribe frames JPEG para el dashboard en vivo."""
        if self._screencast_active:
            return
        effective_page = target_page or self.page
        if not effective_page or effective_page.is_closed():
            self.logger.warning("start_screencast: no hay pagina activa.")
            return

        # Escuchar apertura de nuevas pestañas para seguirlas.
        if not hasattr(self, "_on_page_listener_attached"):
            self.context.on("page", self._handle_new_page_screencast)
            self._on_page_listener_attached = True

        ok = await self._move_screencast_to_page(effective_page, initial_start=True)
        if not ok:
            return

        if self._screencast_watch_task is None or self._screencast_watch_task.done():
            self._screencast_watch_task = asyncio.create_task(self._screencast_watch_active_page_loop())

    async def _move_screencast_to_page(self, target_page: Page, *, initial_start: bool = False) -> bool:
        if not target_page or target_page.is_closed():
            return False

        async with self._screencast_switch_lock:
            if self._screencast_page is target_page and self._screencast_active and self._cdp_session:
                return True

            try:
                if not getattr(target_page, "_screencast_close_listener_attached", False):
                    def _on_close() -> None:
                        asyncio.create_task(self._handle_screencast_page_closed(target_page))
                    target_page.on("close", _on_close)
                    setattr(target_page, "_screencast_close_listener_attached", True)
            except Exception:
                pass

            try:
                if self._cdp_session:
                    await self._cdp_session.send("Page.stopScreencast")
                    await self._cdp_session.detach()
            except Exception:
                pass
            finally:
                self._cdp_session = None
                self._screencast_active = False

            self._screencast_page = target_page
            try:
                self._cdp_session = await self.context.new_cdp_session(target_page)
            except Exception as exc:
                self.logger.warning("No se pudo abrir CDP session para screencast: %s", exc)
                return False

            _LIVE_FRAME_DIR.mkdir(parents=True, exist_ok=True)

            quality = int(os.getenv("LIVE_STREAM_QUALITY", "85"))
            max_width = int(os.getenv("LIVE_STREAM_WIDTH", "1920"))
            max_height = int(os.getenv("LIVE_STREAM_HEIGHT", "1080"))
            every_nth = int(os.getenv("LIVE_STREAM_EVERY_NTH", "2"))

            async def _on_frame(params: dict) -> None:
                try:
                    data = base64.b64decode(params["data"])
                    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jpg", dir=str(_LIVE_FRAME_DIR))
                    try:
                        os.write(tmp_fd, data)
                    finally:
                        os.close(tmp_fd)

                    success = False
                    for _ in range(3):
                        try:
                            os.replace(tmp_path, str(self._screencast_path))
                            success = True
                            break
                        except OSError:
                            await asyncio.sleep(0.01)

                    if not success:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    if self._cdp_session:
                        await self._cdp_session.send(
                            "Page.screencastFrameAck",
                            {"sessionId": params["sessionId"]},
                        )
                except Exception:
                    pass

            self._cdp_session.on("Page.screencastFrame", _on_frame)

            try:
                await self._cdp_session.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": quality,
                        "maxWidth": max_width,
                        "maxHeight": max_height,
                        "everyNthFrame": every_nth,
                    },
                )
                self._screencast_active = True
                if not initial_start:
                    self.logger.info("Screencast reenganchado a la pestaña activa.")
                return True
            except Exception as exc:
                self.logger.warning("No se pudo iniciar screencast CDP: %s", exc)
                self._cdp_session = None
                return False

    async def _page_looks_active(self, page: Page) -> bool:
        if not page or page.is_closed():
            return False
        try:
            return bool(
                await page.evaluate(
                    "() => document.hasFocus() || document.visibilityState === 'visible'"
                )
            )
        except Exception:
            return False

    async def _pick_best_screencast_page(self) -> Optional[Page]:
        if not self.context:
            return None

        candidates = [p for p in self.context.pages if not p.is_closed()]
        if not candidates:
            return None

        # Priorizar la pagina de trabajo actual de la automatizacion.
        # En algunos flujos Playwright sigue operando sobre una pestana
        # que no queda en foco visual del navegador.
        if self.page and not self.page.is_closed():
            return self.page

        for p in reversed(candidates):
            if await self._page_looks_active(p):
                return p

        if self._screencast_page and not self._screencast_page.is_closed():
            return self._screencast_page
        return candidates[-1]

    async def sync_screencast_with_page(self) -> None:
        """Sincroniza el stream con self.page cuando esta cambia en el flujo."""
        if not self._screencast_active:
            return
        if not self.page or self.page.is_closed():
            return
        if self.page is self._screencast_page:
            return
        try:
            await self._move_screencast_to_page(self.page)
        except Exception:
            pass

    async def _screencast_watch_active_page_loop(self) -> None:
        while self._screencast_active:
            try:
                best_page = await self._pick_best_screencast_page()
                if best_page and best_page is not self._screencast_page:
                    await self._move_screencast_to_page(best_page)
            except Exception:
                pass
            await asyncio.sleep(0.5)

    async def _handle_new_page_screencast(self, new_page: Page) -> None:
        """Si se abre otra pestaña, mover el visor en vivo a esa pestaña."""
        if not self._screencast_active:
            return

        self.logger.info("Nueva pestaña detectada; moviendo visor en vivo...")
        # No tocar self.page: es la pestaña de trabajo del flujo.
        try:
            await self._move_screencast_to_page(new_page)
        except Exception as e:
            self.logger.warning("Error al mover screencast a nueva pestaña: %s", e)

    async def _handle_screencast_page_closed(self, closed_page: Page) -> None:
        """Si se cierra la pestaña en stream, reenganchar a una pestaña viva."""
        if not self._screencast_active:
            return
        if closed_page is not self._screencast_page:
            return

        fallback_page: Optional[Page] = None
        if self.page and not self.page.is_closed():
            fallback_page = self.page
        elif self.context:
            for p in self.context.pages:
                if not p.is_closed():
                    fallback_page = p
                    break

        if not fallback_page:
            self.logger.warning("Screencast: se cerró la pestaña activa y no hay fallback disponible.")
            return

        self.logger.info("Screencast: pestaña cerrada; reenganchando visor a pestaña principal...")
        await self._move_screencast_to_page(fallback_page)

    async def stop_screencast(self) -> None:
        """Detiene el CDP Screencast y limpia el archivo de frame."""
        if not self._screencast_active:
            return
        try:
            if self._cdp_session:
                await self._cdp_session.send("Page.stopScreencast")
        except Exception:
            pass
        try:
            if self._cdp_session:
                await self._cdp_session.detach()
        except Exception:
            pass
        self._cdp_session = None
        self._screencast_active = False
        self._screencast_page = None
        if self._screencast_watch_task and not self._screencast_watch_task.done():
            self._screencast_watch_task.cancel()
        self._screencast_watch_task = None

        # No eliminamos el frame para que el dashboard pueda mostrar la Ãºltima vista
        # disponible mientras no haya un nuevo tramite activo.
        self.logger.info("Screencast en vivo detenido.")

    # ------------------------------------------------------------------ #

    async def capture_error_screenshot(self, filename: str = "error.png") -> Optional[Path]:
        if not self.page:
            return None
        path = self.config.dir_screenshots / filename
        try:
            # Si hay screencast activo, esto puede fallar o interferir,
            # pero Playwright suele manejarlo bien.
            await self.page.screenshot(path=path, full_page=True)
        except Exception:
            return None
        return path
