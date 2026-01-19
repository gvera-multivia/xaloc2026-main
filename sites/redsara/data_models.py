from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

@dataclass
class DatosDireccion:
    tipo_via: str
    direccion: str
    provincia: str
    ciudad: str
    codigo_postal: str
    es_extranjero: bool = False

@dataclass
class DatosRepresentante:
    nif: str
    nombre: str
    apellido: str
    email: str
    telefono: str
    direccion: DatosDireccion
    es_representante: bool = True

@dataclass
class DatosPresentador:
    igual_que_representante: bool = True
    direccion: Optional[DatosDireccion] = None

@dataclass
class DatosInteresado:
    nombre: str
    apellido: str
    segundo_apellido: str
    nif: str
    tipo_documento: str = "NIF" # NIF, NIE, CIF, PASAPORTE
    direccion: Optional[DatosDireccion] = None
    email: Optional[str] = None
    telefono: Optional[str] = None

@dataclass
class ArchivoAdjunto:
    ruta: Path
    tipo_documento: str = "Otros"
    descripcion: str = ""
