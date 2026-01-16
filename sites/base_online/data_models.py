from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaseOnlineReposicionData:
    tipus_objecte: str
    dades_especifiques: str
    tipus_solicitud_value: str
    exposo: str
    solicito: str


@dataclass(frozen=True)
class BaseOnlineTarget:
    """
    Punto de ramificación en Common Desktop.

    - P1: Solicitud de identificación de conductor (M250)
    - P2: Alegaciones (M203)
    - P3: Recurso de reposición (recursTelematic)
    """

    protocol: str  # "P1" | "P2" | "P3"
    reposicion: BaseOnlineReposicionData | None = None
