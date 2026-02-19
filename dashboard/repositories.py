from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from core.runtime_flags import is_redis_queue_mode

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

try:
    import pyodbc
except Exception:  # pragma: no cover
    pyodbc = None


def utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


class SqliteHistoryRepository:
    def __init__(self, sqlite_db_path: str, logger: Optional[logging.Logger] = None):
        self.sqlite_db_path = Path(sqlite_db_path)
        self.logger = logger or logging.getLogger("dashboard.sqlite_history_repo")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_days(self, *, source: str) -> list[str]:
        source_norm = source.lower().strip()
        conn = self._conn()
        days: set[str] = set()
        try:
            if source_norm in {"all", "incidents"}:
                rows = conn.execute("SELECT DISTINCT day FROM realtime_incidents ORDER BY day DESC").fetchall()
                days.update(str(row["day"]) for row in rows if row["day"])
            if source_norm in {"all", "success"}:
                rows = conn.execute(
                    "SELECT DISTINCT day FROM realtime_task_results WHERE status='success' ORDER BY day DESC"
                ).fetchall()
                days.update(str(row["day"]) for row in rows if row["day"])
            return sorted(days, reverse=True)
        except Exception as exc:
            self.logger.warning("Error listando dias de historico en SQLite: %s", exc)
            return []
        finally:
            conn.close()

    def list_incidents(self, *, day: str, page: int, page_size: int) -> dict[str, Any]:
        conn = self._conn()
        if not self.sqlite_db_path.exists():
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        offset = max(0, (page - 1) * page_size)
        try:
            count_row = conn.execute("SELECT COUNT(*) FROM realtime_incidents WHERE day = ?", (day,)).fetchone()
            total = int(count_row[0] if count_row else 0)
            rows = conn.execute(
                """
                SELECT site_id, resource_id, expediente, incident_type, reason,
                       day, started_at, ended_at, payload
                FROM realtime_incidents
                WHERE day = ?
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (day, page_size, offset),
            ).fetchall()
            items = [
                {
                    "site_id": row["site_id"],
                    "resource_id": row["resource_id"],
                    "expediente": row["expediente"],
                    "incident_type": row["incident_type"],
                    "reason": row["reason"],
                    "day": row["day"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "payload": _decode_json(row["payload"]),
                }
                for row in rows
            ]
            return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("Error listando incidencias en SQLite: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def list_successes(self, *, day: str, page: int, page_size: int) -> dict[str, Any]:
        conn = self._conn()
        if not self.sqlite_db_path.exists():
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        offset = max(0, (page - 1) * page_size)
        try:
            count_row = conn.execute(
                "SELECT COUNT(*) FROM realtime_task_results WHERE day = ? AND status='success'",
                (day,),
            ).fetchone()
            total = int(count_row[0] if count_row else 0)
            rows = conn.execute(
                """
                SELECT site_id, resource_id, job_id, protocol, day, started_at, ended_at, payload, result
                FROM realtime_task_results
                WHERE day = ?
                  AND status = 'success'
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
                    "day": row["day"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "payload": _decode_json(row["payload"]),
                    "result": _decode_json(row["result"]),
                }
                for row in rows
            ]
            return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("Error listando exitos en SQLite: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
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


class SQLServerHistoryRepository:
    def __init__(
        self,
        *,
        conn_str: Optional[str],
        assigned_user: Optional[str],
        logger: Optional[logging.Logger] = None,
    ):
        self.conn_str = (conn_str or "").strip() or None
        self.assigned_user = (assigned_user or "").strip() or None
        self.logger = logger or logging.getLogger("dashboard.sqlserver_repo")
        self._resource_columns_cache: Optional[set[str]] = None

    def _conn(self):
        if not self.conn_str or pyodbc is None:
            return None
        # Acceso de solo lectura mediante el driver si es posible o asumiendo SELECTs
        return pyodbc.connect(self.conn_str)

    @staticmethod
    def _date_expr() -> str:
        """
        Normaliza FUsuarioCompletado a string 'YYYY-MM-DD' para lectura y comparación.
        Esto elimina el componente de hora (00:00:00) de los resultados.
        """
        return "CONVERT(varchar(10), rs.FUsuarioCompletado, 23)"

    def _build_where(self) -> tuple[str, list[Any]]:
        # Filtro base: que la fecha exista
        clauses = ["rs.FUsuarioCompletado IS NOT NULL"]
        params: list[Any] = []
        
        # Filtro opcional por usuario asignado (limpiando espacios y mayúsculas)
        if self.assigned_user:
            clauses.append("UPPER(LTRIM(RTRIM(rs.UsuarioAsignado))) = UPPER(?)")
            params.append(self.assigned_user)
            
        return " AND ".join(clauses), params

    def _resource_columns(self, conn) -> set[str]:
        if self._resource_columns_cache is not None:
            return self._resource_columns_cache

        columns: set[str] = set()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = 'Recursos' AND TABLE_NAME = 'RecursosExp'
                """
            )
            columns = {str(row[0]).strip().lower() for row in cur.fetchall() if row and row[0]}
        except Exception as exc:
            self.logger.warning("No se pudieron leer columnas de Recursos.RecursosExp: %s", exc)
        self._resource_columns_cache = columns
        return columns

    @staticmethod
    def _pick_column_expr(columns: set[str], candidates: list[str], alias: str) -> str:
        for column_name in candidates:
            if column_name.lower() in columns:
                return f"rs.[{column_name}] AS [{alias}]"
        return f"NULL AS [{alias}]"

    def list_days(self, *, source: str) -> list[str]:
        source_norm = source.lower().strip()
        if source_norm not in {"all", "success"}:
            return []
            
        conn = self._conn()
        if conn is None: return []
        
        where_sql, params = self._build_where()
        query = f"""
            SELECT DISTINCT {self._date_expr()} AS day
            FROM Recursos.RecursosExp rs
            WHERE {where_sql}
            ORDER BY day DESC
        """
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            return [str(row[0]) for row in cur.fetchall() if row and row[0]]
        except Exception as exc:
            self.logger.warning("Error en lectura de días (SQL Server): %s", exc)
            return []
        finally:
            conn.close()

    def list_successes(self, *, day: str, page: int, page_size: int) -> dict[str, Any]:
        conn = self._conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
            
        offset = max(0, (page - 1) * page_size)
        where_sql, params = self._build_where()
        
        # Comparación limpia: string vs string (YYYY-MM-DD)
        where_with_day = f"{where_sql} AND {self._date_expr()} = ?"
        
        try:
            cur = conn.cursor()
            available_columns = self._resource_columns(conn)
            sujeto_expr = self._pick_column_expr(
                available_columns,
                ["SujetoRecurso"],
                "sujeto_recurso",
            )
            tipocliente_expr = self._pick_column_expr(
                available_columns,
                ["TipDeCliente", "TipoDeCliente", "TipusDeClient", "TipoCliente"],
                "tipodecliente",
            )
            empresa_expr = self._pick_column_expr(
                available_columns,
                ["NombreEmpresa", "Empresa"],
                "empresa",
            )
            fase_expr = self._pick_column_expr(
                available_columns,
                ["FaseProcedimiento"],
                "fase_procedimiento",
            )

            # 1. Conteo para paginación
            cur.execute(f"SELECT COUNT(*) FROM Recursos.RecursosExp rs WHERE {where_with_day}", [*params, day])
            total = int(cur.fetchone()[0] or 0)

            # 2. Lectura de datos
            cur.execute(
                f"""
                SELECT rs.idRecurso, rs.idExp, rs.Expedient, rs.Organisme, rs.TExp,
                       rs.UsuarioAsignado, rs.Estado,
                       {self._date_expr()} AS day,
                       rs.FUsuarioCompletado,
                       {sujeto_expr},
                       {tipocliente_expr},
                       {empresa_expr},
                       {fase_expr}
                FROM Recursos.RecursosExp rs
                WHERE {where_with_day}
                ORDER BY rs.FUsuarioCompletado DESC, rs.idRecurso DESC
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
                """,
                [*params, day, offset, page_size],
            )
            
            items = [{
                "site_id": str(row[3] or ""),
                "resource_id": row[0],
                "job_id": str(row[1]) if row[1] is not None else None,
                "protocol": "P2" if row[4] == 2 else ("P3" if row[4] == 3 else f"T-{row[4]}"),
                "day": row[7],
                "started_at": row[8].isoformat() if row[8] else None,
                "payload": {
                    "expediente": row[2],
                    "usuario": row[5],
                    "estado": row[6],
                    "sujeto_recurso": (row[9] or "").strip() if row[9] else None,
                    "tipodecliente": row[10],
                    "empresa": (row[11] or "").strip() if row[11] else None,
                    "fase_procedimiento": (row[12] or "").strip() if row[12] else None,
                },
                "result": {"source": "sqlserver_read_only"}
            } for row in cur.fetchall()]
            
            return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("Error en lectura de éxitos (SQL Server): %s", exc)
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
            if is_redis_queue_mode(self.queue_backend):
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

    def list_current(self, *, day: str | None = None, page: int, page_size: int) -> dict[str, Any]:
        """Return ALL active queue items (queued/processing/pending) regardless of date."""
        offset = max(0, (page - 1) * page_size)
        conn = self._conn()
        try:
            if is_redis_queue_mode(self.queue_backend):
                count_row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM job_runs
                    WHERE state IN ('queued', 'processing')
                    """,
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
                    ORDER BY started_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (page_size, offset),
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
                """,
            ).fetchone()
            total = int(count_row[0] if count_row else 0)
            rows = conn.execute(
                """
                SELECT site_id, resource_id, id, protocol, status,
                       created_at AS started_at, processed_at AS ended_at, payload
                FROM tramite_queue
                WHERE status IN ('pending', 'processing')
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
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

    def get_live(self, *, day: str) -> Optional[dict[str, Any]]:
        conn = self._conn()
        try:
            if is_redis_queue_mode(self.queue_backend):
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
                    "job_id": row["job_id"] if is_redis_queue_mode(self.queue_backend) else row["id"],
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

    def get_completion_marker(self, *, day: str) -> dict[str, Any]:
        conn = self._conn()
        try:
            if is_redis_queue_mode(self.queue_backend):
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS finished_count,
                           MAX(finished_at) AS last_finished_at
                    FROM job_runs
                    WHERE state IN ('completed', 'succeeded', 'failed', 'dead', 'cancelled')
                      AND substr(COALESCE(finished_at, updated_at, created_at), 1, 10) = ?
                    """,
                    (day,),
                ).fetchone()
            else:
                try:
                    row = conn.execute(
                        """
                        SELECT COUNT(*) AS finished_count,
                               MAX(finished_at) AS last_finished_at
                        FROM job_runs
                        WHERE state IN ('completed', 'succeeded', 'failed', 'dead', 'cancelled')
                          AND substr(COALESCE(finished_at, updated_at, created_at), 1, 10) = ?
                        """,
                        (day,),
                    ).fetchone()
                except Exception:
                    row = conn.execute(
                        """
                        SELECT COUNT(*) AS finished_count,
                               MAX(processed_at) AS last_finished_at
                        FROM tramite_queue
                        WHERE status IN ('completed', 'failed')
                          AND substr(COALESCE(processed_at, created_at), 1, 10) = ?
                        """,
                        (day,),
                    ).fetchone()

            finished_count = int(row["finished_count"] if row and row["finished_count"] is not None else 0)
            last_finished_at = row["last_finished_at"] if row else None
            marker = f"{finished_count}|{last_finished_at or ''}"
            return {
                "day": day,
                "completed_count": finished_count,
                "last_completed_at": last_finished_at,
                "marker": marker,
            }
        except Exception as exc:
            self.logger.warning("Error obteniendo completion marker en SQLite: %s", exc)
            return {"day": day, "completed_count": 0, "last_completed_at": None, "marker": "0|"}
        finally:
            conn.close()
