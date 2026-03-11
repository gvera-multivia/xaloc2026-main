import re
import pandas as pd
from scrapping_valencia import normalizar_documento, tipo_identificacion, get_matricula


def open_browser(playwright):
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    return browser, context, page


def fill_client_identification(page, fila) -> None:
    if pd.isna(fila["tipodecliente"]):
        raise ValueError(
            "tipodecliente no encontrado (cliente no vinculado al recurso)"
        )

    tipo_id_select = page.locator(
        '[id="o0solicitud_gral_din-section≡xf-581≡grid-5-grid≡din_tipo_identificacion-control≡select1≡≡c"]'
    )
    tipo_id_select.wait_for(state="visible")

    if fila["tipodecliente"] == "2":
        if pd.isna(fila["nifempresa"]):
            raise ValueError("nifempresa no encontrado para cliente de tipo empresa")
        if pd.isna(fila["Nombrefiscal"]):
            raise ValueError("Nombrefiscal no encontrado para cliente de tipo empresa")

        tipo_id_select.select_option("2")  # CIF de empresa

        nif_input = page.locator(
            '[id="o0solicitud_gral_din-section≡xf-581≡grid-5-grid≡din_numero_identificacion-control≡xforms-input-1"]'
        )
        nif_input.wait_for(state="visible")
        nif_input.fill(fila["nifempresa"])

        entidad_input = page.locator(
            '[id="o0solicitud_gral_din-section≡xf-581≡grid-5-grid≡din_entidad-control≡xforms-input-1"]'
        )
        entidad_input.wait_for(state="visible")
        entidad_input.fill(str(fila["Nombrefiscal"]))
    else:
        if pd.isna(fila["nif"]):
            raise ValueError("nif no encontrado para cliente persona física")
        if pd.isna(fila["Nombre"]):
            raise ValueError("Nombre no encontrado para cliente persona física")
        if pd.isna(fila["Apellido1"]):
            raise ValueError("Apellido1 no encontrado para cliente persona física")

        documento = normalizar_documento(fila["nif"])
        tipo_doc = tipo_identificacion(documento)
        if tipo_doc == "NIF":
            tipo_id_select.select_option("1")
        elif tipo_doc == "NIE":
            tipo_id_select.select_option("3")
        elif tipo_doc == "PASAPORTE":
            tipo_id_select.select_option("4")
        else:
            raise ValueError(f"Tipo de documento no reconocido: {tipo_doc}")

        nif_input = page.locator(
            '[id="o0solicitud_gral_din-section≡xf-581≡grid-5-grid≡din_numero_identificacion-control≡xforms-input-1"]'
        )
        nif_input.wait_for(state="visible")
        nif_input.fill(documento)

        nombre_input = page.locator(
            '[id="o0solicitud_gral_din-section≡xf-581≡grid-5-grid≡din_nombre-control≡xforms-input-1"]'
        )
        nombre_input.wait_for(state="visible")
        nombre_input.fill(str(fila["Nombre"]))

        page.locator(
            '[id="o0solicitud_gral_din-section≡xf-581≡grid-5-grid≡din_apellido1-control≡xforms-input-1"]'
        ).fill(str(fila["Apellido1"]))

        if pd.notna(fila["Apellido2"]):
            page.locator(
                '[id="o0solicitud_gral_din-section≡xf-581≡grid-5-grid≡din_apellido2-control≡xforms-input-1"]'
            ).fill(str(fila["Apellido2"]))


def fill_default_address(page) -> None:
    lengua_select = page.locator(
        '[id="o0solicitud_gral_dco-section≡xf-819≡grid-14-grid≡dco_lengua-control≡select1≡≡c"]'
    )
    lengua_select.wait_for(state="visible")
    lengua_select.select_option("1")  # Castellano

    provincia_select = page.locator(
        '[id="o0solicitud_gral_direccion-section≡xf-936≡grid-22_2-grid≡din_dir_provincia-control≡select1≡≡c"]'
    )
    provincia_select.wait_for(state="visible")
    provincia_select.select_option("9")  # Barcelona

    municipio_select = page.locator(
        '[id="o0solicitud_gral_direccion-section≡xf-936≡grid-22_2-grid≡din_dir_municipio-control≡select1≡≡c"]'
    )
    municipio_select.wait_for(state="visible")
    municipio_select.select_option("21")  # Barcelona

    page.locator(
        '[id="o0solicitud_gral_direccion-section≡xf-936≡grid-22_2-grid≡din_dir_direccion-control≡xforms-input-1"]'
    ).fill("Carrer General Mitre")

    page.locator(
        '[id="o0solicitud_gral_direccion-section≡xf-936≡grid-25_2-grid≡din_dir_num-control≡xforms-input-1"]'
    ).fill("169")

    page.locator(
        '[id="o0solicitud_gral_direccion-section≡xf-936≡grid-25_2-grid≡din_dir_cp-control≡xforms-input-1"]'
    ).fill("08022")


def fill_mu_numbers(page, fila, ref_prefix: str, meta_prefix: str) -> None:
    numeros_mu = fila["Expedient"].split()
    numero1 = numeros_mu[1]
    numero2 = numeros_mu[2]
    numero3 = numeros_mu[3]
    numero4 = numeros_mu[4]

    ref_mu1 = page.locator(f'[id="{ref_prefix}≡ref_mu1-control≡xforms-input-1"]')
    ref_mu1.wait_for(state="visible")
    ref_mu1.fill(numero1)

    page.locator(f'[id="{ref_prefix}≡ref_mu2-control≡xforms-input-1"]').fill(numero2)
    page.locator(f'[id="{ref_prefix}≡ref_mu3-control≡xforms-input-1"]').fill(numero3)
    page.locator(f'[id="{ref_prefix}≡ref_mu4-control≡xforms-input-1"]').fill(numero4)

    page.locator(f'[id="{meta_prefix}≡numero_boletin-control≡xforms-input-1"]').fill(
        fila["Expedient"]
    )

    page.locator(
        f'[id="{meta_prefix}≡matricula_vehiculo-control≡xforms-input-1"]'
    ).fill(get_matricula(fila["Matricula"], fila["Matricula2"], fila["Matricula3"]))


def upload_document(page, archivo_path: str, num_ciclos: int = 2) -> None:
    for _ in range(num_ciclos):
        page.get_by_role("link", name="Seleccionar").nth(0).click()
        page.wait_for_load_state("networkidle")
        page.locator('[id="uploadForm:upload"]').set_input_files(archivo_path)
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name=re.compile(r"Acceptar|Aceptar")).click()
        page.wait_for_load_state("networkidle")
