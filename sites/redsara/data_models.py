from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RedSaraDireccion:
    tipo_via: str
    direccion: str
    provincia: str
    ciudad: str
    codigo_postal: str
    gerent_pobl: str | None = None


@dataclass(frozen=True)
class RedSaraInteresado:
    es_empresa: bool
    num_cliente: str | None = None
    nombre: str = ""
    apellido1: str = ""
    apellido2: str = ""
    nif: str = ""
    cif: str = ""
    empresa: str = ""
    email: str | None = None
    telefono: str | None = None
    direccion: RedSaraDireccion | None = None


@dataclass(frozen=True)
class RedSaraRepresentante:
    nif: str = ""
    nombre: str = ""
    apellido: str = ""
    email: str = ""
    telefono: str = ""
    direccion: RedSaraDireccion | None = None
    es_representante: bool = True


@dataclass(frozen=True)
class RedSaraPresentador:
    igual_que_representante: bool = True


@dataclass(frozen=True)
class RedSaraRecurso:
    organismo: str = ""
    fase: str = ""
    expediente: str = ""
    recent_pdf: dict[str, Any] = field(default_factory=dict)
    es_carpeta: bool = False


@dataclass(frozen=True)
class RedSaraTarget:
    representante: RedSaraRepresentante
    presentador: RedSaraPresentador
    interesado: RedSaraInteresado
    recurso: RedSaraRecurso
    archivos_adjuntos: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
