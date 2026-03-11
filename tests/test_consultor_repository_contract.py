from __future__ import annotations

import pytest

from core.repositories.resource_repository import ResourceRepository


def test_build_query_uses_canonical_superset_for_all_supported_sites() -> None:
    repo = ResourceRepository(conn_str="")
    for site_id in sorted(ResourceRepository.SUPPORTED_SITES):
        query, params = repo._build_query(
            site_id=site_id,
            config={
                "query_organisme": "%TEST_A%|%TEST_B%",
                "filtro_texp": "2,3",
            },
        )
        assert "FROM Recursos.RecursosExp rs" in query
        assert "LEFT JOIN clientes c" in query
        assert "LEFT JOIN expedientes e" in query
        assert "LEFT JOIN DadesIdentif di" in query
        assert "LEFT JOIN attachments_resource_documents att" in query
        assert params == ["%TEST_A%", "%TEST_B%", 2, 3]


def test_build_query_unknown_site_raises() -> None:
    repo = ResourceRepository(conn_str="")
    with pytest.raises(ValueError):
        repo._build_query(site_id="unknown_site", config={})
