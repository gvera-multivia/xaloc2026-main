"""
Controlador del sitio Madrid Ayuntamiento.
Corregido para validación BDC y segregación de secciones.
"""

from __future__ import annotations
import logging
from pathlib import Path

from sites.madrid.config import MadridConfig
from sites.madrid.data_models import (
    MadridFormData, 
    MadridTarget,
    ExpedienteData,
    TipoExpediente,
    NaturalezaEscrito,
    TipoDocumento,
    InteresadoData,
    RepresentanteData,
    NotificacionData,
    IdentificacionData,
    DireccionData,
    ContactoData,
)

class MadridController:
    site_id = "madrid"
    display_name = "Madrid Ayuntamiento"

    def create_config(self, *, headless: bool) -> MadridConfig:
        """Crea la configuración para el sitio Madrid."""
        config = MadridConfig()
        config.navegador.headless = bool(headless)
        return config

    def create_demo_data(
        self,
        *,
        headless: bool = True,
        # --- Datos del Expediente ---
        exp_tipo: str = "opcion1",
        exp_nnn: str = "911",
        exp_eeeeeeeee: str = "102532229",
        exp_d: str = "3",
        # --- Matrícula (Sección 2) ---
        matricula: str = "1234ABC",
        # --- Datos del Interesado (Sección _id21:2) ---
        inter_telefono: str = "600123456",
        inter_email_check: bool = True,
        # --- Datos del Representante (Sección _id21:3) ---
        # Usamos una dirección REAL de Madrid para pasar la validación BDC
        rep_tipo_via: str = "CALLE",
        rep_nombre_via: str = "GRAN VIA",
        rep_numero: str = "1",
        rep_cp: str = "28013",
        rep_municipio: str = "MADRID",
        rep_email: str = "representante@example.com",
        rep_movil: str = "600123123",
        # --- Datos de Notificación (Sección _id21:5) ---
        notif_nombre: str = "JUAN",
        notif_apellido1: str = "PEREZ",
        notif_apellido2: str = "GARCIA",
        notif_razon_social: str = "",
        naturaleza: str = "A", 
        expone: str = "Expongo que los hechos no concuerdan con la realidad.",
        solicita: str = "Solicito la revisión del expediente.",
        archivos: list[str] | None = None,
    ) -> MadridTarget:
        
        # 1. Configuración del Expediente
        tipo_exp = TipoExpediente.OPCION1 if exp_tipo == "opcion1" else TipoExpediente.OPCION2
        expediente = ExpedienteData(
            tipo=tipo_exp, nnn=exp_nnn, eeeeeeeee=exp_eeeeeeeee, d=exp_d
        )
        
        # 2. Interesado (_id21:2): SOLO teléfono y confirmación de aviso
        # Esto evita que el bot intente tocar campos bloqueados del interesado.
        interesado = InteresadoData(
            telefono=inter_telefono,
            confirmar_email=inter_email_check,
            confirmar_sms=False,
        )
        
        # 3. Representante (_id21:3): Dirección física REAL
        representante = RepresentanteData(
            direccion=DireccionData(
                tipo_via=rep_tipo_via,
                nombre_via=rep_nombre_via,
                tipo_numeracion="NUM",
                numero=rep_numero,
                codigo_postal=rep_cp,
                municipio=rep_municipio,
                provincia="MADRID",
                pais="ESPAÑA",
            ),
            contacto=ContactoData(
                email=rep_email,
                movil=rep_movil,
                telefono=inter_telefono,
            ),
        )
        
        # 4. Notificación (_id21:5): Identidad y domicilio de envío
        # Usamos los mismos datos reales del representante para asegurar éxito.
        notificacion = NotificacionData(
            identificacion=IdentificacionData(
                tipo_documento=TipoDocumento.NIE,
                numero_documento="X1234567L",
                nombre=notif_nombre,
                apellido1=notif_apellido1,
                apellido2=notif_apellido2,
                razon_social=notif_razon_social,
            ),
            direccion=DireccionData(
                pais="ESPAÑA",
                provincia="MADRID",
                municipio=rep_municipio,
                tipo_via=rep_tipo_via,
                nombre_via=rep_nombre_via,
                tipo_numeracion="NUM",
                numero=rep_numero,
                codigo_postal=rep_cp,
            ),
            contacto=ContactoData(
                email=rep_email,
                movil=rep_movil,
                telefono=inter_telefono,
            ),
        )
        
        # 1. Definimos el mapa de tipos
        naturaleza_map = {
            "A": NaturalezaEscrito.ALEGACION,
            "R": NaturalezaEscrito.RECURSO,
            "I": NaturalezaEscrito.IDENTIFICACION_CONDUCTOR
        }

        # 2. Construcción del Target
        form_data = MadridFormData(
            expediente=expediente,
            matricula=matricula,
            interesado=interesado,
            representante=representante,
            notificacion=notificacion,
            # .get() permite establecer un valor por defecto si la letra no coincide (ej. ALEGACION)
            naturaleza=naturaleza_map.get(naturaleza, NaturalezaEscrito.ALEGACION),
            expone=expone,
            solicita=solicita,
        )
        
        if archivos is None:
            archivos = ["pdfs-prueba/test1.pdf", "pdfs-prueba/test2.pdf"]

        return MadridTarget(
            form_data=form_data,
            archivos_adjuntos=[Path(a) for a in archivos] if archivos else [],
            headless=headless,
        )

    create_target = create_demo_data

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genéricas de DB a argumentos de create_target.
        """
        return {
            "matricula": data.get("plate_number"),
            "inter_telefono": data.get("user_phone"),
            "rep_email": data.get("representative_email"),
            "rep_movil": data.get("representative_phone"),
            "rep_nombre_via": data.get("representative_street"),
            "rep_numero": data.get("representative_number"),
            "rep_cp": data.get("representative_zip"),
            "rep_municipio": data.get("representative_city"),
            "notif_nombre": data.get("notif_name"),
            "notif_apellido1": data.get("notif_surname1"),
            "notif_apellido2": data.get("notif_surname2"),
            "exp_tipo": data.get("expediente_tipo"),
            "exp_nnn": data.get("expediente_nnn"),
            "exp_eeeeeeeee": data.get("expediente_eeeeeeeee"),
            "exp_d": data.get("expediente_d"),
            "naturaleza": data.get("naturaleza"),
            "expone": data.get("expone"),
            "solicita": data.get("solicita"),
            "archivos": data.get("archivos"),
        }

def get_controller() -> MadridController:
    return MadridController()
