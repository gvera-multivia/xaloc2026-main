from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget

logger = logging.getLogger("xaloc_automation.terrassa")


async def _visible_upload_indices(page: "Page") -> list[int]:
    indices = await page.evaluate(
        """() => {
            const out = [];
            const nodes = Array.from(document.querySelectorAll("input[id^='fileUpload']"));
            for (const el of nodes) {
                const m = (el.id || "").match(/^fileUpload(\\d+)$/);
                if (!m) continue;
                const idx = Number(m[1]);
                if (!Number.isFinite(idx)) continue;
                const form = document.getElementById(`fitxers${idx}`);
                const block = document.getElementById(`uploadFitxer${idx}`);
                if (!form || !block) continue;
                out.push(idx);
            }
            out.sort((a, b) => a - b);
            return Array.from(new Set(out));
        }"""
    )
    return [int(x) for x in (indices or [])]


async def _resolve_upload_index(
    page: "Page",
    *,
    preferred_index: int,
    used_indices: set[int],
    timeout_ms: int,
) -> int:
    waited = 0
    step_ms = 500
    last_visible: list[int] = []
    while waited <= timeout_ms:
        visible = await _visible_upload_indices(page)
        last_visible = visible
        free = [idx for idx in visible if idx not in used_indices]
        if preferred_index in free:
            return preferred_index
        if free:
            return min(free)
        await page.wait_for_timeout(step_ms)
        waited += step_ms

    # Terrassa a veces no pinta un bloque nuevo y obliga a reutilizar uno existente.
    # En ese caso elegimos un bloque visible en vez de abortar.
    if last_visible:
        if preferred_index in last_visible:
            return preferred_index
        return min(last_visible)

    raise RuntimeError(
        f"terrassa-docs: no hay bloques de subida visibles para doc index={preferred_index}. "
        f"bloques_ya_usados={sorted(used_indices)}"
    )


async def run_documentos(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    docs = list(datos.documentos or [])
    if not docs:
        docs = [
            {"fitxer": str(p), "descripcio": p.stem[:70] or "Documento", "tipus": "Al-legacio"}
            for p in (datos.archivos_para_subir or [])
        ]

    if not docs:
        base_path = str(datos.payload.get("docs_base_path") or r"\\SERVER-DOC\clientes")
        sujeto = str(datos.payload.get("nombre") or "").strip()
        raise ValueError(
            f"terrassa: faltan documentos para subida. Revisar carpeta cliente en {base_path} (sujeto: {sujeto})."
        )

    total_docs = len(docs)
    used_upload_indices: set[int] = set()

    for index, doc in enumerate(docs):
        file_path = Path(str(doc.get("fitxer") or "")).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(str(file_path))

        descripcio = str(doc.get("descripcio") or "Documento").strip()[:79]
        tipus = str(doc.get("tipus") or "Al-legacio").strip()

        block_timeout = min(int(config.timeouts.subida_archivo), 12000)
        upload_index = await _resolve_upload_index(
            page,
            preferred_index=index,
            used_indices=used_upload_indices,
            timeout_ms=block_timeout,
        )

        block_sel = f"#uploadFitxer{upload_index}"
        form_sel = f"form#fitxers{upload_index}"
        file_sel = f"input#fileUpload{upload_index}"

        logger.info(
            "[terrassa-docs] doc %s/%s -> upload_index=%s file=%s block_sel=%s form_sel=%s file_sel=%s",
            index + 1,
            total_docs,
            upload_index,
            str(file_path),
            block_sel,
            form_sel,
            file_sel,
        )

        await page.wait_for_selector(f"{block_sel} {form_sel} {file_sel}", timeout=min(block_timeout, 8000))
        form = page.locator(form_sel).first
        # Evitar dependencia de labels o idioma: usar estructura del bloque por id.
        desc_input = form.locator("input[type='text']").first
        tipo_select = form.locator("select").first
        file_input = form.locator(file_sel).first

        if upload_index in used_upload_indices:
            logger.warning(
                "[terrassa-docs] reutilizando bloque index=%s por ausencia de bloque nuevo visible",
                upload_index,
            )

        await desc_input.fill(descripcio)
        try:
            await tipo_select.select_option(label=tipus, timeout=5000)
            logger.info("[terrassa-docs] tipo seleccionado por label exacta: %s", tipus)
        except PlaywrightTimeoutError:
            # Fallback robusto por acentos/codificacion: buscar por texto normalizado.
            option_value = await tipo_select.evaluate(
                """(sel, targetLabel) => {
                    const norm = (txt) => (txt || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .trim()
                        .toLowerCase();
                    const wanted = norm(targetLabel);
                    const options = Array.from(sel.options || []);
                    let found = options.find((o) => norm(o.textContent || "") === wanted);
                    if (!found) {
                        found = options.find((o) => norm(o.textContent || "").includes(wanted));
                    }
                    if (!found) {
                        found = options.find((o) => (o.value || "").trim() && (o.value || "") !== "-");
                    }
                    return found ? found.value : null;
                }""",
                tipus,
            )
            if option_value:
                await tipo_select.select_option(value=str(option_value), timeout=5000)
                logger.info(
                    "[terrassa-docs] tipo seleccionado por fallback normalizado. label=%s value=%s",
                    tipus,
                    option_value,
                )
            else:
                logger.warning("[terrassa-docs] no se encontro opcion de tipo para label=%s", tipus)

        await file_input.set_input_files(str(file_path))
        # En algunos builds el onchange no siempre se dispara con set_input_files.
        try:
            await file_input.evaluate(
                """(el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }"""
            )
        except Exception:
            pass

        used_upload_indices.add(upload_index)

        # Confirmacion adicional: que el nombre del fichero aparezca en la pagina.
        try:
            await page.wait_for_selector(f"text={file_path.name}", timeout=min(int(config.timeouts.subida_archivo), 20000))
            logger.info("[terrassa-docs] nombre de fichero visible tras upload: %s", file_path.name)
        except PlaywrightTimeoutError:
            logger.warning("[terrassa-docs] no se vio el nombre del fichero subido: %s", file_path.name)

        # Web inestable: margen fijo para que procese y pinte el siguiente bloque real.
        if index < (total_docs - 1):
            await page.wait_for_timeout(5000)

    return page
