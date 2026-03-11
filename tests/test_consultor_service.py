from __future__ import annotations

from core.consultor.service import ConsultorService
from core.domain import ResourceDomain


class _FakeRepository:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int) -> list[ResourceDomain]:
        out: list[ResourceDomain] = []
        for row in self.rows[: max(0, int(limit))]:
            out.append(ResourceDomain.from_row(site_id=site_id, row=row))
        return out


def test_consultor_service_keeps_legacy_shape_and_adds_canonical() -> None:
    row = {
        "idRecurso": 123,
        "idExp": 999,
        "Expedient": "2026/0001",
        "Organisme": "AYUNTAMIENTO X",
        "TExp": 2,
        "Estado": 0,
        "numclient": 10,
        "SujetoRecurso": "PERSONA A",
        "FaseProcedimiento": "denuncia",
        "UsuarioAsignado": "",
        "cliente_nif": "12345678A",
        "cliente_nombre": "NOMBRE",
        "cliente_apellido1": "AP1",
        "cliente_apellido2": "AP2",
        "cliente_domicilio": "CALLE 1",
        "cliente_numero": "1",
        "cliente_cp": "08001",
        "cliente_municipio": "BARCELONA",
        "cliente_provincia": "BARCELONA",
        "adjuntos": [{"id": 1, "filename": "doc.pdf"}],
    }
    fake = _FakeRepository([row])
    svc = ConsultorService(conn_str="unused", repository=fake)

    resources = svc.get_pending_resources(site_id="madrid", config={}, limit=5)
    assert len(resources) == 1

    meta = resources[0].metadata
    assert meta["idRecurso"] == 123
    assert "__canonical_v1" in meta
    assert "__legacy_aliases" not in meta
    assert meta["__canonical_v1"]["resource"]["id"] == 123
    assert meta["__canonical_v1"]["client"]["name"]["first"] == "NOMBRE"


def test_consultor_service_returns_empty_when_limit_zero() -> None:
    fake = _FakeRepository([{"idRecurso": 1, "Expedient": "X"}])
    svc = ConsultorService(conn_str="unused", repository=fake)
    resources = svc.get_pending_resources(site_id="madrid", config={}, limit=0)
    assert resources == []
