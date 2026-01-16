from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List


@dataclass(frozen=True)
class BaseOnlineP1ContactData:
    telefon_mobil: str | None = None
    telefon_fix: str | None = None
    correu: str | None = None


@dataclass(frozen=True)
class BaseOnlineP1IdentificacionData:
    expedient_id_ens: str
    expedient_any: str
    expedient_num: str
    num_butlleti: str
    data_denuncia: str  # dd/mm/YYYY
    matricula: str
    identificacio: str  # DNI/NIE/PASAPORTE
    llicencia_conduccio: str
    nom_complet: str
    adreca: str


@dataclass(frozen=True)
class BaseOnlineP1Data:
    contacte: BaseOnlineP1ContactData
    identificacio: BaseOnlineP1IdentificacionData


@dataclass(frozen=True)
class BaseOnlineReposicionData:
    tipus_objecte: str
    dades_especifiques: str
    tipus_solicitud_value: str
    exposo: str
    solicito: str
    archivos_adjuntos: Optional[List[Path]]


@dataclass(frozen=True)
class BaseOnlineTarget:
    """
    Punto de ramificación en Common Desktop.

    - P1: Solicitud de identificación de conductor (M250)
    - P2: Alegaciones (M203)
    - P3: Recurso de reposición (recursTelematic)
    """

    protocol: str  # "P1" | "P2" | "P3"
    p1: BaseOnlineP1Data | None = None
    p3: BaseOnlineReposicionData | None = None
    # Compat (arquitectura anterior)
    reposicion: BaseOnlineReposicionData | None = None
    p1: BaseOnlineP1Data | None = None
