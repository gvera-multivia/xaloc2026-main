from __future__ import annotations

import os
from typing import Optional


VALID_QUEUE_MODES = {"sqlite", "redis_list", "redis_streams"}


def _is_true(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_pg_source_of_truth_enabled() -> bool:
    return _is_true(os.getenv("USE_PG_SOURCE_OF_TRUTH", "1"))


def normalize_queue_mode(value: str) -> str:
    mode = (value or "").strip().lower()
    if mode in {"redis", "redis_list"}:
        return "redis_list"
    if mode == "redis_streams":
        return "redis_streams"
    if mode == "sqlite":
        return "sqlite"
    return "redis_streams"


def get_queue_mode(explicit: Optional[str] = None) -> str:
    raw = explicit
    if raw is None:
        raw = os.getenv("QUEUE_MODE")
    if not (raw or "").strip():
        # Backwards compatibility with legacy env var.
        raw = os.getenv("QUEUE_BACKEND", "redis_streams")
    return normalize_queue_mode(raw or "redis_streams")


def is_redis_queue_mode(mode: str) -> bool:
    return normalize_queue_mode(mode) in {"redis_list", "redis_streams"}


def is_redis_streams_pilot_enabled() -> bool:
    return _is_true(os.getenv("REDIS_STREAMS_PILOT_ENABLED", "0"))


def get_report_pg_dsn(explicit: Optional[str] = None) -> Optional[str]:
    dsn = (explicit or "").strip()
    if not dsn:
        dsn = (os.getenv("REPORT_PG_DSN") or "").strip()
    if not dsn:
        dsn = (os.getenv("PG_DSN") or "").strip()
    if not dsn:
        return None

    lowered = dsn.lower()
    if lowered in {"0", "1", "true", "false", "yes", "no", "on", "off", "enabled", "disabled"}:
        return None
    if "://" in dsn or "=" in dsn:
        return dsn
    return None
