from datetime import date

from core.pg_runtime_store import PgRuntimeStore


class FakeCursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.calls.append((str(query), params))

    def fetchone(self):
        return next(self.rows)


class FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1


def test_reserve_next_job_is_atomic_parameterized_and_pause_aware():
    connection = FakeConnection(
        [
            (7, "job-7", "madrid", 700, {"fecpres": "2026-09-22", "max_attempts": 3}, date(2026, 9, 22)),
            (1,),
        ]
    )
    store = object.__new__(PgRuntimeStore)
    store._conn = lambda: connection

    result = store.reserve_next_job(
        business_today=date(2026, 9, 22),
        worker_id="worker-7",
    )

    reservation_sql, reservation_params = connection.cursor_instance.calls[0]
    assert "FOR UPDATE SKIP LOCKED" in reservation_sql
    assert "site_processing_pauses" in reservation_sql
    assert "resource_processing_pauses" in reservation_sql
    assert "oc.active = FALSE" in reservation_sql
    assert "j.submission_date <= %s" in reservation_sql
    assert reservation_params == (date(2026, 9, 22),) * 3
    assert "2026-09-22" not in reservation_sql
    assert connection.commits == 1
    assert result == {
        "job_id": "job-7",
        "site_id": "madrid",
        "resource_id": 700,
        "payload": {"fecpres": "2026-09-22", "max_attempts": 3},
        "submission_date": "2026-09-22",
        "attempt": 1,
    }

    attempt_sql, attempt_params = connection.cursor_instance.calls[2]
    assert "ON CONFLICT (job_id, attempt_no)" in attempt_sql
    assert attempt_params == (7, 1, "worker-7")


def test_reserve_next_job_returns_none_when_no_eligible_job():
    connection = FakeConnection([None])
    store = object.__new__(PgRuntimeStore)
    store._conn = lambda: connection

    result = store.reserve_next_job(
        business_today=date(2026, 9, 22),
        worker_id="worker-empty",
    )

    assert result is None
    assert connection.commits == 1
