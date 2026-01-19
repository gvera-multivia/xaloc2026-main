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
    
    # =========================================================================
    # NAVEGACIÓN (pasos 1-11 del madrid-guide.md)
    # =========================================================================
    
    # Paso 1: Botón "Tramitar en línea" (abre bloque #verTodas)
    boton_tramitar_selector: str = "#tramitarClick"
    bloque_tramitar_selector: str = "#verTodas"
    
    # Paso 2: Enlace "Registro Electrónico" (navega a servpub.madrid.es)
    registro_electronico_selector: str = "a[href^='https://servpub.madrid.es/WFORS_WBWFORS/servlet']"
    
    # Paso 3: Primer botón "Continuar" en servpub.madrid.es
    continuar_1_selector: str = "input#btn1[type='submit'][value='Continuar']"
    
    # Paso 4: Botón "Iniciar tramitación"
    iniciar_tramitacion_selector: str = "#btnConAuth"
    
    # Paso 5: Método de acceso "DNIe / Certificado"
    certificado_login_selector: str = "a.login-sede-opt-link:has-text('DNIe / Certificado')"
    
    # Paso 6: Certificado (popup de Windows)
    stealth_disable_webdriver: bool = True
    
    # Paso 7: Botón "Continuar" tras autenticación
    continuar_post_auth_selector: str = "#btnContinuar"
    
    # Paso 8: Radio "Tramitar nueva solicitud"
    radio_nuevo_tramite_selector: str = "#checkboxNuevoTramite"
    
    # Paso 9: Radio "Persona o Entidad interesada" + botón Continuar
    radio_interesado_selector: str = "#checkboxInteresado"
    continuar_interesado_selector: str = "input#btn1[type='button'][value='Continuar']"
    
    # Paso 10: Condicional - botón "Nuevo trámite"
    boton_nuevo_tramite_condicional: str = "#btnNuevoTramite"
    
    # Paso 11: Criterio de llegada al formulario
    formulario_llegada_selector: str = "form"
    
    # =========================================================================
    # FORMULARIO - Sección 1: Datos del expediente
    # =========================================================================
    
    # Radios para tipo de expediente
    expediente_tipo_1_selector: str = "#TIPO_EXPEDIENTE_1"  # NNN/EEEEEEEEE.D
    expediente_tipo_2_selector: str = "#TIPO_EXPEDIENTE_2"  # LLL/AAAA/EEEEEEEEE
    
    # Campos opción 1 (NNN/EEEEEEEEE.D) - escapar el punto en CSS
    expediente_1_nnn_selector: str = ".formula2_EXP1\\.1"
    expediente_1_exp_selector: str = ".formula2_EXP1\\.2"
    expediente_1_d_selector: str = ".formula2_EXP1\\.3"
    
    # Campos opción 2 (LLL/AAAA/EEEEEEEEE)
    expediente_2_lll_selector: str = ".formula2_EXP2\\.1"
    expediente_2_aaaa_selector: str = ".formula2_EXP2\\.2"
    expediente_2_exp_selector: str = ".formula2_EXP2\\.3"
    
    # =========================================================================
    # FORMULARIO - Sección 2: Matrícula
    # =========================================================================
    
    matricula_selector: str = ".formula2_GESTION_MULTAS_MATRICULA"
    # =========================================================================
    # FORMULARIO - Sección 3: Datos del interesado (SOLO TELÉFONO)
    # =========================================================================
    
    # Solo tocamos el teléfono del interesado, el resto se queda como está
    interesado_telefono_selector: str = "input[name*='_id21:2'][name*='TELEFONO']"
    interesado_check_email_selector: str = "input[name*='_id21:2'][name*='CHECKEMAIL']"
    interesado_check_sms_selector: str = "input[name*='_id21:2'][name*='CHECKSMS']"
    
    # =========================================================================
    # FORMULARIO - Sección 4: Datos del representante (CAMPOS ACTIVOS)
    # =========================================================================
    
    # Forzamos el selector a buscar dentro de '_id21:3' (Sección del Representante)
    
    # País y Provincia
    representante_pais_selector: str = "select[name*='_id21:3'][name*='PAIS']"
    representante_provincia_selector: str = "select[name*='_id21:3'][name*='PROVINCIA']"

    # Dirección (Municipio, Tipo Vía, Nombre)
    representante_municipio_selector: str = "input[name*='_id21:3'][name*='_id28:4:_id31:0']"
    representante_tipo_via_selector: str = "select[name*='_id21:3'][name*='_id28:4:_id31:1']"
    representante_nombre_via_selector: str = "input[name*='_id21:3'][name*='_id28:4:_id31:2']"
    
    # Numeración (Tipo, Número, Portal)
    representante_tipo_num_selector: str = "select[name*='_id21:3'][name*='_id28:5:_id31:0']"
    representante_numero_selector: str = "input[name*='_id21:3'][name*='_id28:5:_id31:1']"
    representante_portal_selector: str = "input[name*='_id21:3'][name*='_id28:5:_id31:2']"
    
    # Detalles (Escalera, Planta, Puerta, CP)
    representante_escalera_selector: str = "input[name*='_id21:3'][name*='_id28:6:_id31:0']"
    representante_planta_selector: str = "input[name*='_id21:3'][name*='_id28:6:_id31:1']"
    representante_puerta_selector: str = "input[name*='_id21:3'][name*='_id28:6:_id31:2']"
    representante_codpostal_selector: str = "input[name*='_id21:3'][name*='_id28:6:_id31:3']"
    
    # Contacto (Email, Móvil, Teléfono)
    representante_email_selector: str = "input[name*='_id21:3'][name*='_id28:7:_id31:0']"
    representante_movil_selector: str = "input[name*='_id21:3'][name*='_id28:7:_id31:1']"
    representante_telefono_selector: str = "input[name*='_id21:3'][name*='_id28:7:_id31:2']"
    
    # Checkboxes de confirmación (Representante)
    representante_check_email_selector: str = "input[name*='_id21:3'][name*='CHECKEMAIL']"
    representante_check_sms_selector: str = "input[name*='_id21:3'][name*='CHECKSMS']"
    
    # =========================================================================
    # FORMULARIO - Sección 5: Datos de notificación
    # =========================================================================
    
    # Botones de copia
    notificacion_copiar_interesado_selector: str = "input[type='submit'][value='Copiar datos del interesado']"
    notificacion_copiar_representante_selector: str = "input[type='submit'][value='Copiar datos del representante']"
    
    # Identificación
    # Tipo documento - select
    notificacion_tipo_doc_selector: str = "select[name*='_id28:2:_id31:0:_id35:0:_id574']"
    
    # Número de documento
    notificacion_num_doc_selector: str = "input[name*='_id28:2:_id31:1:_id35:0:_id64']"
    
    # Nombre
    notificacion_nombre_selector: str = "input[name*='_id28:2:_id31:2:_id35:0:_id64']"
    
    # Primer apellido
    notificacion_apellido1_selector: str = "input[name*='_id28:3:_id31:0:_id35:0:_id64']"
    
    # Segundo apellido
    notificacion_apellido2_selector: str = "input[name*='_id28:3:_id31:1:_id35:0:_id64']"
    
    # Razón social
    notificacion_razon_social_selector: str = "input[name*='_id28:4:_id31:0:_id35:0:_id64']"
    
    # Dirección
    # País - select
    notificacion_pais_selector: str = "select[name*='_id28:5:_id31:0:_id35:0:_id574']"
    
    # Provincia - select
    notificacion_provincia_selector: str = "select[name*='_id28:5:_id31:1:_id35:0:_id574']"
    
    # Municipio
    notificacion_municipio_selector: str = "input[name*='_id28:6:_id31:0:_id35:0:_id64']"
    
    # Tipo vía - select
    notificacion_tipo_via_selector: str = "select[name*='_id28:6:_id31:1:_id35:0:_id574']"
    
    # Nombre vía (Domicilio)
    notificacion_nombre_via_selector: str = "input[name*='_id28:6:_id31:2:_id35:0:_id64']"
    
    # Tipo de numeración - select
    notificacion_tipo_num_selector: str = "select[name*='_id28:7:_id31:0:_id35:0:_id574']"
    
    # Número
    notificacion_numero_selector: str = "input[name*='_id28:7:_id31:1:_id35:0:_id435']"
    
    # Portal
    notificacion_portal_selector: str = "input[name*='_id28:7:_id31:2:_id35:0:_id64']"
    
    # Escalera
    notificacion_escalera_selector: str = "input[name*='_id28:8:_id31:0:_id35:0:_id64']"
    
    # Planta
    notificacion_planta_selector: str = "input[name*='_id28:8:_id31:1:_id35:0:_id64']"
    
    # Puerta
    notificacion_puerta_selector: str = "input[name*='_id28:8:_id31:2:_id35:0:_id64']"
    
    # C.P. (Código Postal)
    notificacion_codpostal_selector: str = "input[name*='_id28:8:_id31:3:_id35:0:_id276']"
    
    # Contacto
    # Email
    notificacion_email_selector: str = "input[name*='_id28:9:_id31:0:_id35:0:_id170']"
    
    # Móvil
    notificacion_movil_selector: str = "input[name*='_id28:9:_id31:1:_id35:0:_id64']"
    
    # Teléfono
    notificacion_telefono_selector: str = "input[name*='_id28:9:_id31:2:_id35:0:_id64']"
    
    # =========================================================================
    # FORMULARIO - Sección 6: Naturaleza del escrito
    # =========================================================================
    
    naturaleza_alegacion_selector: str = "#GESTION_MULTAS_NATURALEZA_1"  # value="A"
    naturaleza_recurso_selector: str = "#GESTION_MULTAS_NATURALEZA_2"    # value="R"
    naturaleza_identificacion_selector: str = "#GESTION_MULTAS_NATURALEZA_3"  # value="I"
    
    # =========================================================================
    # FORMULARIO - Sección 7: Expone y Solicita
    # =========================================================================
    
    expone_selector: str = ".formula2_GESTION_MULTAS_EXPONE"
    solicita_selector: str = ".formula2_GESTION_MULTAS_SOLICITA"
    
    # =========================================================================
    # FORMULARIO - Sección 8: Botones finales
    # =========================================================================
    
    guardar_borrador_selector: str = "input[name='guardar_borrador'][type='submit']"
    continuar_formulario_selector: str = "input[type='submit'][value='Continuar']"
    
    # =========================================================================
    # Configuración de esperas
    # =========================================================================
    
    default_timeout: int = 30000  # 30 segundos
    navigation_timeout: int = 60000  # 60 segundos para navegaciones con certificado
    
    # =========================================================================
    # Configuración del navegador
    # =========================================================================
    
    lang: str = "es"  # Español para evitar popup de traductor
    disable_translate_ui: bool = True
