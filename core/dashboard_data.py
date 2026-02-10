from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency
    psycopg = None


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class DashboardDataSource:
    def __init__(
        self,
        *,
        sqlite_db_path: str = "db/xaloc_database.db",
        pg_dsn: Optional[str] = None,
        queue_backend: Optional[str] = None,
    ):
        self.logger = logging.getLogger("dashboard_data")
        self.sqlite_db_path = Path(sqlite_db_path)
        self.pg_dsn = (pg_dsn or os.getenv("REPORT_PG_DSN") or "").strip() or None
        self.queue_backend = (queue_backend or os.getenv("QUEUE_BACKEND", "sqlite")).strip().lower()

    def _sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _pg_conn(self):
        if not self.pg_dsn or psycopg is None:
            return None
        return psycopg.connect(self.pg_dsn)

    def list_days(self, *, source: str, page: int, page_size: int) -> dict[str, Any]:
        source_norm = source.lower().strip()
        days: set[str] = set()
        if source_norm in {"all", "incidents"}:
            days.update(self._days_from_incidents())
        if source_norm in {"all", "success"}:
            days.update(self._days_from_success())
        if source_norm in {"all", "queue"}:
            days.update(self._days_from_queue())
        days_sorted = sorted(days, reverse=True)
        total = len(days_sorted)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return {
            "items": days_sorted[start:end],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def _days_from_incidents(self) -> set[str]:
        conn = self._pg_conn()
        if conn is None:
            return set()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT day::text FROM realtime_incidents ORDER BY 1 DESC")
                return {str(row[0]) for row in cur.fetchall() if row and row[0]}
        except Exception as exc:
            self.logger.warning("No se pudo listar dias de incidencias (PG): %s", exc)
            return set()
        finally:
            conn.close()

    def _days_from_success(self) -> set[str]:
        conn = self._pg_conn()
        if conn is None:
            return set()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT day::text
                    FROM realtime_task_results
                    WHERE status = 'success'
                    ORDER BY 1 DESC
                    """
                )
                return {str(row[0]) for row in cur.fetchall() if row and row[0]}
        except Exception as exc:
            self.logger.warning("No se pudo listar dias de exitos (PG): %s", exc)
            return set()
        finally:
            conn.close()

    def _days_from_queue(self) -> set[str]:
        days: set[str] = set()
        conn = self._sqlite_conn()
        try:
            if self.queue_backend == "redis":
                cur = conn.execute(
                    """
                    SELECT DISTINCT substr(COALESCE(queued_at, created_at), 1, 10) AS day
                    FROM job_runs
                    WHERE state IN ('queued', 'processing')
                    """
                )
            else:
                cur = conn.execute(
                    """
                    SELECT DISTINCT substr(created_at, 1, 10) AS day
                    FROM tramite_queue
                    WHERE status IN ('pending', 'processing')
                    """
                )
            for row in cur.fetchall():
                day = row["day"] if isinstance(row, sqlite3.Row) else row[0]
                if day:
                    days.add(str(day))
            return days
        except Exception as exc:
            self.logger.warning("No se pudo listar dias de cola (SQLite): %s", exc)
            return days
        finally:
            conn.close()

    def list_incidents(self, *, day: Optional[str], page: int, page_size: int) -> dict[str, Any]:
        conn = self._pg_conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        day_filter = (day or "").strip() or _utc_today_iso()
        offset = max(0, (page - 1) * page_size)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM realtime_incidents
                    WHERE day = %s::date
                    """,
                    (day_filter,),
                )
                total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    """
                    SELECT
                        site_id,
                        resource_id,
                        expediente,
                        incident_type,
                        reason,
                        day::text AS day,
                        started_at,
                        ended_at,
                        payload
                    FROM realtime_incidents
                    WHERE day = %s::date
                    ORDER BY started_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (day_filter, page_size, offset),
                )
                rows = cur.fetchall()
                items = [
                    {
                        "site_id": row[0],
                        "resource_id": row[1],
                        "expediente": row[2],
                        "incident_type": row[3],
                        "reason": row[4],
                        "day": row[5],
                        "started_at": row[6].isoformat() if row[6] else None,
                        "ended_at": row[7].isoformat() if row[7] else None,
                        "payload": row[8],
                    }
                    for row in rows
                ]
                return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("No se pudo listar incidencias (PG): %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def list_successes(self, *, day: Optional[str], page: int, page_size: int) -> dict[str, Any]:
        conn = self._pg_conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        day_filter = (day or "").strip() or _utc_today_iso()
        offset = max(0, (page - 1) * page_size)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM realtime_task_results
                    WHERE day = %s::date
                      AND status = 'success'
                    """,
                    (day_filter,),
                )
                total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    """
                    SELECT
                        site_id,
                        resource_id,
                        job_id,
                        protocol,
                        day::text AS day,
                        started_at,
                        ended_at,
                        payload,
                        result
                    FROM realtime_task_results
                    WHERE day = %s::date
                      AND status = 'success'
                    ORDER BY started_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (day_filter, page_size, offset),
                )
                rows = cur.fetchall()
                items = [
                    {
                        "site_id": row[0],
                        "resource_id": row[1],
                        "job_id": row[2],
                        "protocol": row[3],
                        "day": row[4],
                        "started_at": row[5].isoformat() if row[5] else None,
                        "ended_at": row[6].isoformat() if row[6] else None,
                        "payload": row[7],
                        "result": row[8],
                    }
                    for row in rows
                ]
                return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("No se pudo listar exitos (PG): %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def list_queue(self, *, day: Optional[str], page: int, page_size: int) -> dict[str, Any]:
        day_filter = (day or "").strip() or _utc_today_iso()
        offset = max(0, (page - 1) * page_size)
        conn = self._sqlite_conn()
        try:
            if self.queue_backend == "redis":
                count_row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM job_runs
                    WHERE state IN ('queued', 'processing')
                      AND substr(COALESCE(queued_at, created_at), 1, 10) = ?
                    """,
                    (day_filter,),
                ).fetchone()
                total = int(count_row[0] if count_row else 0)
                rows = conn.execute(
                    """
                    SELECT
                        site_id,
                        resource_id,
                        job_id,
                        protocol,
                        state,
                        COALESCE(queued_at, created_at) AS started_at,
                        updated_at AS ended_at,
                        payload_snapshot AS payload
                    FROM job_runs
                    WHERE state IN ('queued', 'processing')
                      AND substr(COALESCE(queued_at, created_at), 1, 10) = ?
                    ORDER BY started_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (day_filter, page_size, offset),
                ).fetchall()
                items = [
                    {
                        "site_id": row["site_id"],
                        "resource_id": row["resource_id"],
                        "job_id": row["job_id"],
                        "protocol": row["protocol"],
                        "state": row["state"],
                        "day": str(row["started_at"] or "")[:10],
                        "started_at": row["started_at"],
                        "ended_at": row["ended_at"],
                        "payload": row["payload"],
                    }
                    for row in rows
                ]
                return {"items": items, "page": page, "page_size": page_size, "total": total}

            count_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM tramite_queue
                WHERE status IN ('pending', 'processing')
                  AND substr(created_at, 1, 10) = ?
                """,
                (day_filter,),
            ).fetchone()
            total = int(count_row[0] if count_row else 0)
            rows = conn.execute(
                """
                SELECT
                    site_id,
                    resource_id,
                    id,
                    protocol,
                    status,
                    created_at AS started_at,
                    processed_at AS ended_at,
                    payload
                FROM tramite_queue
                WHERE status IN ('pending', 'processing')
                  AND substr(created_at, 1, 10) = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (day_filter, page_size, offset),
            ).fetchall()
            items = [
                {
                    "site_id": row["site_id"],
                    "resource_id": row["resource_id"],
                    "queue_ref": row["id"],
                    "protocol": row["protocol"],
                    "state": row["status"],
                    "day": str(row["started_at"] or "")[:10],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "payload": row["payload"],
                }
                for row in rows
            ]
            return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("No se pudo listar cola actual (SQLite): %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()
