"""
Configuración del sitio BASE On-line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.base_config import BaseConfig


@dataclass
class BaseOnlineFlowTimeouts:
    selector_default: int = 5000
    popup_load: int = 10000
    ajax_idle: int = 12000
    dom_stable: int = 2000
    dom_content_loaded: int = 6000
    page_load: int = 10000
    click_popup: int = 3000
    cert_button_visible: int = 20000


@dataclass
class BaseOnlineSelectors:
    landing_link_href: str = "a[href*='/sav/valid']"
    landing_link_logo: str = "a.logo_text:has-text('Base On-line')"
    popup_step1_ready: str = "#form_0\\:llistaMunicipis, #form_0\\:llistaPais, #form_0\\:llistaProvincia"
    popup_continue: str = "input[type='submit'][value*='Continuar' i]"
    p1_expedient_id_ens: str = "#form\\:clau_expedient_id_ens"
    p1_expedient_any: str = "#form\\:clau_expedient_any_exp"
    p1_expedient_num: str = "#form\\:clau_expedient_num_exp"
    p1_num_butlleti: str = "#form\\:num_butlleti"
    p1_data_denuncia: str = "#form\\:data_denuncia"
    p1_matricula: str = "#form\\:matricula"
    p1_identificacio: str = "#form\\:identificacio"
    p1_llicencia_conduccio: str = "#form\\:llicencia_conduccio"
    p1_nom_complet: str = "#form\\:nom_complet"
    p1_btn_contacte_continuar: str = "input[type='submit'][name='form:j_id20'][value='Continuar']"
    p1_btn_step2_continuar: str = "input[type='submit'][name='form:j_id24'][value='Continuar']"
    p1_btn_step3_continuar: str = "input[type='submit'][name='form:j_id29'][value='Continuar']"
    p1_btn_signar_presentar: str = "input[type='button'][value='Signar i Presentar']"
    p1_popup_pais: str = "#form_0\\:llistaPais"
    p1_popup_provincia: str = "#form_0\\:llistaProvincia"
    p1_popup_municipi: str = "#form_0\\:llistaMunicipis"
    p1_popup_cp: str = "#form_0\\:llistaCP"
    p1_popup_vies: str = "#form_0\\:llistaVies"
    p1_popup_nom: str = "#form_0\\:nom"
    p1_popup_numero: str = "#form_0\\:numero"
    p1_popup_pis: str = "#form_0\\:pis"
    p1_popup_porta: str = "#form_0\\:porta"


@dataclass
class BaseOnlineScripts:
    click_link_js: str = """
        () => {
          const enlace = document.querySelector("a.logo_text[href*='/sav/valid']")
                      || document.querySelector("a[href*='/sav/valid']");
          if (enlace) enlace.click();
        }
    """
    check_cp_loaded: str = """
        () => {
          const cpSel = document.querySelector('#form_0\\:llistaCP');
          return !!cpSel && cpSel.options && cpSel.options.length > 1;
        }
    """
    post_login_ready: str = """
        () => {
          const u = (location && location.href) ? location.href : '';
          return u.includes('/commons-desktop/index')
            || u.includes('baseonline.cat/pst/flow/')
            || (!u.includes('valid.aoc.cat') && !u.includes('cert.valid.aoc.cat'));
        }
    """


@dataclass
class BaseOnlineDefaults:
    country: str = "ESP"
    street_type: str = "CL"
    street_number: str = "S/N"


@dataclass
class BaseOnlineConfig(BaseConfig):
    site_id: str = "base_online"
    url_base: str = "https://www.base.cat/ciutada/ca/tramits/multes-i-sancions/multes-i-sancions.html"
    flow_timeouts: BaseOnlineFlowTimeouts = field(default_factory=BaseOnlineFlowTimeouts)
    selectors: BaseOnlineSelectors = field(default_factory=BaseOnlineSelectors)
    scripts: BaseOnlineScripts = field(default_factory=BaseOnlineScripts)
    defaults: BaseOnlineDefaults = field(default_factory=BaseOnlineDefaults)

    # Landing
    base_online_link_selector: str = "a.logo_text[href*='/sav/valid'], a.logo_text[href*='base.cat/sav/valid']"

    # Login / VÀLid
    cert_button_selector: str = "#btnContinuaCert, [data-testid='certificate-btn']"
    url_post_login: str = "**/commons-desktop/index.*"
    stealth_disable_webdriver: bool = True

    # Formulario P3 (Recurs de reposició)
    p3_radio_ibi: str = "#radio1"
    p3_radio_ivtm: str = "#radio2"
    p3_radio_executiu: str = "#radio3"
    p3_radio_altres: str = "#radio4"
    p3_textarea_dades: str = "#form0\\:dades"
    p3_select_tipus: str = "select[name='form0:j_id124']"
    p3_textarea_exposo: str = "#form0\\:exposo"
    p3_textarea_solicito: str = "#form0\\:solicito"
    p3_button_continuar: str = "input[type='submit'][value='Continuar']"
