from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceDomain:
    id: int
    site_id: str
    expediente: str
    estado: int
    usuario_asignado: str
    texp: int
    fase: str
    direccion_raw: str
    numero: str
    piso: str
    puerta: str
    cp: str
    poblacion: str
    provincia: str
    nif: str
    cif: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, *, site_id: str, row: dict[str, Any]) -> "ResourceDomain":
        def _str(key: str) -> str:
            value = row.get(key)
            return str(value).strip() if value is not None else ""

        def _int(key: str) -> int:
            value = row.get(key)
            try:
                return int(value or 0)
            except Exception:
                return 0

        return cls(
            id=_int("idRecurso"),
            site_id=str(site_id).strip(),
            expediente=_str("Expedient"),
            estado=_int("Estado"),
            usuario_asignado=_str("UsuarioAsignado"),
            texp=_int("TExp"),
            fase=_str("FaseProcedimiento"),
            direccion_raw=_str("cliente_domicilio") or _str("conduc_adr"),
            numero=_str("cliente_numero"),
            piso=_str("cliente_planta"),
            puerta=_str("cliente_puerta"),
            cp=_str("cliente_cp") or _str("conduc_codpost"),
            poblacion=_str("cliente_municipio") or _str("conduc_pobl"),
            provincia=_str("cliente_provincia") or _str("conduc_prov"),
            nif=_str("cliente_nif"),
            cif=_str("cif") or _str("cliente_nif_empresa"),
            metadata=dict(row or {}),
        )
