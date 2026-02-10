from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from core.sqlite_db import SQLiteDatabase


def _make_db_path() -> Path:
    root = Path("tmp") / "pytest_local"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"sqlite_{uuid4().hex}.db"


def test_tramite_queue_dedupe_by_site_resource() -> None:
    db_path = _make_db_path()
    db = SQLiteDatabase(str(db_path))

    payload = {"idRecurso": 123, "expediente": "X"}
    task1 = db.insert_task("madrid", None, payload)
    task2 = db.insert_task("madrid", None, payload)

    assert task1 > 0
    assert task2 == task1
    db_path.unlink(missing_ok=True)


def test_tramite_queue_allows_reenqueue_after_failed() -> None:
    db_path = _make_db_path()
    db = SQLiteDatabase(str(db_path))

    payload = {"idRecurso": 321, "expediente": "X"}
    task1 = db.insert_task("madrid", None, payload)

    conn = db.get_connection()
    try:
        conn.execute("UPDATE tramite_queue SET status = 'failed' WHERE id = ?", (task1,))
        conn.commit()
    finally:
        conn.close()

    task2 = db.insert_task("madrid", None, payload)

    assert task2 != task1
    assert task2 > task1
    db_path.unlink(missing_ok=True)


def test_pending_authorization_dedupe_by_site_resource() -> None:
    db_path = _make_db_path()
    db = SQLiteDatabase(str(db_path))

    payload = {"idRecurso": 999, "expediente": "X"}
    p1 = db.insert_pending_authorization("madrid", payload, authorization_type="gesdoc", reason="x")
    p2 = db.insert_pending_authorization("madrid", payload, authorization_type="gesdoc", reason="x")

    assert p1 > 0
    assert p2 == p1
    db_path.unlink(missing_ok=True)


def test_lock_site_by_priority() -> None:
    db_path = _make_db_path()
    db = SQLiteDatabase(str(db_path))

    db.insert_task("xaloc_girona", None, {"idRecurso": 1})
    db.insert_task("madrid", None, {"idRecurso": 2})

    locked = db.get_locked_site_by_priority({"madrid": 0, "base_online": 1, "xaloc_girona": 2})
    assert locked == "madrid"
    db_path.unlink(missing_ok=True)
