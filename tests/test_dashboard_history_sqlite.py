import os
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.append(os.getcwd())

from dashboard import DashboardService


def _db_path() -> Path:
    root = Path("tmp") / "pytest-dashboard"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"history-{uuid.uuid4().hex}.db"


def _prepare_history_db(path: Path) -> None:
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
        conn.execute(
            """
            INSERT INTO realtime_task_results
            (dedupe_key, site_id, resource_id, job_id, protocol, status, day, started_at, ended_at, payload, result, error)
            VALUES
            ('task:madrid:success:rid:1', 'madrid', 1, 'j1', 'p1', 'success', '2026-02-10', '2026-02-10T10:00:00', '2026-02-10T10:01:00', '{"p":1}', '{"ok":true}', NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO realtime_incidents
            (dedupe_key, site_id, resource_id, expediente, incident_type, reason, day, started_at, ended_at, payload)
            VALUES
            ('incident:madrid:X:rid:2', 'madrid', 2, '2026/2', 'X', 'bad', '2026-02-10', '2026-02-10T11:00:00', '2026-02-10T11:00:01', '{"q":2}')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_dashboard_service_reads_history_from_sqlite_when_no_pg_dsn() -> None:
    path = _db_path()
    _prepare_history_db(path)
    service = DashboardService(sqlite_db_path=str(path), pg_dsn=None)

    successes = service.list_history_successes(day="2026-02-10", page=1, page_size=10)
    incidents = service.list_history_incidents(day="2026-02-10", page=1, page_size=10)

    assert successes["total"] == 1
    assert incidents["total"] == 1
    assert successes["items"][0]["result"]["ok"] is True
    assert incidents["items"][0]["payload"]["q"] == 2

