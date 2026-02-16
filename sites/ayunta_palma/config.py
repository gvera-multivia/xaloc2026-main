"""
Configuración del sitio Ayunta Palma.
"""

from __future__ import annotations

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
    persona_nombre: str = "#ctl00_ctl00_cphM_cph_txtPersonaNombre"
    persona_apellido1: str = "#ctl00_ctl00_cphM_cph_txtPersonaApellido1"
    persona_apellido2: str = "#ctl00_ctl00_cphM_cph_txtPersonaApellido2"
    persona_pais: str = "#ctl00_ctl00_cphM_cph_ddlPersonaPais"
    email_selector: str = "#ctl00_ctl00_cphM_cph_ddlPersonaEmailNotificacionSelector"
    email_input: str = "#ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion"
    email_confirm_input: str = "#ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion2"
    telefono_selector: str = "#ctl00_ctl00_cphM_cph_ddlPersonaTelefonoMovilSelector"
    telefono_input: str = "#ctl00_ctl00_cphM_cph_txtPersonaTelefonoMovil"
    btn_aceptar_modal: str = ".ui-dialog:visible .btn-bar-horizontal-centrada-inner button:has-text(\"Aceptar\")"
    btn_indicar_representante: str = "button:has-text(\"Indicar representante\")"
    btn_siguiente: str = ".btn-bar-horizontal-centrada-inner button:has-text(\"Siguiente\")"
    input_siguiente: str = "#ctl00_ctl00_cphM_cph_btnSiguiente"
    btn_anadir_documento: str = ".btn-bar-horizontal-centrada-inner button:has-text(\"Añadir\")"
    btn_confirmar_archivo: str = ".panel-dialog button:has-text(\"Aceptar\")"
    velo: str = "#velo"
    alegaciones_frame: str = "#ventanaModal"
    alegaciones_input: str = "input[type='text'].form-control"
    alegaciones_textarea: str = "textarea.form-control"
    alegaciones_confirm: str = "button:has-text(\"Confirmar\")"
    archivo_input: str = "#ctl00_ctl00_cphM_cph_pnlNuevoFichero input[type='file']"


@dataclass
class AyuntaPalmaConfig(BaseConfig):
    site_id: str = "ayunta_palma"
    url_base: str = (
        "https://palma.sedipualba.es/carpetaciudadana/login.aspx?"
        "returnUrl=https%3a%2f%2fpalma.sedipualba.es%2fcarpetaciudadana%2fnueva_entrada.aspx%3fidtramite%3d13809"
    )
    selectors: AyuntaPalmaSelectors = field(default_factory=AyuntaPalmaSelectors)
