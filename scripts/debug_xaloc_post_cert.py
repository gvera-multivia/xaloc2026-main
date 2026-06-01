from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sites.xaloc_girona.automation import XalocGironaAutomation
from sites.xaloc_girona.config import XalocConfig
from sites.xaloc_girona.flows.login import (
    _aceptar_cookies_si_aparece,
    _attach_cert_debug_observers,
    _click_cert_button_robusto,
)


POST_CERT_TEXT_RE = re.compile(
    r"nova\s+sol|tria\s+represent|representaci[oó]|mandat\s+de\s+representaci[oó]|"
    r"n[uú]mero\s+den[uú]ncia|matr[ií]cula|presentaci[oó]\s+de\s+la\s+sol",
    re.IGNORECASE,
)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value or "").strip("_")
    return cleaned[:80] or fallback


async def _is_post_cert_candidate(page) -> bool:  # type: ignore[no-untyped-def]
    try:
        url = (page.url or "").lower()
        if "seu.xalocgirona.cat/sta/reg/tramit" in url:
            return True
        if "seu.xalocgirona.cat/sta/" in url and "valid.aoc.cat" not in url:
            text = await page.locator("body").inner_text(timeout=1500)
            return bool(POST_CERT_TEXT_RE.search(text or ""))
    except Exception:
        return False
    return False


async def _wait_for_post_cert_page(context, seed_page, timeout_ms: int):  # type: ignore[no-untyped-def]
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    best = seed_page
    while asyncio.get_running_loop().time() < deadline:
        for page in list(context.pages):
            try:
                if await _is_post_cert_candidate(page):
                    return page
                if "seu.xalocgirona.cat" in (page.url or "").lower():
                    best = page
            except Exception:
                continue
        await seed_page.wait_for_timeout(500)
    return best


async def _collect_dom_summary(page) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return await page.evaluate(
        """() => {
            const short = (v, n = 240) => String(v || '').replace(/\\s+/g, ' ').trim().slice(0, n);
            const labelFor = (el) => {
                const id = el.id;
                if (id) {
                    const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                    if (explicit) return short(explicit.textContent);
                }
                const parent = el.closest('label');
                if (parent) return short(parent.textContent);
                const container = el.closest('.form-group, .field, .row, .col, div');
                if (container) {
                    const label = container.querySelector('label');
                    if (label) return short(label.textContent);
                }
                return '';
            };
            const cssPath = (el) => {
                if (!el || !el.tagName) return '';
                if (el.id) return `${el.tagName.toLowerCase()}#${el.id}`;
                const name = el.getAttribute('name');
                if (name) return `${el.tagName.toLowerCase()}[name="${name}"]`;
                const testid = el.getAttribute('data-testid');
                if (testid) return `${el.tagName.toLowerCase()}[data-testid="${testid}"]`;
                return el.tagName.toLowerCase();
            };
            const mapEl = (el) => ({
                tag: el.tagName.toLowerCase(),
                selector: cssPath(el),
                id: el.id || '',
                name: el.getAttribute('name') || '',
                type: el.getAttribute('type') || '',
                text: short(el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title')),
                label: labelFor(el),
                placeholder: el.getAttribute('placeholder') || '',
                required: !!el.required || el.getAttribute('aria-required') === 'true',
                disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
                classes: short(el.className, 180),
            });
            return {
                url: location.href,
                title: document.title,
                bodyText: short(document.body ? document.body.innerText : '', 5000),
                buttons: Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], a[role="button"], a.btn')).map(mapEl),
                links: Array.from(document.querySelectorAll('a[href]')).slice(0, 120).map((el) => ({
                    selector: cssPath(el),
                    text: short(el.innerText || el.textContent),
                    href: el.href || el.getAttribute('href') || '',
                    classes: short(el.className, 180),
                })),
                fields: Array.from(document.querySelectorAll('input, textarea, select')).map(mapEl),
                fileInputs: Array.from(document.querySelectorAll('input[type="file"]')).map(mapEl),
                radios: Array.from(document.querySelectorAll('input[type="radio"]')).map(mapEl),
                checkboxes: Array.from(document.querySelectorAll('input[type="checkbox"]')).map(mapEl),
            };
        }"""
    )


async def _dump_page_artifacts(page, out_dir: Path, name: str) -> None:  # type: ignore[no-untyped-def]
    page_dir = out_dir / name
    page_dir.mkdir(parents=True, exist_ok=True)
    try:
        (page_dir / "url.txt").write_text(page.url or "", encoding="utf-8")
    except Exception:
        pass
    try:
        (page_dir / "dom.html").write_text(await page.content(), encoding="utf-8", errors="ignore")
    except Exception as exc:
        (page_dir / "dom_error.txt").write_text(str(exc), encoding="utf-8")
    try:
        text = await page.locator("body").inner_text(timeout=3000)
        (page_dir / "body.txt").write_text(text, encoding="utf-8", errors="ignore")
    except Exception as exc:
        (page_dir / "body_error.txt").write_text(str(exc), encoding="utf-8")
    try:
        summary = await _collect_dom_summary(page)
        (page_dir / "dom_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        (page_dir / "dom_summary_error.txt").write_text(str(exc), encoding="utf-8")
    try:
        await page.screenshot(path=page_dir / "screenshot.png", full_page=True)
    except Exception as exc:
        (page_dir / "screenshot_error.txt").write_text(str(exc), encoding="utf-8")


async def _click_optional_new_request(page, out_dir: Path) -> None:  # type: ignore[no-untyped-def]
    candidates = [
        page.locator('button[data-testid="choosepars-continue-button"]').first,
        page.get_by_role("button", name=re.compile(r"nova\s+sol|nueva\s+sol", re.IGNORECASE)).first,
        page.locator("button", has_text=re.compile(r"nova\s+sol|nueva\s+sol", re.IGNORECASE)).first,
    ]
    button = None
    for candidate in candidates:
        try:
            if await candidate.count() > 0:
                await candidate.wait_for(state="visible", timeout=3000)
                button = candidate
                break
        except Exception:
            continue
    if button is None:
        logging.warning("No se encontro boton NOVA SOL.LICITUD para avanzar en diagnostico.")
        return

    logging.info("Diagnostico: click seguro en NOVA SOL.LICITUD para capturar pantalla siguiente.")
    await button.scroll_into_view_if_needed(timeout=3000)
    await button.click(no_wait_after=True)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        await page.wait_for_timeout(3000)
    await _dump_page_artifacts(page, out_dir, "10_after_nova_solicitud")


async def _manual_watch(context, out_dir: Path, *, seconds: int, interval: float) -> None:  # type: ignore[no-untyped-def]
    logging.info(
        "manual-watch activo durante %ss. Navega manualmente; se capturaran cambios de URL/texto cada %.1fs.",
        seconds,
        interval,
    )
    deadline = asyncio.get_running_loop().time() + max(1, seconds)
    last_signature = ""
    capture_index = 0

    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(max(0.5, interval))
        pages = list(context.pages)
        if not pages:
            continue

        interesting = []
        for page in pages:
            try:
                url = page.url or ""
            except Exception:
                url = ""
            if "xalocgirona.cat" in url or "valid.aoc.cat" in url:
                interesting.append(page)
        if not interesting:
            interesting = pages[-1:]

        page = interesting[-1]
        try:
            url = page.url or ""
            text = await page.locator("body").inner_text(timeout=1500)
            text_sig = re.sub(r"\s+", " ", text or "").strip()[:400]
            signature = f"{url}|{text_sig}"
        except Exception:
            signature = getattr(page, "url", "")

        if signature == last_signature:
            continue

        last_signature = signature
        capture_index += 1
        name = f"manual_{capture_index:02d}_{_safe_name(getattr(page, 'url', ''), 'page')}"
        logging.info("manual-watch: captura %s url=%s", capture_index, getattr(page, "url", ""))
        await _dump_page_artifacts(page, out_dir, name)


async def run(args: argparse.Namespace) -> int:
    if args.load_env:
        _load_dotenv(ROOT / ".env")

    os.environ.setdefault("XALOC_CERT_DEBUG", "1")
    if args.keep_open:
        os.environ["XALOC_KEEP_BROWSER_OPEN"] = "1"
        os.environ["XALOC_KEEP_TAB_OPEN"] = "1"

    out_dir = ROOT / "tmp" / "xaloc_post_cert_debug" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(out_dir / "debug.log", encoding="utf-8"),
        ],
    )

    config = XalocConfig()
    config.navegador.headless = bool(args.headless)
    if args.profile_dir:
        config.navegador.perfil_path = Path(args.profile_dir)
    if args.channel:
        config.navegador.canal = args.channel
    config.timeouts.login = int(args.timeout_ms)

    logging.info("Artefactos: %s", out_dir)
    logging.info(
        "Browser config: headless=%s channel=%s profile=%s",
        config.navegador.headless,
        config.navegador.canal,
        config.navegador.perfil_path,
    )

    async with XalocGironaAutomation(config) as bot:
        if not bot.page or not bot.context:
            raise RuntimeError("No se pudo inicializar navegador Playwright.")

        page = bot.page
        logging.info("Navegando a %s", config.url_base)
        await page.goto(config.url_base, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await _aceptar_cookies_si_aparece(page, config)
        await _dump_page_artifacts(page, out_dir, "01_public")

        enlace = page.get_by_role(
            "link",
            name=re.compile(config.selectors.tramite_link_regex, re.IGNORECASE),
        ).first
        await enlace.wait_for(state="visible", timeout=config.flow_timeouts.link_appear)

        logging.info("Click en Tramitacio en linia; esperando popup VALid.")
        try:
            async with page.expect_popup(timeout=15000) as popup_info:
                await enlace.click(no_wait_after=True)
            valid_page = await popup_info.value
        except Exception:
            logging.warning("No se detecto popup; usando la pagina activa/contexto como fallback.")
            await page.wait_for_timeout(2000)
            candidates = [p for p in bot.context.pages if "valid.aoc.cat" in (p.url or "").lower()]
            valid_page = candidates[-1] if candidates else bot.context.pages[-1]

        await valid_page.wait_for_load_state("domcontentloaded")
        await _attach_cert_debug_observers(valid_page)
        await _dump_page_artifacts(valid_page, out_dir, "02_valid")

        logging.info("Click en certificado VALid.")
        try:
            await _click_cert_button_robusto(
                page=valid_page,
                selector=config.selectors.cert_button,
                timeout_ms=config.flow_timeouts.cert_button_appear,
                click_timeout_ms=config.timeouts.login,
            )
        except Exception as exc:
            logging.warning("Click certificado devolvio error/timeout; se continua esperando por si navego: %s", exc)

        post_page = await _wait_for_post_cert_page(bot.context, valid_page, int(args.timeout_ms))
        logging.info("Pagina post-cert candidata: %s", getattr(post_page, "url", ""))

        for idx, p in enumerate(list(bot.context.pages), start=1):
            page_name = f"{idx:02d}_{_safe_name(getattr(p, 'url', ''), 'page')}"
            await _dump_page_artifacts(p, out_dir, page_name)

        await _dump_page_artifacts(post_page, out_dir, "99_post_cert_candidate")

        if args.click_nova:
            await _click_optional_new_request(post_page, out_dir)

        if args.manual_watch:
            await _manual_watch(
                bot.context,
                out_dir,
                seconds=int(args.manual_watch_seconds),
                interval=float(args.manual_watch_interval),
            )

        result = {
            "out_dir": str(out_dir),
            "post_cert_url": getattr(post_page, "url", ""),
            "pages": [getattr(p, "url", "") for p in bot.context.pages],
            "keep_open": bool(args.keep_open),
        }
        (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if args.keep_open:
            logging.info("keep-open activo. Navegador queda abierto hasta cerrar manualmente/proceso.")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnostica el post-login con certificado de XALOC Girona sin ejecutar ningun tramite."
    )
    parser.add_argument("--timeout-ms", type=int, default=90000, help="Tiempo maximo esperando post-certificado.")
    parser.add_argument("--profile-dir", default="", help="Perfil Playwright/Chromium a usar. Por defecto, el de XalocConfig/env.")
    parser.add_argument("--channel", default="", help="Canal Chromium/Edge. Por defecto, XalocConfig/env.")
    parser.add_argument("--headless", action="store_true", help="Ejecutar headless. No recomendado para diagnostico de certificado.")
    parser.add_argument("--no-load-env", dest="load_env", action="store_false", help="No cargar .env local.")
    parser.add_argument("--keep-open", action="store_true", help="Mantener navegador abierto al terminar para inspeccion manual.")
    parser.add_argument(
        "--click-nova",
        action="store_true",
        help="Avanza solo desde la pantalla de borradores con NOVA SOL.LICITUD y captura la pantalla siguiente.",
    )
    parser.add_argument(
        "--manual-watch",
        action="store_true",
        help="Modo observador: captura pantallas mientras navegas manualmente, sin hacer clicks automaticos.",
    )
    parser.add_argument("--manual-watch-seconds", type=int, default=900, help="Duracion del modo observador.")
    parser.add_argument("--manual-watch-interval", type=float, default=2.0, help="Intervalo de captura del observador.")
    parser.set_defaults(load_env=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
