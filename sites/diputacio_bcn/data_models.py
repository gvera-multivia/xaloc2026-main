from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DiputacioBcnTarget:
    idRecurso: int | None = None
    expediente: str = ""
    archivos_adjuntos: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    tipo_representado: str = "fisica"
    nif_interessat: str = ""
    nom_cr4: str = ""
    cognom1: str = ""
    cognom2: str = ""
    nom_juridica: str = ""
    fase_procedimiento: str = ""
    municipio: str = ""
    matricula: str = ""
    doc_acreditativa: str = ""
    doc_tramite: str = ""
    comentari: str = ""
    telefon: str = ""
    email: str = ""
    headless: bool = True
