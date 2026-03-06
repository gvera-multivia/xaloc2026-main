from __future__ import annotations

from dataclasses import dataclass, field

from core.base_config import BaseConfig


@dataclass
class RedsaraSelectors:
    nuevo_registro_link: str = "dnt-horizontal-menu-item[idoption='2']"
    # Cl@ve IdP gateway: robust AFIRMA match across onclick variants.
    afirma_login_button: str = (
        "button.idp-button[onclick*='selectedIdP'][onclick*='AFIRMA'], "
        "button.idp-button[data-idp='AFIRMA']"
    )
    # Backward compatibility for previous misspelled attribute name.
    afima_login_button: str = afirma_login_button
    step1_heading: str = "app-create-registry-step1"
    step1_next_button: str = "app-create-registry-step1 dnt-button:has-text('Siguiente')"
    step2_heading: str = "app-create-registry-step2"

    # Representative section
    represented_street_type_id: str = "represented.streetType"
    represented_address_input: str = "dnt-input[formcontrolname='streetName'] input[placeholder='Introduce dirección']:not([type='hidden'])"
    represented_province_id: str = "represented.province"
    represented_city_id: str = "represented.city"
    represented_country_id: str = "represented.country"
    represented_zip_input: str = "dnt-input[formcontrolname='zipCode'] input[placeholder='Código Postal']:not([type='hidden'])"

    # Interested section
    interested_doc_type_id: str = "tipoDoc"
    interested_doc_number_input: str = "dnt-input[formcontrolname='docNumber'] input:not([type='hidden'])"
    interested_name_input: str = "dnt-input[formcontrolname='name'] input[autocomplete='given-name']:not([type='hidden'])"
    interested_surname1_input: str = "dnt-input[formcontrolname='surname'] input[autocomplete='family-name']:not([type='hidden'])"
    interested_surname2_input: str = "dnt-input[formcontrolname='lastName'] input:not([type='hidden'])"
    interested_street_type_id: str = "streetType"
    interested_country_id: str = "country"
    interested_address_input: str = "dnt-input[formcontrolname='streetName'] input[placeholder='Introducir dirección']:not([type='hidden'])"
    interested_province_id: str = "interested.province"
    interested_city_id: str = "interested.city"
    interested_zip_input: str = "dnt-input[formcontrolname='zipCode'] input[placeholder='Introducir C.P.']:not([type='hidden'])"
    interested_phone_input: str = "dnt-input[formcontrolname='phone'] input[placeholder='Introducir teléfono']:not([type='hidden'])"
    interested_email_input: str = ":nth-match(dnt-input[formcontrolname='email'] input[placeholder='Introducir email']:not([type='hidden']), 2)"

    # Explicit final contact fields in Step 1
    final_phone_input: str = "dnt-input[formcontrolname='phone'] input:not([type='hidden'])"
    final_email_input: str = "dnt-input[formcontrolname='email'] input:not([type='hidden'])"

    # Checkboxes
    email_alert_checkbox_input: str = "dnt-checkbox[name='emailAlert']"

    # Step 2
    destination_organism_id: str = "destinationOrganism"
    subject_input: str = "dnt-input[formcontrolname='subject'] input:not([type='hidden'])"
    exposes_textarea: str = "dnt-input[formcontrolname='exposes'] textarea"
    solicit_textarea: str = "dnt-input[formcontrolname='solicit'] textarea"
    step2_next_button: str = "app-create-registry-step2 dnt-button:has-text('Siguiente')"

    # Step 3
    attachments_input: str = "input#attachments[type='file']"


@dataclass
class RedsaraFlowTimeouts:
    auth_wait_ms: int = 30000
    navigation_timeout_ms: int = 60000
    short_wait_ms: int = 400


@dataclass
class RedsaraConfig(BaseConfig):
    site_id: str = "redsara"
    url_base: str = "https://reg.redsara.es/es/"
    url_nuevo_registro: str = "https://reg.redsara.es/es/nuevo-registro"

    selectors: RedsaraSelectors = field(default_factory=RedsaraSelectors)
    flow_timeouts: RedsaraFlowTimeouts = field(default_factory=RedsaraFlowTimeouts)

    lang: str = "es"
    disable_translate_ui: bool = True
    stealth_disable_webdriver: bool = True
