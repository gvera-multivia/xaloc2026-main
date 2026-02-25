from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from core.errors import RestartRequiredError, RestartWithProfileResetError, RetryWithoutAttemptError
from core.site_registry import get_site, get_site_controller
from .models import ProcessOutcome
from .utils import call_with_supported_kwargs

logger = logging.getLogger("worker.browser_executor")


async def execute_browser_flow(
    *,
    site_id: str,
    protocol: Optional[str],
    payload: dict,
    archivos_para_subir: list[Path],
) -> ProcessOutcome:
    original_payload = dict(payload)
    prev_keep_browser_open = os.getenv("XALOC_KEEP_BROWSER_OPEN")
    prev_keep_tab_open = os.getenv("XALOC_KEEP_TAB_OPEN")
    screencast_enabled = (os.getenv("XALOC_ENABLE_CDP_SCREENCAST") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        controller = get_site_controller(site_id)
        AutomationCls = get_site(site_id)

        headless = 1 if os.getenv("XALOC_HEADLESS") == "1" else 0
        config = call_with_supported_kwargs(controller.create_config, headless=headless, protocol=protocol)
        config.navegador.perfil_path = Path("profiles/worker").absolute()

        mapped_data = controller.map_data(payload)
        mapped_data.update({"protocol": protocol, "headless": headless})

        if site_id == "madrid":
            mapped_data["archivos"] = archivos_para_subir
        elif site_id == "xaloc_girona":
            mapped_data["archivos_adjuntos"] = archivos_para_subir
        elif site_id == "base_online":
            if not protocol:
                raise ValueError("Falta 'protocol' para tareas del site 'base_online'.")
            key = f"{protocol.upper().strip().lower()}_archivos"
            mapped_data[key] = archivos_para_subir
        elif site_id == "ayunta_palma":
            mapped_data["archivos"] = archivos_para_subir

        datos = call_with_supported_kwargs(controller.create_target, **mapped_data)
        keep_browser_open_disabled = (os.getenv("XALOC_DISABLE_KEEP_BROWSER_OPEN") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if (not keep_browser_open_disabled) and site_id in ["madrid", "base_online", "ayunta_palma"]:
            os.environ["XALOC_KEEP_BROWSER_OPEN"] = "1"
            os.environ["XALOC_KEEP_TAB_OPEN"] = "0" if site_id == "ayunta_palma" else "1"

        async with AutomationCls(config) as bot:
            if screencast_enabled:
                try:
                    await bot.start_screencast()
                except Exception as exc:
                    logger.warning("No se pudo iniciar screencast: %s", exc)
            try:
                screenshot_path = await bot.ejecutar_flujo_completo(datos)
            except RestartRequiredError as e:
                screenshot_path = None
                try:
                    screenshot_path = await bot.capture_error_screenshot("restart_required.png")
                except Exception:
                    pass
                try:
                    if isinstance(e, RestartWithProfileResetError):
                        await bot.restart_browser_with_clean_profile()
                    else:
                        await bot.restart_browser()
                except Exception:
                    pass
                return ProcessOutcome(
                    success=False,
                    error=f"RestartRequiredError: {e}",
                    screenshot=str(screenshot_path) if screenshot_path else None,
                    release_without_attempt=True,
                    payload_updates=payload,
                )
            except RetryWithoutAttemptError as e:
                screenshot_path = None
                try:
                    screenshot_path = await bot.capture_error_screenshot("retry_without_attempt.png")
                except Exception:
                    pass
                try:
                    await bot.restart_browser()
                except Exception:
                    pass
                return ProcessOutcome(
                    success=False,
                    error=str(e),
                    screenshot=str(screenshot_path) if screenshot_path else None,
                    release_without_attempt=True,
                    payload_updates=payload,
                )
            except PlaywrightTimeoutError as e:
                screenshot_path = None
                try:
                    screenshot_path = await bot.capture_error_screenshot("playwright_timeout.png")
                except Exception:
                    pass
                error_detail = str(e).strip()
                error_msg = "Timeout de Playwright"
                if error_detail:
                    error_msg = f"{error_msg}: {error_detail[:260]}"
                return ProcessOutcome(
                    success=False,
                    error=error_msg,
                    screenshot=str(screenshot_path) if screenshot_path else None,
                    payload_updates=payload,
                )
            except PlaywrightError as e:
                return ProcessOutcome(
                    success=False,
                    error=f"Error de Playwright: {e}",
                    payload_updates=payload,
                )
            else:
                payload_updates = payload if payload != original_payload else {}
                return ProcessOutcome(
                    success=True,
                    screenshot=str(screenshot_path) if screenshot_path else None,
                    payload_updates=payload_updates,
                )
            finally:
                if screencast_enabled:
                    try:
                        await bot.stop_screencast()
                    except Exception:
                        pass
    finally:
        if prev_keep_browser_open is None:
            os.environ.pop("XALOC_KEEP_BROWSER_OPEN", None)
        else:
            os.environ["XALOC_KEEP_BROWSER_OPEN"] = prev_keep_browser_open
        if prev_keep_tab_open is None:
            os.environ.pop("XALOC_KEEP_TAB_OPEN", None)
        else:
            os.environ["XALOC_KEEP_TAB_OPEN"] = prev_keep_tab_open
