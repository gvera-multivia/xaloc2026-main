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
        p1_address_street: str | None = None,
        p1_address_number: str | None = None,
        p1_address_zip: str | None = None,
        p1_address_city: str | None = None,
        p1_address_province: str | None = None,
        p1_archivos: str | list[str] | None = None,
        p3_tipus_objecte: str | None = None,
        p3_dades_especifiques: str | None = None,
        p3_tipus_solicitud_value: str | None = None,
        p3_exposo: str | None = None,
        p3_solicito: str | None = None,
        p3_archivos: str | list[str] | None = None, # Cambiado a plural para claridad
        p2_nif: str | None = None,
        p2_rao_social: str | None = None,
        p2_archivos: str | list[str] | None = None,
    ) -> BaseOnlineTarget:
        protocol_norm = (protocol or "P1").upper().strip()
        reposicion = None
        p1 = None
        p3 = None
        p2 = None

        if protocol_norm == "P1":
            lista_raw_p1 = []
            if p1_archivos:
                lista_raw_p1 = [p1_archivos] if isinstance(p1_archivos, str) else p1_archivos
            else:
                lista_raw_p1 = ["pdfs-prueba/test1.pdf"]

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
                        calle=p1_address_street or "CALLE PRUEBA",
                        numero=p1_address_number or "1",
                        codigo_postal=p1_address_zip or "43001",
                        municipio=p1_address_city or "TARRAGONA",
                        provincia=p1_address_province or "TARRAGONA",
                        ampliacion_municipio="AMPLIACION MUNICIPIO",
                        ampliacion_calle="AMPLIACION CALLE",
                    ),
                ),
                archivos_adjuntos=[Path(a) for a in lista_raw_p1],
            )

        if protocol_norm == "P2":
            lista_raw_p2 = []
            if p2_archivos:
                lista_raw_p2 = [p2_archivos] if isinstance(p2_archivos, str) else p2_archivos
            else:
                lista_raw_p2 = ["pdfs-prueba/test1.pdf"]

            p2 = BaseOnlineP2Data(
                nif=p2_nif or "12345678Z",
                rao_social=p2_rao_social or "Nombre/Razón social",
                contacte=BaseOnlineP1ContactData(
                    telefon_mobil=p1_telefon_mobil or "600123123",
                    telefon_fix=p1_telefon_fix,
                    correu=p1_correu or "test@example.com",
                ),
                expedient_id_ens="43150",
                expedient_any="2017",
                expedient_num="1596",
                butlleti="BUT/2026/001",
                exposo="Exposición de prueba.",
                solicito="Solicitud de prueba.",
                archivos_adjuntos=[Path(a) for a in lista_raw_p2],
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

    def create_target_strict(
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
        p1_address_street: str | None = None,
        p1_address_number: str | None = None,
        p1_address_zip: str | None = None,
        p1_address_city: str | None = None,
        p1_address_province: str | None = None,
        p1_archivos: str | list[str] | None = None,
        p3_tipus_objecte: str | None = None,
        p3_dades_especifiques: str | None = None,
        p3_tipus_solicitud_value: str | None = None,
        p3_exposo: str | None = None,
        p3_solicito: str | None = None,
        p3_archivos: str | list[str] | None = None,
        p2_nif: str | None = None,
        p2_rao_social: str | None = None,
        p2_archivos: str | list[str] | None = None,
    ) -> BaseOnlineTarget:
        protocol_norm = (protocol or "P1").upper().strip()
        reposicion = None
        p1 = None
        p3 = None
        p2 = None

        if protocol_norm == "P1":
            lista_raw_p1 = []
            if p1_archivos:
                lista_raw_p1 = [p1_archivos] if isinstance(p1_archivos, str) else p1_archivos

            p1 = BaseOnlineP1Data(
                contacte=BaseOnlineP1ContactData(
                    telefon_mobil=p1_telefon_mobil or "",
                    telefon_fix=p1_telefon_fix or "",
                    correu=p1_correu or "",
                ),
                identificacio=BaseOnlineP1IdentificacionData(
                    expedient_id_ens=p1_expedient_id_ens or "",
                    expedient_any=p1_expedient_any or "",
                    expedient_num=p1_expedient_num or "",
                    num_butlleti=p1_num_butlleti or "",
                    data_denuncia=p1_data_denuncia or "",
                    matricula=p1_matricula or "",
                    identificacio=p1_identificacio or "",
                    llicencia_conduccio=p1_llicencia_conduccio or "",
                    nom_complet=p1_nom_complet or "",
                    adreca=p1_adreca,
                    adreca_detall=BaseOnlineAddressData(
                        sigla="",
                        calle=p1_address_street or "",
                        numero=p1_address_number or "",
                        codigo_postal=p1_address_zip or "",
                        municipio=p1_address_city or "",
                        provincia=p1_address_province or "",
                        ampliacion_municipio="",
                        ampliacion_calle="",
                    ),
                ),
                archivos_adjuntos=[Path(a) for a in lista_raw_p1],
            )

        if protocol_norm == "P2":
            lista_raw_p2 = []
            if p2_archivos:
                lista_raw_p2 = [p2_archivos] if isinstance(p2_archivos, str) else p2_archivos

            p2 = BaseOnlineP2Data(
                nif=p2_nif or "",
                rao_social=p2_rao_social or "",
                contacte=BaseOnlineP1ContactData(
                    telefon_mobil=p1_telefon_mobil or "",
                    telefon_fix=p1_telefon_fix or "",
                    correu=p1_correu or "",
                ),
                expedient_id_ens=p1_expedient_id_ens or "",
                expedient_any=p1_expedient_any or "",
                expedient_num=p1_expedient_num or "",
                butlleti=p1_num_butlleti or "",
                exposo="",
                solicito="",
                archivos_adjuntos=[Path(a) for a in lista_raw_p2],
            )

        if protocol_norm == "P3":
            lista_raw = []
            if p3_archivos:
                lista_raw = [p3_archivos] if isinstance(p3_archivos, str) else p3_archivos

            archivos_paths = [Path(a) for a in lista_raw]

            reposicion = BaseOnlineReposicionData(
                tipus_objecte=p3_tipus_objecte or "",
                dades_especifiques=p3_dades_especifiques or "",
                tipus_solicitud_value=str(p3_tipus_solicitud_value or ""),
                exposo=p3_exposo or "",
                solicito=p3_solicito or "",
                archivos_adjuntos=archivos_paths,
            )
            p3 = reposicion
        return BaseOnlineTarget(protocol=protocol_norm, p1=p1, p2=p2, p3=p3, reposicion=reposicion)

    create_target = create_demo_data

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genéricas de DB a argumentos de create_target.
        """
        return {
            "p1_telefon_mobil": data.get("p1_telefon_mobil") or data.get("user_phone"),
            "p1_telefon_fix": data.get("p1_telefon_fix"),
            "p1_correu": data.get("p1_correu") or data.get("user_email"),
            "p1_matricula": data.get("p1_matricula") or data.get("plate_number"),
            "p1_expedient_id_ens": data.get("p1_expedient_id_ens") or data.get("expediente_id_ens"),
            "p1_expedient_any": data.get("p1_expedient_any") or data.get("expediente_any"),
            "p1_expedient_num": data.get("p1_expedient_num") or data.get("expediente_num"),
            "p1_num_butlleti": data.get("p1_num_butlleti") or data.get("num_butlleti"),
            "p1_data_denuncia": data.get("p1_data_denuncia") or data.get("data_denuncia"),
            "p1_identificacio": data.get("p1_identificacio") or data.get("nif"),
            "p1_llicencia_conduccio": data.get("p1_llicencia_conduccio") or data.get("llicencia_conduccio"),
            "p1_nom_complet": data.get("p1_nom_complet") or data.get("name"),
            "p1_adreca": data.get("p1_adreca"),
            "p1_address_street": data.get("p1_address_street") or data.get("address_street"),
            "p1_address_number": data.get("p1_address_number") or data.get("address_number"),
            "p1_address_zip": data.get("p1_address_zip") or data.get("address_zip"),
            "p1_address_city": data.get("p1_address_city") or data.get("address_city"),
            "p1_address_province": data.get("p1_address_province") or data.get("address_province"),
            # P2 mapping example (podría ser necesario ajustar según protocolo)
            "p2_nif": data.get("p2_nif") or data.get("nif"),
            "p2_rao_social": data.get("p2_rao_social") or data.get("name"),
            "p3_tipus_objecte": data.get("p3_tipus_objecte"),
            "p3_dades_especifiques": data.get("p3_dades_especifiques"),
            "p3_tipus_solicitud_value": data.get("p3_tipus_solicitud_value"),
            "p3_exposo": data.get("p3_exposo"),
            "p3_solicito": data.get("p3_solicito"),
            # Archivos
            "p1_archivos": data.get("p1_archivos") or data.get("archivos"),
            "p2_archivos": data.get("p2_archivos") or data.get("archivos"),
            "p3_archivos": data.get("p3_archivos") or data.get("archivos"),
        }

def get_controller() -> BaseOnlineController:
    return BaseOnlineController()

__all__ = ["BaseOnlineController", "get_controller"]
