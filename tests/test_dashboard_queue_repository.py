import os
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.append(os.getcwd())

from dashboard.repositories import SqliteQueueRepository


def _build_sqlite_queue_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE tramite_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT,
                resource_id INTEGER,
                protocol TEXT,
                status TEXT,
                created_at TEXT,
                processed_at TEXT,
                payload TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tramite_queue (site_id, resource_id, protocol, status, created_at, processed_at, payload)
            VALUES ('madrid', 101, 'P-1', 'pending', '2026-02-10T10:00:00', NULL, '{"a":1}')
            """
        )
        conn.execute(
            """
            INSERT INTO tramite_queue (site_id, resource_id, protocol, status, created_at, processed_at, payload)
            VALUES ('madrid', 102, 'P-2', 'processing', '2026-02-10T11:00:00', NULL, '{"b":2}')
            """
        )
        conn.commit()
    finally:
        conn.close()


def _workspace_db_path() -> Path:
    root = Path("tmp") / "pytest-dashboard"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"queue-{uuid.uuid4().hex}.db"


def test_sqlite_queue_repository_get_live_returns_processing_item() -> None:
    db_path = _workspace_db_path()
    _build_sqlite_queue_db(db_path)
    repo = SqliteQueueRepository(sqlite_db_path=str(db_path), queue_backend="sqlite")

    item = repo.get_live(day="2026-02-10")

    assert item is not None
    assert item["state"] == "processing"
    assert item["resource_id"] == 102
    assert item["day"] == "2026-02-10"


def test_sqlite_queue_repository_list_current_includes_pending_and_processing() -> None:
    db_path = _workspace_db_path()
    _build_sqlite_queue_db(db_path)
    repo = SqliteQueueRepository(sqlite_db_path=str(db_path), queue_backend="sqlite")

    result = repo.list_current(day="2026-02-10", page=1, page_size=20)

    assert result["total"] == 2
    assert len(result["items"]) == 2
    states = {row["state"] for row in result["items"]}
    assert states == {"pending", "processing"}
