from __future__ import annotations

import logging
import os
import sys

sys.path.append(os.getcwd())

from dashboard.services import DashboardService


class _FakeAdminStore:
    def __init__(self, items: list[dict]) -> None:
        self.items = list(items)
        self.unblocked: list[tuple[str, int]] = []

    def list_blocked_resources(self, *, site_id: str | None = None) -> list[dict]:
        items = self.items
        if site_id:
            items = [item for item in items if item.get("site_id") == site_id]
        return [dict(item) for item in items]

    def unblock_resource(self, *, site_id: str, resource_id: int) -> bool:
        before = len(self.items)
        self.items = [
            item
            for item in self.items
            if not (item.get("site_id") == site_id and int(item.get("resource_id")) == int(resource_id))
        ]
        removed = len(self.items) != before
        if removed:
            self.unblocked.append((site_id, int(resource_id)))
        return removed


def _service(items: list[dict]) -> DashboardService:
    service = DashboardService.__new__(DashboardService)
    service.logger = logging.getLogger("test.dashboard.blacklist")
    service.sqlserver_conn_str = "DRIVER=stub"
    service.admin_store = _FakeAdminStore(items)
    service._get_resource_variant = lambda **kwargs: (None, None)  # type: ignore[method-assign]
    return service


def test_list_blacklist_prunes_only_completed_xvia_resources(monkeypatch) -> None:
    service = _service(
        [
            {"site_id": "madrid", "resource_id": 101, "reason": "old completed"},
            {"site_id": "madrid", "resource_id": 102, "reason": "still pending"},
        ]
    )
    monkeypatch.setattr(service, "_get_completed_xvia_resource_ids", lambda ids: {101})

    items = service.list_blacklist()

    assert [item["resource_id"] for item in items] == [102]
    assert service.admin_store.unblocked == [("madrid", 101)]


def test_list_blacklist_keeps_items_when_xvia_check_fails(monkeypatch) -> None:
    service = _service(
        [
            {"site_id": "madrid", "resource_id": 101, "reason": "old completed"},
            {"site_id": "madrid", "resource_id": 102, "reason": "still pending"},
        ]
    )

    def _raise(ids):
        raise RuntimeError("sqlserver unavailable")

    monkeypatch.setattr(service, "_get_completed_xvia_resource_ids", _raise)

    items = service.list_blacklist()

    assert [item["resource_id"] for item in items] == [101, 102]
    assert service.admin_store.unblocked == []
