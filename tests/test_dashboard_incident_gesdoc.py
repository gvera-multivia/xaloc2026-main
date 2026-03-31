from __future__ import annotations

import logging
import os
import sys
from types import SimpleNamespace

sys.path.append(os.getcwd())

import core.repositories.resource_repository as resource_repo
from dashboard.services import DashboardService


def _service() -> DashboardService:
    service = DashboardService.__new__(DashboardService)
    service.logger = logging.getLogger("test.dashboard.gesdoc")
    return service


def test_missing_authorization_detection_is_conservative() -> None:
    service = _service()

    assert service._looks_like_missing_authorization_incident(
        {
            "incident_type": "AUTHORIZATION_MISSING",
            "reason": "No se encontro autorizacion AUT en la carpeta del cliente",
        }
    )
    assert not service._looks_like_missing_authorization_incident(
        {
            "incident_type": "FOLDER_MISSING",
            "reason": "No se encontro la carpeta del cliente",
        }
    )


def test_enrich_incident_items_with_gesdoc_marks_purple_when_client_folder_exists(monkeypatch) -> None:
    service = _service()

    class _FakeRepo:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_resources_by_ids(self, *, site_id: str, resource_ids: list[int]):
            return [
                SimpleNamespace(
                    id=101,
                    metadata={
                        "numclient": 43880,
                        "cliente_tipo": 2,
                        "SujetoRecurso": "EMPRESA TEST",
                    },
                )
            ]

    monkeypatch.setattr(resource_repo, "ResourceRepository", _FakeRepo)
    monkeypatch.setattr(
        service,
        "_resolve_client_folder_context",
        lambda **kwargs: {"exists": True, "path": r"\\SERVER-DOC\clientes\E\EMPRESA TEST"},
    )

    items = [
        {
            "site_id": "atc",
            "resource_id": 101,
            "incident_type": "AUTHORIZATION_MISSING",
            "reason": "No se encontro autorizacion AUT en la carpeta del cliente",
            "payload": {},
        }
    ]

    service._enrich_incident_items_with_gesdoc(items=items, conn_str="DRIVER=stub")

    item = items[0]
    assert item["numclient"] == 43880
    assert item["cliente_tipo"] == 2
    assert item["gesdoc_missing_auth_candidate"] is True
    assert item["client_folder_exists"] is True
    assert item["gesdoc_ui_variant"] == "purple"
