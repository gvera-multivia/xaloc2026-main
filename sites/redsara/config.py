from __future__ import annotations

from dataclasses import dataclass, field

from core.base_config import BaseConfig


@dataclass
class RedSaraSelectors:
    nuevo_registro_link: str = ".dnt-link.dnt-link--l"
    certificado_button: str = "button:has-text('Acceso DNIe / Certificado')"
    cert_clave_xpath: str = '//*[@id="ID_main"]/div[2]/div/div/div/article[2]/div[4]/button'
    destination_organism_input: str = '#destinationOrganism input[type="text"]'
    attachments_input: str = "#attachments"
    final_checkbox_terms: str = 'dnt-checkbox[formcontrolname="checkTerms"]'
    firmar_registrar_btn: str = 'dnt-button[title-text="Firmar y registrar (Cl@ve)"] > button'
    descargar_justificante_btn: str = "dnt-button:has-text('Descargar justificante')"


@dataclass
class RedSaraFlowTimeouts:
    cert_wait: int = 30000
    short_wait: int = 5000
    medium_wait: int = 15000
    long_wait: int = 60000
    save_wait: int = 120000


@dataclass
class RedSaraConfig(BaseConfig):
    site_id: str = "redsara"
    url_base: str = "https://reg.redsara.es/es/"
    lang: str = "es"
    selectors: RedSaraSelectors = field(default_factory=RedSaraSelectors)
    flow_timeouts: RedSaraFlowTimeouts = field(default_factory=RedSaraFlowTimeouts)
