from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class ValenciaConfig(BaseConfig):
    site_id: str = "valencia"
    url_base: str = "https://sede.valencia.es"
    url_mu_de_30: str = "https://sede.valencia.es/sede/registro/procedimiento/MU.DE.30"
    url_mu_de_50: str = "https://sede.valencia.es/sede/registro/procedimiento/MU.DE.50"
    url_mu_sa_40: str = "https://sede.valencia.es/sede/registro/procedimiento/MU.SA.40"
    iniciar_tramite_selector: str = '[id="formIniciarTramite:iniciarTramite"]'
    save_form_selector: str = '[id="formularioInstancia:saveForm"]'
