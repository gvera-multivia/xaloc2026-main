from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

from playwright.async_api import Page

from sites.valencia.data_models import ValenciaTarget

logger = logging.getLogger("xaloc_automation.valencia")


def clean(value: object) -> str:
    return str(value or "").strip()


def normalize_document(doc: str) -> str:
    value = clean(doc).upper()
    return re.sub(r"[.\-\s]", "", value)


def tipo_identificacion(doc: str) -> str:
    value = normalize_document(doc)
    if re.fullmatch(r"\d{8}[A-Z]", value):
        return "NIF"
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", value):
        return "NIE"
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-Z]", value):
        return "CIF"
    if re.fullmatch(r"[A-Z0-9]{5,12}", value):
        return "PASAPORTE"
    raise ValueError(f"Documento no valido: {value}")


def split_full_name(full_name: str) -> tuple[str, str, str]:
    tokens = [t for t in clean(full_name).split() if t]
    if not tokens:
        return "", "", ""
    if len(tokens) == 1:
        return tokens[0], "", ""
    if len(tokens) == 2:
        return tokens[0], tokens[1], ""
    return tokens[0], tokens[1], " ".join(tokens[2:])


def get_matricula(*candidates: str) -> str:
    for raw in candidates:
        value = re.sub(r"\s+", "", clean(raw).upper())
        if value and re.fullmatch(r"[A-Z0-9]{1,15}", value):
            return value
    raise ValueError("No se pudo inferir matricula valida")


def extraer_numero_direccion(direccion: str) -> str:
    m = re.search(r"\d+", clean(direccion))
    return m.group(0) if m else "0"


def provincia_por_cp(cp: str) -> str:
    value = re.sub(r"\D+", "", clean(cp))[:5]
    if len(value) != 5:
        return "NO CONSTA"
    return {
        "46": "VALENCIA",
        "08": "BARCELONA",
        "28": "MADRID",
    }.get(value[:2], "NO CONSTA")


def _selector(prefix: str, suffix: str) -> str:
    return f'[id="{prefix}\u2261{suffix}"]'


async def click_and_wait(page: Page, locator: str) -> None:
    await page.locator(locator).click()
    await page.wait_for_load_state("networkidle")


RoleName = Literal["button", "link"]


async def click_role_and_wait(page: Page, *, role: RoleName, name_pattern: str) -> None:
    target = page.get_by_role(role, name=re.compile(name_pattern))
    await target.first.click()
    await page.wait_for_load_state("networkidle")


async def fill_client_identification(page: Page, datos: ValenciaTarget) -> None:
    tipo_id_selector = _selector(
        "o0solicitud_gral_din-section\u2261xf-581\u2261grid-5-grid",
        "din_tipo_identificacion-control\u2261select1\u2261\u2261c",
    )
    tipo_id = page.locator(tipo_id_selector)
    await tipo_id.wait_for(state="visible")

    tipodecliente = clean(datos.tipodecliente)
    nif_persona = normalize_document(clean(datos.nif) or clean(datos.conduc_dni))
    nif_empresa = normalize_document(clean(datos.nifempresa))
    is_company = tipodecliente == "2" or (not nif_persona and bool(nif_empresa))

    logger.info(
        "valencia.fill_client_identification idRecurso=%s expediente=%s tipodecliente=%s is_company=%s nif=%s conduc_dni=%s nifempresa=%s",
        clean(datos.idRecurso),
        clean(datos.expediente),
        tipodecliente,
        is_company,
        clean(datos.nif),
        clean(datos.conduc_dni),
        clean(datos.nifempresa),
    )

    if is_company:
        nombre_fiscal = clean(datos.nombrefiscal) or clean(datos.nombre)
        if not nif_empresa:
            raise ValueError("valencia: falta nifempresa para cliente empresa")
        if not nombre_fiscal:
            raise ValueError("valencia: falta nombrefiscal para cliente empresa")
        await tipo_id.select_option("2")
        await page.locator(
            _selector(
                "o0solicitud_gral_din-section\u2261xf-581\u2261grid-5-grid",
                "din_numero_identificacion-control\u2261xforms-input-1",
            )
        ).fill(nif_empresa)
        await page.locator(
            _selector(
                "o0solicitud_gral_din-section\u2261xf-581\u2261grid-5-grid",
                "din_entidad-control\u2261xforms-input-1",
            )
        ).fill(nombre_fiscal)
        return

    documento = nif_persona
    if not documento:
        logger.error(
            "valencia: documento vacio para persona fisica. nombre=%s ap1=%s ap2=%s payload_keys=%s",
            clean(datos.nombre),
            clean(datos.apellido1),
            clean(datos.apellido2),
            sorted(list((datos.payload or {}).keys())),
        )
        raise ValueError(
            "valencia: falta documento cliente (nif/conduc_dni) para persona fisica "
            f"[idRecurso={clean(datos.idRecurso)}, expediente={clean(datos.expediente)}]"
        )
    doc_type = tipo_identificacion(documento)
    if doc_type == "NIF":
        await tipo_id.select_option("1")
    elif doc_type == "NIE":
        await tipo_id.select_option("3")
    else:
        await tipo_id.select_option("4")

    await page.locator(
        _selector(
            "o0solicitud_gral_din-section\u2261xf-581\u2261grid-5-grid",
            "din_numero_identificacion-control\u2261xforms-input-1",
        )
    ).fill(documento)
    await page.locator(
        _selector(
            "o0solicitud_gral_din-section\u2261xf-581\u2261grid-5-grid",
            "din_nombre-control\u2261xforms-input-1",
        )
    ).fill(clean(datos.nombre))
    await page.locator(
        _selector(
            "o0solicitud_gral_din-section\u2261xf-581\u2261grid-5-grid",
            "din_apellido1-control\u2261xforms-input-1",
        )
    ).fill(clean(datos.apellido1))
    if clean(datos.apellido2):
        await page.locator(
            _selector(
                "o0solicitud_gral_din-section\u2261xf-581\u2261grid-5-grid",
                "din_apellido2-control\u2261xforms-input-1",
            )
        ).fill(clean(datos.apellido2))


async def fill_default_address(page: Page) -> None:
    await page.locator(
        _selector(
            "o0solicitud_gral_dco-section\u2261xf-819\u2261grid-14-grid",
            "dco_lengua-control\u2261select1\u2261\u2261c",
        )
    ).select_option("1")
    await page.locator(
        _selector(
            "o0solicitud_gral_dco-section\u2261xf-819\u2261grid-14-grid",
            "dco_movil-control\u2261xforms-input-1",
        )
    ).fill("722761154")
    await page.locator(
        _selector(
            "o0solicitud_gral_dco-section\u2261xf-819\u2261grid-15-grid",
            "dco_correoElectronico-control\u2261xforms-input-1",
        )
    ).fill("INFO@XVIA-SERVICIOSJURIDICOS.COM")
    await page.locator(
        _selector(
            "o0solicitud_gral_direccion-section\u2261xf-936\u2261grid-22_2-grid",
            "din_dir_provincia-control\u2261select1\u2261\u2261c",
        )
    ).select_option("9")
    await page.locator(
        _selector(
            "o0solicitud_gral_direccion-section\u2261xf-936\u2261grid-22_2-grid",
            "din_dir_municipio-control\u2261select1\u2261\u2261c",
        )
    ).select_option("21")
    await page.locator(
        _selector(
            "o0solicitud_gral_direccion-section\u2261xf-936\u2261grid-22_2-grid",
            "din_dir_direccion-control\u2261xforms-input-1",
        )
    ).fill("Carrer General Mitre")
    await page.locator(
        _selector(
            "o0solicitud_gral_direccion-section\u2261xf-936\u2261grid-25_2-grid",
            "din_dir_num-control\u2261xforms-input-1",
        )
    ).fill("169")
    await page.locator(
        _selector(
            "o0solicitud_gral_direccion-section\u2261xf-936\u2261grid-25_2-grid",
            "din_dir_cp-control\u2261xforms-input-1",
        )
    ).fill("08022")


def build_ref_prefix(datos: ValenciaTarget) -> str:
    if datos.tramite_tipo == "identificacion_conductor":
        return "o0seccion_expone-section\u2261grid-6-grid"
    return "o0seccion_hechos-section\u2261grid-2-grid"


def build_meta_prefix(datos: ValenciaTarget) -> str:
    if datos.tramite_tipo == "identificacion_conductor":
        return "o0seccion_expone-section\u2261grid-7-grid"
    return "o0seccion_hechos-section\u2261grid-3-grid"


async def fill_mu_numbers(page: Page, datos: ValenciaTarget) -> None:
    tokens = clean(datos.expediente).split()
    if len(tokens) < 5:
        raise ValueError(f"valencia: expediente invalido para MU: {datos.expediente}")

    ref_prefix = build_ref_prefix(datos)
    meta_prefix = build_meta_prefix(datos)
    await page.locator(
        _selector(ref_prefix, "ref_mu1-control\u2261xforms-input-1")
    ).fill(tokens[1])
    await page.locator(
        _selector(ref_prefix, "ref_mu2-control\u2261xforms-input-1")
    ).fill(tokens[2])
    await page.locator(
        _selector(ref_prefix, "ref_mu3-control\u2261xforms-input-1")
    ).fill(tokens[3])
    await page.locator(
        _selector(ref_prefix, "ref_mu4-control\u2261xforms-input-1")
    ).fill(tokens[4])
    await page.locator(
        _selector(meta_prefix, "numero_boletin-control\u2261xforms-input-1")
    ).fill(clean(datos.expediente))
    await page.locator(
        _selector(meta_prefix, "matricula_vehiculo-control\u2261xforms-input-1")
    ).fill(get_matricula(datos.matricula, datos.matricula2, datos.matricula3))


async def fill_identificacion_conductor(page: Page, datos: ValenciaTarget) -> None:
    payload = datos.payload or {}
    texp = int(datos.texp or 0)
    p = lambda *keys: next((clean(payload.get(k)) for k in keys if clean(payload.get(k))), "")
    d = lambda *vals: next((clean(v) for v in vals if clean(v)), "")

    # Misma logica del flujo anterior: para TExp 3/4 priorizar secundarios,
    # con fallback al otro bloque si faltan datos.
    if texp in (3, 4):
        documento_identificado = d(
            p("Conducdni2", "conduc_dni2"),
            datos.conduc_dni,
            p("Conducdni", "conduc_dni"),
        )
        nombre_completo = d(
            p("ConducNom2", "conduc_nom2"),
            datos.conduc_nom,
            p("ConducNom", "conduc_nom"),
        )
        cp = d(
            p("ConducCodpost2", "conduc_codpost2"),
            datos.conduc_codpost,
            p("ConducCodpost", "conduc_codpost"),
        )
        direccion = d(
            p("ConducAdr2", "conduc_adr2"),
            datos.conduc_adr,
            p("ConducAdr", "conduc_adr"),
        )
    else:
        documento_identificado = d(
            datos.conduc_dni,
            p("Conducdni", "conduc_dni"),
            p("Conducdni2", "conduc_dni2"),
        )
        nombre_completo = d(
            datos.conduc_nom,
            p("ConducNom", "conduc_nom"),
            p("ConducNom2", "conduc_nom2"),
        )
        cp = d(
            datos.conduc_codpost,
            p("ConducCodpost", "conduc_codpost"),
            p("ConducCodpost2", "conduc_codpost2"),
        )
        direccion = d(
            datos.conduc_adr,
            p("ConducAdr", "conduc_adr"),
            p("ConducAdr2", "conduc_adr2"),
        )

    if not documento_identificado:
        raise ValueError("valencia: falta documento del conductor (Conducdni/Conducdni2)")
    if not nombre_completo:
        raise ValueError("valencia: falta nombre del conductor (ConducNom/ConducNom2)")

    doc = normalize_document(documento_identificado)
    logger.info(
        "valencia.fill_identificacion_conductor texp=%s doc=%s nombre=%s cp=%s direccion=%s",
        texp,
        doc,
        nombre_completo,
        cp,
        direccion,
    )

    cif_licencia = page.locator(
        _selector(
            "o0seccion_datos_adicionales-section\u2261grid-1-grid",
            "cif_licencia-control\u2261xforms-input-1",
        )
    )
    await cif_licencia.wait_for(state="visible")
    await cif_licencia.fill(doc)
    await page.wait_for_load_state("networkidle")

    async def _try_fill_conductor_address() -> None:
        if not cp or not direccion:
            logger.warning(
                "valencia.fill_identificacion_conductor sin direccion completa de conductor (cp=%s direccion=%s)",
                cp,
                direccion,
            )
            return
        # En algunas variantes el bloque de direccion del conductor tambien aparece para persona fisica.
        provincia = provincia_por_cp(cp)
        provincia_selector = _selector(
            "o0section-2-section\u2261xf-1550\u2261grid-22_2_2-grid",
            "din_dir_provincia_2-control\u2261select1\u2261\u2261c",
        )
        direccion_selector = _selector(
            "o0section-2-section\u2261xf-1550\u2261grid-22_2_2-grid",
            "din_dir_direccion_2-control\u2261xforms-input-1",
        )
        numero_selector = _selector(
            "o0section-2-section\u2261xf-1550\u2261grid-25_2_2-grid",
            "din_dir_num_2-control\u2261xforms-input-1",
        )
        prov = page.locator(provincia_selector)
        direc = page.locator(direccion_selector)
        num = page.locator(numero_selector)
        if await prov.count():
            await prov.first.select_option(label=provincia)
        if await direc.count():
            await direc.first.fill(direccion)
        if await num.count():
            await num.first.fill(extraer_numero_direccion(direccion))
        if await prov.count() or await direc.count() or await num.count():
            logger.info(
                "valencia.fill_identificacion_conductor direccion completada provincia=%s direccion=%s",
                provincia,
                direccion,
            )

    doc_type = tipo_identificacion(doc)
    if doc_type in {"NIF", "NIE", "PASAPORTE"}:
        persona_radio = page.locator(
            _selector("o0seccion_identificacion_conductor-section\u2261grid-2-grid", "id_tipo_persona-control\u2261\u2261e0")
        )
        await persona_radio.wait_for(state="visible")
        await persona_radio.check()

        nombre, ap1, ap2 = split_full_name(nombre_completo)
        if not nombre:
            raise ValueError("valencia: nombre del conductor no valido")
        if not ap1:
            raise ValueError("valencia: apellido1 del conductor no valido")
        if not ap2:
            ap2 = d(
                clean(payload.get("Apellido2")),
                clean(datos.apellido2),
                "",
            )
        logger.info(
            "valencia.fill_identificacion_conductor persona nombre=%s ap1=%s ap2=%s",
            nombre,
            ap1,
            ap2,
        )

        await page.locator(
            _selector("o0seccion_identificacion_conductor-section\u2261grid-3-grid", "id_nombre-control\u2261xforms-input-1")
        ).fill(nombre)
        await page.locator(
            _selector("o0seccion_identificacion_conductor-section\u2261grid-3-grid", "id_apellido1-control\u2261xforms-input-1")
        ).fill(ap1)
        if ap2:
            await page.locator(
                _selector("o0seccion_identificacion_conductor-section\u2261grid-3-grid", "id_apellido2-control\u2261xforms-input-1")
            ).fill(ap2)
        await page.locator(
            _selector("o0seccion_identificacion_conductor-section\u2261grid-4-grid", "id_permiso-control\u2261xforms-input-1")
        ).fill(doc)
        await _try_fill_conductor_address()
        return

    if clean(datos.nifempresa) and normalize_document(doc) == normalize_document(clean(datos.nifempresa)):
        raise ValueError("valencia: el conductor no puede ser la empresa misma")

    await page.locator(
        _selector("o0seccion_identificacion_conductor-section\u2261grid-2-grid", "id_tipo_persona-control\u2261\u2261e1")
    ).check()
    await page.locator(
        _selector("o0seccion_identificacion_conductor-section\u2261grid-4-grid", "id_permiso-control\u2261xforms-input-1")
    ).fill(doc)
    await page.locator(
        _selector("o0seccion_identificacion_conductor-section\u2261grid-4-grid", "id_razon_social-control\u2261xforms-input-1")
    ).fill(nombre_completo)
    await page.locator(
        _selector("o0seccion_identificacion_conductor-section\u2261grid-5-grid", "id_cif-control\u2261xforms-input-1")
    ).fill(doc)

    await _try_fill_conductor_address()


async def fill_text_if_present(page: Page, selectors: list[str], text: str) -> bool:
    value = clean(text)
    if not value:
        return False
    for selector in selectors:
        field = page.locator(selector)
        if await field.count():
            await field.first.fill(value)
            return True
    return False


async def upload_documents(page: Page, files: list[Path]) -> None:
    existing_files = [
        Path(file_path) for file_path in files if Path(file_path).exists()
    ]
    if not existing_files:
        return

    async def _click_select_tipo1(batch_number: int) -> None:
        # Camino principal (el que funcionaba en el flujo standalone):
        # page.get_by_role("link", name="Seleccionar").nth(0).click()
        try:
            primary = page.get_by_role("link", name="Seleccionar").nth(0)
            await primary.click(timeout=5000)
            await page.wait_for_load_state("networkidle")
            logger.info(
                "valencia.upload_documents click seleccionar tipo1 ok batch=%s via=primary_nth0",
                batch_number,
            )
            return
        except Exception:
            pass

        # Tipo1 suele ser <a ...><div>Seleccionar</div></a>, pero varia segun pantalla.
        role_link = page.get_by_role("link", name=re.compile(r"Seleccionar", re.IGNORECASE))
        role_count = await role_link.count()
        for idx in range(role_count):
            candidate = role_link.nth(idx)
            try:
                if not await candidate.is_visible():
                    continue
                await candidate.scroll_into_view_if_needed()
                await candidate.click(timeout=3000)
                await page.wait_for_load_state("networkidle")
                logger.info(
                    "valencia.upload_documents click seleccionar tipo1 ok batch=%s via=role_link index=%s",
                    batch_number,
                    idx,
                )
                return
            except Exception:
                try:
                    await candidate.click(timeout=3000, force=True)
                    await page.wait_for_load_state("networkidle")
                    logger.info(
                        "valencia.upload_documents click seleccionar tipo1 ok batch=%s via=role_link_force index=%s",
                        batch_number,
                        idx,
                    )
                    return
                except Exception:
                    continue

        selectors = [
            'a[href*="/documentos/"]:has-text("Seleccionar")',
            'a[href*="documentos"]:has-text("Seleccionar")',
            'a:has-text("Seleccionar")',
            'a:has(div:has-text("Seleccionar"))',
        ]
        for selector in selectors:
            locator = page.locator(selector)
            count = await locator.count()
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if not await candidate.is_visible():
                        continue
                    await candidate.scroll_into_view_if_needed()
                    await candidate.click(timeout=3000)
                    await page.wait_for_load_state("networkidle")
                    logger.info(
                        "valencia.upload_documents click seleccionar tipo1 ok batch=%s selector=%s index=%s",
                        batch_number,
                        selector,
                        idx,
                    )
                    return
                except Exception:
                    try:
                        await candidate.click(timeout=3000, force=True)
                        await page.wait_for_load_state("networkidle")
                        logger.info(
                            "valencia.upload_documents click seleccionar tipo1 ok batch=%s selector=%s index=%s forced=1",
                            batch_number,
                            selector,
                            idx,
                        )
                        return
                    except Exception:
                        continue
        raise RuntimeError("No se encontro el control 'Seleccionar' tipo1 para subir documentos.")

    async def _click_select_tipo2(batch_number: int) -> None:
        selectors = [
            'input[type="submit"][value="Seleccionar"]',
            'input[type="submit"][value*="Seleccionar"]',
        ]
        for selector in selectors:
            locator = page.locator(selector)
            count = await locator.count()
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if not await candidate.is_visible():
                        continue
                    if await candidate.is_disabled():
                        continue
                    await candidate.click()
                    await page.wait_for_load_state("networkidle")
                    logger.info(
                        "valencia.upload_documents click seleccionar tipo2 ok batch=%s selector=%s index=%s",
                        batch_number,
                        selector,
                        idx,
                    )
                    return
                except Exception:
                    continue
        raise RuntimeError("No se encontro el control 'Seleccionar' tipo2 para subir documentos.")

    async def _upload_batch(batch: list[Path], *, batch_number: int) -> None:
        if not batch:
            return
        is_tipo2 = batch_number not in (1, 2)
        if not is_tipo2:
            await _click_select_tipo1(batch_number)
        else:
            await _click_select_tipo2(batch_number)

        # En Tipo2 el formulario solicita descripcion del archivo.
        if is_tipo2 and len(batch) == 1:
            descripcion = batch[0].stem[:200]
            comentarios = page.locator('[id="uploadForm:comentarios"]')
            if await comentarios.count():
                try:
                    await comentarios.first.fill(descripcion)
                except Exception:
                    pass
        if len(batch) == 1:
            await page.locator('[id="uploadForm:upload"]').set_input_files(
                str(batch[0])
            )
        else:
            await page.locator('[id="uploadForm:upload"]').set_input_files(
                [str(p) for p in batch]
            )
        await page.wait_for_load_state("networkidle")
        await page.get_by_role(
            "button", name=re.compile(r"Acceptar|Aceptar", re.IGNORECASE)
        ).first.click()
        await page.wait_for_load_state("networkidle")

    # Flujo comun:
    # 1) Tipo1 + primer archivo
    # 2) Tipo1 + segundo archivo
    # 3) Mientras queden archivos: Tipo2 + un archivo + aceptar
    await _upload_batch(existing_files[:1], batch_number=1)
    await _upload_batch(existing_files[1:2], batch_number=2)
    for file_path in existing_files[2:]:
        await _upload_batch([file_path], batch_number=3)
