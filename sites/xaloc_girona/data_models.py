from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class DatosMulta:
    email: str
    num_denuncia: str
    matricula: str
    num_expediente: str
    motivos: str
    archivos_adjuntos: Optional[List[Path]] = None

    @property
    def archivos_para_subir(self) -> List[Path]:
        return self.archivos_adjuntos if self.archivos_adjuntos else []

