from __future__ import annotations

from pathlib import Path
from playwright.async_api import Page


async def subir_adjuntos(page: Page, archivos: list[Path]):
    """
    Sube los archivos adjuntos uno por uno.
    """
    if not archivos:
        # If no files, just continue?
        # The recording flow went to upload page, so we assume we are there.
        pass

    # The recording shows usage of #fichero and #fichero1.
    # It seems the system might allow uploading multiple files by filling one input,
    # then maybe clicking "Clicar per adjuntar" to add it to the list?
    # Or maybe #fichero1 appears after #fichero is used?

    # Strategy:
    # For each file, try to find an available file input.
    # If not available, maybe we need to click "Clicar per adjuntar" (Attach) first?
    # The recording sequence:
    # 1. Upload to #fichero
    # 2. Upload to #fichero1
    # 3. Click "Clicar per adjuntar" (div#adjuntar > table > ... > a)
    # 4. Click Continue

    # It seems "Clicar per adjuntar" might be "Add another" or "Upload the selected ones".
    # Given the recording, it seems we can interact with #fichero and #fichero1 directly.

    # Let's try to upload files.
    for i, archivo in enumerate(archivos):
        if not archivo.exists():
            continue

        # Try to find an input
        input_id = f"#fichero{i if i > 0 else ''}" # #fichero, #fichero1, #fichero2...

        # Check if element exists, if not, maybe we need to trigger something?
        # But for now let's assume standard behavior as per recording.
        if await page.locator(input_id).count() > 0:
             await page.set_input_files(input_id, archivo)
        else:
            # Fallback: try using the main #fichero input for all?
            # Or assume we maxed out inputs.
            pass

    # Click "Clicar per adjuntar" (Attach)
    # Selector: div#adjuntar > table > tbody > tr:nth-of-type(2) > td > a
    # Text: "Clicar per adjuntar"
    # This might be necessary to confirm the upload.
    try:
        attach_btn = page.locator("a", has_text="Clicar per adjuntar")
        if await attach_btn.count() > 0 and await attach_btn.is_visible():
            await attach_btn.click()
            await page.wait_for_timeout(1000) # Wait for processing
    except Exception:
        pass

    # Click Continue (on upload page)
    # Selector: div#continuar > a
    await page.click("div#continuar > a")

    # Back to Form page or Confirmation page?
    # Recording shows:
    # -> documentSignSend.jsp (with # hash)
    # -> TramitaForm (back to form?)
    # -> Check lopdok
    # -> Click Continuar

    # Wait for return to form or next step.
    # The check #lopdok interaction suggests we are back at the form or a summary section.
    await page.wait_for_selector("#lopdok")

    # Check LOPD
    await page.check("#lopdok")

    # Final Continue
    # Selector: div#botoncontinuar > a
    await page.click("div#botoncontinuar > a")

    # Wait for signature page or final step
    await page.wait_for_url("**/TramitaSign**")
