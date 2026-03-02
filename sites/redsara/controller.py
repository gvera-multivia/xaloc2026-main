from __future__ import annotations

from pathlib import Path

from sites.redsara.config import RedSaraConfig
from sites.redsara.data_models import (
    RedSaraDireccion,
    RedSaraInteresado,
    RedSaraPresentador,
    RedSaraRecurso,
    RedSaraRepresentante,
    RedSaraTarget,
)


class RedSaraController:
    site_id = "redsara"
    display_name = "RedSARA"

    def create_config(self, *, headless: bool) -> RedSaraConfig:
        config = RedSaraConfig()
        config.navegador.headless = bool(headless)
        return config

    def map_data(self, data: dict) -> dict:
        default_email = "info@xvia-serviciosjuridicos.com"
        default_phone = "932531411"
        tipo_via = data.get("tipoVia") or "CALLE"
        direccion = data.get("direccion")
        provincia = data.get("provincia")
        ciudad = data.get("poblacion")
        codigo_postal = data.get("codigoPostal")

        return {
            "payload": data,
            "representante_email": data.get("representante_email") or data.get("user_email") or data.get("email") or default_email,
            "representante_telefono": data.get("representante_telefono") or data.get("user_phone") or data.get("telefono") or default_phone,
            "representante_tipo_via": data.get("representante_tipo_via") or tipo_via,
            "representante_direccion": data.get("representante_direccion") or direccion,
            "representante_provincia": data.get("representante_provincia") or provincia,
            "representante_ciudad": data.get("representante_ciudad") or ciudad,
            "representante_cp": data.get("representante_cp") or codigo_postal,
            "interesado_es_empresa": data.get("interesado_es_empresa", data.get("esEmpresa")),
            "interesado_num_cliente": data.get("numCliente"),
            "interesado_nombre": data.get("nombre"),
            "interesado_apellido1": data.get("apellido1"),
            "interesado_apellido2": data.get("apellido2"),
            "interesado_nif": data.get("nif"),
            "interesado_cif": data.get("cif"),
            "interesado_empresa": data.get("empresa"),
            "interesado_email": data.get("interesado_email") or data.get("email") or default_email,
            "interesado_telefono": data.get("interesado_telefono") or data.get("telefono") or default_phone,
            "interesado_tipo_via": data.get("interesado_tipo_via") or tipo_via,
            "interesado_direccion": data.get("interesado_direccion") or direccion,
            "interesado_provincia": data.get("interesado_provincia") or provincia,
            "interesado_ciudad": data.get("interesado_ciudad") or ciudad,
            "interesado_gerent_pobl": data.get("gerentPobl"),
            "interesado_cp": data.get("interesado_cp") or codigo_postal,
            "recurso_organismo": data.get("recurso_organismo", data.get("organismo")),
            "recurso_fase": data.get("recurso_fase", data.get("fase")),
            "recurso_expediente": data.get("recurso_expediente", data.get("expediente")),
            "recurso_recent_pdf": data.get("recurso_recent_pdf") or data.get("recentPDF") or {},
            "recurso_es_carpeta": data.get("recurso_es_carpeta", data.get("esCarpeta")),
            "archivos_adjuntos": data.get("archivos_adjuntos") or data.get("archivos") or [],
        }

    def create_target(
        self,
        *,
        representante_email: str | None = None,
        representante_telefono: str | None = None,
        representante_tipo_via: str | None = None,
        representante_direccion: str | None = None,
        representante_provincia: str | None = None,
        representante_ciudad: str | None = None,
        representante_cp: str | None = None,
        interesado_es_empresa: bool | None = None,
        interesado_num_cliente: str | None = None,
        interesado_nombre: str | None = None,
        interesado_apellido1: str | None = None,
        interesado_apellido2: str | None = None,
        interesado_nif: str | None = None,
        interesado_cif: str | None = None,
        interesado_empresa: str | None = None,
        interesado_email: str | None = None,
        interesado_telefono: str | None = None,
        interesado_tipo_via: str | None = None,
        interesado_direccion: str | None = None,
        interesado_provincia: str | None = None,
        interesado_ciudad: str | None = None,
        interesado_gerent_pobl: str | None = None,
        interesado_cp: str | None = None,
        recurso_organismo: str | None = None,
        recurso_fase: str | None = None,
        recurso_expediente: str | None = None,
        recurso_recent_pdf: dict | None = None,
        recurso_es_carpeta: bool | None = None,
        archivos_adjuntos: list[Path] | list[str] | None = None,
        payload: dict | None = None,
        **_kwargs,
    ) -> RedSaraTarget:
        def _to_bool(value: bool | str | int | None) -> bool:
            if isinstance(value, bool):
                return value
            if value is None:
                return False
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
            return False

        def _req(name: str, value: str | None) -> str:
            v = (value or "").strip()
            if not v:
                raise ValueError(f"redsara: falta '{name}'.")
            return v

        if interesado_es_empresa is None:
            raise ValueError("redsara: falta 'interesado_es_empresa'.")
        es_empresa = _to_bool(interesado_es_empresa)
        es_carpeta = _to_bool(recurso_es_carpeta)

        representante_dir = RedSaraDireccion(
            tipo_via=_req("representante_tipo_via", representante_tipo_via),
            direccion=_req("representante_direccion", representante_direccion),
            provincia=_req("representante_provincia", representante_provincia),
            ciudad=_req("representante_ciudad", representante_ciudad),
            codigo_postal=_req("representante_cp", representante_cp),
        )
        representante = RedSaraRepresentante(
            email=_req("representante_email", representante_email),
            telefono=_req("representante_telefono", representante_telefono),
            direccion=representante_dir,
        )

        interesado_dir = RedSaraDireccion(
            tipo_via=_req("interesado_tipo_via", interesado_tipo_via),
            direccion=_req("interesado_direccion", interesado_direccion),
            provincia=_req("interesado_provincia", interesado_provincia),
            ciudad=_req("interesado_ciudad", interesado_ciudad),
            codigo_postal=_req("interesado_cp", interesado_cp),
            gerent_pobl=(interesado_gerent_pobl or "").strip() or None,
        )
        interesado = RedSaraInteresado(
            es_empresa=es_empresa,
            num_cliente=(interesado_num_cliente or "").strip() or None,
            nombre=(interesado_nombre or "").strip(),
            apellido1=(interesado_apellido1 or "").strip(),
            apellido2=(interesado_apellido2 or "").strip(),
            nif=(interesado_nif or "").strip(),
            cif=(interesado_cif or "").strip(),
            empresa=(interesado_empresa or "").strip(),
            email=(interesado_email or "").strip() or None,
            telefono=(interesado_telefono or "").strip() or None,
            direccion=interesado_dir,
        )

        recurso = RedSaraRecurso(
            organismo=(recurso_organismo or "").strip(),
            fase=_req("recurso_fase", recurso_fase),
            expediente=_req("recurso_expediente", recurso_expediente),
            recent_pdf=recurso_recent_pdf or {},
            es_carpeta=es_carpeta,
        )

        paths = [Path(a) if isinstance(a, str) else a for a in (archivos_adjuntos or [])]
        return RedSaraTarget(
            representante=representante,
            presentador=RedSaraPresentador(igual_que_representante=True),
            interesado=interesado,
            recurso=recurso,
            archivos_adjuntos=paths,
            payload=payload or {},
        )


def get_controller() -> RedSaraController:
    return RedSaraController()


__all__ = ["RedSaraController", "get_controller"]
