from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ServeiCatTransTarget:
    idRecurso: int | None = None
    idExp: int | None = None
    numclient: int | None = None
    expediente: str = ""
    servicio_territorial: str = ""
    expediente_numero: str = ""
    digito_control: str = ""
    codigo_personal: str = ""
    tipo_persona: str = "fisica"
    nombre: str = ""
    apellido1: str = ""
    apellido2: str = ""
    nif: str = ""
    razon_social: str = ""
    nif_empresa: str = ""
    email: str = ""
    telefono_movil: str = ""
    direccion_tipo_via: str = ""
    direccion_nombre_via: str = ""
    direccion_numero: str = ""
    direccion_cp: str = ""
    direccion_comarca: str = ""
    direccion_municipio: str = ""
    tipo_escrito: str = "alegaciones"
    expongo: str = ""
    solicito: str = ""
    archivos_para_subir: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    headless: bool = True
