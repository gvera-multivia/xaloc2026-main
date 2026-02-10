import os
import sys

sys.path.append(os.getcwd())

from core.realtime_store import NullRealtimeStore, PostgresConfig, PostgresRealtimeStore, build_realtime_store


def test_postgres_config_from_env_absent() -> None:
    previous = os.environ.pop("REPORT_PG_DSN", None)
    try:
        cfg = PostgresConfig.from_env()
        assert cfg is None
    finally:
        if previous is not None:
            os.environ["REPORT_PG_DSN"] = previous


def test_postgres_config_from_env_rejects_flag_values() -> None:
    previous = os.environ.get("REPORT_PG_DSN")
    os.environ["REPORT_PG_DSN"] = "1"
    try:
        cfg = PostgresConfig.from_env()
        assert cfg is None
    finally:
        if previous is None:
            os.environ.pop("REPORT_PG_DSN", None)
        else:
            os.environ["REPORT_PG_DSN"] = previous


def test_realtime_store_dedupe_keys() -> None:
    store = PostgresRealtimeStore(config=PostgresConfig(dsn="postgresql://dummy"))
    task_key = store._task_dedupe_key(site_id="madrid", status="failed", resource_id=123, job_id="j1")
    inc_key = store._incident_dedupe_key(
        site_id="madrid",
        incident_type="SITE_RULE_DISCARDED",
        resource_id=123,
        expediente="2026/1",
    )
    assert task_key == "task:madrid:failed:rid:123"
    assert inc_key == "incident:madrid:SITE_RULE_DISCARDED:rid:123"


def test_build_realtime_store_without_env_returns_null() -> None:
    previous = os.environ.pop("REPORT_PG_DSN", None)
    try:
        store = build_realtime_store()
        assert isinstance(store, NullRealtimeStore)
    finally:
        if previous is not None:
            os.environ["REPORT_PG_DSN"] = previous


def test_build_realtime_store_with_invalid_flag_env_returns_null() -> None:
    previous = os.environ.get("REPORT_PG_DSN")
    os.environ["REPORT_PG_DSN"] = "1"
    try:
        store = build_realtime_store()
        assert isinstance(store, NullRealtimeStore)
    finally:
        if previous is None:
            os.environ.pop("REPORT_PG_DSN", None)
        else:
            os.environ["REPORT_PG_DSN"] = previous
