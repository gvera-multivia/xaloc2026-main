#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from core.runtime_flags import get_report_pg_dsn


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load_sqlite_jobs(sqlite_path: str, day: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT job_id, site_id, state, attempt, max_attempts, updated_at, created_at
            FROM job_runs
            WHERE substr(COALESCE(updated_at, created_at), 1, 10) = ?
            """,
            (day,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _load_pg_jobs(pg_dsn: str, day: str) -> list[dict[str, Any]]:
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, status, updated_at, created_at
                FROM jobs
                WHERE substr(COALESCE(updated_at::text, created_at::text), 1, 10) = %s
                """,
                (day,),
            )
            rows = cur.fetchall()
    return [
        {
            "job_id": row[0],
            "status": row[1],
            "updated_at": str(row[2]) if row[2] is not None else None,
            "created_at": str(row[3]) if row[3] is not None else None,
        }
        for row in rows
    ]


def reconcile(*, sqlite_path: str, pg_dsn: str, day: str) -> dict[str, Any]:
    sqlite_jobs = _load_sqlite_jobs(sqlite_path, day)
    pg_jobs = _load_pg_jobs(pg_dsn, day)

    sqlite_by_id = {str(i["job_id"]): i for i in sqlite_jobs if i.get("job_id")}
    pg_by_id = {str(i["job_id"]): i for i in pg_jobs if i.get("job_id")}

    sqlite_ids = set(sqlite_by_id.keys())
    pg_ids = set(pg_by_id.keys())

    missing_in_pg = sorted(sqlite_ids - pg_ids)
    extra_in_pg = sorted(pg_ids - sqlite_ids)

    state_mismatch: list[dict[str, str]] = []
    for job_id in sorted(sqlite_ids & pg_ids):
        s_state = str(sqlite_by_id[job_id].get("state") or "")
        p_state = str(pg_by_id[job_id].get("status") or "")
        if s_state != p_state:
            state_mismatch.append({"job_id": job_id, "sqlite_state": s_state, "pg_status": p_state})

    return {
        "day": day,
        "sqlite_total": len(sqlite_jobs),
        "pg_total": len(pg_jobs),
        "sqlite_states": dict(Counter(str(i.get("state") or "") for i in sqlite_jobs)),
        "pg_states": dict(Counter(str(i.get("status") or "") for i in pg_jobs)),
        "missing_in_pg": missing_in_pg,
        "extra_in_pg": extra_in_pg,
        "state_mismatch": state_mismatch,
        "ok": len(missing_in_pg) == 0 and len(extra_in_pg) == 0 and len(state_mismatch) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconciliacion diaria SQLite vs PostgreSQL (jobs).")
    parser.add_argument("--day", default=_today_iso(), help="Dia ISO YYYY-MM-DD")
    parser.add_argument("--sqlite", default="db/xaloc_database.db", help="Ruta SQLite")
    parser.add_argument("--pg-dsn", default=None, help="DSN PostgreSQL (si no, usa REPORT_PG_DSN/PG_DSN)")
    parser.add_argument("--strict", action="store_true", help="Exit code 1 si hay divergencias")
    args = parser.parse_args()

    sqlite_path = str(Path(args.sqlite))
    pg_dsn = (args.pg_dsn or get_report_pg_dsn() or "").strip()
    if not pg_dsn:
        raise SystemExit("Falta DSN PostgreSQL (--pg-dsn o REPORT_PG_DSN/PG_DSN).")

    summary = reconcile(sqlite_path=sqlite_path, pg_dsn=pg_dsn, day=str(args.day))
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.strict and not summary["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

