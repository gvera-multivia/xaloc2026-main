"""
Modelos de datos para el sitio Selva.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class DatosSolicitud:
    # Contact Info
    contact_phone: str
    contact_mobile: str
    contact_fax: str
    contact_other_phone: str

    # Request Info
    municipality: str  # Value or text? Usually safer to use value if known, or text if select_option works well with label
    theme: str # Value
    expose_text: str
    request_text: str

    # Attachments
    attachments: List[Path] = field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        return bool(self.attachments)
