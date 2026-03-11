from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ValenciaTarget:
    idRecurso: int | None = None
    idExp: int | None = None
    expediente: str = ""
    fase_procedimiento: str = ""
    tramite_tipo: str = ""
    tramite_code: str = ""

    tipodecliente: str = ""
    nif: str = ""
    nifempresa: str = ""
    nombre: str = ""
    apellido1: str = ""
    apellido2: str = ""
    nombrefiscal: str = ""

    conduc_nom: str = ""
    conduc_dni: str = ""
    conduc_codpost: str = ""
    conduc_adr: str = ""

    texp: int = 0
    matricula: str = ""
    matricula2: str = ""
    matricula3: str = ""

    expone: str = ""
    solicita: str = ""

    archivos_para_subir: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    headless: bool = True
