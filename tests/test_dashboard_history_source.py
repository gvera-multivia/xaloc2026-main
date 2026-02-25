import os
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.append(os.getcwd())

from dashboard.services import DashboardService
from dashboard.repositories import SqliteHistoryRepository


def _db_path() -> Path:
    root = Path("tmp") / "pytest-dashboard"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"history-source-{uuid.uuid4().hex}.db"


def _prepare_min_history_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE realtime_task_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT UNIQUE,
                site_id TEXT,
                resource_id INTEGER,
                job_id TEXT,
                protocol TEXT,
                status TEXT,
                day TEXT,
                started_at TEXT,
                ended_at TEXT,
                payload TEXT,
                result TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE realtime_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT UNIQUE,
                site_id TEXT,
                resource_id INTEGER,
                expediente TEXT,
                incident_type TEXT,
                reason TEXT,
                day TEXT,
                started_at TEXT,
                ended_at TEXT,
                payload TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_dashboard_history_defaults_to_sqlite_even_with_sqlserver_env() -> None:
    db_path = _db_path()
    _prepare_min_history_db(db_path)

    prev_source = os.environ.get("DASHBOARD_HISTORY_SOURCE")
    prev_assigned = os.environ.get("DASHBOARD_ASSIGNED_USER")
    try:
        os.environ.pop("DASHBOARD_HISTORY_SOURCE", None)
        os.environ["DASHBOARD_ASSIGNED_USER"] = "test-user"
        service = DashboardService(sqlite_db_path=str(db_path), pg_dsn=None)
    finally:
        if prev_source is None:
            os.environ.pop("DASHBOARD_HISTORY_SOURCE", None)
        else:
            os.environ["DASHBOARD_HISTORY_SOURCE"] = prev_source

        if prev_assigned is None:
            os.environ.pop("DASHBOARD_ASSIGNED_USER", None)
        else:
            os.environ["DASHBOARD_ASSIGNED_USER"] = prev_assigned

    assert isinstance(service.success_history_repo, SqliteHistoryRepository)

