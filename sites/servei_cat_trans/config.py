from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class ServeiCatTransConfig(BaseConfig):
    site_id: str = "servei_cat_trans"
    url_base: str = "https://transit.gencat.cat/es/gestions/multes-i-sancions/presentacio-escrits/"
    url_service_entry: str = (
        "https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzar.do"
        "?reqCode=inicial&set-locale=es_ES&idServei=TRN001SIGN"
        "&urlRetorn=http://transit.gencat.cat/es/gestions/expedients_sancionadors/presentacio_d_escrits"
    )
    url_service_entry_identificacion: str = (
        "https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzar.do"
        "?reqCode=inicial&set-locale=es_ES&idServei=TRN002SIGN"
    )
    url_form_presentador: str = (
        "https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzaruploadSecure.do"
        "?reqCode=autenticarFormulariHtml&presentador=P"
    )
    navigation_timeout: int = 120000
    auth_timeout_ms: int = 180000
    form_ready_timeout_ms: int = 60000
    upload_inputs_timeout_ms: int = 60000
    service_link_selector: str = "a[href*='idServei=TRN001SIGN']"
    service_link_selector_identificacion: str = "a[href*='idServei=TRN002SIGN']"
    access_button_selector: str = "input[value='Acceder']"
    cert_button_selector: str = "#btnContinuaCert"
    presentador_link_selector: str = "a.link_tramit[href*='renderitzaruploadSecure.do'][href*='presentador=P']"
    expediente_ok_pattern: str = "Los datos del expediente son correctos"
    default_tipo_via: str = "Ronda"
    default_nombre_via: str = "DEL GENERAL MITRE"
    default_numero_via: str = "169"
    default_cp: str = "08022"
    default_provincia: str = "Barcelona"
    default_comarca: str = "Barcelonès"
    default_municipio: str = "BARCELONA"
