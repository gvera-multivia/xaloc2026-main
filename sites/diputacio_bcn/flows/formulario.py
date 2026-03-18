from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import DiputacioBcnConfig
    from ..data_models import DiputacioBcnTarget


def _existing_file(path_value: str) -> str:
    candidate = Path(str(path_value or "").strip())
    if candidate and candidate.exists() and candidate.is_file():
        return str(candidate)
    return ""


def _pick_latest_open_page(page: "Page") -> "Page":
    if not page.is_closed():
        return page
    pages = [p for p in page.context.pages if not p.is_closed()]
    if not pages:
        raise RuntimeError("No hay pestañas activas tras la redirección de identificación.")
    return pages[-1]


async def _paso4_fisica(page: "Page", datos: "DiputacioBcnTarget") -> None:
    await page.get_by_role(
        "link",
        name="La entidad actúa en representación de una persona física",
    ).click()
    await page.locator("#nifcr4c").fill((datos.nif_interessat or "00000000T").upper())
    await page.locator("#nomcr4c").fill(datos.nom_cr4 or "Nom")
    await page.locator("#cognom1cr4c").fill(datos.cognom1 or "Cognom1")
    await page.locator("#cognom2cr4c").fill(datos.cognom2 or "Cognom2")
    await page.locator("#collapseFour").get_by_role("button", name="Continuar").click()


async def _paso4_juridica(page: "Page", datos: "DiputacioBcnTarget") -> None:
    await page.get_by_role(
        "link",
        name="La entidad actúa en representación de otra entidad",
    ).click()
    await page.locator("#identificadorInteressatCR5Rep").fill((datos.nif_interessat or "").upper())
    await page.locator("#nomInteressatCR5Rep").fill(datos.nom_juridica or "Empresa SL")
    await page.locator("#collapseFive").get_by_role("button", name="Continuar").click()


async def run_formulario(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = config
    page = _pick_latest_open_page(page)

    if "/Home/representacioPas1juridica" not in page.url:
        try:
            await page.wait_for_url("https://valid.aoc.cat/**", timeout=120000)
        except Exception:
            page = _pick_latest_open_page(page)
        if "/Home/representacioPas1juridica" not in page.url:
            btn_cert = page.locator("#btnContinuaCert")
            await btn_cert.wait_for(state="visible", timeout=60000)
            try:
                await btn_cert.click(force=True, timeout=10000)
            except Exception:
                await page.evaluate(
                    "() => { const b = document.querySelector('#btnContinuaCert'); if (b) b.click(); }"
                )
            await page.wait_for_url("**/Home/representacioPas1juridica**", timeout=180000)

    await page.get_by_role("radio", name="Representante legal").click()
    await page.get_by_role("button", name="La entidad es representante de otra persona interesada").click()

    await page.wait_for_url("**/Home/representacioPas2juridica**", timeout=120000)
    if (datos.tipo_representado or "fisica").strip().lower() == "juridica":
        await _paso4_juridica(page, datos)
    else:
        await _paso4_fisica(page, datos)

    await page.wait_for_url("**/Home/representacioPas3juridica**", timeout=120000)
    await page.wait_for_load_state("networkidle", timeout=15000)

    doc_path = _existing_file(datos.doc_acreditativa)
    if not doc_path:
        raise RuntimeError(
            "Falta documento acreditativo para paso 3b. Define DIPUTACIO_BCN_DOC_ACREDITATIVA o payload.doc_acreditativa."
        )

    # La página tiene #ComentFile (descripción) y #fakeBrowse (input[type='button'])
    # igual que la pantalla de documentos. Rellenar descripción antes de subir
    # porque upload() lee $("#ComentFile").val() al enviar el AJAX.
    # NOTA: tras el AJAX el div #formFiles se reemplaza entero → el fill se hace
    # aquí solo para que upload() lo lea en el momento del onchange del file input.
    await page.locator("#ComentFile").wait_for(state="visible", timeout=15000)
    await page.locator("#ComentFile").fill("Poder de representacion")

    # #fakeBrowse es un input[type='button'] que llama CridaUpload() → jQuery trigger
    # en el input[type='file'] oculto. expect_file_chooser lo intercepta.
    fake_browse = page.locator("#fakeBrowse").first
    if await fake_browse.count() == 0:
        raise RuntimeError("No se encuentra #fakeBrowse en representacioPas3juridica.")

    chooser_ok = False
    try:
        async with page.expect_file_chooser(timeout=10000) as fc_info:
            await fake_browse.click(force=True)
        fc = await fc_info.value
        await fc.set_files(doc_path)
        chooser_ok = True
    except Exception:
        chooser_ok = False

    if not chooser_ok:
        # Fallback: set_input_files sobre el input[type='file'] oculto via DataTransfer
        import base64 as _b64
        _file_bytes = Path(doc_path).read_bytes()
        _file_b64 = _b64.b64encode(_file_bytes).decode()
        _file_name = Path(doc_path).name
        await page.evaluate(
            """([b64, name]) => {
                const input = document.querySelector("input[type='file']");
                if (!input) return;
                const byteChars = atob(b64);
                const byteArr = new Uint8Array(byteChars.length);
                for (let i = 0; i < byteChars.length; i++) byteArr[i] = byteChars.charCodeAt(i);
                const file = new File([byteArr], name, { type: 'application/octet-stream' });
                const dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            [_file_b64, _file_name],
        )

    # Esperar a que el AJAX de upload complete (#formFiles se actualiza con la fila)
    for _attempt in range(10):
        rows = await page.evaluate("""() => {
            const tbody = document.querySelector('#formFiles tbody');
            if (!tbody) return 0;
            return Array.from(tbody.querySelectorAll('tr')).filter(tr => {
                const tds = tr.querySelectorAll('td');
                return tds.length >= 2 && (tds[0].textContent || '').trim();
            }).length;
        }""")
        if rows > 0:
            break
        await page.wait_for_timeout(1000)

    # Continuar: input[type='submit'] con value='Continuar'
    continuar = page.locator("input[type='submit'][value='Continuar']").first
    if await continuar.count() == 0:
        continuar = page.locator("input[type='submit'][value='Continua']").first
    await continuar.click()
    return _pick_latest_open_page(page)
