import os
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.append(os.getcwd())

from core.sqlite_db import SQLiteDatabase
from dashboard.services import DashboardService


def _db_path() -> Path:
    root = Path("tmp") / "pytest-worker-runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"worker-runtime-{uuid.uuid4().hex}.db"


def _set_processing(db_path: Path, *, task_id: int, started_at: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            UPDATE tramite_queue
            SET status = 'processing',
                processed_at = ?
            WHERE id = ?
            """,
            (started_at, int(task_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _task_status(db_path: Path, *, task_id: int) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status FROM tramite_queue WHERE id = ?", (int(task_id),)).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        conn.close()


def test_reconcile_keeps_processing_when_worker_uuid_is_alive() -> None:
    path = _db_path()
    db = SQLiteDatabase(db_path=str(path))
    job_id = "job-alive-1"
    worker_id = "worker-alive-1"
    task_id = db.insert_task("madrid", "P1", {"idRecurso": 201, "job_id": job_id})
    _set_processing(path, task_id=task_id, started_at=datetime.now().isoformat())
    db.upsert_job_run(
        job_id=job_id,
        site_id="madrid",
        resource_id=201,
        protocol="P1",
        payload_snapshot={"idRecurso": 201, "job_id": job_id},
        state="processing",
    )
    db.update_job_run_state(job_id, "processing", worker_id=worker_id)
    db.upsert_worker_runtime(worker_id=worker_id, run_id="r1", pid=123, status="online", current_job_id=job_id)

    result = db.reconcile_processing_with_worker_runtime(heartbeat_timeout_seconds=90, limit=50)

    assert result["recovered"] == 0
    assert _task_status(path, task_id=task_id) == "processing"


def test_reconcile_recovers_processing_when_worker_uuid_is_not_alive() -> None:
    path = _db_path()
    db = SQLiteDatabase(db_path=str(path))
    job_id = "job-dead-1"
    worker_id = "worker-dead-1"
    task_id = db.insert_task("madrid", "P1", {"idRecurso": 202, "job_id": job_id})
    _set_processing(path, task_id=task_id, started_at=datetime.now().isoformat())
    db.upsert_job_run(
        job_id=job_id,
        site_id="madrid",
        resource_id=202,
        protocol="P1",
        payload_snapshot={"idRecurso": 202, "job_id": job_id},
        state="processing",
    )
    db.update_job_run_state(job_id, "processing", worker_id=worker_id)
    db.upsert_worker_runtime(worker_id=worker_id, run_id="r2", pid=124, status="online", current_job_id=job_id)
    db.mark_worker_runtime_offline(worker_id=worker_id)

    result = db.reconcile_processing_with_worker_runtime(heartbeat_timeout_seconds=90, limit=50)

    assert result["recovered"] == 1
    assert result["items"][0]["job_id"] == job_id
    assert _task_status(path, task_id=task_id) == "pending"


def test_dashboard_remove_queue_item_uses_uuid_runtime_recovery() -> None:
    path = _db_path()
    db = SQLiteDatabase(db_path=str(path))
    job_id = "job-dead-2"
    worker_id = "worker-dead-2"
    task_id = db.insert_task("madrid", "P1", {"idRecurso": 203, "job_id": job_id})
    _set_processing(path, task_id=task_id, started_at=datetime.now().isoformat())
    db.upsert_job_run(
        job_id=job_id,
        site_id="madrid",
        resource_id=203,
        protocol="P1",
        payload_snapshot={"idRecurso": 203, "job_id": job_id},
        state="processing",
    )
    db.update_job_run_state(job_id, "processing", worker_id=worker_id)
    db.upsert_worker_runtime(worker_id=worker_id, run_id="r3", pid=125, status="online", current_job_id=job_id)
    db.mark_worker_runtime_offline(worker_id=worker_id)

    original_assigned_user = os.environ.get("DASHBOARD_ASSIGNED_USER")
    os.environ["DASHBOARD_ASSIGNED_USER"] = "test-user"
    try:
        service = DashboardService(sqlite_db_path=str(path), queue_backend="sqlite")
    finally:
        if original_assigned_user is None:
            os.environ.pop("DASHBOARD_ASSIGNED_USER", None)
        else:
            os.environ["DASHBOARD_ASSIGNED_USER"] = original_assigned_user

    result = service.remove_queue_item(site_id="madrid", resource_id=203)
    assert result["removed"] is True
    assert result["recovered_processing"] is True
