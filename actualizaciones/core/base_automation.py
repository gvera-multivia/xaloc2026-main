"""
BaseAutomation: orquestador reusable (Playwright + perfil persistente).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

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
    _DEFAULT_CERT_PATTERNS: tuple[str, ...] = (
        "https://sede.madrid.es/*",
        "https://servcla.madrid.es/*",
        "https://servpub.madrid.es/*",
        "https://www.xalocgirona.cat/*",
        "https://seu.xalocgirona.cat/*",
        "https://www.base.cat/*",
        "https://www.baseonline.cat/*",
        "https://valid.aoc.cat/*",
        "https://cert.valid.aoc.cat/*",
        "https://cas.madrid.es/*",
        "https://pasarela.clave.gob.es/*",
        "https://[*.]madrid.es/*",
        "https://[*.]clave.gob.es/*",
        "https://cas.madrid.es:443/*",
        "https://pasarela.clave.gob.es:443/*",
        "https://cert.valid.aoc.cat:443/*",
        "https://palma.sedipualba.es/*",
        "https://identificacionssl.sedipualba.es/*",
        "https://reg.redsara.es/*",
        "https://aoberta.terrassa.cat/*",
        "https://sede.valencia.es/*",
    )
    _DEFAULT_CLIENT_CERT_ORIGINS: tuple[str, ...] = (
        "https://sede.madrid.es",
        "https://servcla.madrid.es",
        "https://servpub.madrid.es",
        "https://www.xalocgirona.cat",
        "https://seu.xalocgirona.cat",
        "https://www.base.cat",
        "https://www.baseonline.cat",
        "https://cert.valid.aoc.cat",
        "https://valid.aoc.cat",
        "https://cas.madrid.es",
        "https://pasarela.clave.gob.es",
        "https://palma.sedipualba.es",
        "https://identificacionssl.sedipualba.es",
        "https://reg.redsara.es",
        "https://aoberta.terrassa.cat",
        "https://sede.valencia.es",
    )

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
            use_policy = (os.getenv("XALOC_CERT_AUTOSELECT_VIA_POLICY") or "1").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            cli_fallback = (os.getenv("XALOC_CERT_AUTOSELECT_CLI_FALLBACK") or "1").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            should_add_cli_arg = (not use_policy) or cli_fallback
            if should_add_cli_arg:
                cert_rules_json = (os.getenv("XALOC_CERT_AUTOSELECT_RULES_JSON") or "").strip()
                if cert_rules_json:
                    cert_cn = (self.config.navegador.certificado_cn or "").strip()
                    rendered = (
                        cert_rules_json
                        .replace("__CERT_CN__", cert_cn)
                        .replace("${CERTIFICADO_CN}", cert_cn)
                    )
                    try:
                        parsed = json.loads(rendered)
                        normalized = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
                        args.append(f"--auto-select-certificate-for-urls={normalized}")
                    except Exception as e:
                        self.logger.warning(
                            "XALOC_CERT_AUTOSELECT_RULES_JSON invalido (%s). Se aplica fallback de pattern unico.",
                            e,
                        )
                        cert_rules_json = ""
                if not cert_rules_json:
                    cert_cn = (self.config.navegador.certificado_cn or "").strip()
                    cert_filter = {"SUBJECT": {"CN": cert_cn}} if cert_cn else {}
                    pattern_from_env = (os.getenv("XALOC_CERT_AUTOSELECT_PATTERN") or "").strip()
                    patterns = [pattern_from_env] if pattern_from_env else list(self._DEFAULT_CERT_PATTERNS)
                    policy = json.dumps(
                        [{"pattern": p, "filter": cert_filter} for p in patterns],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    args.append(f"--auto-select-certificate-for-urls={policy}")

        if self.config.lang:
            args.append(f"--lang={self.config.lang}")

        disable_features: list[str] = []
        if self.config.disable_translate_ui:
            disable_features.append("TranslateUI")
        if self.config.autofirma_auto_open:
            # Evitar bloqueo por dialogo de protocolo externo (afirma://) en Linux/headless.
            disable_features.append("ExternalProtocolDialog")
            args.append("--protocol-handler-registration-mode=auto")
            args.append("--disable-popup-blocking")

        if disable_features:
            merged_disable_features: list[str] = []
            existing_args: list[str] = []
            for arg in args:
                if arg.startswith("--disable-features="):
                    current = arg.split("=", 1)[1]
                    merged_disable_features.extend(
                        [f.strip() for f in current.split(",") if f.strip()]
                    )
                else:
                    existing_args.append(arg)

            for feature in disable_features:
                if feature not in merged_disable_features:
                    merged_disable_features.append(feature)

            args = existing_args
            args.append(
                f"--disable-features={','.join(merged_disable_features)}"
            )

        device_scale_factor = (os.getenv("XALOC_CHROMIUM_DEVICE_SCALE_FACTOR") or "").strip()
        if device_scale_factor:
            args.append(f"--force-device-scale-factor={device_scale_factor}")

        if (os.getenv("XALOC_BROWSER_DEBUG") or "0").strip().lower() in {"1", "true", "yes", "on"}:
            args.extend(
                [
                    "--enable-logging=stderr",
                    "--log-level=0",
                    "--v=1",
                ]
            )
            if (os.getenv("XALOC_CHROMIUM_NETLOG") or "0").strip().lower() in {"1", "true", "yes", "on"}:
                args.extend(
                    [
                        "--log-net-log=/tmp/chromium-netlog.json",
                        "--net-log-capture-mode=IncludeSensitive",
                    ]
                )
        if (os.getenv("XALOC_CHROMIUM_REMOTE_DEBUG") or "0").strip().lower() in {"1", "true", "yes", "on"}:
            remote_debug_port = (os.getenv("XALOC_CHROMIUM_REMOTE_DEBUG_PORT") or "9222").strip() or "9222"
            args.extend(
                [
                    "--remote-debugging-address=0.0.0.0",
                    f"--remote-debugging-port={remote_debug_port}",
                ]
            )

        return args

    def _build_client_certificates(self) -> list[dict]:
        enabled = (os.getenv("PLAYWRIGHT_USE_CLIENT_CERTIFICATES") or "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not enabled:
            return []

        cert_path = (os.getenv("PLAYWRIGHT_CERT_PATH") or "/data/certificates/certificate.pfx").strip()
        if not cert_path or not Path(cert_path).exists():
            return []

        origins_raw = (os.getenv("PLAYWRIGHT_CLIENT_CERT_ORIGINS") or "").strip()
        if origins_raw:
            raw_list = [o.strip() for o in origins_raw.split(",") if o.strip()]
        else:
            raw_list = list(self._DEFAULT_CLIENT_CERT_ORIGINS)

        origins: list[str] = []
        for raw in raw_list:
            try:
                parsed = urlparse(raw)
                if parsed.scheme and parsed.netloc:
                    origin = f"{parsed.scheme}://{parsed.netloc}"
                    if origin not in origins:
                        origins.append(origin)
            except Exception:
                continue

        if not origins:
            return []

        passphrase = (os.getenv("PLAYWRIGHT_CERT_PASSWORD") or "").strip()
        certs: list[dict] = []
        for origin in origins:
            item: dict = {"origin": origin, "pfxPath": cert_path}
            if passphrase:
                item["passphrase"] = passphrase
            certs.append(item)
        self.logger.info(
            "client_certificates habilitado con %s origen(es): %s",
            len(certs),
            ", ".join(origins),
        )
        return certs

    def _prepare_protocol_preferences(self, user_data_dir: str) -> None:
        if not self.config.autofirma_auto_open:
            return
        try:
            pref_path = Path(user_data_dir) / "Default" / "Preferences"
            pref_path.parent.mkdir(parents=True, exist_ok=True)

            prefs = {}
            if pref_path.exists():
                try:
                    prefs = json.loads(pref_path.read_text(encoding="utf-8"))
                except Exception:
                    prefs = {}

            protocol_handler = prefs.setdefault("protocol_handler", {})
            excluded = protocol_handler.setdefault("excluded_schemes", {})
            protocols_raw = (os.getenv("XALOC_AUTOFIRMA_PROTOCOLS") or "").strip()
            protocols = [p.strip() for p in protocols_raw.split(",") if p.strip()]
            if not protocols:
                protocols = [str(self.config.autofirma_protocol or "").strip() or "afirma"]
            for proto in protocols:
                excluded[proto] = False

            pairs = protocol_handler.get("allowed_origin_protocol_pairs")
            origins_raw = (os.getenv("XALOC_AUTOFIRMA_ALLOWED_ORIGINS") or "").strip()
            origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
            if not origins:
                origins = [str(self.config.autofirma_origin)]
            wanted_pairs = [{"protocol": proto, "origin": origin} for proto in protocols for origin in origins]

            # Chromium puede guardar esta clave como lista de objetos
            # o como diccionario {origin: [protocols]} segun version/perfil.
            if isinstance(pairs, list):
                for wanted in wanted_pairs:
                    if not any(
                        isinstance(p, dict)
                        and str(p.get("protocol")) == str(wanted["protocol"])
                        and str(p.get("origin")) == str(wanted["origin"])
                        for p in pairs
                    ):
                        pairs.append(wanted)
            elif isinstance(pairs, dict):
                for origin in origins:
                    current = pairs.get(origin)
                    if isinstance(current, list):
                        for proto in protocols:
                            if proto not in current:
                                current.append(proto)
                    elif isinstance(current, str):
                        merged = [current]
                        for proto in protocols:
                            if proto not in merged:
                                merged.append(proto)
                        pairs[origin] = merged
                    else:
                        pairs[origin] = list(protocols)
            else:
                protocol_handler["allowed_origin_protocol_pairs"] = wanted_pairs

            pref_path.write_text(
                json.dumps(prefs, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception as e:
            self.logger.warning("No se pudieron preparar preferencias de protocolo para AutoFirma: %s", e)

    async def _launch_persistent_context_with_fallback(
        self,
        *,
        user_data_dir: str,
        args: list[str],
        viewport_kwargs: dict,
    ) -> BrowserContext:
        def _cleanup_chromium_singleton_lockfiles() -> None:
            try:
                base = Path(user_data_dir)
                for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                    p = base / name
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
            except Exception:
                pass

        def _build_ephemeral_profile_with_cert_db() -> str:
            src = Path(user_data_dir)
            tmp = Path(tempfile.mkdtemp(prefix="xaloc_profile_", dir=str(src.parent)))
            # Mantener prefs mínimas si existen.
            for name in ("Local State", "Preferences"):
                for candidate in (src / name, src / "Default" / name):
                    if not candidate.exists():
                        continue
                    dest = tmp / Path("Default") / name if candidate.parent.name == "Default" else tmp / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(candidate, dest)
                    except Exception:
                        pass

            # Importar certificado directamente en NSS del perfil temporal.
            cert_path = Path(os.getenv("PLAYWRIGHT_CERT_PATH") or "/data/certificates/certificate.pfx")
            cert_password = os.getenv("PLAYWRIGHT_CERT_PASSWORD") or ""
            try:
                if cert_path.exists():
                    # Chromium puede consultar NSS en rutas distintas segun build/runtime:
                    # perfil directo o $HOME/.pki/nssdb. Preparamos ambas en el perfil temporal.
                    db_dirs = [tmp, tmp / ".pki" / "nssdb"]
                    for db_dir in db_dirs:
                        db_dir.mkdir(parents=True, exist_ok=True)
                        subprocess.run(["certutil", "-N", "--empty-password", "-d", f"sql:{db_dir}"], check=True)

                    p12_pass = tmp / ".p12_pass.txt"
                    db_pass = tmp / ".db_pass.txt"
                    p12_pass.write_text(cert_password, encoding="utf-8")
                    db_pass.write_text("\n", encoding="utf-8")
                    for db_dir in db_dirs:
                        subprocess.run(
                            [
                                "pk12util",
                                "-i",
                                str(cert_path),
                                "-d",
                                f"sql:{db_dir}",
                                "-w",
                                str(p12_pass),
                                "-k",
                                str(db_pass),
                            ],
                            check=True,
                        )
            except Exception as e:
                self.logger.warning("No se pudo importar certificado en perfil temporal: %s", e)
            return str(tmp)

        launch_kwargs = dict(
            user_data_dir=user_data_dir,
            channel=self.config.navegador.canal,
            headless=self.config.navegador.headless,
            args=args,
            ignore_https_errors=True,
            accept_downloads=True,
            ignore_default_args=["--disable-extensions"],
            **viewport_kwargs,
        )
        client_certs = self._build_client_certificates()
        if client_certs:
            launch_kwargs["client_certificates"] = client_certs
        # En runner docker evitamos heredar locks huérfanos entre tareas/contenedores.
        if (os.getenv("XALOC_FORCE_UNLOCK_PROFILE") or "1").strip().lower() in {"1", "true", "yes", "on"}:
            _cleanup_chromium_singleton_lockfiles()
        cert_retry_done = False
        lock_retry_done = False
        ephemeral_used = False
        crash_retry_done = False
        channel_fallback_done = False
        display_fallback_done = False
        allow_headless_on_display_error = (
            os.getenv("XALOC_ALLOW_HEADLESS_FALLBACK_ON_DISPLAY_ERROR", "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )

        while True:
            try:
                return await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as exc:
                msg = str(exc).lower()

                if (
                    not cert_retry_done
                    and "client_certificates" in launch_kwargs
                    and (
                        "failed to load client certificate" in msg
                        or "unsupported tls certificate" in msg
                        or "legacy provider" in msg
                    )
                ):
                    self.logger.warning(
                        "Playwright no pudo cargar client_certificates (OpenSSL legacy). "
                        "Reintentando usando solo NSS del perfil."
                    )
                    launch_kwargs.pop("client_certificates", None)
                    cert_retry_done = True
                    continue

                if (
                    "processsingleton" in msg
                    or "process_singleton" in msg
                    or "profile appears to be in use" in msg
                    or "singleton" in msg
                ):
                    if not lock_retry_done:
                        self.logger.warning(
                            "Chromium profile lock detectado. Limpiando lockfiles y reintentando..."
                        )
                        _cleanup_chromium_singleton_lockfiles()
                        await asyncio.sleep(0.2)
                        lock_retry_done = True
                        continue
                    if not ephemeral_used:
                        self.logger.warning("Persisten locks del perfil. Fallback a perfil temporal clonado.")
                        launch_kwargs["user_data_dir"] = _build_ephemeral_profile_with_cert_db()
                        ephemeral_used = True
                        lock_retry_done = False
                        continue

                if (
                    not crash_retry_done
                    and "target page, context or browser has been closed" in msg
                ):
                    has_singleton = "processsingleton" in msg or "singleton" in msg
                    self.logger.warning(
                        "Edge/Chromium se cerró durante launch%s. "
                        "Limpiando locks, terminando procesos residuales y reintentando.",
                        " (ProcessSingleton)" if has_singleton else "",
                    )
                    _cleanup_chromium_singleton_lockfiles()
                    canal = launch_kwargs.get("channel", "")
                    if canal == "msedge":
                        try:
                            subprocess.run(
                                ["taskkill", "/F", "/IM", "msedge.exe"],
                                capture_output=True,
                                check=False,
                            )
                        except Exception:
                            pass
                    crash_retry_done = True
                    await asyncio.sleep(1.5)
                    continue

                if (
                    not channel_fallback_done
                    and "channel" in launch_kwargs
                    and "msedge" in msg
                    and ("is not found" in msg or "distribution" in msg)
                ):
                    self.logger.warning(
                        "Canal '%s' no disponible en este entorno. Fallback automatico a Chromium.",
                        self.config.navegador.canal,
                    )
                    launch_kwargs.pop("channel", None)
                    channel_fallback_done = True
                    continue

                if (
                    allow_headless_on_display_error
                    and not display_fallback_done
                    and not bool(launch_kwargs.get("headless", False))
                    and (
                        "missing x server or $display" in msg
                        or "the platform failed to initialize" in msg
                        or "ozone_platform_x11" in msg
                    )
                ):
                    self.logger.warning(
                        "No hay DISPLAY/X server disponible para Chromium. "
                        "Reintentando en modo headless para evitar caida del runner."
                    )
                    launch_kwargs["headless"] = True
                    display_fallback_done = True
                    continue

                raise

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
        self._prepare_protocol_preferences(user_data_dir)
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
                self.context = await self._launch_persistent_context_with_fallback(
                    user_data_dir=user_data_dir,
                    args=args,
                    viewport_kwargs=viewport_kwargs,
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
        self.context = await self._launch_persistent_context_with_fallback(
            user_data_dir=user_data_dir,
            args=args,
            viewport_kwargs=viewport_kwargs,
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

            old_session = self._cdp_session
            old_page = self._screencast_page
            old_active = self._screencast_active

            try:
                if not getattr(target_page, "_screencast_close_listener_attached", False):
                    def _on_close() -> None:
                        asyncio.create_task(self._handle_screencast_page_closed(target_page))
                    target_page.on("close", _on_close)
                    setattr(target_page, "_screencast_close_listener_attached", True)
            except Exception:
                pass

            # IMPORTANTE: no desmontar la sesion anterior hasta confirmar que
            # la nueva pestaña acepta CDP. Si la pestaña nueva se cierra rápido
            # (ej. popup social bloqueado), mantenemos el stream previo vivo.
            try:
                new_session = await self.context.new_cdp_session(target_page)
            except Exception as exc:
                self.logger.warning("No se pudo abrir CDP session para screencast (target volatile/cerrado): %s", exc)
                return False

            _LIVE_FRAME_DIR.mkdir(parents=True, exist_ok=True)

            quality = int(os.getenv("LIVE_STREAM_QUALITY", "85"))
            max_width = int(os.getenv("LIVE_STREAM_WIDTH", "1920"))
            max_height = int(os.getenv("LIVE_STREAM_HEIGHT", "1080"))
            # 30fps / 8 ~= 3.75fps (objetivo operacional ~4fps por defecto).
            every_nth = int(os.getenv("LIVE_STREAM_EVERY_NTH", "8"))

            async def _on_frame(params: dict, _session=new_session) -> None:
                try:
                    data = base64.b64decode(params["data"])
                    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jpg", dir=str(_LIVE_FRAME_DIR))
                    try:
                        os.write(tmp_fd, data)
                    finally:
                        os.close(tmp_fd)

                    success = False
                    # En Windows el endpoint del dashboard puede tener el archivo abierto
                    # brevemente; damos margen extra para no congelar frames.
                    for _ in range(25):
                        try:
                            os.replace(tmp_path, str(self._screencast_path))
                            success = True
                            break
                        except OSError:
                            await asyncio.sleep(0.02)

                    if not success:
                        try:
                            # Fallback best-effort: intentar sobrescritura directa.
                            try:
                                with open(self._screencast_path, "wb") as dst:
                                    dst.write(data)
                                success = True
                            except Exception:
                                pass
                            if success:
                                return
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    if _session:
                        await _session.send(
                            "Page.screencastFrameAck",
                            {"sessionId": params["sessionId"]},
                        )
                except Exception:
                    pass

            new_session.on("Page.screencastFrame", _on_frame)

            try:
                await new_session.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": quality,
                        "maxWidth": max_width,
                        "maxHeight": max_height,
                        "everyNthFrame": every_nth,
                    },
                )
                # Ya tenemos nueva sesion funcionando: ahora desmontamos la anterior.
                if old_session and old_session is not new_session:
                    try:
                        await old_session.send("Page.stopScreencast")
                    except Exception:
                        pass
                    try:
                        await old_session.detach()
                    except Exception:
                        pass

                self._cdp_session = new_session
                self._screencast_page = target_page
                self._screencast_active = True
                if not initial_start:
                    self.logger.info("Screencast reenganchado a la pestaña activa.")
                return True
            except Exception as exc:
                self.logger.warning("No se pudo iniciar screencast CDP: %s", exc)
                try:
                    await new_session.detach()
                except Exception:
                    pass
                # Restaurar estado previo para no dejar el stream apagado por un popup efimero.
                self._cdp_session = old_session
                self._screencast_page = old_page
                self._screencast_active = old_active
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

        # Algunos popups (social/ads) nacen y mueren en milisegundos.
        # Evitar cortar el stream por targets efimeros.
        try:
            await asyncio.sleep(0.15)
        except Exception:
            pass
        if new_page.is_closed():
            return

        self.logger.info("Nueva pestaña detectada; moviendo visor en vivo...")
        # No tocar self.page: es la pestaña de trabajo del flujo.
        try:
            moved = await self._move_screencast_to_page(new_page)
            if not moved:
                self.logger.info("Screencast: ignorando pestaña nueva no enganchable; se mantiene target anterior.")
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
