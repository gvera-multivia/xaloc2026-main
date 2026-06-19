from __future__ import annotations

import os
import sys

sys.path.append(os.getcwd())

from core.repositories.resource_repository import ResourceRepository


def _repo() -> ResourceRepository:
    return ResourceRepository(conn_str="DRIVER=dummy;", logger=None)


def test_full_query_requires_fpresentacion_within_fourteen_days() -> None:
    repo = _repo()

    query, params = repo._build_query(
        site_id="servei_cat_trans",
        config={"query_organisme": "%SERVEI CATALA%", "filtro_texp": "2,3"},
    )

    assert "e.fpresentacion IS NOT NULL" in query
    assert "CAST(e.fpresentacion AS date) <= DATEADD(day, 14, CAST(GETDATE() AS date))" in query
    assert "LEFT JOIN expedientes e ON rs.idExp = e.idexpediente" in query
    assert params == ["%SERVEI CATALA%", 2, 3]


def test_light_query_requires_fpresentacion_within_fourteen_days() -> None:
    repo = _repo()

    query, params = repo._build_light_query(
        site_id="xaloc_girona",
        config={"query_organisme": "%XALOC%", "filtro_texp": "2"},
    )

    assert "LEFT JOIN expedientes e ON rs.idExp = e.idexpediente" in query
    assert "e.fpresentacion IS NOT NULL" in query
    assert "CAST(e.fpresentacion AS date) <= DATEADD(day, 14, CAST(GETDATE() AS date))" in query
    assert params == ["%XALOC%", 2]
