from __future__ import annotations
import logging
from pathlib import Path

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import (
    BaseOnlineP2Data,
    BaseOnlineP1ContactData,
    BaseOnlineP1Data,
    BaseOnlineAddressData,
    BaseOnlineP1IdentificacionData,
    BaseOnlineReposicionData,
    BaseOnlineTarget,
)

class BaseOnlineController:
    site_id = "base_online"
    display_name = "BASE On-line"

    def create_config(self, *, headless: bool) -> BaseOnlineConfig:
        config = BaseOnlineConfig()
        config.navegador.headless = bool(headless)
        return config

    def create_demo_data(
        self,
        *,
        protocol: str | None = None,
        p1_telefon_mobil: str | None = None,
        p1_telefon_fix: str | None = None,
        p1_correu: str | None = None,
        p1_expedient_id_ens: str | None = None,
        p1_expedient_any: str | None = None,
        p1_expedient_num: str | None = None,
        p1_num_butlleti: str | None = None,
        p1_data_denuncia: str | None = None,
        p1_matricula: str | None = None,
        p1_identificacio: str | None = None,
        p1_llicencia_conduccio: str | None = None,
        p1_nom_complet: str | None = None,
        p1_adreca: str | None = None,
        p3_tipus_objecte: str | None = None,
        p3_dades_especifiques: str | None = None,
        p3_tipus_solicitud_value: str | None = None,
        p3_exposo: str | None = None,
        p3_solicito: str | None = None,
        p3_archivos: str | list[str] | None = None, # Cambiado a plural para claridad
        p2_nif: str | None = None,
        p2_rao_social: str | None = None,
    ) -> BaseOnlineTarget:
        protocol_norm = (protocol or "P1").upper().strip()
        reposicion = None
        p1 = None
        p3 = None
        p2 = None

        if protocol_norm == "P1":
            p1 = BaseOnlineP1Data(
                contacte=BaseOnlineP1ContactData(
                    telefon_mobil=p1_telefon_mobil or "600123123",
                    telefon_fix=p1_telefon_fix,
                    correu=p1_correu or "test@example.com",
                ),
                identificacio=BaseOnlineP1IdentificacionData(
                    expedient_id_ens=p1_expedient_id_ens or "43150",
                    expedient_any=p1_expedient_any or "2017",
                    expedient_num=p1_expedient_num or "1596",
                    num_butlleti=p1_num_butlleti or "BUT/2026/001",
                    data_denuncia=p1_data_denuncia or "21/03/2017",
                    matricula=p1_matricula or "1234ABC",
                    identificacio=p1_identificacio or "12345678Z",
                    llicencia_conduccio=p1_llicencia_conduccio or "LIC123456",
                    nom_complet=p1_nom_complet or "Nombre Apellidos",
                    adreca=p1_adreca,
                    adreca_detall=BaseOnlineAddressData(
                        sigla="CL",
                        calle="CALLE PRUEBA",
                        numero="1",
                        codigo_postal="43001",
                        municipio="TARRAGONA",
                        provincia="TARRAGONA",
                        ampliacion_municipio="AMPLIACION MUNICIPIO",
                        ampliacion_calle="AMPLIACION CALLE",
                    ),
                ),
            )

        if protocol_norm == "P2":
            p2 = BaseOnlineP2Data(
                nif=p2_nif or "12345678Z",
                rao_social=p2_rao_social or "Nombre/Razón social",
                contacte=BaseOnlineP1ContactData(
                    telefon_mobil=p1_telefon_mobil or "600123123",
                    telefon_fix=p1_telefon_fix,
                    correu=p1_correu or "test@example.com",
                ),
            )
        
        if protocol_norm == "P3":
            # Procesamos los archivos: si viene uno solo en string, lo metemos en lista.
            # Si no viene nada, usamos el de prueba por defecto.
            lista_raw = []
            if p3_archivos:
                lista_raw = [p3_archivos] if isinstance(p3_archivos, str) else p3_archivos
            else:
                lista_raw = ["pdfs-prueba/test3.pdf"]

            archivos_paths = [Path(a) for a in lista_raw]

            reposicion = BaseOnlineReposicionData(
                tipus_objecte=p3_tipus_objecte or "IVTM",
                dades_especifiques=p3_dades_especifiques or "1234-ABC (Matrícula de prueba)",
                tipus_solicitud_value=str(p3_tipus_solicitud_value or "1"),
                exposo=p3_exposo or "Exposición de motivos de prueba para el recurso.",
                solicito=p3_solicito or "Solicitud de prueba para el recurso.",
                archivos_adjuntos=archivos_paths, # Ahora es una lista
            )
            p3 = reposicion
        return BaseOnlineTarget(protocol=protocol_norm, p1=p1, p2=p2, p3=p3, reposicion=reposicion)

def get_controller() -> BaseOnlineController:
    return BaseOnlineController()

__all__ = ["BaseOnlineController", "get_controller"]
