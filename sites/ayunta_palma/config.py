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
    login_option_cert_titulo: str = "#optSsl tr:first-child .titulo-opcion"
    btn_nueva_instancia: str = "button.redirect-url.stop-click-propagation.btn-icono"
    btn_nueva_instancia_visible: str = (
        "div.btn-bar-horizontal-centrada-inner:has(input#ctl00_ctl00_cphM_cph_btnUltimoBorradorCancelar) "
        "button.btn-icono"
    )
    input_nueva_instancia: str = "#ctl00_ctl00_cphM_cph_btnUltimoBorradorCancelar"
    btn_nuevo_interesado: str = ".btn-bar-horizontal-centrada-inner button:has-text(\"Nuevo/a interesado/a\")"
    btn_nuevo_interesado_visible: str = (
        "div.btn-bar-horizontal-centrada-inner:has(input#ctl00_ctl00_cphM_cph_btnListaInteresadosOpcionesNuevo) "
        "button:has-text(\"Nuevo/a interesado/a\")"
    )
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
    btn_aceptar_modal: str = ".ui-dialog:visible .btn-bar-horizontal-centrada-inner button:has-text(\"Aceptar\")"
    input_aceptar_modal_persona: str = "#ctl00_ctl00_cphM_cph_btnAceptarPersona"
    btn_aceptar_modal_visible: str = (
        ".ui-dialog:visible .btn-bar-horizontal-centrada-inner:has(input#ctl00_ctl00_cphM_cph_btnAceptarPersona) "
        "button.btn-bl1, .ui-dialog:visible .btn-bar-horizontal-centrada-inner:has(input#ctl00_ctl00_cphM_cph_btnAceptarPersona) button.btn-icono"
    )
    btn_indicar_representante: str = "button:has-text(\"Indicar representante\")"
    input_indicar_representante: str = "#ctl00_ctl00_cphM_cph_repListaInteresados_ctl00_btnListaInteresadosItemNuevoRepresentante"
    btn_indicar_representante_visible: str = (
        "div.btn-bar-horizontal-centrada-inner:has(input#ctl00_ctl00_cphM_cph_repListaInteresados_ctl00_btnListaInteresadosItemNuevoRepresentante) "
        "button.btn-icono"
    )
    btn_siguiente: str = ".btn-bar-horizontal-centrada-inner button:has-text(\"Siguiente\")"
    btn_siguiente_visible: str = (
        "div.btn-bar-horizontal-centrada-inner:has(input#ctl00_ctl00_cphM_cph_btnSiguiente) "
        "button.btn-icono"
    )
    input_siguiente: str = "#ctl00_ctl00_cphM_cph_btnSiguiente"
    chk_proteccion_datos: str = "#ctl00_ctl00_cphM_cph_chkProteccionDatos"
    btn_modal_aceptar: str = ".ui-dialog:visible button:has-text(\"Aceptar\")"
    btn_modal_aceptar_visible: str = ".ui-dialog:visible .btn-bar-horizontal-centrada-inner button.btn-bl1"
    input_modal_aceptar: str = ".ui-dialog:visible input[id$='_btnAceptar']"
    btn_confirmar: str = "button:has-text(\"Confirmar\")"
    btn_confirmar_visible: str = "div.btn-bar-horizontal-centrada-inner:has(input[id$='_btnConfirmar']) button.btn-icono"
    input_confirmar: str = "input[id$='_btnConfirmar']"
    btn_firmar: str = "button:has-text(\"Firmar\")"
    input_firmar: str = "#ctl00_ctl00_cphM_cph_btnFirmar"
    btn_signar_tots_documents: str = "button:has-text(\"Signar tots els documents\")"
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
    url_nueva_instancia_directa: str = (
        "https://palma.sedipualba.es/carpetaciudadana/nueva_entrada.aspx?idtramite=13809&recuperar=false"
    )
    selectors: AyuntaPalmaSelectors = field(default_factory=AyuntaPalmaSelectors)
