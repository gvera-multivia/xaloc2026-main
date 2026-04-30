from __future__ import annotations

from dataclasses import dataclass

from sites.adapters.xaloc_girona import XalocAdapter


@dataclass
class _FakeResource:
    metadata: dict


class _FakeRepo:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int):
        return [_FakeResource(metadata=item) for item in self._items[:limit]]


def test_xaloc_fetch_candidates_keeps_estado_zero_with_historical_completed_date() -> None:
    adapter = XalocAdapter()
    repo = _FakeRepo(
        [
            {
                "idRecurso": 501,
                "idExp": 7001,
                "Expedient": "2026/12345",
                "Organisme": "XALOC DIPUTACIO DE GIRONA - LA BISBAL D´EMPORDÀ",
                "Estado": 0,
                "UsuarioAsignado": "",
                "FUsuarioCompletado": "2026-04-29 09:00:00",
                "adjuntos": [],
            }
        ]
    )

    items = adapter.fetch_candidates(
        config={"query_organisme": "%XALOC%", "filtro_texp": "2,3", "regex_expediente": "^.+$"},
        conn_str="",
        authenticated_user="robot",
        limit=10,
        resource_repo=repo,
    )

    assert len(items) == 1
    assert items[0]["idRecurso"] == 501
