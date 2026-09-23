from __future__ import annotations

import os
import sys

sys.path.append(os.getcwd())

from core.repositories.resource_repository import ResourceRepository


def _repo() -> ResourceRepository:
    return ResourceRepository(conn_str="DRIVER=dummy;", logger=None)


def test_full_query_admits_missing_date_and_limits_future_to_fourteen_days() -> None:
    repo = _repo()

    query, params = repo._build_query(
        site_id="servei_cat_trans",
        config={"query_organisme": "%SERVEI CATALA%", "filtro_texp": "2,3"},
    )

    assert "e.fpresentacion IS NULL" in query
    assert "OR CAST(e.fpresentacion AS date) <= DATEADD(day, 14, CAST(GETDATE() AS date))" in query
    assert "LEFT JOIN expedientes e ON rs.idExp = e.idexpediente" in query
    assert params == ["%SERVEI CATALA%", 2, 3]


def test_light_query_admits_missing_date_and_limits_future_to_fourteen_days() -> None:
    repo = _repo()

    query, params = repo._build_light_query(
        site_id="xaloc_girona",
        config={"query_organisme": "%XALOC%", "filtro_texp": "2"},
    )

    assert "LEFT JOIN expedientes e ON rs.idExp = e.idexpediente" in query
    assert "e.fpresentacion IS NULL" in query
    assert "OR CAST(e.fpresentacion AS date) <= DATEADD(day, 14, CAST(GETDATE() AS date))" in query
    assert params == ["%XALOC%", 2]


def test_queries_order_each_site_today_then_recent_past_then_future_then_missing() -> None:
    repo = _repo()

    full_query, _ = repo._build_query(
        site_id="madrid",
        config={"query_organisme": "%MADRID%", "filtro_texp": "2"},
    )
    light_query, _ = repo._build_light_query(
        site_id="xaloc_girona",
        config={"query_organisme": "%XALOC%", "filtro_texp": "2"},
    )

    for query in (full_query, light_query):
        assert "WHEN e.fpresentacion IS NULL THEN 3" in query
        assert "WHEN CAST(e.fpresentacion AS date) <= CAST(GETDATE() AS date) THEN 0" in query
        assert "DATEDIFF(day, CAST(e.fpresentacion AS date), CAST(GETDATE() AS date))" in query
        assert "DATEDIFF(day, CAST(GETDATE() AS date), CAST(e.fpresentacion AS date))" in query
        assert query.index("WHEN e.fpresentacion IS NULL THEN 3") < query.rindex("rs.idRecurso ASC")
