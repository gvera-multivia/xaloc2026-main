"""
Configuración del sitio Madrid Ayuntamiento - Sede Electrónica.
Basado en explore-html/madrid-guide.md y explore-html/llenar formulario-madrid.md
"""

from __future__ import annotations
"""
Configuración del sitio Madrid Ayuntamiento - Sede Electrónica.
Basado en explore-html/madrid-guide.md y explore-html/llenar formulario-madrid.md
"""

from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class MadridConfig(BaseConfig):
    site_id: str = "madrid"
    
    # URL base del trámite (Multas de circulación)
    url_base: str = "https://sede.madrid.es/portal/site/tramites/menuitem.62876cb64654a55e2dbd7003a8a409a0/?vgnextoid=dd7f048aad32e210VgnVCM1000000b205a0aRCRD&vgnextchannel=3838a38813180210VgnVCM100000c90da8c0RCRD&vgnextfmt=default"

    # URLs clave del flujo (se usan como comprobaciones de seguridad)
    url_servcla_inicial_contains: str = "servcla.madrid.es/WFORS_WBWFORS/servlet?action=inicial"
    url_servcla_formulario_contains: str = "WFORS_WBWFORS/servlet?action=opcion"
    
    # =========================================================================
    # Selectores (Cargados desde JSON)
    # =========================================================================
    
    # Navegación
    boton_tramitar_selector: str = ""
    bloque_tramitar_selector: str = ""
    registro_electronico_selector: str = ""
    continuar_1_selector: str = ""
    iniciar_tramitacion_selector: str = ""
    certificado_login_selector: str = ""
    continuar_post_auth_selector: str = ""
    radio_nuevo_tramite_selector: str = ""
    radio_interesado_selector: str = ""
    continuar_interesado_selector: str = ""
    boton_nuevo_tramite_condicional: str = ""
    formulario_llegada_selector: str = ""

    # Formulario
    expediente_tipo_1_selector: str = ""
    expediente_tipo_2_selector: str = ""
    expediente_1_nnn_selector: str = ""
    expediente_1_exp_selector: str = ""
    expediente_1_d_selector: str = ""
    expediente_2_lll_selector: str = ""
    expediente_2_aaaa_selector: str = ""
    expediente_2_exp_selector: str = ""
    matricula_selector: str = ""
    
    # Interesado
    interesado_telefono_selector: str = ""
    interesado_check_email_selector: str = ""
    interesado_check_sms_selector: str = ""
    
    # Representante
    representante_pais_selector: str = ""
    representante_provincia_selector: str = ""
    representante_municipio_selector: str = ""
    representante_tipo_via_selector: str = ""
    representante_nombre_via_selector: str = ""
    representante_tipo_num_selector: str = ""
    representante_numero_selector: str = ""
    representante_portal_selector: str = ""
    representante_escalera_selector: str = ""
    representante_planta_selector: str = ""
    representante_puerta_selector: str = ""
    representante_codpostal_selector: str = ""
    representante_email_selector: str = ""
    representante_movil_selector: str = ""
    representante_telefono_selector: str = ""
    representante_check_email_selector: str = ""
    representante_check_sms_selector: str = ""
    
    # Notificación
    notificacion_copiar_interesado_selector: str = ""
    notificacion_copiar_representante_selector: str = ""
    notificacion_tipo_doc_selector: str = ""
    notificacion_num_doc_selector: str = ""
    notificacion_nombre_selector: str = ""
    notificacion_apellido1_selector: str = ""
    notificacion_apellido2_selector: str = ""
    notificacion_razon_social_selector: str = ""
    notificacion_pais_selector: str = ""
    notificacion_provincia_selector: str = ""
    notificacion_municipio_selector: str = ""
    notificacion_tipo_via_selector: str = ""
    notificacion_nombre_via_selector: str = ""
    notificacion_tipo_num_selector: str = ""
    notificacion_numero_selector: str = ""
    notificacion_portal_selector: str = ""
    notificacion_escalera_selector: str = ""
    notificacion_planta_selector: str = ""
    notificacion_puerta_selector: str = ""
    notificacion_codpostal_selector: str = ""
    notificacion_email_selector: str = ""
    notificacion_movil_selector: str = ""
    notificacion_telefono_selector: str = ""
    
    # Naturaleza / Expone / Solicita
    naturaleza_alegacion_selector: str = ""
    naturaleza_recurso_selector: str = ""
    naturaleza_identificacion_selector: str = ""
    expone_selector: str = ""
    solicita_selector: str = ""
    
    # Botones finales
    guardar_borrador_selector: str = ""
    continuar_formulario_selector: str = ""
    adjuntos_continuar_selector: str = ""
    firma_registrar_selector: str = ""

    # =========================================================================
    # Configuración de esperas y navegador
    # =========================================================================
    
    default_timeout: int = 30000
    navigation_timeout: int = 60000
    stealth_disable_webdriver: bool = True
    lang: str = "es"
    disable_translate_ui: bool = True

    def __post_init__(self):
        """Cargar selectores desde JSON."""
        import json
        from pathlib import Path
        
        # Ruta relativa al archivo config.py actual
        json_path = Path(__file__).parent / "selectors.json"
        
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    selectors = json.load(f)
                
                # Inyectar valores en la instancia
                for key, value in selectors.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
            except Exception as e:
                # Fallback: en un sistema real quizás querríamos fallar, 
                # pero aquí permitimos continuar si algo falla, logs lo avisarán.
                print(f"Error cargando selectors.json: {e}")
        else:
            print(f"Warning: {json_path} no encontrado.")
