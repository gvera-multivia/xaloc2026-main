import os
import sys
from datetime import date
import pytest

sys.path.append(os.getcwd())

pytest.importorskip("psycopg")

from core.pg_control_plane_store import PgControlPlaneStore


def test_build_dedup_key() -> None:
    key = PgControlPlaneStore.build_dedup_key(
        organism_id="madrid",
        external_resource_id="123",
        job_type="P2",
    )
    assert key == "madrid:123:P2"


def test_build_batch_group_key() -> None:
    key = PgControlPlaneStore.build_batch_group_key(
        organism_id="base_online",
        job_type="P1",
        cert_profile="default",
        priority=50,
    )
    assert key == "base_online:P1:default:50"


class _Cursor:
    def __init__(self):
        self.calls = []
        self.rows = iter([None, None])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.calls.append((str(query), params))

    def fetchone(self):
        return next(self.rows)


class _Connection:
    def __init__(self):
        self.cursor_instance = _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass


def test_upsert_job_persists_normalized_submission_date() -> None:
    connection = _Connection()
    store = object.__new__(PgControlPlaneStore)
    store.dsn = "postgresql://unused"
    store._conn = lambda: connection

    result = store.upsert_job_from_draft(
        draft_id="draft-1",
        dedup_key="madrid:none:P1",
        priority=100,
        payload={"organism_id": "madrid", "fecpres": "22/09/2026"},
    )

    insert_sql, insert_params = connection.cursor_instance.calls[2]
    assert "submission_date" in insert_sql
    assert insert_params[3] == date(2026, 9, 22)
    assert result["dispatch"] is True


def test_control_plane_ensures_priority_schema_before_writes() -> None:
    connection = _Connection()
    store = object.__new__(PgControlPlaneStore)
    store._conn = lambda: connection

    store.ensure_priority_queue_schema()

    statements = [sql for sql, _ in connection.cursor_instance.calls]
    assert statements[0] == "SELECT pg_advisory_xact_lock(%s)"
    assert "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS submission_date DATE" in statements[1]
    assert "pg_input_is_valid" in statements[2]
    assert "ix_jobs_status_submission_priority" in statements[3]
