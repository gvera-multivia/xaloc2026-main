from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Literal


@dataclass
class DatosMandatario:
    """Datos del representado (persona física o jurídica)."""
    tipo_persona: Literal["FISICA", "JURIDICA"]
    
    # Persona Jurídica (CIF)
    cif_documento: Optional[str] = None  # Primeros 8 caracteres del CIF
    cif_control: Optional[str] = None    # Último dígito del CIF
    razon_social: Optional[str] = None   # Nombre de la empresa
    
    # Persona Física (NIF/NIE)
    tipo_doc: Optional[Literal["NIF", "PS"]] = None  # NIF o Pasaporte (NIE)
    doc_numero: Optional[str] = None     # Primeros 8 caracteres del NIF/NIE
    doc_control: Optional[str] = None    # Último carácter (letra) del NIF/NIE
    nombre: Optional[str] = None
    apellido1: Optional[str] = None
    apellido2: Optional[str] = None


@dataclass
class DatosMulta:
    email: str
    num_denuncia: str
    matricula: str
    num_expediente: str
    motivos: str
    archivos_adjuntos: Optional[List[Path]] = None
    mandatario: Optional[DatosMandatario] = None  # NUEVO: Datos del mandatario

    @property
    def archivos_para_subir(self) -> List[Path]:
        return self.archivos_adjuntos if self.archivos_adjuntos else []

