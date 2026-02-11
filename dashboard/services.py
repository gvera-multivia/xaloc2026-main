from __future__ import annotations

import logging
import os
from typing import Any

from core.sqlserver_utils import build_sqlserver_connection_string
from .repositories import (
    PostgresHistoryRepository,
    SQLServerHistoryRepository,
    SqliteHistoryRepository,
    SqliteQueueRepository,
    utc_today_iso,
)


class DashboardService:
    def __init__(
        self,
        *,
        sqlite_db_path: str | None = None,
        queue_backend: str | None = None,
        pg_dsn: str | None = None,
    ):
        self.logger = logging.getLogger("dashboard.service")
        sqlite_path = sqlite_db_path or os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db")
        sqlserver_assigned_user = (
            os.getenv("DASHBOARD_ASSIGNED_USER")
            or os.getenv("XVIA_ASSIGNED_USER")
            or os.getenv("XVIA_EMAIL")
            or ""
        ).strip()

        sqlserver_conn_str = ""
        try:
            sqlserver_conn_str = build_sqlserver_connection_string()
        except Exception:
            sqlserver_conn_str = ""

        pg_dsn_value = (pg_dsn or os.getenv("REPORT_PG_DSN") or "").strip()
        lowered = pg_dsn_value.lower()
        has_valid_pg_dsn = bool(
            pg_dsn_value
            and lowered not in {"0", "1", "true", "false", "yes", "no", "on", "off", "enabled", "disabled"}
            and ("://" in pg_dsn_value or "=" in pg_dsn_value)
        )
        has_valid_sqlserver = bool(sqlserver_conn_str)
        if has_valid_sqlserver:
            self.success_history_repo = SQLServerHistoryRepository(
                conn_str=sqlserver_conn_str,
                assigned_user=sqlserver_assigned_user,
                logger=self.logger,
            )
        elif has_valid_pg_dsn:
            self.success_history_repo = PostgresHistoryRepository(
                pg_dsn=pg_dsn_value,
                logger=self.logger,
            )
        else:
            self.success_history_repo = SqliteHistoryRepository(
                sqlite_db_path=sqlite_path,
                logger=self.logger,
            )
        self.incidents_history_repo = SqliteHistoryRepository(
            sqlite_db_path=sqlite_path,
            logger=self.logger,
        )
        self.queue_repo = SqliteQueueRepository(
            sqlite_db_path=sqlite_path,
            queue_backend=queue_backend or os.getenv("QUEUE_BACKEND", "sqlite"),
            logger=self.logger,
        )

    @staticmethod
    def _paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return {"items": items[start:end], "page": page, "page_size": page_size, "total": len(items)}

    def list_history_days(self, *, source: str, page: int, page_size: int) -> dict[str, Any]:
        source_norm = (source or "all").strip().lower()
        if source_norm == "incidents":
            days = self.incidents_history_repo.list_days(source="incidents")
        elif source_norm == "success":
            days = self.success_history_repo.list_days(source="success")
        else:
            days = sorted(
                set(self.success_history_repo.list_days(source="success"))
                | set(self.incidents_history_repo.list_days(source="incidents")),
                reverse=True,
            )
        return self._paginate(days, page, page_size)

    def list_history_incidents(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.incidents_history_repo.list_incidents(day=day_value, page=page, page_size=page_size)

    def list_history_successes(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.success_history_repo.list_successes(day=day_value, page=page, page_size=page_size)

    def list_queue_days(self, *, page: int, page_size: int) -> dict[str, Any]:
        days = self.queue_repo.list_days()
        return self._paginate(days, page, page_size)

    def list_queue_current(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.list_current(day=day_value, page=page, page_size=page_size)

    def get_queue_live(self, *, day: str | None) -> Optional[dict[str, Any]]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.get_live(day=day_value)
