from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core.queue_gateway import QueueJob
from core.worker.completion_guard import SQLServerCompletionGuard
from core.worker.consumer import _ack_if_already_completed


class _Cursor:
    def __init__(self, *, row=None, error: Exception | None = None) -> None:
        self.row = row
        self.error = error
        self.execute_calls: list[tuple[str, tuple[int, ...]]] = []
        self.closed = False

    def execute(self, query: str, params: tuple[int, ...]) -> None:
        self.execute_calls.append((query, params))
        if self.error is not None:
            raise self.error

    def fetchone(self):
        return self.row

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, cursors: list[_Cursor]) -> None:
        self.cursors = cursors
        self.closed = False

    def cursor(self) -> _Cursor:
        return self.cursors.pop(0)

    def close(self) -> None:
        self.closed = True


def test_completion_guard_uses_parameterized_query_and_reuses_connection() -> None:
    first_cursor = _Cursor(row=(1, None))
    second_cursor = _Cursor(row=(2, None))
    connection = _Connection([first_cursor, second_cursor])
    connect_calls = []

    def _connect(conn_str: str, *, autocommit: bool):
        connect_calls.append((conn_str, autocommit))
        return connection

    guard = SQLServerCompletionGuard(conn_str="stub", connect=_connect)

    pending = guard.check(101)
    completed = guard.check(102)

    assert pending is not None and pending.completed is False
    assert completed is not None and completed.completed is True
    assert connect_calls == [("stub", True)]
    assert first_cursor.execute_calls[0][1] == (101,)
    assert second_cursor.execute_calls[0][1] == (102,)
    assert "WHERE idRecurso = ?" in first_cursor.execute_calls[0][0]


def test_completion_guard_does_not_skip_reopened_resource_with_historical_date() -> None:
    cursor = _Cursor(row=(0, "2026-09-21 10:00:00"))
    guard = SQLServerCompletionGuard(
        conn_str="stub",
        connect=lambda *_args, **_kwargs: _Connection([cursor]),
    )

    status = guard.check(201)

    assert status is not None
    assert status.completed is False
    assert status.estado == 0


def test_completion_guard_fails_open_and_reconnects_after_sql_error() -> None:
    broken_connection = _Connection([_Cursor(error=RuntimeError("sql unavailable"))])
    healthy_connection = _Connection([_Cursor(row=(1, None))])
    connections = [broken_connection, healthy_connection]

    guard = SQLServerCompletionGuard(
        conn_str="stub",
        connect=lambda *_args, **_kwargs: connections.pop(0),
    )

    assert guard.check(301) is None
    assert broken_connection.closed is True
    recovered = guard.check(301)
    assert recovered is not None and recovered.completed is False


class _CompletionGuard:
    def __init__(self, status) -> None:
        self.status = status

    def check(self, resource_id: int):
        assert resource_id == 401
        return self.status


class _QueueGateway:
    def __init__(self) -> None:
        self.acks = []

    async def ack(self, job, *, result=None, screenshot=None) -> None:
        self.acks.append((job, result, screenshot))


class _RealtimeStore:
    def __init__(self) -> None:
        self.successes = []

    def record_task_success(self, **kwargs) -> None:
        self.successes.append(kwargs)


def test_completed_job_is_acked_without_execution() -> None:
    from core.worker.completion_guard import ResourceCompletionStatus

    job = QueueJob(
        job_id="job-401",
        site_id="madrid",
        protocol="P1",
        payload={"idRecurso": 401},
        resource_id=401,
    )
    queue_gateway = _QueueGateway()
    realtime_store = _RealtimeStore()
    status = ResourceCompletionStatus(
        resource_id=401,
        found=True,
        completed=True,
        estado=2,
        completed_at="2026-09-21 11:00:00",
    )

    skipped = asyncio.run(
        _ack_if_already_completed(
            job=job,
            completion_guard=_CompletionGuard(status),
            queue_gateway=queue_gateway,
            realtime_store=realtime_store,
            started_at=datetime.now(timezone.utc),
        )
    )

    assert skipped is True
    assert len(queue_gateway.acks) == 1
    result = queue_gateway.acks[0][1]
    assert result["reason"] == "resource_already_completed_in_sqlserver"
    assert result["sqlserver_estado"] == 2
    assert len(realtime_store.successes) == 1


def test_sql_check_failure_does_not_ack_job() -> None:
    job = QueueJob(
        job_id="job-402",
        site_id="madrid",
        protocol="P1",
        payload={"idRecurso": 401},
        resource_id=401,
    )
    queue_gateway = _QueueGateway()

    skipped = asyncio.run(
        _ack_if_already_completed(
            job=job,
            completion_guard=_CompletionGuard(None),
            queue_gateway=queue_gateway,
            realtime_store=_RealtimeStore(),
            started_at=datetime.now(timezone.utc),
        )
    )

    assert skipped is False
    assert queue_gateway.acks == []
