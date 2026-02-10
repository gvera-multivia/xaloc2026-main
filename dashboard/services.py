from __future__ import annotations

import logging
import os
from typing import Any

from .repositories import PostgresHistoryRepository, SqliteQueueRepository, utc_today_iso


class DashboardService:
    def __init__(
        self,
        *,
        sqlite_db_path: str | None = None,
        queue_backend: str | None = None,
        pg_dsn: str | None = None,
    ):
        self.logger = logging.getLogger("dashboard.service")
        self.history_repo = PostgresHistoryRepository(
            pg_dsn=pg_dsn or os.getenv("REPORT_PG_DSN"),
            logger=self.logger,
        )
        self.queue_repo = SqliteQueueRepository(
            sqlite_db_path=sqlite_db_path or os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db"),
            queue_backend=queue_backend or os.getenv("QUEUE_BACKEND", "sqlite"),
            logger=self.logger,
        )

    @staticmethod
    def _paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return {"items": items[start:end], "page": page, "page_size": page_size, "total": len(items)}

    def list_history_days(self, *, source: str, page: int, page_size: int) -> dict[str, Any]:
        days = self.history_repo.list_days(source=source)
        return self._paginate(days, page, page_size)

    def list_history_incidents(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.history_repo.list_incidents(day=day_value, page=page, page_size=page_size)

    def list_history_successes(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.history_repo.list_successes(day=day_value, page=page, page_size=page_size)

    def list_queue_days(self, *, page: int, page_size: int) -> dict[str, Any]:
        days = self.queue_repo.list_days()
        return self._paginate(days, page, page_size)

    def list_queue_current(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.list_current(day=day_value, page=page, page_size=page_size)

    def get_queue_live(self, *, day: str | None) -> Optional[dict[str, Any]]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.get_live(day=day_value)
