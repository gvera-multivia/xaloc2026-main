"""
Modelos de datos para automatizar el flujo de Ayunta Palma.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class AyuntaPalmaContacto:
    correo: str
    telefono: str


@dataclass(frozen=True)
class AyuntaPalmaPersonaFisica:
    tipo_documento: str  # F | X | P
    documento: str
    nombre: str
    apellido1: str
    apellido2: str | None = None
    pais: str | None = None


@dataclass(frozen=True)
class AyuntaPalmaPersonaJuridica:
    nif: str
    razon_social: str


@dataclass(frozen=True)
class AyuntaPalmaAlegaciones:
    expediente: str
    matricula: str
    expone: str
    solicita: str


@dataclass(frozen=True)
class AyuntaPalmaTarget:
    tipo_persona: str  # "PersonaFisica" | "PersonaJuridica"
    contacto: AyuntaPalmaContacto
    fisica: AyuntaPalmaPersonaFisica | None = None
    juridica: AyuntaPalmaPersonaJuridica | None = None
    alegaciones: AyuntaPalmaAlegaciones | None = None
    archivos: List[Path] | None = None
