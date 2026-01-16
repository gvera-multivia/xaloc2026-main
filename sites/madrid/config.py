"""
Configuración del sitio Madrid Ayuntamiento - Sede Electrónica.
Basado en explore-html/madrid-guide.md
"""

from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class MadridConfig(BaseConfig):
    site_id: str = "madrid"
    
    # URL base del trámite (Multas de circulación)
    url_base: str = "https://sede.madrid.es/portal/site/tramites/menuitem.62876cb64654a55e2dbd7003a8a409a0/?vgnextoid=dd7f048aad32e210VgnVCM1000000b205a0aRCRD&vgnextchannel=3838a38813180210VgnVCM100000c90da8c0RCRD&vgnextfmt=default"
    
    # Paso 1: Botón "Tramitar en línea" (abre bloque #verTodas)
    boton_tramitar_selector: str = "#tramitarClick"
    bloque_tramitar_selector: str = "#verTodas"
    
    # Paso 2: Enlace "Registro Electrónico" (navega a servpub.madrid.es)
    registro_electronico_selector: str = "a[href^='https://servpub.madrid.es/WFORS_WBWFORS/servlet']"
    
    # Paso 3: Primer botón "Continuar" en servpub.madrid.es
    # Nota: btn1 se reutiliza más adelante con type='button', aquí es type='submit'
    continuar_1_selector: str = "input#btn1[type='submit'][value='Continuar']"
    
    # Paso 4: Botón "Iniciar tramitación"
    iniciar_tramitacion_selector: str = "#btnConAuth"
    
    # Paso 5: Método de acceso "DNIe / Certificado"
    certificado_login_selector: str = "a.login-sede-opt-link:has-text('DNIe / Certificado')"
    
    # Paso 6: Certificado (popup de Windows)
    # Reutiliza utils/windows_popup.py
    stealth_disable_webdriver: bool = True
    
    # Paso 7: Botón "Continuar" tras autenticación
    continuar_post_auth_selector: str = "#btnContinuar"
    
    # Paso 8: Radio "Tramitar nueva solicitud"
    radio_nuevo_tramite_selector: str = "#checkboxNuevoTramite"
    
    # Paso 9: Radio "Persona o Entidad interesada" + botón Continuar
    radio_interesado_selector: str = "#checkboxInteresado"
    # Aquí btn1 es type='button', no 'submit'
    continuar_interesado_selector: str = "input#btn1[type='button'][value='Continuar']"
    
    # Paso 10: Condicional - botón "Nuevo trámite" (si existe trámite a medias)
    boton_nuevo_tramite_condicional: str = "#btnNuevoTramite"
    
    # Paso 11: Criterio de llegada al formulario
    # (A definir tras captura real - por ahora usaremos espera genérica)
    formulario_llegada_selector: str = "form"  # Placeholder
    
    # Configuración de esperas
    # Evitar networkidle, usar domcontentloaded + esperas específicas
    default_timeout: int = 30000  # 30 segundos
    navigation_timeout: int = 60000  # 60 segundos para navegaciones con certificado
