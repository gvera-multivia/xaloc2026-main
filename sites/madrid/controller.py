"""
Controlador del sitio Madrid Ayuntamiento.
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
        # Expediente
        exp_tipo: str = "opcion1",
        exp_nnn: str = "911",
        exp_eeeeeeeee: str = "102532229",
        exp_d: str = "3",
        exp_lll: str = "MSA",
        exp_aaaa: str = "2025",
        exp_num: str = "123456789",
        # Matrícula
        matricula: str = "1234ABC",
        # Interesado
        inter_telefono: str = "600123456",
        inter_email: bool = True,
        inter_sms: bool = False,
        # Representante
        rep_tipo_via: str = "CALLE",
        rep_nombre_via: str = "CALLE PRUEBA",
        rep_portal: str = "1",
        rep_cp: str = "28001",
        rep_municipio: str = "MADRID",
        rep_provincia: str = "MADRID",
        rep_email: str = "representante@example.com",
        rep_movil: str = "600123123",
        # Notificación
        notif_copiar: str = "",  # "interesado", "representante" o vacío
        notif_tipo_doc: str = "NIE",
        notif_num_doc: str = "X1234567L",
        notif_nombre: str = "JUAN",
        notif_apellido1: str = "PEREZ",
        notif_apellido2: str = "GARCIA",
        notif_razon_social: str = "EMPRESA DE PRUEBA SL",
        notif_pais: str = "ESPAÑA",
        notif_provincia: str = "MADRID",
        notif_municipio: str = "MADRID",
        notif_tipo_via: str = "CALLE",
        notif_nombre_via: str = "CALLE PRUEBA",
        notif_numero: str = "1",
        notif_cp: str = "28001",
        notif_email: str = "juan.perez@example.com",
        notif_movil: str = "600123456",
        # Naturaleza
        naturaleza: str = "A",  # A=Alegación, R=Recurso, I=Identificación
        # Expone y Solicita
        expone: str = "Expongo que el día de los hechos denunciados no me encontraba en el lugar indicado.",
        solicita: str = "Solicito que se archive el expediente sancionador por falta de pruebas.",
        # Archivos
        archivos: list[str] | None = None,
    ) -> MadridTarget:
        """
        Crea datos de demostración para el sitio Madrid.
        Todos los parámetros son configurables desde CLI.
        """
        
        # Determinar tipo de expediente
        tipo_exp = TipoExpediente.OPCION1 if exp_tipo == "opcion1" else TipoExpediente.OPCION2
        
        expediente = ExpedienteData(
            tipo=tipo_exp,
            nnn=exp_nnn,
            eeeeeeeee=exp_eeeeeeeee,
            d=exp_d,
            lll=exp_lll,
            aaaa=exp_aaaa,
            exp_num=exp_num,
        )
        
        # Interesado
        interesado = InteresadoData(
            telefono=inter_telefono,
            confirmar_email=inter_email,
            confirmar_sms=inter_sms,
        )
        
        # Representante
        representante = RepresentanteData(
            direccion=DireccionData(
                tipo_via=rep_tipo_via,
                nombre_via=rep_nombre_via,
                tipo_numeracion="NUM",
                numero="1",
                portal=rep_portal,
                escalera="A",
                planta="1",
                puerta="A",
                codigo_postal=rep_cp,
                municipio=rep_municipio,
                provincia=rep_provincia,
                pais="ESPAÑA",
            ),
            contacto=ContactoData(
                email=rep_email,
                movil=rep_movil,
                telefono=inter_telefono,
            ),
        )
        
        # Tipo de documento para notificación
        if notif_tipo_doc == "NIF":
            tipo_doc = TipoDocumento.NIF
        elif notif_tipo_doc == "NIE":
            tipo_doc = TipoDocumento.NIE
        else:
            tipo_doc = TipoDocumento.PASAPORTE
        
        # Notificación
        notificacion = NotificacionData(
            copiar_desde=notif_copiar,
            identificacion=IdentificacionData(
                tipo_documento=tipo_doc,
                numero_documento=notif_num_doc,
                nombre=notif_nombre,
                apellido1=notif_apellido1,
                apellido2=notif_apellido2,
                razon_social=notif_razon_social,
            ),
            direccion=DireccionData(
                pais=notif_pais,
                provincia=notif_provincia,
                municipio=notif_municipio,
                tipo_via=notif_tipo_via,
                nombre_via=notif_nombre_via,
                tipo_numeracion="NUM",
                numero=notif_numero,
                portal="1",
                escalera="A",
                planta="1",
                puerta="A",
                codigo_postal=notif_cp,
            ),
            contacto=ContactoData(
                email=notif_email,
                movil=notif_movil,
                telefono=inter_telefono,
            ),
        )
        
        # Naturaleza del escrito
        if naturaleza == "R":
            nat = NaturalezaEscrito.RECURSO
        elif naturaleza == "I":
            nat = NaturalezaEscrito.IDENTIFICACION_CONDUCTOR
        else:
            nat = NaturalezaEscrito.ALEGACION
        
        # Crear datos del formulario
        form_data = MadridFormData(
            expediente=expediente,
            matricula=matricula,
            interesado=interesado,
            representante=representante,
            notificacion=notificacion,
            naturaleza=nat,
            expone=expone,
            solicita=solicita,
        )
        
        # Archivos adjuntos
        archivos_paths = []
        if archivos:
            archivos_paths = [Path(a) for a in archivos]
        
        return MadridTarget(
            form_data=form_data,
            archivos_adjuntos=archivos_paths,
            headless=headless,
        )


def get_controller() -> MadridController:
    """Factory function para el registro de sitios."""
    return MadridController()


__all__ = ["MadridController", "get_controller"]
