from __future__ import annotations

from core.consultor.parity import compare_resources_for_parity
from core.domain import ResourceDomain


def _make_resource(site_id: str, row: dict) -> ResourceDomain:
    return ResourceDomain.from_row(site_id=site_id, row=row)


def test_compare_resources_for_parity_ok() -> None:
    row = {
        "idRecurso": 10,
        "idExp": 20,
        "Expedient": "EXP-1",
        "Organisme": "ORG",
        "TExp": 2,
        "Estado": 0,
        "numclient": 100,
        "SujetoRecurso": "A",
        "FaseProcedimiento": "fase",
        "UsuarioAsignado": "",
    }
    legacy = [_make_resource("madrid", row)]
    consultor = [_make_resource("madrid", dict(row))]
    parity = compare_resources_for_parity(legacy_resources=legacy, consultor_resources=consultor)
    assert parity["ok"] is True
    assert parity["mismatches"] == []
    assert parity["only_legacy"] == []
    assert parity["only_consultor"] == []


def test_compare_resources_for_parity_detects_mismatch() -> None:
    legacy_row = {
        "idRecurso": 10,
        "idExp": 20,
        "Expedient": "EXP-1",
        "Organisme": "ORG",
        "TExp": 2,
        "Estado": 0,
        "numclient": 100,
        "SujetoRecurso": "A",
        "FaseProcedimiento": "fase-a",
        "UsuarioAsignado": "",
    }
    consultor_row = dict(legacy_row)
    consultor_row["FaseProcedimiento"] = "fase-b"

    legacy = [_make_resource("madrid", legacy_row)]
    consultor = [_make_resource("madrid", consultor_row)]
    parity = compare_resources_for_parity(legacy_resources=legacy, consultor_resources=consultor)

    assert parity["ok"] is False
    assert len(parity["mismatches"]) == 1
    assert parity["mismatches"][0]["idRecurso"] == 10
    assert parity["mismatches"][0]["diffs"][0]["field"] == "FaseProcedimiento"

