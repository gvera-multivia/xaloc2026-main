from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.redis_client as redis_client


class _FakeConnectionPool:
    calls: list[tuple[str, dict]] = []

    @classmethod
    def from_url(cls, url: str, **kwargs):
        cls.calls.append((url, kwargs))
        return object()


class _FakeRedis:
    def __init__(self, *, connection_pool):
        self.connection_pool = connection_pool


@pytest.fixture(autouse=True)
def _reset_redis_singletons(monkeypatch):
    fake_module = SimpleNamespace(ConnectionPool=_FakeConnectionPool, Redis=_FakeRedis)
    monkeypatch.setattr(redis_client, "redis", fake_module)
    monkeypatch.setattr(redis_client, "_redis_client", None)
    monkeypatch.setattr(redis_client, "_redis_pool", None)
    _FakeConnectionPool.calls.clear()
    monkeypatch.setenv("REDIS_ENABLED", "1")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.delenv("REDIS_SOCKET_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("REDIS_CONNECT_TIMEOUT_SECONDS", raising=False)


def test_redis_pool_sets_timeouts_above_blocking_stream_reads() -> None:
    client = redis_client.get_redis_client()

    assert client is not None
    _, kwargs = _FakeConnectionPool.calls[0]
    assert kwargs["socket_timeout"] == 30.0
    assert kwargs["socket_connect_timeout"] == 5.0
    assert kwargs["socket_timeout"] > 5.0


def test_redis_pool_accepts_explicit_timeout_configuration(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("REDIS_CONNECT_TIMEOUT_SECONDS", "7.5")

    redis_client.get_redis_client()

    _, kwargs = _FakeConnectionPool.calls[0]
    assert kwargs["socket_timeout"] == 45.0
    assert kwargs["socket_connect_timeout"] == 7.5


@pytest.mark.parametrize("value", ["invalid", "0", "-1"])
def test_redis_pool_rejects_invalid_timeout_configuration(monkeypatch, value: str) -> None:
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", value)

    redis_client.get_redis_client()

    _, kwargs = _FakeConnectionPool.calls[0]
    assert kwargs["socket_timeout"] == 30.0
