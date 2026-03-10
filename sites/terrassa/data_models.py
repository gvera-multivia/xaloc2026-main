from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TerrassaTarget:
    idRecurso: int | None = None
    idExp: int | None = None
    numclient: int | None = None
    expediente: str = ""
    is_company: bool = False
    document_type_value: str = "1"
    document_number: str = ""
    nombre: str = ""
    apellido1: str = ""
    apellido2: str = ""
    fecha_infraccion: str = ""
    matricula: str = ""
    marca: str = "Otros"
    alegaciones: str = ""
    observaciones: str = ""
    documentos: list[dict[str, str]] = field(default_factory=list)
    archivos_para_subir: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    headless: bool = True
    fase_procedimiento: str = ""
    sujeto_recurso: str = ""
