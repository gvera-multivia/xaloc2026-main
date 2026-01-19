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
    
    # Solo tocamos teléfono y checkboxes de confirmación dentro de la sección _id21:2
    interesado_telefono_selector: str = "input[name*='_id21:2'].formula2_COMUNES_INTERESADO_TELEFONO"
    interesado_check_email_selector: str = "input[name*='_id21:2'].formula2_COMUNES_INTERESADO_CHECKEMAIL"
    interesado_check_sms_selector: str = "input[name*='_id21:2'].formula2_COMUNES_INTERESADO_CHECKSMS"
    
    # =========================================================================
    # FORMULARIO - Sección 4: Datos del representante (CAMPOS ACTIVOS)
    # =========================================================================
    
    # Forzamos el selector a buscar dentro de '_id21:3' (Sección del Representante)
    
    # País y Provincia
    representante_pais_selector: str = "select[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_PAIS"
    representante_provincia_selector: str = "select[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_PROVINCIA"

    # Dirección (Municipio, Tipo Vía, Nombre)
    representante_municipio_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_MUNICIPIO"
    representante_tipo_via_selector: str = "select[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_TIPOVIA"
    representante_nombre_via_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_NOMBREVIA"
    
    # Numeración (Tipo, Número, Portal)
    representante_tipo_num_selector: str = "select[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_TIPONUM"
    representante_numero_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_NUMERO"
    representante_portal_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_PORTAL"
    
    # Detalles (Escalera, Planta, Puerta, CP)
    representante_escalera_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_ESCALERA"
    representante_planta_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_PLANTA"
    representante_puerta_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_PUERTA"
    representante_codpostal_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_CODPOSTAL"
    
    # Contacto (Email, Móvil, Teléfono)
    representante_email_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_EMAIL"
    representante_movil_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_MOVIL"
    representante_telefono_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_TELEFONO"
    
    # Checkboxes de confirmación (Representante)
    representante_check_email_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_CHECKEMAIL"
    representante_check_sms_selector: str = "input[name*='_id21:3'].formula2_COMUNES_REPRESENTANTE_CHECKSMS"
    
    # =========================================================================
    # FORMULARIO - Sección 5: Datos de notificación
    # =========================================================================
    
    # Botones de copia
    notificacion_copiar_interesado_selector: str = "input[type='submit'][value='Copiar datos del interesado']"
    notificacion_copiar_representante_selector: str = "input[type='submit'][value='Copiar datos del representante']"
    
    # Identificación (forzar _id21:5 para evitar colisiones con otras secciones, p.ej. _id21:4)
    notificacion_tipo_doc_selector: str = "select[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_TIPODOC"
    notificacion_num_doc_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_NUMIDENT"
    notificacion_nombre_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_NOMBRE"
    notificacion_apellido1_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_APELLIDO1"
    notificacion_apellido2_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_APELLIDO2"
    notificacion_razon_social_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_RAZONSOCIAL"
    
    # Dirección
    notificacion_pais_selector: str = "select[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_PAIS"
    notificacion_provincia_selector: str = "select[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_PROVINCIA"
    notificacion_municipio_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_MUNICIPIO"
    notificacion_tipo_via_selector: str = "select[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_TIPOVIA"
    notificacion_nombre_via_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_NOMBREVIA"
    notificacion_tipo_num_selector: str = "select[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_TIPONUM"
    notificacion_numero_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_NUMERO"
    notificacion_portal_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_PORTAL"
    notificacion_escalera_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_ESCALERA"
    notificacion_planta_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_PLANTA"
    notificacion_puerta_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_PUERTA"
    notificacion_codpostal_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_CODPOSTAL"
    
    # Contacto
    notificacion_email_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_EMAIL"
    notificacion_movil_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_MOVIL"
    notificacion_telefono_selector: str = "input[name*='_id21:5'].formula2_COMUNES_NOTIFICACION_TELEFONO"
    
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
    # ADJUNTOS / FIRMA (pantallas posteriores)
    # =========================================================================

    # Botón "Continuar" tras adjuntar documentos
    adjuntos_continuar_selector: str = "input[id='formDesigner:_id699'][type='submit'][value='Continuar']"

    # Botón final "Firma y registrar" (NO se pulsa en modo demo)
    firma_registrar_selector: str = "input#btRedireccion"
    
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
