from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from core.justificantes_storage import (
    build_receipt_filename,
    resolve_receipt_dir_from_payload,
    save_receipt_from_tmp,
)

if TYPE_CHECKING:
    from playwright.async_api import Download
    from playwright.async_api import Frame, Page
    from playwright.async_api import Response

    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget

from .form_scope import wait_form_scope
from .cookies import dismiss_cookie_banner_if_present

logger = logging.getLogger("xaloc_automation.servei_cat_trans.confirmacion")

_SIGN_BTN_SELECTORS = (
    "#signarFormButton",
    "input#signarFormButton[type='submit']",
    "input[type='submit'][value*='Firmar']",
    "input[type='submit'][value*='Firma y env']",
    "button:has-text('Firmar y enviar')",
    "button:has-text('Firma y envía')",
)
_SIGNADOR_JNLP_RE = re.compile(r"https://signador\.aoc\.cat/signador/jnlp\?id=[^\\s]+", re.IGNORECASE)
_SIGNADOR_DOWNLOAD_RE = re.compile(r"/signador/download\?identificador=", re.IGNORECASE)
_RECEIPT_PAGE_RE = re.compile(r"/tramitarupload\.do\?reqCode=tramitarHtml", re.IGNORECASE)
_RECEIPT_LINK_SELECTOR = "a.link_tramit[href*='reqCode=generarAcusamentRebuda']"
_JNLP_TIMEOUT_MS = 120000
_DOWNLOAD_POLL_TIMEOUT_MS = int(os.getenv("XALOC_SERVEI_JNLP_DOWNLOAD_POLL_MS", "20000"))
_REDIRECT_TIMEOUT_MS = 180000
_RECEIPT_TIMEOUT_MS = 120000
_ACTION_TIMEOUT_MS = 30000
_INTER_ACTION_DELAY_MS = 1200


def _safe_resource_id(datos: "ServeiCatTransTarget") -> str:
    rid = datos.idRecurso if getattr(datos, "idRecurso", None) is not None else datos.payload.get("idRecurso")
    rid_txt = str(rid or "unknown").strip()
    return rid_txt or "unknown"


def _safe_filename(name: str, fallback: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return fallback
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", raw).strip("._")
    return safe or fallback


def _extract_jnlp_candidate_urls(html_text: str, *, base_url: str) -> list[str]:
    text = str(html_text or "")
    decoded = html.unescape(text)
    patterns = [
        r"""https://signador\.aoc\.cat[^\s"'<>]+""",
        r"""href=['"]([^'"]*jnlp[^'"]*)['"]""",
        r"""src=['"]([^'"]*jnlp[^'"]*)['"]""",
        r"""['"]([^'"]+\.jnlp(?:\?[^'"]*)?)['"]""",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for pat in patterns:
        for m in re.findall(pat, decoded, flags=re.IGNORECASE):
            url = m if isinstance(m, str) else m[0]
            u = str(url or "").strip()
            if not u:
                continue
            abs_url = u if u.lower().startswith("http") else urljoin(base_url, u)
            if abs_url.lower().startswith("javascript:"):
                continue
            if " " in abs_url:
                continue
            key = abs_url.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(abs_url)
    return out


def _extract_signador_identificador(html_text: str, *, fallback_url: str) -> str:
    text = str(html_text or "")
    patterns = (
        r"""id=['"]identificador['"][^>]*value=['"]([^'"]+)['"]""",
        r"""name=['"]identificador['"][^>]*value=['"]([^'"]+)['"]""",
        r"""AppletSignatura\.QUERY\s*=\s*["']id=([^"']+)["']""",
        r"""[?&]id=([0-9a-fA-F-]{16,})""",
    )
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            val = str(m.group(1) or "").strip()
            if val:
                return val
    m = re.search(r"""[?&]id=([^&\s]+)""", str(fallback_url or ""), flags=re.IGNORECASE)
    return str(m.group(1) or "").strip() if m else ""


def _looks_like_jnlp_bytes(content: bytes) -> bool:
    head = (content or b"")[:8192].lower()
    # Algunos JNLP vienen truncados/compactados sin cierre en primeros bytes.
    # Basta detectar cabecera XML/etiqueta jnlp en el inicio.
    if b"<jnlp" in head:
        return True
    if b"<?xml" in head and b"jnlp" in head:
        return True
    return False


def _looks_like_jnlp_response(*, content_type: str, body: bytes) -> bool:
    ctype = str(content_type or "").lower()
    if "application/x-java-jnlp-file" in ctype:
        return True
    if "application/xml" in ctype or "text/xml" in ctype:
        return _looks_like_jnlp_bytes(body)
    return _looks_like_jnlp_bytes(body)


def _looks_like_jnlp_file(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return False
        return _looks_like_jnlp_bytes(path.read_bytes())
    except Exception:
        return False


def _download_dirs() -> list[Path]:
    raw_dirs = [
        "/app/tmp/downloads",
        os.getenv("PLAYWRIGHT_DOWNLOADS_PATH") or "",
        os.getenv("XALOC_DOWNLOAD_DIR") or "",
        "/root/Downloads",
        str(Path.home() / "Downloads"),
        "/home/pwuser/Downloads",
        "/tmp/Downloads",
        "/downloads",
    ]
    dirs: list[Path] = []
    seen: set[str] = set()
    for raw in raw_dirs:
        txt = str(raw or "").strip()
        if not txt:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        p = Path(txt)
        if p.exists() and p.is_dir():
            dirs.append(p)
    return dirs


def _recent_download_candidates(*, max_age_s: int = 900, since_ts: float | None = None) -> list[tuple[float, Path]]:
    now = time.time()
    candidates: list[tuple[float, Path]] = []
    for base in _download_dirs():
        try:
            for child in base.iterdir():
                if not child.is_file():
                    continue
                if child.suffix.lower() in {".crdownload", ".tmp", ".part"}:
                    continue
                try:
                    mtime = float(child.stat().st_mtime)
                except Exception:
                    continue
                if now - mtime > max_age_s:
                    continue
                if since_ts is not None and mtime < since_ts:
                    continue
                candidates.append((mtime, child))
        except Exception:
            continue
    return sorted(candidates, key=lambda it: it[0], reverse=True)


def _find_recent_jnlp_in_downloads(*, max_age_s: int = 900, since_ts: float | None = None) -> Path | None:
    for _, path in _recent_download_candidates(max_age_s=max_age_s, since_ts=since_ts):
        if _looks_like_jnlp_file(path):
            logger.info(
                "servei_cat_trans.confirmacion: JNLP localizado en Downloads (fallback): %s",
                path,
            )
            return path
    return None


def _find_recent_download_candidate(*, max_age_s: int = 900, since_ts: float | None = None) -> Path | None:
    for _, path in _recent_download_candidates(max_age_s=max_age_s, since_ts=since_ts):
        return path
    return None


def _persist_jnlp_for_run(src_path: Path, *, rid: str) -> Path:
    tmp_dir = Path("tmp") / "servei_cat_trans" / "firma" / rid
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / f"signador_{rid}.jnlp"
    shutil.copy2(src_path, out_path)
    return out_path


def _firm_tmp_dir(*, rid: str) -> Path:
    tmp_dir = Path("tmp") / "servei_cat_trans" / "firma" / rid
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir


async def _stream_subprocess_output(stream, *, rid: str, tag: str, out_path: Path) -> None:
    if stream is None:
        return
    try:
        with out_path.open("ab") as fh:
            while True:
                line = await stream.readline()
                if not line:
                    break
                fh.write(line)
                fh.flush()
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.info("servei_cat_trans.confirmacion: [%s] %s %s", rid, tag, text)
    except Exception as exc:
        logger.warning(
            "servei_cat_trans.confirmacion: [%s] error leyendo salida de subprocess (%s): %s",
            rid,
            tag,
            exc,
        )


async def _find_sign_button(scope: "Page | Frame"):
    await dismiss_cookie_banner_if_present(scope)
    candidates = [
        scope.get_by_role("button", name=re.compile(r"Firmar|Signar", re.IGNORECASE)).first,
        scope.get_by_role("button", name=re.compile(r"env[ií]a", re.IGNORECASE)).first,
    ]
    candidates.extend(scope.locator(selector).first for selector in _SIGN_BTN_SELECTORS)

    for locator in candidates:
        if await locator.count() == 0:
            continue
        try:
            await locator.wait_for(state="visible", timeout=4000)
            return locator
        except Exception:
            continue
    raise RuntimeError("servei_cat_trans.confirmacion: no se encontro el boton de 'Firma y envía'.")


async def _try_discover_signador_jnlp_url(page: "Page") -> str:
    urls: list[str] = []
    for p in list(page.context.pages):
        try:
            urls.append(str(p.url or "").strip())
        except Exception:
            continue

    for url in urls:
        if _SIGNADOR_JNLP_RE.search(url):
            return url

    for p in list(page.context.pages):
        try:
            href = await p.evaluate(
                """() => {
                    const el = document.querySelector("a[href*='signador.aoc.cat/signador/jnlp']");
                    return el ? (el.getAttribute("href") || "") : "";
                }"""
            )
        except Exception:
            href = ""
        href_txt = str(href or "").strip()
        if href_txt and _SIGNADOR_JNLP_RE.search(href_txt):
            return href_txt

    return ""


async def _try_discover_signador_download_url(page: "Page") -> str:
    for p in list(page.context.pages):
        try:
            result = await p.evaluate(
                """() => {
                    const hidden = document.querySelector("#identificador, input[name='identificador']");
                    const id = hidden ? String(hidden.value || "").trim() : "";
                    if (!id) return "";
                    return "https://signador.aoc.cat/signador/download?identificador=" + encodeURIComponent(id) + "&browser=&firefoxVersion=";
                }"""
            )
        except Exception:
            result = ""
        url = str(result or "").strip()
        if url and _SIGNADOR_DOWNLOAD_RE.search(url):
            return url
    return ""


async def _force_trigger_signador_download(page: "Page", *, rid: str) -> None:
    signador_pages: list["Page"] = []
    for p in list(page.context.pages):
        try:
            u = str(p.url or "")
        except Exception:
            u = ""
        if "signador.aoc.cat" in u:
            signador_pages.append(p)

    if not signador_pages:
        logger.info("servei_cat_trans.confirmacion: [%s] no hay pestaña de signador para trigger forzado.", rid)
        return

    for idx, p in enumerate(signador_pages, start=1):
        try:
            current_url = str(p.url or "")
        except Exception:
            current_url = ""
        try:
            trigger = await p.evaluate(
                """() => {
                    const out = { invoked: false, mode: "", ident: "", href: "" };
                    const hidden = document.querySelector("#identificador, input[name='identificador']");
                    const ident = hidden ? String(hidden.value || "").trim() : "";
                    if (ident) {
                        out.ident = ident;
                        out.href = "/signador/download?identificador=" + encodeURIComponent(ident) + "&browser=&firefoxVersion=";
                    }
                    try {
                        if (typeof window.signaturaGetApplet === "function") {
                            const app = window.signaturaGetApplet();
                            if (app && typeof app.getJNLP === "function") {
                                app.getJNLP();
                                out.invoked = true;
                                out.mode = "signaturaGetApplet.getJNLP";
                            }
                        }
                    } catch (_) {}
                    if (!out.invoked) {
                        try {
                            if (window.myAppletSignatura && typeof window.myAppletSignatura.getJNLP === "function") {
                                window.myAppletSignatura.getJNLP();
                                out.invoked = true;
                                out.mode = "myAppletSignatura.getJNLP";
                            }
                        } catch (_) {}
                    }
                    if (!out.invoked && out.href) {
                        window.location.href = out.href;
                        out.invoked = true;
                        out.mode = "location.href(download)";
                    }
                    return out;
                }"""
            )
        except Exception as exc:
            logger.warning(
                "servei_cat_trans.confirmacion: [%s] trigger forzado fallo en pagina signador #%s (%s): %s",
                rid,
                idx,
                current_url,
                exc,
            )
            continue

        ident = str((trigger or {}).get("ident") or "").strip()
        href = str((trigger or {}).get("href") or "").strip()
        mode = str((trigger or {}).get("mode") or "").strip()
        invoked = bool((trigger or {}).get("invoked"))
        logger.info(
            "servei_cat_trans.confirmacion: [%s] trigger forzado signador #%s invoked=%s mode=%s ident=%s href=%s url=%s",
            rid,
            idx,
            invoked,
            mode,
            ident,
            href,
            current_url,
        )
        if href:
            abs_href = urljoin(current_url or "https://signador.aoc.cat/signador/", href)
            try:
                await p.goto(abs_href, wait_until="domcontentloaded", timeout=15000)
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] goto forzado a descarga signador ok url=%s",
                    rid,
                    abs_href,
                )
            except Exception as exc:
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] goto forzado descarga signador devolvio excepcion (esperable si descarga): %s",
                    rid,
                    exc,
                )


async def _download_jnlp_from_response(page: "Page", *, rid: str) -> Path:
    signador_url = await _try_discover_signador_jnlp_url(page)
    if not signador_url:
        signador_url = await _try_discover_signador_download_url(page)
    if not signador_url:
        await _force_trigger_signador_download(page, rid=rid)
        await page.wait_for_timeout(1500)
        recovered = _find_recent_jnlp_in_downloads(max_age_s=1800)
        if recovered:
            logger.info(
                "servei_cat_trans.confirmacion: [%s] JNLP recuperado tras trigger forzado desde Downloads: %s",
                rid,
                recovered,
            )
            return _persist_jnlp_for_run(recovered, rid=rid)
        signador_url = await _try_discover_signador_download_url(page) or await _try_discover_signador_jnlp_url(page)
    if not signador_url:
        raise RuntimeError(
            "servei_cat_trans.confirmacion: no se detecto URL JNLP tras pulsar 'Firma y envía'."
        )

    logger.info(
        "servei_cat_trans.confirmacion: [%s] fallback URL JNLP detectada=%s",
        rid,
        signador_url,
    )
    resp = await page.context.request.get(signador_url, timeout=90000)
    content_type = str(resp.headers.get("content-type") or "")
    logger.info(
        "servei_cat_trans.confirmacion: [%s] fallback HTTP status=%s content-type=%s url=%s",
        rid,
        resp.status,
        content_type,
        signador_url,
    )
    if not resp.ok:
        raise RuntimeError(
            f"servei_cat_trans.confirmacion: fallo descargando JNLP ({resp.status}) url={signador_url}"
        )

    body = await resp.body()
    if not _looks_like_jnlp_bytes(body):
        tmp_dir = _firm_tmp_dir(rid=rid)
        debug_path = tmp_dir / "signador_fallback_response_preview.txt"
        html_text = ""
        try:
            html_text = body.decode("utf-8", errors="ignore")
            debug_path.write_bytes(body[:65536])
        except Exception:
            pass
        identificador = _extract_signador_identificador(html_text, fallback_url=signador_url)
        if identificador:
            download_url = (
                f"https://signador.aoc.cat/signador/download"
                f"?identificador={identificador}&browser=&firefoxVersion="
            )
            try:
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] fallback download directo por identificador=%s url=%s",
                    rid,
                    identificador,
                    download_url,
                )
                direct_resp = await page.context.request.get(
                    download_url,
                    headers={"Referer": signador_url},
                    timeout=90000,
                )
                direct_ct = str(direct_resp.headers.get("content-type") or "")
                direct_body = await direct_resp.body()
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] download directo status=%s content-type=%s bytes=%s",
                    rid,
                    direct_resp.status,
                    direct_ct,
                    len(direct_body or b""),
                )
                if direct_resp.ok and _looks_like_jnlp_response(content_type=direct_ct, body=direct_body):
                    out_path = tmp_dir / f"signador_{rid}.jnlp"
                    out_path.write_bytes(direct_body)
                    logger.info(
                        "servei_cat_trans.confirmacion: [%s] JNLP recuperado por download directo en %s",
                        rid,
                        out_path,
                    )
                    return out_path
            except Exception as direct_exc:
                logger.warning(
                    "servei_cat_trans.confirmacion: [%s] fallo en download directo por identificador (%s)",
                    rid,
                    direct_exc,
                )
        for candidate_url in _extract_jnlp_candidate_urls(html_text, base_url=signador_url):
            try:
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] probando URL JNLP candidata extraida de HTML: %s",
                    rid,
                    candidate_url,
                )
                candidate_resp = await page.context.request.get(candidate_url, timeout=90000)
                candidate_ct = str(candidate_resp.headers.get("content-type") or "")
                candidate_body = await candidate_resp.body()
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] candidata status=%s content-type=%s bytes=%s",
                    rid,
                    candidate_resp.status,
                    candidate_ct,
                    len(candidate_body or b""),
                )
                if candidate_resp.ok and _looks_like_jnlp_response(content_type=candidate_ct, body=candidate_body):
                    out_path = tmp_dir / f"signador_{rid}.jnlp"
                    out_path.write_bytes(candidate_body)
                    logger.info(
                        "servei_cat_trans.confirmacion: [%s] JNLP recuperado desde URL candidata en %s",
                        rid,
                        out_path,
                    )
                    return out_path
            except Exception as candidate_exc:
                logger.warning(
                    "servei_cat_trans.confirmacion: [%s] fallo probando URL candidata (%s): %s",
                    rid,
                    candidate_url,
                    candidate_exc,
                )
        logger.warning(
            "servei_cat_trans.confirmacion: [%s] fallback no devuelve JNLP (bytes=%s content-type=%s identificador=%s) preview=%s",
            rid,
            len(body or b""),
            content_type,
            identificador,
            debug_path,
        )
        raise RuntimeError(
            "servei_cat_trans.confirmacion: el contenido descargado no parece un fichero JNLP valido."
        )

    tmp_dir = _firm_tmp_dir(rid=rid)
    out_path = tmp_dir / f"signador_{rid}.jnlp"
    out_path.write_bytes(body)
    logger.info(
        "servei_cat_trans.confirmacion: [%s] JNLP descargado por URL fallback en %s (%s bytes)",
        rid,
        out_path,
        len(body),
    )
    return out_path


async def _capture_jnlp_download(page: "Page", sign_button, *, rid: str) -> Path:
    download_task = asyncio.create_task(page.context.wait_for_event("download", timeout=_JNLP_TIMEOUT_MS))
    response_task = asyncio.create_task(
        page.context.wait_for_event(
            "response",
            predicate=lambda r: (
                "signador.aoc.cat/signador/jnlp" in str(getattr(r, "url", "")).lower()
                or "signador.aoc.cat/signador/download" in str(getattr(r, "url", "")).lower()
            ),
            timeout=_JNLP_TIMEOUT_MS,
        )
    )
    click_ts = time.time()
    logger.info(
        "servei_cat_trans.confirmacion: [%s] esperando descarga JNLP (timeout_event_ms=%s poll_ms=%s)",
        rid,
        _JNLP_TIMEOUT_MS,
        _DOWNLOAD_POLL_TIMEOUT_MS,
    )
    click_error: Exception | None = None
    try:
        await dismiss_cookie_banner_if_present(page)
        logger.info("servei_cat_trans.confirmacion: [%s] click en boton firma final", rid)
        await sign_button.click(force=True, timeout=_ACTION_TIMEOUT_MS)
        await page.wait_for_timeout(_INTER_ACTION_DELAY_MS)
        await _force_trigger_signador_download(page, rid=rid)
    except Exception as exc:
        click_error = exc

    if click_error is not None:
        if not download_task.done():
            download_task.cancel()
        if not response_task.done():
            response_task.cancel()
        raise RuntimeError(f"servei_cat_trans.confirmacion: fallo al pulsar 'Firma y envía': {click_error}") from click_error

    # En algunos entornos el navegador descarga fuera del evento de Playwright.
    # Sondeamos descargas recientes tras el click para recuperar el JNLP enseguida.
    poll_deadline = time.monotonic() + (_DOWNLOAD_POLL_TIMEOUT_MS / 1000.0)
    poll_checks = 0
    response_checked = False
    logger.info("servei_cat_trans.confirmacion: [%s] inicio sondeo de descargas locales", rid)
    while time.monotonic() < poll_deadline:
        poll_checks += 1
        if response_task.done() and not response_checked:
            response_checked = True
            try:
                resp: "Response" = response_task.result()
                body = await resp.body()
                ctype = str((await resp.all_headers()).get("content-type") or "")
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] response jnlp capturada url=%s status=%s content-type=%s bytes=%s",
                    rid,
                    resp.url,
                    resp.status,
                    ctype,
                    len(body or b""),
                )
                if _looks_like_jnlp_bytes(body):
                    tmp_dir = _firm_tmp_dir(rid=rid)
                    out_path = tmp_dir / f"signador_{rid}.jnlp"
                    out_path.write_bytes(body)
                    logger.info(
                        "servei_cat_trans.confirmacion: [%s] JNLP valido recuperado desde response_task url=%s",
                        rid,
                        resp.url,
                    )
                    if not download_task.done():
                        download_task.cancel()
                    return out_path
                logger.warning(
                    "servei_cat_trans.confirmacion: [%s] response detectada pero contenido no JNLP. Intentando /download directo.",
                    rid,
                )
                # La URL /jnlp devuelve HTML. Extraemos identificador e intentamos /download directamente.
                try:
                    html_text = body.decode("utf-8", errors="ignore")
                    identificador = _extract_signador_identificador(html_text, fallback_url=resp.url)
                    if identificador:
                        download_url = (
                            f"https://signador.aoc.cat/signador/download"
                            f"?identificador={identificador}&browser=&firefoxVersion="
                        )
                        logger.info(
                            "servei_cat_trans.confirmacion: [%s] intentando download directo identificador=%s url=%s",
                            rid, identificador, download_url,
                        )
                        direct_resp = await page.context.request.get(
                            download_url,
                            headers={"Referer": resp.url},
                            timeout=90000,
                        )
                        direct_body = await direct_resp.body()
                        direct_ct = str(direct_resp.headers.get("content-type") or "")
                        logger.info(
                            "servei_cat_trans.confirmacion: [%s] download directo status=%s ct=%s bytes=%s",
                            rid, direct_resp.status, direct_ct, len(direct_body or b""),
                        )
                        if direct_resp.ok and _looks_like_jnlp_response(content_type=direct_ct, body=direct_body):
                            tmp_dir = _firm_tmp_dir(rid=rid)
                            out_path = tmp_dir / f"signador_{rid}.jnlp"
                            out_path.write_bytes(direct_body)
                            logger.info(
                                "servei_cat_trans.confirmacion: [%s] JNLP recuperado por download directo en %s",
                                rid, out_path,
                            )
                            if not download_task.done():
                                download_task.cancel()
                            return out_path
                except Exception as direct_exc:
                    logger.warning(
                        "servei_cat_trans.confirmacion: [%s] fallo download directo desde response HTML: %s",
                        rid, direct_exc,
                    )
            except Exception as exc:
                logger.warning(
                    "servei_cat_trans.confirmacion: [%s] error procesando response_task JNLP (%s)",
                    rid,
                    exc,
                )
        recovered = _find_recent_jnlp_in_downloads(since_ts=click_ts)
        if recovered:
            if not download_task.done():
                download_task.cancel()
            if not response_task.done():
                response_task.cancel()
            logger.info(
                "servei_cat_trans.confirmacion: [%s] JNLP detectado por sondeo en intento=%s ruta=%s",
                rid,
                poll_checks,
                recovered,
            )
            return _persist_jnlp_for_run(recovered, rid=rid)
        maybe = _find_recent_download_candidate(since_ts=click_ts)
        if maybe and _looks_like_jnlp_file(maybe):
            if not download_task.done():
                download_task.cancel()
            if not response_task.done():
                response_task.cancel()
            logger.info(
                "servei_cat_trans.confirmacion: [%s] item descargado detectado y validado como JNLP: %s",
                rid,
                maybe,
            )
            return _persist_jnlp_for_run(maybe, rid=rid)
        await page.wait_for_timeout(250)
    logger.info(
        "servei_cat_trans.confirmacion: [%s] sondeo completado sin JNLP local (%s intentos)",
        rid,
        poll_checks,
    )

    # Si ya comprobamos que la response era HTML (no JNLP), no esperamos download_task 120s.
    # Cancelamos y vamos directamente al fallback _download_jnlp_from_response.
    if response_checked:
        logger.info(
            "servei_cat_trans.confirmacion: [%s] response ya verificada como no-JNLP; saltando espera download_task, fallback directo.",
            rid,
        )
        if not download_task.done():
            download_task.cancel()
        return await _download_jnlp_from_response(page, rid=rid)

    try:
        download: "Download" = await download_task
        tmp_dir = _firm_tmp_dir(rid=rid)
        suggested = _safe_filename(download.suggested_filename, f"signador_{rid}.jnlp")
        if not suggested.lower().endswith(".jnlp"):
            suggested = f"{Path(suggested).stem}.jnlp"
        out_path = tmp_dir / suggested
        await download.save_as(str(out_path))
        logger.info(
            "servei_cat_trans.confirmacion: [%s] evento download capturado filename=%s ruta=%s",
            rid,
            download.suggested_filename,
            out_path,
        )
        if not _looks_like_jnlp_file(out_path):
            logger.warning(
                "servei_cat_trans.confirmacion: [%s] download capturado pero no parece JNLP valido (%s).",
                rid,
                out_path,
            )
            recovered = _find_recent_jnlp_in_downloads()
            if recovered:
                if not response_task.done():
                    response_task.cancel()
                logger.info(
                    "servei_cat_trans.confirmacion: [%s] recuperado JNLP alternativo tras validacion fallida: %s",
                    rid,
                    recovered,
                )
                return _persist_jnlp_for_run(recovered, rid=rid)
            return await _download_jnlp_from_response(page, rid=rid)
        logger.info("servei_cat_trans.confirmacion: [%s] JNLP valido por evento download", rid)
        if not response_task.done():
            response_task.cancel()
        return out_path
    except Exception as exc:
        if not download_task.done():
            download_task.cancel()
        if not response_task.done():
            response_task.cancel()
        logger.warning(
            "servei_cat_trans.confirmacion: [%s] fallo esperando evento download (%s).",
            rid,
            exc,
        )
        recovered = _find_recent_jnlp_in_downloads()
        if recovered:
            if not response_task.done():
                response_task.cancel()
            logger.info(
                "servei_cat_trans.confirmacion: [%s] recuperado JNLP desde descargas tras excepcion de evento: %s",
                rid,
                recovered,
            )
            return _persist_jnlp_for_run(recovered, rid=rid)
        logger.warning("servei_cat_trans.confirmacion: [%s] no se capturo download directo; fallback por URL.", rid)
        return await _download_jnlp_from_response(page, rid=rid)


_JAVA8_CANDIDATES = (
    "/tmp/jdk8u432-b06-jre/bin/java",
    "/usr/lib/jvm/java-8-openjdk-amd64/bin/java",
    "/opt/java8/bin/java",
)
_NETX_JAR_CANDIDATES = (
    "/usr/share/icedtea-web/netx.jar",
    "/usr/share/java/icedtea-web.jar",
    "/usr/share/java/netx.jar",
)


def _resolve_java_command(jnlp_path: Path) -> list[str]:
    jnlp_arg = str(jnlp_path)
    try:
        # IcedTea-Web en Linux falla con rutas absolutas sin esquema ("no protocol").
        # Forzamos file:// para que javaws cargue correctamente el JNLP local.
        jnlp_arg = jnlp_path.resolve().as_uri()
    except Exception:
        jnlp_arg = str(jnlp_path)

    # El applet de signador.aoc.cat usa sun.misc.BASE64Decoder que fue eliminado en Java 11.
    # Priorizamos Java 8 + netx.jar para garantizar compatibilidad.
    java8_bin = None
    for candidate in _JAVA8_CANDIDATES:
        if Path(candidate).exists():
            java8_bin = candidate
            break

    netx_jar = None
    for candidate in _NETX_JAR_CANDIDATES:
        if Path(candidate).exists():
            netx_jar = candidate
            break

    if java8_bin and netx_jar:
        logger.info("servei_cat_trans.confirmacion: usando Java 8 (%s) + netx.jar para JNLP", java8_bin)
        return [
            java8_bin,
            "-cp", netx_jar,
            "net.sourceforge.jnlp.runtime.Boot",
            "-headless", "-nosecurity", "-Xnofork",
            jnlp_arg,
        ]

    # Fallback: javaws del sistema (puede fallar con Java 11+ si el applet usa APIs legacy)
    javaws_bin = shutil.which("javaws") or shutil.which("itweb-javaws")
    if javaws_bin:
        logger.warning(
            "servei_cat_trans.confirmacion: Java 8 no disponible, usando javaws del sistema. "
            "El applet puede fallar con sun.misc.BASE64Decoder."
        )
        return [javaws_bin, "-headless", "-nosecurity", "-Xnofork", jnlp_arg]

    if netx_jar:
        return ["java", "-jar", netx_jar, "-headless", "-nosecurity", "-Xnofork", str(jnlp_path)]

    raise RuntimeError(
        "servei_cat_trans.confirmacion: no hay ejecutor JNLP disponible. "
        "Instala javaws/icedtea-netx en el contenedor."
    )


def _ensure_firefox_nss_profile() -> None:
    """Crea un perfil Firefox con el certificado PFX importado en NSS.

    El applet AOC (signador.aoc.cat) usa MozillaKeyStores que busca
    certificados exclusivamente en el perfil de Firefox.
    """
    if os.name == "nt":
        return
    ff_dir = Path("/root/.mozilla/firefox")
    profile_dir = ff_dir / "xaloc.default"
    if (profile_dir / "cert9.db").exists():
        logger.info("servei_cat_trans.confirmacion: Firefox NSS profile ya existe")
        return

    logger.info("servei_cat_trans.confirmacion: creando Firefox NSS profile para applet AOC")
    profile_dir.mkdir(parents=True, exist_ok=True)

    # profiles.ini para que MozillaKeyStores localice el perfil
    (ff_dir / "profiles.ini").write_text(
        "[General]\nStartWithLastProfile=1\n\n"
        "[Profile0]\nName=default\nIsRelative=1\n"
        "Path=xaloc.default\nDefault=1\n",
        encoding="utf-8",
    )

    # Inicializar NSS (sql: y dbm: por compatibilidad)
    for db_prefix in ("sql:", "dbm:"):
        try:
            subprocess.run(
                ["certutil", "-d", f"{db_prefix}{profile_dir}", "-N", "--empty-password"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    # Importar PFX
    cert_path = os.environ.get("PLAYWRIGHT_CERT_PATH", "/data/certificates/certificate.pfx")
    cert_pass = os.environ.get("PLAYWRIGHT_CERT_PASSWORD", "NetMulti01")
    if Path(cert_path).exists():
        for db_prefix in ("sql:", "dbm:"):
            try:
                r = subprocess.run(
                    ["pk12util", "-d", f"{db_prefix}{profile_dir}", "-i", cert_path, "-W", cert_pass],
                    capture_output=True, timeout=10,
                )
                logger.info(
                    "servei_cat_trans.confirmacion: pk12util %s rc=%s", db_prefix, r.returncode,
                )
            except Exception as exc:
                logger.warning("servei_cat_trans.confirmacion: pk12util %s fallo: %s", db_prefix, exc)

        # Marcar CAs como trusted para que el applet valide la cadena
        try:
            r = subprocess.run(
                ["certutil", "-d", f"sql:{profile_dir}", "-L"],
                capture_output=True, timeout=5,
            )
            for line in r.stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                # Las CAs importadas tienen trust ",,   " — las marcamos como trusted
                if line and (",,   " in line or ",," in line) and not line.startswith("Certificate"):
                    nickname = line.rsplit("  ", 1)[0].strip()
                    if nickname:
                        subprocess.run(
                            ["certutil", "-d", f"sql:{profile_dir}", "-M", "-n", nickname, "-t", "CT,C,C"],
                            capture_output=True, timeout=5,
                        )
                        logger.info("servei_cat_trans.confirmacion: CA trusted: %s", nickname)
        except Exception:
            pass

        # Listar certificados importados
        try:
            r = subprocess.run(
                ["certutil", "-d", f"sql:{profile_dir}", "-L"],
                capture_output=True, timeout=5,
            )
            logger.info("servei_cat_trans.confirmacion: certs en Firefox NSS:\n%s", r.stdout.decode(errors="ignore"))
        except Exception:
            pass
    else:
        logger.warning("servei_cat_trans.confirmacion: PFX no encontrado en %s", cert_path)


async def _start_linux_dialog_auto_acceptor(*, timeout_s: int = 150):
    if os.name == "nt":
        return None
    if not shutil.which("xdotool"):
        raise RuntimeError(
            "servei_cat_trans.confirmacion: xdotool no disponible para aceptar dialogs de Java."
        )

    script = f"""
set -e
end_ts=$((SECONDS+{timeout_s}))
acted_on=""

click_button_run() {{
  local wid="$1"
  # Get window geometry to compute button position
  local geo
  geo="$(xdotool getwindowgeometry --shell "$wid" 2>/dev/null)" || return 1
  local wx wy ww wh
  eval "$geo"  # sets X, Y, WIDTH, HEIGHT
  wx=$X; wy=$Y; ww=$WIDTH; wh=$HEIGHT
  # "Run" button is bottom-left area of the dialog (~15% from left, ~90% from top)
  local bx=$(( wx + ww * 15 / 100 ))
  local by=$(( wy + wh * 90 / 100 ))
  echo "dialog-click-run wid=$wid at=$bx,$by (win=${{ww}}x${{wh}}+${{wx}}+${{wy}})"
  xdotool mousemove --sync "$bx" "$by" 2>/dev/null || true
  sleep 0.1
  xdotool click 1 2>/dev/null || true
  sleep 0.15
  xdotool click 1 2>/dev/null || true
}}

while [ $SECONDS -lt $end_ts ]; do
  # Priority 1: "Security Approval Required" dialog
  sec_ids="$(xdotool search --onlyvisible --name 'Security Approval Required' 2>/dev/null || true)"
  if [ -n "$sec_ids" ]; then
    for id in $sec_ids; do
      echo "dialog-match-security id=$id"
      xdotool windowactivate --sync "$id" 2>/dev/null || true
      sleep 0.2
      # Try mouse click on Run button first (most reliable for Java Swing)
      click_button_run "$id"
      # Also try keyboard as backup
      xdotool key --window "$id" Alt+r 2>/dev/null || true
      sleep 0.05
      xdotool key --window "$id" Return 2>/dev/null || true
      echo "dialog-action-security id=$id"
      acted_on="$id"
      # Wait to see if dialog closed
      sleep 0.8
      if ! xdotool getwindowname "$id" >/dev/null 2>&1; then
        echo "dialog-dismissed id=$id"
        acted_on=""
      fi
    done
    sleep 0.5
    continue
  fi

  # Priority 2: AOC cert selection dialog (Java Swing, name=" " or blank, ~500x400)
  # The AOC applet CertSelectionDialog has no title (name is a single space).
  # We detect it by checking for visible Java windows with blank/space name and dialog-like size.
  blank_ids="$(xdotool search --onlyvisible --name ' ' 2>/dev/null || true)"
  for id in $blank_ids; do
    bname="$(xdotool getwindowname "$id" 2>/dev/null || true)"
    # Only match windows with blank or space-only name
    case "$bname" in
      ""|" "|"  ") ;;
      *) continue ;;
    esac
    geo="$(xdotool getwindowgeometry --shell "$id" 2>/dev/null || true)"
    eval "$geo" 2>/dev/null || continue
    # AOC dialog is ~504x407; skip tiny windows and full-screen windows
    if [ "${{WIDTH:-0}}" -gt 200 ] && [ "${{WIDTH:-0}}" -lt 800 ] && [ "${{HEIGHT:-0}}" -gt 200 ] && [ "${{HEIGHT:-0}}" -lt 600 ]; then
      echo "dialog-match-aoc-cert id=$id size=${{WIDTH}}x${{HEIGHT}}"
      xdotool windowactivate --sync "$id" 2>/dev/null || true
      sleep 0.3
      xdotool windowfocus --sync "$id" 2>/dev/null || true
      sleep 0.2
      # "Accepteu" button is at ~37% from left, ~71% from top
      local_bx=$(( X + WIDTH * 37 / 100 ))
      local_by=$(( Y + HEIGHT * 71 / 100 ))
      echo "dialog-click-accepteu id=$id at=$local_bx,$local_by"
      xdotool mousemove --sync "$local_bx" "$local_by" 2>/dev/null || true
      sleep 0.15
      xdotool click 1 2>/dev/null || true
      sleep 0.2
      xdotool click 1 2>/dev/null || true
      # Also try keyboard shortcuts as backup
      xdotool key --window "$id" Alt+a 2>/dev/null || true
      sleep 0.1
      xdotool key --window "$id" Return 2>/dev/null || true
      sleep 0.8
      if ! xdotool getwindowname "$id" >/dev/null 2>&1; then
        echo "dialog-dismissed-aoc-cert id=$id"
      fi
    fi
  done

  # Priority 3: Other security/certificate dialogs (NOT main Autofirma window)
  ids="$(xdotool search --onlyvisible --name '.' 2>/dev/null || true)"
  for id in $ids; do
    name="$(xdotool getwindowname "$id" 2>/dev/null || true)"
    lname="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
    # Skip main Autofirma window (not a dialog to dismiss)
    case "$lname" in
      autofirma*|*autofirma\ v*) continue ;;
    esac
    case "$lname" in
      *xdg-open*|*open*application*|*icedtea*|*certificat*|*certificate*|*seguridad*|*security*|*approval*|*trust*|*seleccio*)
        echo "dialog-match-other id=$id name=$name"
        xdotool windowactivate --sync "$id" 2>/dev/null || true
        sleep 0.2
        # Try clicking Run/OK/Accept button area
        click_button_run "$id"
        xdotool key --window "$id" Alt+r 2>/dev/null || true
        xdotool key --window "$id" Alt+o 2>/dev/null || true
        xdotool key --window "$id" Alt+a 2>/dev/null || true
        xdotool key --window "$id" Return 2>/dev/null || true
        echo "dialog-action-other id=$id"
        sleep 0.8
      ;;
    esac
  done
  sleep 0.5
done
echo "dialog-watcher-timeout"
"""
    return await asyncio.create_subprocess_exec(
        "bash",
        "-lc",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _terminate_process(proc, *, timeout_s: float = 5.0) -> None:
    if proc is None:
        return
    try:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    except Exception:
        return


async def _wait_for_receipt_page(page: "Page", *, timeout_ms: int, sign_proc=None) -> "Page":
    deadline = time.monotonic() + (timeout_ms / 1000)
    next_progress_log = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if sign_proc is not None and sign_proc.returncode is not None and int(sign_proc.returncode) != 0:
            raise RuntimeError(
                f"servei_cat_trans.confirmacion: el proceso de firma JNLP finalizo con error (rc={sign_proc.returncode})."
            )
        for p in list(page.context.pages):
            try:
                current = str(p.url or "")
            except Exception:
                continue
            if _RECEIPT_PAGE_RE.search(current):
                return p
        if time.monotonic() >= next_progress_log:
            rc = None if sign_proc is None else sign_proc.returncode
            try:
                current_url = str(page.url or "")
            except Exception:
                current_url = ""
            logger.info(
                "servei_cat_trans.confirmacion: esperando redireccion post-firma (rc=%s url_actual=%s)",
                rc,
                current_url,
            )
            next_progress_log = time.monotonic() + 10.0
        await page.wait_for_timeout(500)
    raise RuntimeError(
        "servei_cat_trans.confirmacion: no se alcanzo la pagina final de registro tras la firma JNLP."
    )


async def _download_receipt(page: "Page", *, rid: str) -> Path:
    await dismiss_cookie_banner_if_present(page)
    link = page.locator(_RECEIPT_LINK_SELECTOR).first
    await link.wait_for(state="visible", timeout=_RECEIPT_TIMEOUT_MS)
    await page.wait_for_timeout(1000)

    tmp_dir = Path("tmp") / "servei_cat_trans" / "justificantes" / rid
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with page.expect_download(timeout=60000) as dl_info:
            await dismiss_cookie_banner_if_present(page)
            await link.click(force=True, timeout=_ACTION_TIMEOUT_MS)
        download = await dl_info.value
        suggested = _safe_filename(download.suggested_filename, f"justificante_{rid}.pdf")
        if not suggested.lower().endswith(".pdf"):
            suggested = f"{Path(suggested).stem}.pdf"
        tmp_path = tmp_dir / suggested
        await download.save_as(str(tmp_path))
        return tmp_path
    except Exception:
        href = str(await link.get_attribute("href") or "").strip()
        if not href:
            raise RuntimeError(
                "servei_cat_trans.confirmacion: enlace de justificante visible, pero sin href descargable."
            )
        url = urljoin(str(page.url or ""), href)
        resp = await page.context.request.get(url, timeout=90000)
        if not resp.ok:
            raise RuntimeError(
                f"servei_cat_trans.confirmacion: fallo en descarga HTTP del justificante ({resp.status})."
            )
        content = await resp.body()
        if not content.startswith(b"%PDF"):
            raise RuntimeError(
                "servei_cat_trans.confirmacion: la descarga del justificante no devolvio un PDF valido."
            )
        tmp_path = tmp_dir / f"justificante_{rid}.pdf"
        tmp_path.write_bytes(content)
        return tmp_path


async def _store_receipt(tmp_path: Path, datos: "ServeiCatTransTarget") -> Path:
    expediente = str(datos.expediente or (datos.payload or {}).get("expediente") or "UNKNOWN").strip() or "UNKNOWN"
    destino_dir = resolve_receipt_dir_from_payload(
        payload=datos.payload or {},
        fase_procedimiento=str((datos.payload or {}).get("fase_procedimiento") or (datos.payload or {}).get("FaseProcedimiento") or "").strip() or None,
    )
    final_name = build_receipt_filename(expediente=expediente, template="JUSTIFICANTE - {expediente}.pdf")
    return save_receipt_from_tmp(tmp_path=tmp_path, destino_dir=destino_dir, filename=final_name)


async def run_confirmacion(page: "Page", config: "ServeiCatTransConfig", datos: "ServeiCatTransTarget") -> "Page":
    _ = config
    if not isinstance(datos.payload, dict):
        datos.payload = {}
    datos.payload["servei_cat_trans_justificante_descargado"] = False
    datos.payload.pop("servei_cat_trans_justificante_path", None)
    datos.payload.pop("servei_cat_trans_justificante_artifact_path", None)

    if (os.getenv("XALOC_HEADLESS") or "0").strip() in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "servei_cat_trans.confirmacion: la firma JNLP requiere navegador con UI. "
            "Configura XALOC_HEADLESS=0 en playwright-runner."
        )

    await page.wait_for_timeout(500)
    await dismiss_cookie_banner_if_present(page)
    scope: "Page | Frame" = await wait_form_scope(page, timeout_ms=20000)
    sign_button = await _find_sign_button(scope)
    rid = _safe_resource_id(datos)
    logger.info(
        "servei_cat_trans.confirmacion: [%s] inicio run_confirmacion headless=%s",
        rid,
        os.getenv("XALOC_HEADLESS"),
    )

    logger.info("servei_cat_trans.confirmacion: iniciando firma final JNLP (idRecurso=%s).", rid)
    jnlp_path = await _capture_jnlp_download(page, sign_button, rid=rid)
    try:
        jnlp_size = jnlp_path.stat().st_size
    except Exception:
        jnlp_size = -1
    logger.info("servei_cat_trans.confirmacion: [%s] JNLP descargado en %s (bytes=%s)", rid, jnlp_path, jnlp_size)

    _ensure_firefox_nss_profile()
    java_cmd = _resolve_java_command(jnlp_path)
    logger.info("servei_cat_trans.confirmacion: [%s] ejecutando firma con comando=%s", rid, " ".join(java_cmd))

    tmp_dir = _firm_tmp_dir(rid=rid)
    java_stdout_log = tmp_dir / "javaws_stdout.log"
    java_stderr_log = tmp_dir / "javaws_stderr.log"
    dialog_log = tmp_dir / "dialog_watcher.log"

    dialog_watcher = await _start_linux_dialog_auto_acceptor(timeout_s=180)
    logger.info("servei_cat_trans.confirmacion: [%s] watcher dialogs iniciado pid=%s", rid, getattr(dialog_watcher, "pid", None))
    dialog_out_task = asyncio.create_task(
        _stream_subprocess_output(
            getattr(dialog_watcher, "stdout", None),
            rid=rid,
            tag="[dialog][OUT]",
            out_path=dialog_log,
        )
    )
    dialog_err_task = asyncio.create_task(
        _stream_subprocess_output(
            getattr(dialog_watcher, "stderr", None),
            rid=rid,
            tag="[dialog][ERR]",
            out_path=dialog_log,
        )
    )
    sign_proc = await asyncio.create_subprocess_exec(
        *java_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    logger.info("servei_cat_trans.confirmacion: [%s] proceso java lanzado pid=%s", rid, sign_proc.pid)
    # En modo -headless, IcedTea-Web muestra prompt de seguridad por stdin:
    #   [YES, NO, SANDBOX]
    # Enviamos "R YES" (remember + accept) repetido para cubrir multiples prompts.
    # El pipe buffer guarda los datos hasta que javaws los lea.
    try:
        # Multiples lineas por si hay mas de un prompt de seguridad
        stdin_payload = b"R YES\nR YES\nR YES\nYES\nYES\n"
        sign_proc.stdin.write(stdin_payload)
        await sign_proc.stdin.drain()
        logger.info("servei_cat_trans.confirmacion: [%s] enviado respuestas YES a stdin de javaws (%d bytes)", rid, len(stdin_payload))
    except Exception as stdin_exc:
        logger.warning("servei_cat_trans.confirmacion: [%s] error escribiendo stdin javaws: %s", rid, stdin_exc)
    java_out_task = asyncio.create_task(
        _stream_subprocess_output(
            sign_proc.stdout,
            rid=rid,
            tag="[javaws][OUT]",
            out_path=java_stdout_log,
        )
    )
    java_err_task = asyncio.create_task(
        _stream_subprocess_output(
            sign_proc.stderr,
            rid=rid,
            tag="[javaws][ERR]",
            out_path=java_stderr_log,
        )
    )
    await page.wait_for_timeout(_INTER_ACTION_DELAY_MS)
    if sign_proc.returncode is not None:
        logger.warning(
            "servei_cat_trans.confirmacion: [%s] proceso java finalizo demasiado pronto rc=%s",
            rid,
            sign_proc.returncode,
        )
    else:
        logger.info("servei_cat_trans.confirmacion: [%s] proceso java sigue en ejecucion tras arranque", rid)

    try:
        try:
            receipt_page = await _wait_for_receipt_page(page, timeout_ms=_REDIRECT_TIMEOUT_MS, sign_proc=sign_proc)
        finally:
            await _terminate_process(dialog_watcher, timeout_s=2.0)
            await asyncio.gather(dialog_out_task, dialog_err_task, return_exceptions=True)
            logger.info("servei_cat_trans.confirmacion: [%s] watcher dialogs finalizado", rid)

        tmp_receipt = await _download_receipt(receipt_page, rid=rid)
        final_receipt = await _store_receipt(tmp_receipt, datos)

        datos.payload["servei_cat_trans_justificante_descargado"] = True
        datos.payload["servei_cat_trans_justificante_path"] = str(final_receipt)
        datos.payload["servei_cat_trans_justificante_artifact_path"] = str(tmp_receipt)
        logger.info("servei_cat_trans.confirmacion: [%s] justificante guardado en %s", rid, final_receipt)
        return page
    finally:
        await _terminate_process(sign_proc, timeout_s=3.0)
        await asyncio.gather(java_out_task, java_err_task, return_exceptions=True)
        logger.info(
            "servei_cat_trans.confirmacion: [%s] logs firma java stdout=%s stderr=%s dialog=%s",
            rid,
            java_stdout_log,
            java_stderr_log,
            dialog_log,
        )
