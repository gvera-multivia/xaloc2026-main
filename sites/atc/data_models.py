from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class AtcDocumento:
    fitxer: Path
    tipus: str = ""
    descripcio: str = ""


@dataclass
class AtcTarget:
    idRecurso: int | None = None
    idExp: int | None = None
    numclient: int | None = None
    expediente: str = ""
    procedim: str = ""
    protocol: str = "reposicio"
    csv_acto: str = ""
    representado_nif: str = ""
    representado_nombre: str = ""
    alegaciones: str = ""
    motivo_reposicion: str = "Altres motius diferents dels anteriors."
    block_until_date: date | None = None
    tipo_tramite: str = "Aporte de documentos"
    tipo_documento: str = "Expediente"
    impuesto: str = "Impuesto sobre sucesiones y donaciones"
    num_documento: str = ""
    email: str = ""
    telefono: str = ""
    nif_interesado: str = ""
    nombre_interesado: str = ""
    organo: str = "Oficina Central de Gestion Tributaria"
    asunto: str = ""
    documentos: list[AtcDocumento] = field(default_factory=list)
    archivos_adjuntos: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    headless: bool = True
