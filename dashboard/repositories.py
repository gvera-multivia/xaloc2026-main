from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None


def utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


    def get_live(self, *, day: str) -> Optional[dict[str, Any]]:
        conn = self._conn()
        try:
            if self.queue_backend == "redis":
                row = conn.execute(
                    """
                    SELECT site_id, resource_id, job_id, protocol, state,
                           COALESCE(queued_at, created_at) AS started_at,
                           updated_at AS ended_at,
                           payload_snapshot AS payload
                    FROM job_runs
                    WHERE state = 'processing'
                      AND substr(COALESCE(queued_at, created_at), 1, 10) = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (day,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT site_id, resource_id, id, protocol, status AS state,
                           created_at AS started_at, processed_at AS ended_at, payload
                    FROM tramite_queue
                    WHERE status = 'processing'
                      AND substr(created_at, 1, 10) = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (day,),
                ).fetchone()

            if row:
                return {
                    "site_id": row["site_id"],
                    "resource_id": row["resource_id"],
                    "job_id": row["job_id"] if self.queue_backend == "redis" else row["id"],
                    "protocol": row["protocol"],
                    "state": row["state"],
                    "day": str(row["started_at"] or "")[:10],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "payload": row["payload"],
                }
            return None
        except Exception as exc:
            self.logger.warning("Error obteniendo tramite vivo en SQLite: %s", exc)
            return None
        finally:
            conn.close()


class PostgresHistoryRepository:
    def __init__(self, pg_dsn: Optional[str], logger: Optional[logging.Logger] = None):
        self.pg_dsn = (pg_dsn or "").strip() or None
        self.logger = logger or logging.getLogger("dashboard.pg_repo")

    def _conn(self):
        if not self.pg_dsn or psycopg is None:
            return None
        return psycopg.connect(self.pg_dsn)

    def list_days(self, *, source: str) -> list[str]:
        source_norm = source.lower().strip()
        conn = self._conn()
        if conn is None:
            return []
        days: set[str] = set()
        try:
            with conn.cursor() as cur:
                if source_norm in {"all", "incidents"}:
                    cur.execute("SELECT DISTINCT day::text FROM realtime_incidents")
                    days.update(str(row[0]) for row in cur.fetchall() if row and row[0])
                if source_norm in {"all", "success"}:
                    cur.execute("SELECT DISTINCT day::text FROM realtime_task_results WHERE status='success'")
                    days.update(str(row[0]) for row in cur.fetchall() if row and row[0])
            return sorted(days, reverse=True)
        except Exception as exc:
            self.logger.warning("Error listando dias de historico en PG: %s", exc)
            return []
        finally:
            conn.close()

    def list_incidents(self, *, day: str, page: int, page_size: int) -> dict[str, Any]:
        conn = self._conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        offset = max(0, (page - 1) * page_size)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM realtime_incidents WHERE day = %s::date", (day,))
                total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    """
                    SELECT site_id, resource_id, expediente, incident_type, reason,
                           day::text, started_at, ended_at, payload
                    FROM realtime_incidents
                    WHERE day = %s::date
                    ORDER BY started_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (day, page_size, offset),
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
            self.logger.warning("Error listando incidencias en PG: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def list_successes(self, *, day: str, page: int, page_size: int) -> dict[str, Any]:
        conn = self._conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        offset = max(0, (page - 1) * page_size)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM realtime_task_results WHERE day = %s::date AND status='success'",
                    (day,),
                )
                total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    """
                    SELECT site_id, resource_id, job_id, protocol, day::text, started_at, ended_at, payload, result
                    FROM realtime_task_results
                    WHERE day = %s::date
                      AND status = 'success'
                    ORDER BY started_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (day, page_size, offset),
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
            self.logger.warning("Error listando exitos en PG: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()


class SqliteQueueRepository:
    def __init__(self, sqlite_db_path: str, queue_backend: str, logger: Optional[logging.Logger] = None):
        self.sqlite_db_path = Path(sqlite_db_path)
        self.queue_backend = (queue_backend or "sqlite").strip().lower()
        self.logger = logger or logging.getLogger("dashboard.sqlite_repo")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_days(self) -> list[str]:
        conn = self._conn()
        try:
            if self.queue_backend == "redis":
                rows = conn.execute(
                    """
                    SELECT DISTINCT substr(COALESCE(queued_at, created_at), 1, 10) AS day
                    FROM job_runs
                    WHERE state IN ('queued', 'processing')
                    ORDER BY day DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT DISTINCT substr(created_at, 1, 10) AS day
                    FROM tramite_queue
                    WHERE status IN ('pending', 'processing')
                    ORDER BY day DESC
                    """
                ).fetchall()
            return [str(row["day"]) for row in rows if row["day"]]
        except Exception as exc:
            self.logger.warning("Error listando dias de cola en SQLite: %s", exc)
            return []
        finally:
            conn.close()

    def list_current(self, *, day: str, page: int, page_size: int) -> dict[str, Any]:
        offset = max(0, (page - 1) * page_size)
        conn = self._conn()
        try:
            if self.queue_backend == "redis":
                count_row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM job_runs
                    WHERE state IN ('queued', 'processing')
                      AND substr(COALESCE(queued_at, created_at), 1, 10) = ?
                    """,
                    (day,),
                ).fetchone()
                total = int(count_row[0] if count_row else 0)
                rows = conn.execute(
                    """
                    SELECT site_id, resource_id, job_id, protocol, state,
                           COALESCE(queued_at, created_at) AS started_at,
                           updated_at AS ended_at,
                           payload_snapshot AS payload
                    FROM job_runs
                    WHERE state IN ('queued', 'processing')
                      AND substr(COALESCE(queued_at, created_at), 1, 10) = ?
                    ORDER BY started_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (day, page_size, offset),
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
                (day,),
            ).fetchone()
            total = int(count_row[0] if count_row else 0)
            rows = conn.execute(
                """
                SELECT site_id, resource_id, id, protocol, status,
                       created_at AS started_at, processed_at AS ended_at, payload
                FROM tramite_queue
                WHERE status IN ('pending', 'processing')
                  AND substr(created_at, 1, 10) = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (day, page_size, offset),
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
            self.logger.warning("Error listando cola actual en SQLite: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()
