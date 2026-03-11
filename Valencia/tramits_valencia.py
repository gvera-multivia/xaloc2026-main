import re
from playwright.sync_api import Playwright
import pandas as pd
from Naming import split_full_name
from scrapping_valencia import (
    normalizar_documento,
    tipo_identificacion,
    provincia_por_cp,
    extraer_numero_direccion,
)
from page_helpers import (
    open_browser,
    fill_client_identification,
    fill_default_address,
    fill_mu_numbers,
    upload_document,
)


def _clean_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _pick_row_text(fila, *keys: str) -> str:
    for key in keys:
        if key in fila.index:
            text = _clean_text(fila.get(key))
            if text:
                return text
    return ""


def _fill_text_if_present(page, selectors: list[str], text: str) -> None:
    if not text:
        return
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=2000)
            locator.fill(text)
            return
        except Exception:
            continue


def recurso_reposicion(playwright: Playwright, df) -> None:
    if df.empty:
        print("No se encontraron datos para el idRecurso proporcionado.")
        return
    fila = df.iloc[0]
    browser, context, page = open_browser(playwright)

    page.goto("https://sede.valencia.es/sede/registro/procedimiento/MU.SA.40")
    page.wait_for_load_state("networkidle")

    page.locator('[id="formIniciarTramite:iniciarTramite"]').click()
    page.wait_for_load_state("networkidle")

    page.get_by_role(
        "button", name=re.compile(r"Accedir amb certificat|Acceder con certificado")
    ).click()

    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Entitat|Entidad")).click()

    page.wait_for_load_state("networkidle")

    try:
        page.get_by_role("link", name=re.compile(r"Nou tràmit|Nuevo trámite")).click(
            timeout=5000
        )
    except:
        pass

    page.locator('[id="formRepresentacion:radioButtonRepresentacionEntidad:1"]').check()
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Següent|Siguiente")).click()
    page.wait_for_load_state("networkidle")

    iniciar = page.get_by_role("button", name="Iniciar")
    iniciar.wait_for(state="visible")
    iniciar.click()
    page.wait_for_load_state("networkidle")

    fill_client_identification(page, fila)
    fill_default_address(page)

    expone_text = _pick_row_text(fila, "expone", "alegaciones", "motivos")
    _fill_text_if_present(
        page,
        selectors=[
            '[id="o0seccion_hechos-section\\u2261grid-1-grid\\u2261expone-control\\u2261xforms-textarea-1"]',
            '[id="o0seccion_expone-section\\u2261grid-8-grid\\u2261expone-control\\u2261xforms-textarea-1"]',
            '[id="o0seccion_hechos-section\\u2261grid-1-grid\\u2261hechos-control\\u2261xforms-input-1"]',
        ],
        text=expone_text,
    )

    fill_mu_numbers(
        page,
        fila,
        ref_prefix="o0seccion_hechos-section≡grid-2-grid",
        meta_prefix="o0seccion_hechos-section≡grid-3-grid",
    )

    solicita_text = _pick_row_text(fila, "solicita", "observaciones")
    _fill_text_if_present(
        page,
        selectors=[
            '[id="o0seccion_hechos-section\\u2261grid-4-grid\\u2261solicita-control\\u2261xforms-textarea-1"]',
            '[id="o0seccion_expone-section\\u2261grid-9-grid\\u2261solicita-control\\u2261xforms-textarea-1"]',
            '[id="o0solicitud_gral_solicita-section\\u2261xf-1513\\u2261grid-41-grid\\u2261solicita-control\\u2261\\u2261c"]',
        ],
        text=solicita_text,
    )

    page.locator('[id="formularioInstancia:saveForm"]').click()
    page.wait_for_load_state("networkidle")

    archivo_path = "C:\\Users\\Hector Manarguez\\Downloads\\42847-MU 2024 81 60012087 0-EMBARGO-90508.pdf"
    upload_document(page, archivo_path, num_ciclos=2)

    page.pause()

    context.close()
    browser.close()


def identificacion_conductor(playwright: Playwright, df) -> None:
    if df.empty:
        print("No se encontraron datos para el idRecurso proporcionado.")
        return
    fila = df.iloc[0]
    browser, context, page = open_browser(playwright)

    page.goto("https://sede.valencia.es/sede/registro/procedimiento/MU.DE.50")
    page.wait_for_load_state("networkidle")

    page.locator('[id="formIniciarTramite:iniciarTramite"]').click()
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Següent|Siguiente")).click()
    page.wait_for_load_state("networkidle")

    page.get_by_role(
        "button", name=re.compile(r"Accedir amb certificat|Acceder con certificado")
    ).click()

    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Entitat|Entidad")).click()

    page.wait_for_load_state("networkidle")

    try:
        page.get_by_role("link", name=re.compile(r"Nou tràmit|Nuevo trámite")).click(
            timeout=5000
        )
    except:
        pass

    page.locator('input[type="radio"][value="MU.DE.50_002"]').check()
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Següent|Siguiente")).click()
    page.wait_for_load_state("networkidle")

    page.locator('[id="formRepresentacion:radioButtonRepresentacionEntidad:1"]').check()
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Següent|Siguiente")).click()
    page.wait_for_load_state("networkidle")

    iniciar = page.get_by_role("button", name="Iniciar")
    iniciar.wait_for(state="visible")
    iniciar.click()
    page.wait_for_load_state("networkidle")

    fill_client_identification(page, fila)
    fill_default_address(page)

    if fila["TExp"] in (1, 2):
        DNI_Conductor = documento_identificado = fila["Conducdni"]
        Nombre_Conductor = Nombre_Completo = fila["ConducNom"]
        codigo_postal_conductor = fila["ConducCodpost"]
        direccion_conductor = fila["ConducAdr"]
    elif fila["TExp"] in (3, 4):
        DNI_Conductor = documento_identificado = fila["Conducdni2"]
        Nombre_Conductor = Nombre_Completo = fila["ConducNom2"]
        codigo_postal_conductor = fila["ConducCodpost2"]
        direccion_conductor = fila["ConducAdr2"]
    else:
        raise ValueError(f"Tipo de expediente no reconocido: {fila['TExp']}")

    if pd.isna(DNI_Conductor) or pd.isna(Nombre_Conductor):
        raise ValueError("DNI o nombre del conductor no encontrado en la BD")

    page.locator(
        '[id="o0seccion_datos_adicionales-section≡grid-1-grid≡cif_licencia-control≡xforms-input-1"]'
    ).fill(DNI_Conductor)
    page.wait_for_load_state("networkidle")

    tipo_documento_identificado = tipo_identificacion(documento_identificado)
    if tipo_documento_identificado in ["NIF", "NIE", "PASAPORTE"]:
        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-2-grid≡id_tipo_persona-control≡≡e0"]'
        ).check()

        Nombre_Completo = split_full_name(Nombre_Completo)
        Nombre_Conductor = Nombre_Completo[0]
        Apellido1_Conductor = Nombre_Completo[1]
        Apellido2_Conductor = Nombre_Completo[2]

        if not Nombre_Conductor or not Apellido1_Conductor:
            raise ValueError("Nombre o apellido del conductor no válido")

        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-3-grid≡id_nombre-control≡xforms-input-1"]'
        ).fill(Nombre_Conductor)

        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-3-grid≡id_apellido1-control≡xforms-input-1"]'
        ).fill(Apellido1_Conductor)

        if Apellido2_Conductor:
            page.locator(
                '[id="o0seccion_identificacion_conductor-section≡grid-3-grid≡id_apellido2-control≡xforms-input-1"]'
            ).fill(Apellido2_Conductor)

        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-4-grid≡id_permiso-control≡xforms-input-1"]'
        ).fill(DNI_Conductor)

    elif tipo_documento_identificado == "CIF":
        if pd.notna(fila["nifempresa"]) and normalizar_documento(
            str(documento_identificado)
        ) == normalizar_documento(str(fila["nifempresa"])):
            raise ValueError("El conductor no puede ser la empresa misma")

        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-2-grid≡id_tipo_persona-control≡≡e1"]'
        ).check()

        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-4-grid≡id_permiso-control≡xforms-input-1"]'
        ).fill(DNI_Conductor)

        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-4-grid≡id_razon_social-control≡xforms-input-1"]'
        ).fill(str(Nombre_Completo))

        page.locator(
            '[id="o0seccion_identificacion_conductor-section≡grid-5-grid≡id_cif-control≡xforms-input-1"]'
        ).fill(str(documento_identificado))

        provincia = provincia_por_cp(codigo_postal_conductor)
        page.locator(
            '[id="o0section-2-section≡xf-1550≡grid-22_2_2-grid≡din_dir_provincia_2-control≡select1≡≡c"]'
        ).select_option(label=provincia)
        page.wait_for_load_state("networkidle")

        page.locator(
            '[id="o0section-2-section≡xf-1550≡grid-22_2_2-grid≡din_dir_direccion_2-control≡xforms-input-1"]'
        ).fill(direccion_conductor)

        numero = extraer_numero_direccion(direccion_conductor)
        page.locator(
            '[id="o0section-2-section≡xf-1550≡grid-25_2_2-grid≡din_dir_num_2-control≡xforms-input-1"]'
        ).fill(str(numero))

    fill_mu_numbers(
        page,
        fila,
        ref_prefix="o0seccion_expone-section≡grid-6-grid",
        meta_prefix="o0seccion_expone-section≡grid-7-grid",
    )

    page.locator('[id="formularioInstancia:saveForm"]').click()
    page.wait_for_load_state("networkidle")

    archivo_path = "C:\\Users\\Hector Manarguez\\Downloads\\42847-MU 2024 81 60012087 0-EMBARGO-90508.pdf"
    upload_document(page, archivo_path, num_ciclos=2)

    page.pause()

    context.close()
    browser.close()


def alegaciones_denuncia_transito(playwright: Playwright, df) -> None:
    if df.empty:
        print("No se encontraron datos para el idRecurso proporcionado.")
        return
    fila = df.iloc[0]
    browser, context, page = open_browser(playwright)

    page.goto("https://sede.valencia.es/sede/registro/procedimiento/MU.DE.30")
    page.wait_for_load_state("networkidle")

    page.locator('[id="formIniciarTramite:iniciarTramite"]').click()
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Següent|Siguiente")).click()
    page.wait_for_load_state("networkidle")

    page.get_by_role(
        "button", name=re.compile(r"Accedir amb certificat|Acceder con certificado")
    ).click()
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile(r"Entitat|Entidad")).click()
    page.wait_for_load_state("networkidle")

    try:
        page.get_by_role("link", name=re.compile(r"Nou tràmit|Nuevo trámite")).click(
            timeout=5000
        )
    except:
        pass

    page.locator('[id="formRepresentacion:radioButtonRepresentacionEntidad:1"]').check()

    seguent = page.get_by_role("button", name=re.compile(r"Següent|Siguiente"))
    seguent.wait_for(state="visible")
    seguent.click()
    page.wait_for_load_state("networkidle")

    iniciar = page.get_by_role("button", name="Iniciar")
    iniciar.wait_for(state="visible")
    iniciar.click()
    page.wait_for_load_state("networkidle")

    fill_client_identification(page, fila)
    fill_default_address(page)

    expone_text = _pick_row_text(fila, "expone", "alegaciones", "motivos")
    _fill_text_if_present(
        page,
        selectors=[
            '[id="o0seccion_hechos-section\\u2261grid-1-grid\\u2261expone-control\\u2261xforms-textarea-1"]',
            '[id="o0seccion_expone-section\\u2261grid-8-grid\\u2261expone-control\\u2261xforms-textarea-1"]',
            '[id="o0seccion_hechos-section\\u2261grid-1-grid\\u2261hechos-control\\u2261xforms-input-1"]',
        ],
        text=expone_text,
    )

    fill_mu_numbers(
        page,
        fila,
        ref_prefix="o0seccion_hechos-section≡grid-2-grid",
        meta_prefix="o0seccion_hechos-section≡grid-3-grid",
    )

    solicita_text = _pick_row_text(fila, "solicita", "observaciones")
    _fill_text_if_present(
        page,
        selectors=[
            '[id="o0seccion_hechos-section\\u2261grid-4-grid\\u2261solicita-control\\u2261xforms-textarea-1"]',
            '[id="o0seccion_expone-section\\u2261grid-9-grid\\u2261solicita-control\\u2261xforms-textarea-1"]',
            '[id="o0solicitud_gral_solicita-section\\u2261xf-1513\\u2261grid-41-grid\\u2261solicita-control\\u2261\\u2261c"]',
        ],
        text=solicita_text,
    )

    page.locator('[id="formularioInstancia:saveForm"]').click()
    page.wait_for_load_state("networkidle")

    archivo_path = "C:\\Users\\Hector Manarguez\\Downloads\\42847-MU 2024 81 60012087 0-EMBARGO-90508.pdf"
    upload_document(page, archivo_path, num_ciclos=3)

    page.pause()

    context.close()
    browser.close()
