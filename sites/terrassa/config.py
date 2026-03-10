from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class TerrassaConfig(BaseConfig):
    site_id: str = "terrassa"
    url_base: str = "https://aoberta.terrassa.cat"
    url_tramit: str = "https://aoberta.terrassa.cat/tramits/fitxa.jsp?id=3822"
    href_omplir_form: str = "/tramits/ferTramit.jsp?id=3822"
    href_identificar: str = "/demanaIdentitat"
    href_actuar_representant: str = "/accions/identificaRepIntercanvi"
    cert_button_selector: str = (
        "button#btnContinuaCert,"
        "button[data-testid='certificate-btn'],"
        "button#btnContinuaCertCaptcha,"
        "button.btn-certificatDigital"
    )
    continuar_selector: str = "a[onclick*='comprovaFormulari']"
    signar_selector: str = (
        "a[onclick*='enviarDades'][onclick*='accionsFinals.submit'],"
        "a[title*='Signar'],"
        "a img[title*='Signar'],"
        "a[onclick*='procesoFirma'],"
        "button[onclick*='procesoFirma']"
    )
    # Step 2: "Signar" button on the signing overlay
    signar_ordinari_selector: str = "a#boto_signa_ordinari"
    # Success message after signing
    success_selector: str = "p[style*='background-color: green']"
    # Receipt download link
    receipt_link_selector: str = "a[href*='tramit.pdf']"
    auth_timeout_ms: int = 120000
    # Generous timeout for signing (documents take time to process)
    firma_timeout_ms: int = 180000
