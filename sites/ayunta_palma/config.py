"""
ConfiguraciÃ³n del sitio Ayunta Palma.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.base_config import BaseConfig


@dataclass
class AyuntaPalmaSelectors:
    login_frame: str = "#ventanaModal"
    login_option_rows: str = "#optSsl tr"
    btn_nueva_instancia: str = "button.redirect-url.stop-click-propagation:has-text(\"Nueva instancia en blanco\")"
    input_nueva_instancia: str = "#ctl00_ctl00_cphM_cph_btnUltimoBorradorCancelar"
    btn_nuevo_interesado: str = ".btn-bar-horizontal-centrada-inner button:has-text(\"Nuevo/a interesado/a\")"
    input_nuevo_interesado: str = "#ctl00_ctl00_cphM_cph_btnListaInteresadosOpcionesNuevo"
    persona_tipo_usuario: str = "#ctl00_ctl00_cphM_cph_ddlPersonaTipoUsuario"
    persona_tipo_personalidad: str = "#ctl00_ctl00_cphM_cph_ddlPersonaTipoPersonalidad"
    persona_tipo_documento: str = "#ctl00_ctl00_cphM_cph_ddlPersonaTipoDocumentoIdentidad"
    persona_documento: str = "#ctl00_ctl00_cphM_cph_txtPersonaCodigoDocumentoIdentidad"
    persona_razon_social: str = "#ctl00_ctl00_cphM_cph_txtPersonaRazonSocial"
    persona_nombre: str = "#ctl00_ctl00_cphM_cph_txtPersonaNombre"
    persona_apellido1: str = "#ctl00_ctl00_cphM_cph_txtPersonaApellido1"
    persona_apellido2: str = "#ctl00_ctl00_cphM_cph_txtPersonaApellido2"
    persona_pais: str = "#ctl00_ctl00_cphM_cph_ddlPersonaPais"
    email_selector: str = "#ctl00_ctl00_cphM_cph_ddlPersonaEmailNotificacionSelector"
    email_input: str = "#ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion"
    email_confirm_input: str = "#ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion2"
    telefono_selector: str = "#ctl00_ctl00_cphM_cph_ddlPersonaTelefonoMovilSelector"
    telefono_input: str = "#ctl00_ctl00_cphM_cph_txtPersonaTelefonoMovil"
    btn_aceptar_modal: str = ".ui-dialog:visible .btn-bar-horizontal-centrada-inner button:has-text(\"Aceptar\"), .ui-dialog:visible .btn-bar-horizontal-centrada-inner button:has-text(\"Acceptar\")"
    btn_indicar_representante: str = "button:has-text(\"Indicar representante\"), button:has-text(\"Indicar representant\")"
    btn_siguiente: str = ".btn-bar-horizontal-centrada-inner button:has-text(\"Siguiente\"), .btn-bar-horizontal-centrada-inner button:has-text(\"Següent\")"
    input_siguiente: str = "#ctl00_ctl00_cphM_cph_btnSiguiente"
    chk_proteccion_datos: str = "#ctl00_ctl00_cphM_cph_chkProteccionDatos"
    btn_modal_aceptar: str = ".ui-dialog:visible button:has-text(\"Aceptar\"), .ui-dialog:visible button:has-text(\"Acceptar\")"
    btn_confirmar: str = "button:has-text(\"Confirmar\")"
    btn_firmar: str = "button:has-text(\"Firmar\")"
    input_firmar: str = "#ctl00_ctl00_cphM_cph_btnFirmar"
    btn_signar_tots_documents: str = "button:has-text(\"Signar tots els documents\")"
    btn_anadir_documento: str = ".btn-bar-horizontal-centrada-inner button:has-text(\"Añadir\"), .btn-bar-horizontal-centrada-inner button:has-text(\"Afegir\")"
    btn_confirmar_archivo: str = ".panel-dialog button:has-text(\"Aceptar\"), .panel-dialog button:has-text(\"Acceptar\")"
    velo: str = "#velo"
    alegaciones_frame: str = "#ventanaModal"
    alegaciones_input: str = "input[type='text'].form-control"
    alegaciones_textarea: str = "textarea.form-control"
    alegaciones_confirm: str = "button:has-text(\"Confirmar\")"
    archivo_input: str = "#ctl00_ctl00_cphM_cph_pnlNuevoFichero input[type='file']"


@dataclass
class AyuntaPalmaConfig(BaseConfig):
    site_id: str = "ayunta_palma"
    lang: str = "es"
    url_base: str = (
        "https://palma.sedipualba.es/carpetaciudadana/login.aspx?"
        "returnUrl=https%3a%2f%2fpalma.sedipualba.es%2fcarpetaciudadana%2fnueva_entrada.aspx%3fidtramite%3d13809"
    )
    selectors: AyuntaPalmaSelectors = field(default_factory=AyuntaPalmaSelectors)
    autofirma_cli_path: str = field(
        default_factory=lambda: os.getenv(
            "XALOC_AUTOFIRMA_CLI_PATH",
            r"C:\Program Files\AutoFirma\AutoFirma\AutoFirmaCommandLine.exe",
        )
    )
    autofirma_cli_alias: str = field(
        default_factory=lambda: os.getenv("XALOC_AUTOFIRMA_CLI_ALIAS", os.getenv("certificado_cn", ""))
    )


