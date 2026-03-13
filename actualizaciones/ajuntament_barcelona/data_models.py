from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AjuntamentBarcelonaTarget:
    idRecurso: int | None = None
    expediente: str = ""
    archivos_adjuntos: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    headless: bool = True
