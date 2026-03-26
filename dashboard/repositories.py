from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

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


class SqliteHistoryRepository:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("SQLite eliminado. Usa PostgresHistoryRepository.")


class SqliteQueueRepository:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("SQLite eliminado. Usa PostgresQueueRepository.")


class PostgresHistoryRepository:
    def __init__(self, pg_dsn: Optional[str], logger: Optional[logging.Logger] = None):
        self.pg_dsn = (pg_dsn or "").strip() or None
        self.logger = logger or logging.getLogger("dashboard.pg_history_repo")

    def _conn(self):
        if not self.pg_dsn or psycopg is None:
            return None
        try:
            return psycopg.connect(self.pg_dsn)
        except Exception as exc:
            self.logger.warning("No se pudo conectar a PostgreSQL para historico: %s", exc)
            return None

    def _build_user_filter_clause(
        self,
        *,
        user_candidates: Optional[list[str]] = None,
        payload_alias: str = "payload",
    ) -> tuple[str, list[Any]]:
        candidates = [str(v or "").strip() for v in (user_candidates or []) if str(v or "").strip()]
        if not candidates:
            return "", []
        payload_user_expr = (
            f"UPPER(COALESCE("
            f"{payload_alias}->>'UsuarioAsignado', "
            f"{payload_alias}->>'usuario', "
            f"{payload_alias}->>'username', "
            f"{payload_alias}->>'xvia_username', "
            f"{payload_alias}->>'user', "
            f"''))"
        )
        placeholders = ", ".join(["UPPER(%s)"] * len(candidates))
        return f" AND {payload_user_expr} IN ({placeholders})", candidates

    def list_days(self, *, source: str, user_candidates: Optional[list[str]] = None) -> list[str]:
        source_norm = (source or "").strip().lower()
        conn = self._conn()
        if conn is None:
            return []
        days: set[str] = set()
        user_filter_sql, user_params = self._build_user_filter_clause(
            user_candidates=user_candidates,
            payload_alias="payload",
        )
        try:
            with conn.cursor() as cur:
                if source_norm in {"all", "incidents"}:
                    cur.execute("SELECT DISTINCT day::text FROM realtime_incidents")
                    days.update(str(row[0]) for row in cur.fetchall() if row and row[0])
                if source_norm in {"all", "success"}:
                    cur.execute(
                        f"SELECT DISTINCT day::text FROM realtime_task_results WHERE status='success'{user_filter_sql}",
                        user_params,
                    )
                    days.update(str(row[0]) for row in cur.fetchall() if row and row[0])
            return sorted(days, reverse=True)
        except Exception as exc:
            self.logger.warning("Error listando dias de historico en PG: %s", exc)
            return []
        finally:
            conn.close()

    def list_incidents(
        self,
        *,
        day: str,
        page: int,
        page_size: int,
        statuses: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        conn = self._conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        offset = max(0, (page - 1) * page_size)
        normalized_statuses = [
            str(s or "").strip().upper()
            for s in (statuses or [])
            if str(s or "").strip()
        ]
        normalized_statuses = [s for s in normalized_statuses if s in {"NEW", "REVIEWED", "RESOLVED"}]
        status_filter_sql = ""
        status_filter_params: list[Any] = []
        if normalized_statuses:
            status_filter_sql = " AND status = ANY(%s)"
            status_filter_params.append(normalized_statuses)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM realtime_incidents WHERE day = %s::date{status_filter_sql}",
                    (day, *status_filter_params),
                )
                total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    f"""
                    SELECT site_id,
                           COALESCE(
                             resource_id,
                             CASE
                               WHEN (payload->>'idRecurso') ~ '^[0-9]+$' THEN (payload->>'idRecurso')::bigint
                               WHEN (payload->>'resource_id') ~ '^[0-9]+$' THEN (payload->>'resource_id')::bigint
                               ELSE NULL
                             END
                           ) AS resource_id,
                           expediente, incident_type, reason, status,
                           day::text, started_at, ended_at, payload
                    FROM realtime_incidents
                    WHERE day = %s::date
                      {status_filter_sql}
                    ORDER BY started_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (day, *status_filter_params, page_size, offset),
                )
                rows = cur.fetchall()
                items = [
                    {
                        "site_id": row[0],
                        "resource_id": row[1],
                        "expediente": row[2],
                        "incident_type": row[3],
                        "reason": row[4],
                        "status": row[5],
                        "day": row[6],
                        "started_at": row[7].isoformat() if row[7] else None,
                        "ended_at": row[8].isoformat() if row[8] else None,
                        "payload": row[9],
                    }
                    for row in rows
                ]
                return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("Error listando incidencias en PG: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def clear_incident(
        self,
        *,
        site_id: str,
        resource_id: Optional[int],
        incident_type: Optional[str] = None,
    ) -> int:
        conn = self._conn()
        if conn is None:
            return 0
        site = str(site_id or "").strip()
        if not site:
            return 0
        itype = str(incident_type or "").strip() or None
        try:
            with conn.cursor() as cur:
                if resource_id is None:
                    if itype:
                        cur.execute(
                            """
                            DELETE FROM realtime_incidents
                            WHERE site_id = %s
                              AND resource_id IS NULL
                              AND incident_type = %s
                            """,
                            (site, itype),
                        )
                    else:
                        cur.execute(
                            """
                            DELETE FROM realtime_incidents
                            WHERE site_id = %s
                              AND resource_id IS NULL
                            """,
                            (site,),
                        )
                else:
                    if itype:
                        cur.execute(
                            """
                            DELETE FROM realtime_incidents
                            WHERE site_id = %s
                              AND resource_id = %s
                              AND incident_type = %s
                            """,
                            (site, int(resource_id), itype),
                        )
                    else:
                        cur.execute(
                            """
                            DELETE FROM realtime_incidents
                            WHERE site_id = %s
                              AND resource_id = %s
                            """,
                            (site, int(resource_id)),
                        )
                deleted = int(cur.rowcount or 0)
            conn.commit()
            return deleted
        except Exception as exc:
            self.logger.warning(
                "Error limpiando incidencia en PG site=%s resource_id=%s type=%s: %s",
                site,
                resource_id,
                itype,
                exc,
            )
            return 0
        finally:
            conn.close()

    def list_successes(
        self,
        *,
        day: str,
        page: int,
        page_size: int,
        user_candidates: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        conn = self._conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        offset = max(0, (page - 1) * page_size)
        user_filter_sql, user_params = self._build_user_filter_clause(
            user_candidates=user_candidates,
            payload_alias="payload",
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM realtime_task_results WHERE day = %s::date AND status='success'{user_filter_sql}",
                    (day, *user_params),
                )
                total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    f"""
                    SELECT site_id, resource_id, job_id, protocol, day::text, started_at, ended_at, payload, result
                    FROM realtime_task_results
                    WHERE day = %s::date
                      AND status = 'success'
                      {user_filter_sql}
                    ORDER BY started_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (day, *user_params, page_size, offset),
                )
                rows = cur.fetchall()
                items = []
                for row in rows:
                    payload = row[7] if isinstance(row[7], dict) else {}
                    expediente = (
                        payload.get("expediente")
                        or payload.get("expediente_num")
                        or payload.get("denuncia_num")
                        or payload.get("nExp")
                        or payload.get("Expedient")
                    )
                    fase = payload.get("fase_procedimiento") or payload.get("FaseProcedimiento")
                    items.append(
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
                            "expediente": str(expediente).strip() if expediente is not None else None,
                            "fase_procedimiento": str(fase).strip() if fase is not None else None,
                        }
                    )
                return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("Error listando exitos en PG: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def list_top_users(self, *, limit: int = 500, day: Optional[str] = None) -> list[dict[str, Any]]:
        conn = self._conn()
        if conn is None:
            return []
        safe_limit = max(1, min(int(limit), 5000))
        day_value = (day or "").strip() or None
        try:
            with conn.cursor() as cur:
                where_sql = "WHERE status = 'success'"
                params: list[Any] = []
                if day_value:
                    where_sql += " AND day = %s::date"
                    params.append(day_value)
                cur.execute(
                    f"""
                    SELECT
                        UPPER(BTRIM(
                            COALESCE(
                                payload->>'UsuarioAsignado',
                                payload->>'usuario',
                                payload->>'username',
                                payload->>'xvia_username',
                                payload->>'user',
                                ''
                            )
                        )) AS usuario_asignado,
                        COUNT(*) AS total_recursos
                    FROM realtime_task_results
                    {where_sql}
                      AND COALESCE(
                            payload->>'UsuarioAsignado',
                            payload->>'usuario',
                            payload->>'username',
                            payload->>'xvia_username',
                            payload->>'user',
                            ''
                          ) <> ''
                    GROUP BY 1
                    ORDER BY total_recursos DESC, usuario_asignado ASC
                    LIMIT %s
                    """,
                    (*params, safe_limit),
                )
                return [
                    {
                        "usuario_asignado": str(row[0] or "").strip(),
                        "total_recursos": int(row[1] or 0),
                    }
                    for row in cur.fetchall()
                    if row and row[0]
                ]
        except Exception as exc:
            self.logger.warning("Error listando top usuarios en PG: %s", exc)
            return []
        finally:
            conn.close()

    def get_success_total(self, *, day: Optional[str] = None) -> int:
        conn = self._conn()
        if conn is None:
            return 0
        day_value = (day or "").strip() or None
        try:
            with conn.cursor() as cur:
                if day_value:
                    cur.execute(
                        "SELECT COUNT(*) FROM realtime_task_results WHERE status='success' AND day = %s::date",
                        (day_value,),
                    )
                else:
                    cur.execute("SELECT COUNT(*) FROM realtime_task_results WHERE status='success'")
                row = cur.fetchone()
                return int(row[0] if row and row[0] is not None else 0)
        except Exception as exc:
            self.logger.warning("Error leyendo total success en PG: %s", exc)
            return 0
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
        try:
            return pyodbc.connect(self.conn_str, autocommit=True)
        except Exception as exc:
            self.logger.warning("No se pudo conectar a SQL Server para historico: %s", exc)
            return None

    @staticmethod
    def _date_expr() -> str:
        return "CONVERT(varchar(10), rs.FUsuarioCompletado, 23)"

    def _build_where(self, *, assigned_user: Optional[str] = None) -> tuple[str, list[Any]]:
        clauses = ["rs.FUsuarioCompletado IS NOT NULL"]
        params: list[Any] = []
        effective_user = (assigned_user or "").strip() or self.assigned_user
        if effective_user:
            clauses.append("UPPER(LTRIM(RTRIM(rs.UsuarioAsignado))) = UPPER(?)")
            params.append(effective_user)
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

    def list_days(self, *, source: str, assigned_user: Optional[str] = None) -> list[str]:
        if (source or "").strip().lower() not in {"all", "success"}:
            return []
        conn = self._conn()
        if conn is None:
            return []
        where_sql, params = self._build_where(assigned_user=assigned_user)
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
            self.logger.warning("Error en lectura de dias (SQL Server): %s", exc)
            return []
        finally:
            conn.close()

    def list_successes(
        self,
        *,
        day: str,
        page: int,
        page_size: int,
        assigned_user: Optional[str] = None,
    ) -> dict[str, Any]:
        conn = self._conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        offset = max(0, (page - 1) * page_size)
        where_sql, params = self._build_where(assigned_user=assigned_user)
        where_with_day = f"{where_sql} AND {self._date_expr()} = ?"
        try:
            cur = conn.cursor()
            available_columns = self._resource_columns(conn)
            sujeto_expr = self._pick_column_expr(available_columns, ["SujetoRecurso"], "sujeto_recurso")
            tipocliente_expr = self._pick_column_expr(
                available_columns,
                ["TipDeCliente", "TipoDeCliente", "TipusDeClient", "TipoCliente"],
                "tipodecliente",
            )
            empresa_expr = self._pick_column_expr(available_columns, ["NombreEmpresa", "Empresa"], "empresa")
            fase_expr = self._pick_column_expr(available_columns, ["FaseProcedimiento"], "fase_procedimiento")

            cur.execute(f"SELECT COUNT(*) FROM Recursos.RecursosExp rs WHERE {where_with_day}", [*params, day])
            total = int(cur.fetchone()[0] or 0)

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
            items = [
                {
                    "site_id": str(row[3] or ""),
                    "resource_id": row[0],
                    "job_id": str(row[1]) if row[1] is not None else None,
                    "protocol": "P2" if row[4] == 2 else ("P3" if row[4] == 3 else f"T-{row[4]}"),
                    "day": row[7],
                    "started_at": row[8].isoformat() if row[8] else None,
                    "expediente": row[2],
                    "fase_procedimiento": (row[12] or "").strip() if row[12] else None,
                    "payload": {
                        "expediente": row[2],
                        "usuario": row[5],
                        "estado": row[6],
                        "sujeto_recurso": (row[9] or "").strip() if row[9] else None,
                        "tipodecliente": row[10],
                        "empresa": (row[11] or "").strip() if row[11] else None,
                        "fase_procedimiento": (row[12] or "").strip() if row[12] else None,
                    },
                    "result": {"source": "sqlserver_read_only"},
                }
                for row in cur.fetchall()
            ]
            return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("Error en lectura de exitos (SQL Server): %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def list_top_users(self, *, limit: int = 500, day: Optional[str] = None) -> list[dict[str, Any]]:
        conn = self._conn()
        if conn is None:
            return []
        safe_limit = max(1, min(int(limit), 5000))
        day_value = (day or "").strip() or None
        try:
            cur = conn.cursor()
            day_sql = ""
            params: list[Any] = []
            if day_value:
                day_sql = f" AND {self._date_expr()} = ?"
                params.append(day_value)
            cur.execute(
                f"""
                SELECT
                    UPPER(LTRIM(RTRIM(rs.UsuarioAsignado))) AS UsuarioAsignado,
                    COUNT(*) AS TotalRecursos
                FROM Recursos.RecursosExp rs
                WHERE rs.Estado = 2
                  {day_sql}
                  AND rs.UsuarioAsignado IS NOT NULL
                  AND LTRIM(RTRIM(rs.UsuarioAsignado)) <> ''
                GROUP BY UPPER(LTRIM(RTRIM(rs.UsuarioAsignado)))
                ORDER BY TotalRecursos DESC, UsuarioAsignado ASC
                OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
                """,
                (*params, safe_limit),
            )
            return [
                {
                    "usuario_asignado": str(row[0] or "").strip(),
                    "total_recursos": int(row[1] or 0),
                }
                for row in cur.fetchall()
                if row and row[0]
            ]
        except Exception as exc:
            self.logger.warning("Error en lectura top usuarios (SQL Server): %s", exc)
            return []
        finally:
            conn.close()

    def get_success_total(self, *, day: Optional[str] = None) -> int:
        conn = self._conn()
        if conn is None:
            return 0
        day_value = (day or "").strip() or None
        try:
            cur = conn.cursor()
            if day_value:
                cur.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM Recursos.RecursosExp rs
                    WHERE rs.Estado = 2
                      AND {self._date_expr()} = ?
                    """,
                    (day_value,),
                )
            else:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM Recursos.RecursosExp rs
                    WHERE rs.Estado = 2
                    """
                )
            row = cur.fetchone()
            return int(row[0] if row and row[0] is not None else 0)
        except Exception as exc:
            self.logger.warning("Error leyendo total success en SQL Server: %s", exc)
            return 0
        finally:
            conn.close()


class PostgresQueueRepository:
    def __init__(self, pg_dsn: Optional[str], logger: Optional[logging.Logger] = None):
        self.pg_dsn = (pg_dsn or "").strip() or None
        self.logger = logger or logging.getLogger("dashboard.pg_queue_repo")

    def _conn(self):
        if not self.pg_dsn or psycopg is None:
            return None
        try:
            return psycopg.connect(self.pg_dsn)
        except Exception as exc:
            self.logger.warning("No se pudo conectar a PostgreSQL para cola: %s", exc)
            return None

    @staticmethod
    def _site_expr() -> str:
        return "COALESCE(payload_json->>'site_id', NULLIF(split_part(dedup_key, ':', 1), ''), 'unknown')"

    @staticmethod
    def _resource_expr() -> str:
        return (
            "COALESCE("
            "CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$' THEN (payload_json->>'idRecurso')::bigint END,"
            "CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$' THEN ((payload_json->>'idRecurso')::numeric)::bigint END,"
            "CASE WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$' THEN split_part(dedup_key, ':', 2)::bigint END"
            ",CASE WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$' THEN (split_part(dedup_key, ':', 2)::numeric)::bigint END"
            ")"
        )

    @staticmethod
    def _protocol_expr() -> str:
        return "COALESCE(payload_json->>'protocol', payload_json->>'protocolo', NULLIF(split_part(dedup_key, ':', 3), 'none'))"

    def list_days(self) -> list[str]:
        conn = self._conn()
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT TO_CHAR(COALESCE(queued_at, created_at), 'YYYY-MM-DD') AS day
                    FROM jobs
                    WHERE status IN ('queued', 'processing')
                    ORDER BY day DESC
                    """
                )
                return [str(row[0]) for row in cur.fetchall() if row and row[0]]
        except Exception as exc:
            self.logger.warning("Error listando dias de cola en PG: %s", exc)
            return []
        finally:
            conn.close()

    def list_current(self, *, day: str | None = None, page: int, page_size: int) -> dict[str, Any]:
        offset = max(0, (page - 1) * page_size)
        conn = self._conn()
        if conn is None:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        site_expr = self._site_expr()
        resource_expr = self._resource_expr()
        protocol_expr = self._protocol_expr()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM jobs
                    WHERE status IN ('queued', 'processing')
                    """
                )
                total = int(cur.fetchone()[0] or 0)
                cur.execute(
                    f"""
                    SELECT
                        {site_expr} AS site_id,
                        {resource_expr} AS resource_id,
                        job_id,
                        {protocol_expr} AS protocol,
                        status AS state,
                        COALESCE(queued_at, created_at) AS started_at,
                        updated_at AS ended_at,
                        payload_json
                    FROM jobs
                    WHERE status IN ('queued', 'processing')
                    ORDER BY COALESCE(queued_at, created_at) DESC
                    LIMIT %s OFFSET %s
                    """,
                    (page_size, offset),
                )
                rows = cur.fetchall()
                items = [
                    {
                        "site_id": row[0],
                        "resource_id": row[1],
                        "job_id": row[2],
                        "protocol": row[3],
                        "state": row[4],
                        "day": (row[5].date().isoformat() if row[5] else ""),
                        "started_at": row[5].isoformat() if row[5] else None,
                        "ended_at": row[6].isoformat() if row[6] else None,
                        "payload": row[7],
                    }
                    for row in rows
                ]
                return {"items": items, "page": page, "page_size": page_size, "total": total}
        except Exception as exc:
            self.logger.warning("Error listando cola actual en PG: %s", exc)
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        finally:
            conn.close()

    def get_live(self, *, day: str) -> Optional[dict[str, Any]]:
        conn = self._conn()
        if conn is None:
            return None
        site_expr = self._site_expr()
        resource_expr = self._resource_expr()
        protocol_expr = self._protocol_expr()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        {site_expr} AS site_id,
                        {resource_expr} AS resource_id,
                        job_id,
                        {protocol_expr} AS protocol,
                        status AS state,
                        COALESCE(queued_at, created_at) AS started_at,
                        updated_at AS ended_at,
                        payload_json
                    FROM jobs
                    WHERE status = 'processing'
                      AND TO_CHAR(COALESCE(queued_at, created_at), 'YYYY-MM-DD') = %s
                    ORDER BY COALESCE(queued_at, created_at) DESC
                    LIMIT 1
                    """,
                    (day,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "site_id": row[0],
                    "resource_id": row[1],
                    "job_id": row[2],
                    "protocol": row[3],
                    "state": row[4],
                    "day": (row[5].date().isoformat() if row[5] else ""),
                    "started_at": row[5].isoformat() if row[5] else None,
                    "ended_at": row[6].isoformat() if row[6] else None,
                    "payload": row[7],
                }
        except Exception as exc:
            self.logger.warning("Error obteniendo tramite vivo en PG: %s", exc)
            return None
        finally:
            conn.close()

    def get_completion_marker(self, *, day: str) -> dict[str, Any]:
        conn = self._conn()
        empty = {
            "day": day, "completed_count": 0, "last_completed_at": None, "marker": "0|",
            "success_count": 0, "last_success": None,
        }
        if conn is None:
            return empty
        site_expr = self._site_expr()
        resource_expr = self._resource_expr()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS finished_count,
                        MAX(COALESCE(finished_at, updated_at, created_at)) AS last_finished_at
                    FROM jobs
                    WHERE status IN ('completed', 'succeeded', 'failed', 'dead', 'cancelled')
                      AND TO_CHAR(COALESCE(finished_at, updated_at, created_at), 'YYYY-MM-DD') = %s
                    """,
                    (day,),
                )
                row = cur.fetchone()
                finished_count = int(row[0] if row and row[0] is not None else 0)
                last_finished_at = row[1] if row else None
                marker = f"{finished_count}|{last_finished_at.isoformat() if last_finished_at else ''}"

                # Success-specific data for UI notifications
                cur.execute(
                    """
                    SELECT COUNT(*) FROM jobs
                    WHERE status IN ('completed', 'succeeded')
                      AND TO_CHAR(COALESCE(finished_at, updated_at, created_at), 'YYYY-MM-DD') = %s
                    """,
                    (day,),
                )
                srow = cur.fetchone()
                success_count = int(srow[0] if srow and srow[0] is not None else 0)

                last_success = None
                if success_count > 0:
                    cur.execute(
                        f"""
                        SELECT {site_expr} AS site_id,
                               {resource_expr} AS resource_id,
                               COALESCE(finished_at, updated_at, created_at) AS finished_at
                        FROM jobs
                        WHERE status IN ('completed', 'succeeded')
                          AND TO_CHAR(COALESCE(finished_at, updated_at, created_at), 'YYYY-MM-DD') = %s
                        ORDER BY COALESCE(finished_at, updated_at, created_at) DESC
                        LIMIT 1
                        """,
                        (day,),
                    )
                    lrow = cur.fetchone()
                    if lrow:
                        last_success = {
                            "site_id": str(lrow[0] or ""),
                            "resource_id": lrow[1],
                            "finished_at": lrow[2].isoformat() if lrow[2] else None,
                        }

                return {
                    "day": day,
                    "completed_count": finished_count,
                    "last_completed_at": (last_finished_at.isoformat() if last_finished_at else None),
                    "marker": marker,
                    "success_count": success_count,
                    "last_success": last_success,
                }
        except Exception as exc:
            self.logger.warning("Error obteniendo completion marker en PG: %s", exc)
            return empty
        finally:
            conn.close()

    def cancel_queue_item(self, *, site_id: str, resource_id: int) -> dict[str, Any]:
        conn = self._conn()
        if conn is None:
            return {"removed": False, "reason": "pg_unavailable"}
        site_expr = self._site_expr()
        resource_expr = self._resource_expr()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, job_id, status
                    FROM jobs
                    WHERE status IN ('queued', 'processing')
                      AND {site_expr} = %s
                      AND {resource_expr} = %s
                    ORDER BY COALESCE(queued_at, started_at, created_at) DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (str(site_id), int(resource_id)),
                )
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return {"removed": False, "reason": "not_found"}

                row_id = int(row[0])
                job_id = str(row[1] or "")
                status = str(row[2] or "").strip().lower()
                if status == "processing":
                    conn.rollback()
                    return {"removed": False, "reason": "processing", "job_id": job_id}

                cur.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled',
                        error_message = COALESCE(error_message, 'cancelled_by_dashboard'),
                        finished_at = COALESCE(finished_at, NOW()),
                        updated_at = NOW()
                    WHERE id = %s
                      AND status = 'queued'
                    """,
                    (row_id,),
                )
                removed = cur.rowcount > 0
                conn.commit()
                if not removed:
                    return {"removed": False, "reason": "state_conflict", "job_id": job_id}
                return {"removed": True, "reason": "removed", "job_id": job_id}
        except Exception as exc:
            conn.rollback()
            self.logger.warning("Error cancelando item de cola en PG: %s", exc)
            return {"removed": False, "reason": "error"}
        finally:
            conn.close()
