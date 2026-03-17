import os
import sys

sys.path.append(os.getcwd())

from dashboard.repositories import SQLServerHistoryRepository


class _RaisingPyodbc:
    @staticmethod
    def connect(*args, **kwargs):
        raise RuntimeError("sqlserver down")


def test_sqlserver_history_list_days_handles_connection_error(monkeypatch) -> None:
    monkeypatch.setattr("dashboard.repositories.pyodbc", _RaisingPyodbc)
    repo = SQLServerHistoryRepository(conn_str="Driver=broken", assigned_user=None)
    result = repo.list_days(source="success")
    assert result == []


class _TopUsersCursor:
    def __init__(self):
        self.executed = []

    def execute(self, query, params=()):
        self.executed.append((str(query), tuple(params)))
        return self

    def fetchall(self):
        return [
            ("USER_A", 12),
            ("USER_B", 8),
        ]


class _TopUsersConnection:
    def __init__(self):
        self.cursor_obj = _TopUsersCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


class _FakePyodbc:
    @staticmethod
    def connect(*args, **kwargs):
        return _TopUsersConnection()


def test_sqlserver_history_list_top_users_orders_and_maps(monkeypatch) -> None:
    monkeypatch.setattr("dashboard.repositories.pyodbc", _FakePyodbc)
    repo = SQLServerHistoryRepository(conn_str="Driver=ok", assigned_user=None)
    result = repo.list_top_users(limit=10)
    assert result == [
        {"usuario_asignado": "USER_A", "total_recursos": 12},
        {"usuario_asignado": "USER_B", "total_recursos": 8},
    ]
