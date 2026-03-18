from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from core.justificantes_storage import (
    build_receipt_filename,
    resolve_receipt_dir_from_payload,
    save_receipt_from_tmp,
)

from ._dom import get_invalid_required_fields, robust_click, set_bound_value, wait_after_action

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget

logger = logging.getLogger(__name__)
REGISTRO_DESC_MAX_LEN = 15
ATC_CONFIRM_SHORT_TIMEOUT_MS = 10000
ATC_CONFIRM_MEDIUM_TIMEOUT_MS = 30000
ATC_CONFIRM_LONG_TIMEOUT_MS = 60000
ATC_CONFIRM_DOWNLOAD_TIMEOUT_MS = 120000


def _resolve_atc_phase_folder(datos: "AtcTarget") -> str | None:
    payload = dict(getattr(datos, "payload", {}) or {})
    fase = str(payload.get("fase_procedimiento") or payload.get("FaseProcedimiento") or "").strip()
    if fase:
        return fase
    return None


async def _click_presentar(page: "Page") -> None:
    for selector in [
        "button.se-button--primary:has-text('Presentar')",
        "button:has-text('Presentar')",
        "[role='button']:has-text('Presentar')",
    ]:
        try:
            await robust_click(page, selector, timeout=ATC_CONFIRM_SHORT_TIMEOUT_MS)
            return
        except Exception:
            continue
    presentar = page.get_by_role("button", name=re.compile(r"Presentar|Submit", re.IGNORECASE)).first
    await presentar.click(timeout=ATC_CONFIRM_SHORT_TIMEOUT_MS)
    await wait_after_action(page)


def _prepare_payload_for_client_folder(datos: "AtcTarget") -> dict:
    payload = dict(getattr(datos, "payload", {}) or {})
    payload.setdefault("tipodecliente", payload.get("cliente_tipo") or "2")
    payload.setdefault("Nombrefiscal", getattr(datos, "representado_nombre", ""))
    payload.setdefault("nifempresa", getattr(datos, "representado_nif", ""))
    payload.setdefault("expediente", getattr(datos, "expediente", ""))

    # Alias robustos para resolver identidad de cliente (persona física/jurídica).
    if not payload.get("cliente_nombre"):
        payload["cliente_nombre"] = str(payload.get("Nombre") or "").strip()
    if not payload.get("cliente_apellido1"):
        payload["cliente_apellido1"] = str(payload.get("Apellido1") or "").strip()
    if not payload.get("cliente_apellido2"):
        payload["cliente_apellido2"] = str(payload.get("Apellido2") or "").strip()
    if not payload.get("empresa"):
        payload["empresa"] = str(payload.get("Nombrefiscal") or payload.get("representado_nombre") or "").strip()
    if not payload.get("cliente_razon_social"):
        payload["cliente_razon_social"] = str(payload.get("empresa") or "").strip()
    if not payload.get("sujeto_recurso"):
        payload["sujeto_recurso"] = str(payload.get("representado_nombre") or payload.get("nombre_interesado") or "").strip()

    return payload


async def _fill_confirmation_email_and_send(page: "Page", email: str) -> None:
    input_locator = page.locator("#confirmationEmailInput").first
    await input_locator.wait_for(state="visible", timeout=ATC_CONFIRM_MEDIUM_TIMEOUT_MS)
    await set_bound_value(page, "#confirmationEmailInput", email)

    sent = False
    for selector in [
        "button.se-button--primary:has-text('Enviar')",
        "button:has-text('Enviar')",
        "[role='button']:has-text('Enviar')",
    ]:
        try:
            await robust_click(page, selector, timeout=ATC_CONFIRM_SHORT_TIMEOUT_MS)
            sent = True
            break
        except Exception:
            continue
    if not sent:
        enviar = page.get_by_role("button", name=re.compile(r"Enviar|Send", re.IGNORECASE)).first
        await enviar.click(timeout=ATC_CONFIRM_SHORT_TIMEOUT_MS)
        await wait_after_action(page)


async def _download_and_store_receipt(page: "Page", datos: "AtcTarget") -> Path:
    justificante_link = page.locator("a[aria-label*='Justificant'], a:has-text('Justificant')").first
    await justificante_link.wait_for(state="visible", timeout=ATC_CONFIRM_LONG_TIMEOUT_MS)

    async with page.expect_download(timeout=ATC_CONFIRM_DOWNLOAD_TIMEOUT_MS) as dl_info:
        await justificante_link.click(timeout=ATC_CONFIRM_SHORT_TIMEOUT_MS)
        await wait_after_action(page)
    download = await dl_info.value

    tmp_dir = Path("tmp") / "atc_receipts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suggested = (download.suggested_filename or "Justificant_ATC.pdf").strip() or "Justificant_ATC.pdf"
    tmp_path = tmp_dir / suggested
    await download.save_as(str(tmp_path))
    if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
        raise RuntimeError("atc.confirmacion: justificante descargado vacio o inexistente.")

    payload = _prepare_payload_for_client_folder(datos)

    destino = resolve_receipt_dir_from_payload(
        payload=payload,
        fase_procedimiento=_resolve_atc_phase_folder(datos),
    )
    expediente_name = str(getattr(datos, "expediente", "") or "UNKNOWN")
    final_filename = build_receipt_filename(expediente=expediente_name, template="JUSTIFICANTE- {expediente}.pdf")
    final_path = save_receipt_from_tmp(
        tmp_path=tmp_path,
        destino_dir=destino,
        filename=final_filename,
    )
    return final_path


async def _download_and_store_receipt_registro(page: "Page", datos: "AtcTarget") -> Path:
    btn = page.locator("#MainContent_TramitsGenericsControl_ctlSignature_btnPresentacioJustificant").first
    await btn.wait_for(state="visible", timeout=180000)
    await page.wait_for_timeout(2000)

    async with page.expect_download(timeout=180000) as dl_info:
        await btn.click(timeout=ATC_CONFIRM_SHORT_TIMEOUT_MS)
        await wait_after_action(page)
    download = await dl_info.value

    tmp_dir = Path("tmp") / "atc_receipts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suggested = (download.suggested_filename or "Justificante_ATC.pdf").strip() or "Justificante_ATC.pdf"
    tmp_path = tmp_dir / suggested
    await download.save_as(str(tmp_path))
    if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
        raise RuntimeError("atc.confirmacion: justificante (registro) descargado vacio o inexistente.")

    payload = _prepare_payload_for_client_folder(datos)

    destino = resolve_receipt_dir_from_payload(
        payload=payload,
        fase_procedimiento=_resolve_atc_phase_folder(datos),
    )
    expediente_name = str(getattr(datos, "expediente", "") or "UNKNOWN")
    final_filename = build_receipt_filename(expediente=expediente_name, template="JUSTIFICANTE- {expediente}.pdf")
    return save_receipt_from_tmp(tmp_path=tmp_path, destino_dir=destino, filename=final_filename)


def _registro_expected_descs(datos: "AtcTarget") -> dict[int, str]:
    payload = dict(getattr(datos, "payload", {}) or {})
    raw = payload.get("atc_expected_registro_descs") or {}
    out: dict[int, str] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        try:
            idx = int(key)
        except Exception:
            continue
        text = str(value or "").strip()
        if text:
            out[idx] = text[:REGISTRO_DESC_MAX_LEN]
    return out


def _assert_registro_payload_preconditions(datos: "AtcTarget") -> int:
    payload = dict(getattr(datos, "payload", {}) or {})
    expected_count = int(payload.get("atc_expected_registro_attachment_count") or 0)
    source_docs_count = int(payload.get("atc_source_docs_count") or 0)
    bundled_upload = bool(payload.get("atc_bundled_upload"))
    has_resource = bool(payload.get("atc_has_recurso_doc"))
    has_authorization = bool(payload.get("atc_has_authorization_doc"))
    has_minimum_uploaded_units = expected_count >= 1 if bundled_upload else expected_count >= 2
    has_minimum_source_docs = source_docs_count >= 2 if source_docs_count else has_minimum_uploaded_units
    if not has_minimum_uploaded_units or not has_minimum_source_docs or not has_resource or not has_authorization:
        missing_parts: list[str] = []
        if not has_resource:
            missing_parts.append("RECURSO")
        if not has_authorization:
            missing_parts.append("AUTORIZACION")
        if not has_minimum_uploaded_units or not has_minimum_source_docs:
            missing_parts.append("MINIMO_2_ADJUNTOS")
        raise RuntimeError(
            "atc.confirmacion: no se valida ni firma un registro ATC sin adjuntos minimos completos. "
            f"faltan: {', '.join(missing_parts)}"
        )
    return expected_count


async def _collect_registro_slot_issues(page: "Page", *, expected_count: int) -> list[str]:
    issues: list[str] = []
    for idx in range(1, expected_count + 1):
        desc = page.locator(f"#inputAttach{idx}").first
        if await desc.count() <= 0:
            issues.append(f"inputAttach{idx}")
        tipo = page.locator(f"#selectAttach-{idx}").first
        if await tipo.count() <= 0:
            issues.append(f"selectAttach-{idx}")
    return issues


async def _repair_registro_fields_before_validate(
    page: "Page",
    *,
    expected_descs: dict[int, str] | None = None,
) -> list[str]:
    desc_map = {str(k): str(v)[:REGISTRO_DESC_MAX_LEN] for k, v in (expected_descs or {}).items()}
    try:
        return await page.evaluate(
            """({ expectedDescs, maxLen }) => {
                const invalid = [];
                const norm = (v) => String(v || "").trim().replace(/\\s+/g, " ");

                const inputs = Array.from(document.querySelectorAll("input[id^='inputAttach']"));
                inputs.forEach((el, i) => {
                    const idx = i + 1;
                    const wanted = norm((expectedDescs && expectedDescs[String(idx)]) || `Documento ${idx}`).slice(0, maxLen);
                    if (!norm(el.value)) {
                        el.value = wanted;
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                        if (typeof el.blur === "function") el.blur();
                        el.dispatchEvent(new Event("blur", { bubbles: true }));
                    }
                    if (!norm(el.value)) invalid.push(el.id || `inputAttach${i + 1}`);
                });

                const selects = Array.from(document.querySelectorAll("select[id^='selectAttach-']"));
                selects.forEach((el, i) => {
                    if (!norm(el.value)) {
                        const options = Array.from(el.options || []);
                        const byValue = options.find((o) => String(o.value) === "17");
                        const byText = options.find((o) => /otros/i.test(String(o.textContent || o.label || "")));
                        const picked = byValue || byText;
                        if (picked) {
                            el.value = String(picked.value);
                            el.dispatchEvent(new Event("input", { bubbles: true }));
                            el.dispatchEvent(new Event("change", { bubbles: true }));
                            if (typeof el.blur === "function") el.blur();
                            el.dispatchEvent(new Event("blur", { bubbles: true }));
                        }
                    }
                    if (!norm(el.value)) invalid.push(el.id || `selectAttach-${i + 1}`);
                });
                return invalid;
            }""",
            {"expectedDescs": desc_map, "maxLen": REGISTRO_DESC_MAX_LEN},
        )
    except Exception:
        return []


async def _validate_registro_until_signature(page: "Page", datos: "AtcTarget") -> None:
    expected_count = _assert_registro_payload_preconditions(datos)
    expected_descs = _registro_expected_descs(datos)
    signature_btn = page.locator("#MainContent_TramitsGenericsControl_ctlSignature_btnFirmaBroker").first
    for attempt in range(1, 4):
        slot_issues = await _collect_registro_slot_issues(page, expected_count=expected_count)
        if slot_issues:
            raise RuntimeError(
                "atc.confirmacion: ATC no ha registrado todos los slots de adjuntos antes de validar. "
                f"campos detectados: {', '.join(slot_issues)}"
            )
        await _repair_registro_fields_before_validate(page, expected_descs=expected_descs)
        await robust_click(page, "#MainContent_TramitsGenericsControl_btnValidar")
        try:
            await signature_btn.wait_for(state="visible", timeout=ATC_CONFIRM_MEDIUM_TIMEOUT_MS)
            remaining_issues = await _collect_registro_slot_issues(page, expected_count=expected_count)
            if remaining_issues:
                raise RuntimeError(
                    "atc.confirmacion: desaparecieron slots de adjuntos tras validar. "
                    f"campos detectados: {', '.join(remaining_issues)}"
                )
            return
        except Exception as exc:
            invalid_fields = await get_invalid_required_fields(page)
            if invalid_fields:
                if attempt >= 3:
                    raise RuntimeError(
                        "atc.confirmacion: el formulario ATC sigue invalido tras pulsar Validar. "
                        f"campos detectados: {', '.join(invalid_fields)}"
                    ) from exc
                await page.wait_for_timeout(800)
                continue
            if attempt >= 3:
                raise
            await page.wait_for_timeout(1200)


async def run_confirmacion(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    _ = config
    if datos.protocol == "registro_sin_csv":
        await _validate_registro_until_signature(page, datos)
        await page.wait_for_url("**/TramitsGenerics.aspx**", timeout=ATC_CONFIRM_LONG_TIMEOUT_MS)
        await page.wait_for_timeout(3000)
        await robust_click(page, "#MainContent_TramitsGenericsControl_ctlSignature_btnFirmaBroker")
        final_receipt = await _download_and_store_receipt_registro(page, datos)
        try:
            datos.payload["atc_justificante_descargado"] = True
            datos.payload["atc_justificante_path"] = str(final_receipt)
        except Exception:
            logger.warning("atc.confirmacion: no se pudo persistir metadata de justificante registro en payload.")
        return page

    # CA/ES: "Continuar" / EN: "Continue"
    btn = page.get_by_role("button", name=re.compile(r"Continuar|Continue", re.IGNORECASE))
    await btn.first.click()
    await wait_after_action(page)
    await page.wait_for_url("**/resum**", timeout=ATC_CONFIRM_LONG_TIMEOUT_MS)

    # Presentar -> email confirmacion -> enviar -> descargar justificante.
    await _click_presentar(page)
    await _fill_confirmation_email_and_send(page, "info@xvia-serviciosjuridicos.com")
    final_receipt = await _download_and_store_receipt(page, datos)
    try:
        datos.payload["atc_justificante_descargado"] = True
        datos.payload["atc_justificante_path"] = str(final_receipt)
    except Exception:
        logger.warning("atc.confirmacion: no se pudo persistir metadata de justificante en payload.")
    return page
