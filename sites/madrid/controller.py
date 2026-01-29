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

    def create_target_strict(
        self,
        *,
        headless: bool = True,
        exp_tipo: str | None = None,
        exp_nnn: str | None = None,
        exp_eeeeeeeee: str | None = None,
        exp_d: str | None = None,
        exp_lll: str | None = None,
        exp_aaaa: str | None = None,
        exp_exp_num: str | None = None,
        matricula: str | None = None,
        inter_telefono: str | None = None,
        inter_email_check: bool | None = None,
        rep_tipo_via: str | None = None,
        rep_nombre_via: str | None = None,
        rep_numero: str | None = None,
        rep_cp: str | None = None,
        rep_municipio: str | None = None,
        rep_provincia: str | None = None,
        rep_pais: str | None = None,
        rep_tipo_numeracion: str | None = None,
        rep_email: str | None = None,
        rep_movil: str | None = None,
        rep_telefono: str | None = None,
        # Notificación (si no se copia, hay que informar todo)
        notif_copiar_desde: str | None = None,
        notif_tipo_documento: str | None = None,
        notif_numero_documento: str | None = None,
        notif_nombre: str | None = None,
        notif_apellido1: str | None = None,
        notif_apellido2: str | None = None,
        notif_razon_social: str | None = None,
        notif_pais: str | None = None,
        notif_provincia: str | None = None,
        notif_municipio: str | None = None,
        notif_tipo_via: str | None = None,
        notif_nombre_via: str | None = None,
        notif_tipo_numeracion: str | None = None,
        notif_numero: str | None = None,
        notif_codigo_postal: str | None = None,
        notif_email: str | None = None,
        notif_movil: str | None = None,
        notif_telefono: str | None = None,
        naturaleza: str | None = None,
        expone: str | None = None,
        solicita: str | None = None,
        archivos: list[str] | None = None,
    ) -> MadridTarget:
        def _require(name: str, value: str | None) -> str:
            v = (value or "").strip()
            if not v:
                raise ValueError(f"madrid: falta '{name}'.")
            return v

        exp_tipo_norm = _require("exp_tipo", exp_tipo)
        if exp_tipo_norm not in {"opcion1", "opcion2"}:
            raise ValueError("madrid: 'exp_tipo' inválido (usa 'opcion1' o 'opcion2').")
        tipo_exp = TipoExpediente.OPCION2 if exp_tipo_norm == "opcion2" else TipoExpediente.OPCION1

        if tipo_exp == TipoExpediente.OPCION1:
            expediente = ExpedienteData(
                tipo=tipo_exp,
                nnn=_require("exp_nnn", exp_nnn),
                eeeeeeeee=_require("exp_eeeeeeeee", exp_eeeeeeeee),
                d=_require("exp_d", exp_d),
            )
        else:
            expediente = ExpedienteData(
                tipo=tipo_exp,
                lll=_require("exp_lll", exp_lll),
                aaaa=_require("exp_aaaa", exp_aaaa),
                exp_num=_require("exp_exp_num", exp_exp_num),
            )

        if inter_email_check is None:
            raise ValueError("madrid: falta 'inter_email_check'.")
        interesado = InteresadoData(
            telefono=_require("inter_telefono", inter_telefono),
            confirmar_email=bool(inter_email_check),
            confirmar_sms=False,
        )

        representante = RepresentanteData(
            direccion=DireccionData(
                tipo_via=_require("rep_tipo_via", rep_tipo_via),
                nombre_via=_require("rep_nombre_via", rep_nombre_via),
                tipo_numeracion=_require("rep_tipo_numeracion", rep_tipo_numeracion),
                numero=_require("rep_numero", rep_numero),
                codigo_postal=_require("rep_cp", rep_cp),
                municipio=_require("rep_municipio", rep_municipio),
                provincia=_require("rep_provincia", rep_provincia),
                pais=_require("rep_pais", rep_pais),
            ),
            contacto=ContactoData(
                email=_require("rep_email", rep_email),
                movil=_require("rep_movil", rep_movil),
                telefono=_require("rep_telefono", rep_telefono),
            ),
        )

        tipo_doc_raw = _require("notif_tipo_documento", notif_tipo_documento).upper()
        try:
            tipo_doc = TipoDocumento[tipo_doc_raw]
        except KeyError as e:
            raise ValueError("madrid: 'notif_tipo_documento' inválido (NIF, NIE, PASAPORTE).") from e

        notificacion = NotificacionData(
            copiar_desde=(notif_copiar_desde or "").strip(),
            identificacion=IdentificacionData(
                tipo_documento=tipo_doc,
                numero_documento=_require("notif_numero_documento", notif_numero_documento),
                nombre=_require("notif_nombre", notif_nombre),
                apellido1=_require("notif_apellido1", notif_apellido1),
                apellido2=_require("notif_apellido2", notif_apellido2),
                razon_social=(notif_razon_social or "").strip(),
            ),
            direccion=DireccionData(
                pais=_require("notif_pais", notif_pais),
                provincia=_require("notif_provincia", notif_provincia),
                municipio=_require("notif_municipio", notif_municipio),
                tipo_via=_require("notif_tipo_via", notif_tipo_via),
                nombre_via=_require("notif_nombre_via", notif_nombre_via),
                tipo_numeracion=_require("notif_tipo_numeracion", notif_tipo_numeracion),
                numero=_require("notif_numero", notif_numero),
                codigo_postal=_require("notif_codigo_postal", notif_codigo_postal),
            ),
            contacto=ContactoData(
                email=_require("notif_email", notif_email),
                movil=_require("notif_movil", notif_movil),
                telefono=_require("notif_telefono", notif_telefono),
            ),
        )

        naturaleza_map = {
            "A": NaturalezaEscrito.ALEGACION,
            "R": NaturalezaEscrito.RECURSO,
            "I": NaturalezaEscrito.IDENTIFICACION_CONDUCTOR
        }

        nat = _require("naturaleza", naturaleza)
        if nat not in naturaleza_map:
            raise ValueError("madrid: 'naturaleza' inválida (A, R o I).")

        form_data = MadridFormData(
            expediente=expediente,
            matricula=_require("matricula", matricula),
            interesado=interesado,
            representante=representante,
            notificacion=notificacion,
            naturaleza=naturaleza_map[nat],
            expone=_require("expone", expone),
            solicita=_require("solicita", solicita),
        )

        if not archivos:
            raise ValueError("madrid: falta 'archivos' (al menos 1 archivo).")
        archivos_final = archivos

        return MadridTarget(
            form_data=form_data,
            archivos_adjuntos=[Path(a) for a in archivos_final] if archivos_final else [],
            headless=headless,
        )

    create_target = create_target_strict

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genéricas de DB a argumentos de create_target.
        """
        return {
            # Permite dos formatos:
            # - "genérico" (plate_number, representative_*, etc.) para worker-tasks
            # - "avanzado" (matricula, rep_*, exp_*) para sobreescribir defaults del controlador
            "matricula": data.get("matricula") or data.get("plate_number"),
            "inter_telefono": data.get("inter_telefono") or data.get("user_phone"),
            "inter_email_check": data.get("inter_email_check"),
            "rep_tipo_via": data.get("rep_tipo_via"),
            "rep_nombre_via": data.get("rep_nombre_via") or data.get("representative_street"),
            "rep_tipo_numeracion": data.get("rep_tipo_numeracion") or data.get("representative_number_type"),
            "rep_numero": data.get("rep_numero") or data.get("representative_number"),
            "rep_cp": data.get("rep_cp") or data.get("representative_zip"),
            "rep_municipio": data.get("rep_municipio") or data.get("representative_city"),
            "rep_provincia": data.get("rep_provincia") or data.get("representative_province"),
            "rep_pais": data.get("rep_pais") or data.get("representative_country"),
            "rep_email": data.get("rep_email") or data.get("representative_email"),
            "rep_movil": data.get("rep_movil") or data.get("representative_phone"),
            "rep_telefono": data.get("rep_telefono") or data.get("user_phone"),
            "notif_copiar_desde": data.get("notif_copiar_desde"),
            "notif_tipo_documento": data.get("notif_tipo_documento"),
            "notif_numero_documento": data.get("notif_numero_documento"),
            "notif_nombre": data.get("notif_nombre") or data.get("notif_name"),
            "notif_apellido1": data.get("notif_apellido1") or data.get("notif_surname1"),
            "notif_apellido2": data.get("notif_apellido2") or data.get("notif_surname2"),
            "notif_razon_social": data.get("notif_razon_social"),
            "notif_pais": data.get("notif_pais"),
            "notif_provincia": data.get("notif_provincia"),
            "notif_municipio": data.get("notif_municipio") or data.get("rep_municipio") or data.get("representative_city"),
            "notif_tipo_via": data.get("notif_tipo_via") or data.get("rep_tipo_via"),
            "notif_nombre_via": data.get("notif_nombre_via") or data.get("rep_nombre_via") or data.get("representative_street"),
            "notif_tipo_numeracion": data.get("notif_tipo_numeracion") or data.get("rep_tipo_numeracion") or data.get("representative_number_type"),
            "notif_numero": data.get("notif_numero") or data.get("rep_numero") or data.get("representative_number"),
            "notif_codigo_postal": data.get("notif_codigo_postal") or data.get("rep_cp") or data.get("representative_zip"),
            "notif_email": data.get("notif_email") or data.get("rep_email") or data.get("representative_email"),
            "notif_movil": data.get("notif_movil") or data.get("rep_movil") or data.get("representative_phone"),
            "notif_telefono": data.get("notif_telefono") or data.get("rep_telefono") or data.get("user_phone"),
            "exp_tipo": data.get("exp_tipo") or data.get("expediente_tipo"),
            "exp_nnn": data.get("exp_nnn") or data.get("expediente_nnn"),
            "exp_eeeeeeeee": data.get("exp_eeeeeeeee") or data.get("expediente_eeeeeeeee"),
            "exp_d": data.get("exp_d") or data.get("expediente_d"),
            "exp_lll": data.get("exp_lll") or data.get("expediente_lll"),
            "exp_aaaa": data.get("exp_aaaa") or data.get("expediente_aaaa"),
            "exp_exp_num": data.get("exp_exp_num") or data.get("expediente_exp_num"),
            "naturaleza": data.get("naturaleza"),
            "expone": data.get("expone"),
            "solicita": data.get("solicita"),
            "archivos": data.get("archivos") or data.get("archivos_adjuntos"),
        }

def get_controller() -> MadridController:
    return MadridController()
