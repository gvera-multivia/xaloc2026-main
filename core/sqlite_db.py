"""
Módulo de base de datos SQLite para la cola de trámites.
"""
import sqlite3
import json
import logging
import decimal
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

class SQLiteDatabase:
    def __init__(self, db_path: str = "db/xaloc_database.db"):
        self.db_path = Path(db_path)
        self.logger = logging.getLogger("sqlite_db")
        self._init_db()

    def _init_db(self) -> None:
        """Inicializa la base de datos aplicando el esquema si no existe."""
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self.get_connection()
        try:
            # Buscar el schema.sql en db/schema.sql relativo a la raíz
            schema_paths = [Path("db/schema.sql"), Path("db/schema_job_runs.sql")]
            applied_any_schema = False
            for schema_path in schema_paths:
                if not schema_path.exists():
                    continue
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = f.read()
                conn.executescript(schema)
                applied_any_schema = True

            if not applied_any_schema:
                # Fallback simple si no encuentra el archivo (aunque debería)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS tramite_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id TEXT NOT NULL,
                    protocol TEXT,
                    resource_id INTEGER,
                    payload JSON NOT NULL,
                    status TEXT DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    screenshot_path TEXT,
                    error_log TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP,
                    result JSON,
                    attachments_count INTEGER DEFAULT 0,
                    attachments_metadata JSON
                );
                """)
            self._apply_migrations(conn)
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error inicializando DB: {e}")
        finally:
            conn.close()

    def get_connection(self) -> sqlite3.Connection:
        """Devuelve una conexión a la base de datos."""
        return sqlite3.connect(self.db_path)

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """
        Aplica migraciones idempotentes sobre una DB existente.

        Nota: `schema.sql` solo crea tablas si no existen; si cambian columnas,
        hay que añadirlas vía ALTER.
        """
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(tramite_queue)")
        cols = {row[1] for row in cursor.fetchall()}  # (cid, name, type, notnull, dflt_value, pk)
        if "resource_id" not in cols:
            cursor.execute("ALTER TABLE tramite_queue ADD COLUMN resource_id INTEGER")

        # Reemplazar Ã­ndice antiguo (sin partial) por uno que dedupe solo tareas activas.
        cursor.execute("DROP INDEX IF EXISTS ux_tramite_queue_site_resource")
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_tramite_queue_site_resource_active
            ON tramite_queue(site_id, resource_id)
            WHERE resource_id IS NOT NULL AND status IN ('pending', 'processing')
            """
        )

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_authorization_queue'"
        )
        has_pending = cursor.fetchone() is not None
        if has_pending:
            cursor.execute("PRAGMA table_info(pending_authorization_queue)")
            pending_cols = {row[1] for row in cursor.fetchall()}
            if "resource_id" not in pending_cols:
                cursor.execute("ALTER TABLE pending_authorization_queue ADD COLUMN resource_id INTEGER")

        if has_pending:
            cursor.execute("DROP INDEX IF EXISTS ux_pending_authorization_site_resource")
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_authorization_site_resource_pending
                ON pending_authorization_queue(site_id, resource_id)
                WHERE resource_id IS NOT NULL AND status = 'pending'
                """
            )

        # Ampliar regex de Xaloc para aceptar expedientes con sufijo -SAD (y sin sufijo).
        cursor.execute(
            """
            UPDATE organismo_config
            SET regex_expediente = '^\\d{4}/\\d+(?:-(?:MUL|SAD))?$',
                updated_at = ?
            WHERE site_id = 'xaloc_girona'
              AND (
                    regex_expediente = '^\\d{4}/\\d{6}-MUL$'
                 OR regex_expediente = '^\\d{4}/\\d+-MUL$'
                 OR regex_expediente = '^\\d{4}/\\d+(?:-MUL)?$'
              )
            """,
            (datetime.now().isoformat(),),
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS job_runs (
                job_id TEXT PRIMARY KEY,
                site_id TEXT NOT NULL,
                resource_id INTEGER,
                protocol TEXT,
                state TEXT NOT NULL DEFAULT 'created',
                attempt INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                error_code TEXT,
                error_message TEXT,
                payload_snapshot JSON,
                result_snapshot JSON,
                worker_id TEXT,
                trace_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                queued_at TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_job_runs_site_state
            ON job_runs(site_id, state)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS incidencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idRecurso INTEGER,
                nExp TEXT,
                tipo_incidencia TEXT NOT NULL,
                motivo TEXT,
                site_id TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_incidencias_site_tipo_time
            ON incidencias(site_id, tipo_incidencia, timestamp)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS blocked_resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                resource_id INTEGER NOT NULL,
                reason TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_blocked_resources_site_resource
            ON blocked_resources(site_id, resource_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_blocked_resources_site_time
            ON blocked_resources(site_id, created_at)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS site_processing_pauses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL UNIQUE,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_site_processing_pauses_expires
            ON site_processing_pauses(expires_at)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_processing_pauses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                resource_id INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_resource_processing_pauses_site_resource
            ON resource_processing_pauses(site_id, resource_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_resource_processing_pauses_expires
            ON resource_processing_pauses(expires_at)
            """
        )

    def get_pending_task(self) -> Optional[Tuple[int, str, str, Dict[str, Any]]]:
        """
        Busca y reserva la siguiente tarea pendiente.
        Retorna (id, site_id, protocol, payload) o None.
        Marca la tarea como 'processing' de forma atómica.
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            # Transacción inmediata para evitar condiciones de carrera
            cursor.execute("BEGIN IMMEDIATE")

            now_iso = datetime.now().isoformat()
            cursor.execute(
                """
                SELECT id, site_id, protocol, payload
                FROM tramite_queue
                WHERE status = 'pending'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM site_processing_pauses spp
                      WHERE spp.site_id = tramite_queue.site_id
                        AND (spp.expires_at IS NULL OR spp.expires_at > ?)
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM resource_processing_pauses rpp
                      WHERE rpp.site_id = tramite_queue.site_id
                        AND rpp.resource_id = tramite_queue.resource_id
                        AND (rpp.expires_at IS NULL OR rpp.expires_at > ?)
                  )
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now_iso, now_iso),
            )
            row = cursor.fetchone()

            if row:
                task_id = row['id']
                cursor.execute("""
                    UPDATE tramite_queue
                    SET status = 'processing',
                        processed_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), task_id))
                conn.commit()

                payload = json.loads(row['payload'])
                return task_id, row['site_id'], row['protocol'], payload

            conn.commit()
            return None

        except Exception as e:
            self.logger.error(f"Error obteniendo tarea pendiente: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()

    def update_task_status(self, task_id: int, status: str, result: Optional[Dict] = None, error: Optional[str] = None, screenshot: Optional[str] = None) -> None:
        """
        Actualiza el estado de una tarea (completed/failed).
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            update_fields = ["status = ?", "processed_at = ?"]
            params = [status, datetime.now().isoformat()]

            if result:
                update_fields.append("result = ?")
                params.append(json.dumps(result, cls=DecimalEncoder))

            if error:
                update_fields.append("error_log = ?")
                params.append(error)

            if screenshot:
                update_fields.append("screenshot_path = ?")
                params.append(screenshot)

            params.append(task_id)

            query = f"UPDATE tramite_queue SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()

        except Exception as e:
            self.logger.error(f"Error actualizando tarea {task_id}: {e}")
        finally:
            conn.close()

    def insert_task(self, site_id: str, protocol: Optional[str], payload: Dict[str, Any]) -> int:
        """
        Inserta una nueva tarea en la cola.
        """
        resource_id = payload.get("idRecurso")
        try:
            if resource_id is not None:
                resource_id = int(resource_id)
        except Exception:
            resource_id = None

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tramite_queue (site_id, protocol, resource_id, payload)
                VALUES (?, ?, ?, ?)
            """, (site_id, protocol, resource_id, json.dumps(payload, cls=DecimalEncoder)))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if resource_id is None:
                raise
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id
                FROM tramite_queue
                WHERE site_id = ?
                  AND resource_id = ?
                  AND status IN ('pending', 'processing')
                ORDER BY id DESC
                LIMIT 1
                """,
                (site_id, resource_id),
            )
            row = cursor.fetchone()
            existing_id = int(row[0]) if row else -1
            self.logger.info(
                "Duplicado evitado en tramite_queue: site_id=%s resource_id=%s (task_id=%s)",
                site_id,
                resource_id,
                existing_id,
            )
            return existing_id
        except Exception as e:
            self.logger.error(f"Error insertando tarea: {e}")
            raise
        finally:
            conn.close()

    def count_tasks(self, site_id: str, statuses: tuple[str, ...] = ("pending", "processing")) -> int:
        """Cuenta tareas por site y status."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(statuses))
            cursor.execute(
                f"SELECT COUNT(*) FROM tramite_queue WHERE site_id = ? AND status IN ({placeholders})",
                (site_id, *statuses),
            )
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def count_tasks_any(self, statuses: tuple[str, ...] = ("pending", "processing")) -> Dict[str, int]:
        """Cuenta tareas agrupadas por site_id para los status indicados."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(statuses))
            cursor.execute(
                f"""
                SELECT site_id, COUNT(*) as c
                FROM tramite_queue
                WHERE status IN ({placeholders})
                GROUP BY site_id
                """,
                statuses,
            )
            return {str(site_id): int(c) for site_id, c in cursor.fetchall()}
        finally:
            conn.close()

    def requeue_task(self, task_id: int, error: Optional[str] = None) -> None:
        """Devuelve una tarea en processing a pending para reintento."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE tramite_queue
                SET status = 'pending',
                    processed_at = NULL,
                    error_log = ?,
                    attempts = COALESCE(attempts, 0) + 1
                WHERE id = ?
                """,
                ((error or "").strip() or None, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def has_active_task_for_resource(
        self,
        site_id: str,
        resource_id: int,
        statuses: tuple[str, ...] = ("pending", "processing"),
    ) -> bool:
        """Indica si ya existe una tarea activa para (site_id, resource_id)."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(statuses))
            cursor.execute(
                f"""
                SELECT 1
                FROM tramite_queue
                WHERE site_id = ?
                  AND resource_id = ?
                  AND status IN ({placeholders})
                LIMIT 1
                """,
                (site_id, int(resource_id), *statuses),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def has_pending_authorization_for_resource(self, site_id: str, resource_id: int) -> bool:
        """Indica si ya existe autorización pendiente para (site_id, resource_id)."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM pending_authorization_queue
                WHERE site_id = ?
                  AND resource_id = ?
                  AND status = 'pending'
                LIMIT 1
                """,
                (site_id, int(resource_id)),
            )
            return cursor.fetchone() is not None
        except sqlite3.OperationalError:
            # Si la tabla aún no existe en una DB antigua, asumimos que no hay pendientes.
            return False
        finally:
            conn.close()

    def get_locked_site_by_priority(
        self,
        priorities: Dict[str, int],
        statuses: tuple[str, ...] = ("pending", "processing"),
    ) -> Optional[str]:
        """
        Devuelve el site_id que debe quedar "lockeado" segÃºn prioridad,
        si hay tareas pendientes/en proceso en la cola.
        """
        counts = self.count_tasks_any(statuses=statuses)
        candidates = [s for s, c in counts.items() if c > 0]
        if not candidates:
            return None
        return sorted(candidates, key=lambda s: (priorities.get(s, 999), s))[0]

    # ==========================================================================
    # METODOS PARA JOB_RUNS (LEDGER)
    # ==========================================================================

    def upsert_job_run(
        self,
        *,
        job_id: str,
        site_id: str,
        resource_id: Optional[int],
        protocol: Optional[str],
        payload_snapshot: Optional[Dict[str, Any]],
        state: str,
        attempt: int = 0,
        max_attempts: int = 3,
        trace_id: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            queued_at = now if state == "queued" else None
            started_at = now if state == "processing" else None
            finished_at = now if state in {"completed", "failed", "dead", "cancelled"} else None
            cursor.execute(
                """
                INSERT INTO job_runs (
                    job_id, site_id, resource_id, protocol, state, attempt, max_attempts,
                    payload_snapshot, trace_id, queued_at, started_at, finished_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    site_id=excluded.site_id,
                    resource_id=excluded.resource_id,
                    protocol=excluded.protocol,
                    state=excluded.state,
                    attempt=excluded.attempt,
                    max_attempts=excluded.max_attempts,
                    payload_snapshot=COALESCE(excluded.payload_snapshot, job_runs.payload_snapshot),
                    trace_id=COALESCE(excluded.trace_id, job_runs.trace_id),
                    queued_at=COALESCE(excluded.queued_at, job_runs.queued_at),
                    started_at=COALESCE(excluded.started_at, job_runs.started_at),
                    finished_at=COALESCE(excluded.finished_at, job_runs.finished_at),
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    site_id,
                    resource_id,
                    protocol,
                    state,
                    attempt,
                    max_attempts,
                    json.dumps(payload_snapshot, cls=DecimalEncoder) if payload_snapshot is not None else None,
                    trace_id,
                    queued_at,
                    started_at,
                    finished_at,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def update_job_run_state(
        self,
        job_id: str,
        state: str,
        *,
        attempt: Optional[int] = None,
        started: bool = False,
        finished: bool = False,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        worker_id: Optional[str] = None,
        result_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            fields = ["state = ?", "updated_at = ?"]
            params: list[Any] = [state, datetime.now().isoformat()]

            if attempt is not None:
                fields.append("attempt = ?")
                params.append(int(attempt))

            if started:
                fields.append("started_at = ?")
                params.append(datetime.now().isoformat())

            if state == "queued":
                fields.append("queued_at = ?")
                params.append(datetime.now().isoformat())

            if finished:
                fields.append("finished_at = ?")
                params.append(datetime.now().isoformat())

            if error_code is not None:
                fields.append("error_code = ?")
                params.append(error_code)

            if error_message is not None:
                fields.append("error_message = ?")
                params.append(error_message)

            if worker_id is not None:
                fields.append("worker_id = ?")
                params.append(worker_id)

            if result_snapshot is not None:
                fields.append("result_snapshot = ?")
                params.append(json.dumps(result_snapshot, cls=DecimalEncoder))

            params.append(job_id)
            cursor.execute(f"UPDATE job_runs SET {', '.join(fields)} WHERE job_id = ?", params)
            conn.commit()
        finally:
            conn.close()

    def get_job_run(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM job_runs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def count_job_runs(self, site_id: str, states: tuple[str, ...]) -> int:
        if not states:
            return 0
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(states))
            cursor.execute(
                f"SELECT COUNT(*) FROM job_runs WHERE site_id = ? AND state IN ({placeholders})",
                (site_id, *states),
            )
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def count_job_runs_any(self, states: tuple[str, ...]) -> Dict[str, int]:
        if not states:
            return {}
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(states))
            cursor.execute(
                f"""
                SELECT site_id, COUNT(*) as c
                FROM job_runs
                WHERE state IN ({placeholders})
                GROUP BY site_id
                """,
                states,
            )
            return {str(site_id): int(c) for site_id, c in cursor.fetchall()}
        finally:
            conn.close()

    # ==========================================================================
    # METODOS PARA INCIDENCIAS
    # ==========================================================================

    def add_incident(
        self,
        *,
        id_recurso: Optional[int],
        n_exp: Optional[str],
        tipo: str,
        motivo: Optional[str],
        site_id: Optional[str],
    ) -> int:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO incidencias (idRecurso, nExp, tipo_incidencia, motivo, site_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(id_recurso) if id_recurso is not None else None,
                    (n_exp or "").strip() or None,
                    str(tipo),
                    (motivo or "").strip() or None,
                    (site_id or "").strip() or None,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def list_incidents(
        self,
        *,
        site_id: Optional[str] = None,
        tipo: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            clauses = []
            params: list[Any] = []
            if site_id:
                clauses.append("site_id = ?")
                params.append(site_id)
            if tipo:
                clauses.append("tipo_incidencia = ?")
                params.append(tipo)

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            cursor.execute(
                f"""
                SELECT id, idRecurso, nExp, tipo_incidencia, motivo, site_id, timestamp
                FROM incidencias
                {where_sql}
                ORDER BY timestamp ASC, id ASC
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==========================================================================
    # METODOS PARA RECURSOS BLOQUEADOS
    # ==========================================================================

    def block_resource(
        self,
        *,
        site_id: str,
        resource_id: int,
        reason: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO blocked_resources (site_id, resource_id, reason, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, resource_id) DO UPDATE SET
                    reason = excluded.reason,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    str(site_id),
                    int(resource_id),
                    (reason or "").strip() or None,
                    (source or "").strip() or None,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def is_resource_blocked(self, *, site_id: str, resource_id: int) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM blocked_resources
                WHERE site_id = ?
                  AND resource_id = ?
                LIMIT 1
                """,
                (str(site_id), int(resource_id)),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    # ==========================================================================
    # MÉTODOS PARA ORGANISMO_CONFIG
    # ==========================================================================

    def set_site_processing_pause(
        self,
        *,
        site_id: str,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO site_processing_pauses (site_id, reason, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(site_id) DO UPDATE SET
                    reason = excluded.reason,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    str(site_id),
                    (reason or "").strip() or None,
                    now,
                    now,
                    (expires_at or "").strip() or None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def clear_site_processing_pause(self, *, site_id: str) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM site_processing_pauses
                WHERE site_id = ?
                """,
                (str(site_id),),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def is_site_processing_paused(self, *, site_id: str) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                SELECT 1
                FROM site_processing_pauses
                WHERE site_id = ?
                  AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (str(site_id), now),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def list_site_processing_pauses(self, *, active_only: bool = True) -> list[Dict[str, Any]]:
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            if active_only:
                cursor.execute(
                    """
                    SELECT site_id, reason, created_at, updated_at, expires_at
                    FROM site_processing_pauses
                    WHERE expires_at IS NULL OR expires_at > ?
                    ORDER BY site_id ASC
                    """,
                    (now,),
                )
            else:
                cursor.execute(
                    """
                    SELECT site_id, reason, created_at, updated_at, expires_at
                    FROM site_processing_pauses
                    ORDER BY site_id ASC
                    """
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def set_resource_processing_pause(
        self,
        *,
        site_id: str,
        resource_id: int,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO resource_processing_pauses (site_id, resource_id, reason, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, resource_id) DO UPDATE SET
                    reason = excluded.reason,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    str(site_id),
                    int(resource_id),
                    (reason or "").strip() or None,
                    now,
                    now,
                    (expires_at or "").strip() or None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def clear_resource_processing_pause(self, *, site_id: str, resource_id: int) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM resource_processing_pauses
                WHERE site_id = ?
                  AND resource_id = ?
                """,
                (str(site_id), int(resource_id)),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def is_resource_processing_paused(self, *, site_id: str, resource_id: int) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                SELECT 1
                FROM resource_processing_pauses
                WHERE site_id = ?
                  AND resource_id = ?
                  AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (str(site_id), int(resource_id), now),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def list_resource_processing_pauses(self, *, active_only: bool = True) -> list[Dict[str, Any]]:
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            if active_only:
                cursor.execute(
                    """
                    SELECT site_id, resource_id, reason, created_at, updated_at, expires_at
                    FROM resource_processing_pauses
                    WHERE expires_at IS NULL OR expires_at > ?
                    ORDER BY site_id ASC, resource_id ASC
                    """,
                    (now,),
                )
            else:
                cursor.execute(
                    """
                    SELECT site_id, resource_id, reason, created_at, updated_at, expires_at
                    FROM resource_processing_pauses
                    ORDER BY site_id ASC, resource_id ASC
                    """
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def remove_pending_queue_item(self, *, site_id: str, resource_id: int) -> Dict[str, Any]:
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT id, status, payload
                FROM tramite_queue
                WHERE site_id = ?
                  AND resource_id = ?
                  AND status IN ('pending', 'processing')
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (str(site_id), int(resource_id)),
            )
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return {"removed": False, "reason": "not_found"}

            status = str(row["status"])
            if status != "pending":
                conn.commit()
                return {"removed": False, "reason": f"status_{status}"}

            queue_ref = int(row["id"])
            payload_raw = row["payload"] or "{}"
            try:
                payload_obj = json.loads(payload_raw)
            except Exception:
                payload_obj = {}
            job_id = str(payload_obj.get("job_id") or f"sqlite-task-{queue_ref}")

            cursor.execute("DELETE FROM tramite_queue WHERE id = ?", (queue_ref,))
            conn.commit()
            return {"removed": True, "queue_ref": queue_ref, "job_id": job_id}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_active_organismo_configs(self) -> list[Dict[str, Any]]:
        """
        Retorna todas las configuraciones de organismos activos.
        
        Returns:
            Lista de dicts con: site_id, query_organisme, filtro_texp, 
            regex_expediente, login_url, recursos_url
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT site_id, query_organisme, filtro_texp, 
                       regex_expediente, login_url, recursos_url
                FROM organismo_config
                WHERE active = 1
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def update_last_sync(self, site_id: str) -> None:
        """Actualiza el timestamp de última sincronización."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE organismo_config
                SET last_sync_at = ?, updated_at = ?
                WHERE site_id = ?
            """, (datetime.now().isoformat(), datetime.now().isoformat(), site_id))
            conn.commit()
        finally:
            conn.close()
    
    def insert_organismo_config(self, config: Dict[str, Any]) -> int:
        """Inserta una nueva configuración de organismo."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO organismo_config (
                    site_id, query_organisme, filtro_texp, 
                    regex_expediente, login_url, recursos_url, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                config['site_id'],
                config['query_organisme'],
                config['filtro_texp'],
                config['regex_expediente'],
                config['login_url'],
                config['recursos_url'],
                config.get('active', 1)
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def upsert_organismo_config(self, config: Dict[str, Any]) -> int:
        """
        Inserta o actualiza una configuración de organismo (por site_id).

        Returns:
            ID de la fila en organismo_config.
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM organismo_config WHERE site_id = ?", (config["site_id"],))
            row = cursor.fetchone()
            if row:
                config_id = int(row["id"])
                cursor.execute(
                    """
                    UPDATE organismo_config
                    SET query_organisme = ?,
                        filtro_texp = ?,
                        regex_expediente = ?,
                        login_url = ?,
                        recursos_url = ?,
                        active = ?,
                        updated_at = ?
                    WHERE site_id = ?
                    """,
                    (
                        config["query_organisme"],
                        config["filtro_texp"],
                        config["regex_expediente"],
                        config["login_url"],
                        config["recursos_url"],
                        config.get("active", 1),
                        datetime.now().isoformat(),
                        config["site_id"],
                    ),
                )
                conn.commit()
                return config_id

            cursor.execute(
                """
                INSERT INTO organismo_config (
                    site_id, query_organisme, filtro_texp,
                    regex_expediente, login_url, recursos_url, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    config["site_id"],
                    config["query_organisme"],
                    config["filtro_texp"],
                    config["regex_expediente"],
                    config["login_url"],
                    config["recursos_url"],
                    config.get("active", 1),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    # ==========================================================================
    # MÉTODOS PARA PENDING_AUTHORIZATION_QUEUE (GESDOC)
    # ==========================================================================

    def insert_pending_authorization(
        self, 
        site_id: str, 
        payload: Dict[str, Any], 
        authorization_type: str = "gesdoc",
        reason: Optional[str] = None
    ) -> int:
        """
        Inserta una tarea que requiere autorización externa antes de procesarse.
        
        Args:
            site_id: ID del site (ej: 'xaloc_girona')
            payload: Datos del trámite
            authorization_type: Tipo de autorización ('gesdoc', 'manual', etc.)
            reason: Motivo por el que requiere autorización
        
        Returns:
            ID de la tarea insertada
        """
        resource_id = payload.get("idRecurso")
        try:
            if resource_id is not None:
                resource_id = int(resource_id)
        except Exception:
            resource_id = None

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pending_authorization_queue 
                (site_id, resource_id, payload, authorization_type, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (site_id, resource_id, json.dumps(payload, cls=DecimalEncoder), authorization_type, reason))
            conn.commit()
            self.logger.info(f"Tarea añadida a pending_authorization_queue: {cursor.lastrowid} (tipo: {authorization_type})")
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if resource_id is None:
                raise
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id
                FROM pending_authorization_queue
                WHERE site_id = ?
                  AND resource_id = ?
                  AND status = 'pending'
                ORDER BY id DESC
                LIMIT 1
                """,
                (site_id, resource_id),
            )
            row = cursor.fetchone()
            existing_id = int(row[0]) if row else -1
            self.logger.info(
                "Duplicado evitado en pending_authorization_queue: site_id=%s resource_id=%s (pending_id=%s)",
                site_id,
                resource_id,
                existing_id,
            )
            return existing_id
        except Exception as e:
            self.logger.error(f"Error insertando tarea de autorización pendiente: {e}")
            raise
        finally:
            conn.close()

    def get_pending_authorizations(self, authorization_type: Optional[str] = None) -> list[Dict[str, Any]]:
        """
        Obtiene todas las tareas pendientes de autorización.
        
        Args:
            authorization_type: Filtrar por tipo (ej: 'gesdoc'). None = todos.
        
        Returns:
            Lista de tareas pendientes de autorización
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            if authorization_type:
                cursor.execute("""
                    SELECT id, site_id, payload, authorization_type, reason, 
                           status, created_at, notes
                    FROM pending_authorization_queue
                    WHERE status = 'pending' AND authorization_type = ?
                    ORDER BY created_at ASC
                """, (authorization_type,))
            else:
                cursor.execute("""
                    SELECT id, site_id, payload, authorization_type, reason, 
                           status, created_at, notes
                    FROM pending_authorization_queue
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                """)
            
            results = []
            for row in cursor.fetchall():
                item = dict(row)
                item['payload'] = json.loads(item['payload'])
                results.append(item)
            return results
        finally:
            conn.close()

    def authorize_and_move_to_queue(self, pending_id: int, authorized_by: str = "system") -> Optional[int]:
        """
        Autoriza una tarea pendiente y la mueve a la cola principal (tramite_queue).
        
        Args:
            pending_id: ID de la tarea en pending_authorization_queue
            authorized_by: Usuario/sistema que autoriza
        
        Returns:
            ID de la nueva tarea en tramite_queue, o None si falló
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            
            # Obtener la tarea pendiente
            cursor.execute("""
                SELECT site_id, resource_id, payload FROM pending_authorization_queue
                WHERE id = ? AND status = 'pending'
            """, (pending_id,))
            row = cursor.fetchone()
            
            if not row:
                self.logger.warning(f"Tarea pendiente {pending_id} no encontrada o ya procesada")
                conn.rollback()
                return None
             
            site_id = row["site_id"]
            resource_id = row["resource_id"]
            queue_backend = (os.getenv("QUEUE_BACKEND", "sqlite") or "sqlite").strip().lower()
            if queue_backend == "redis":
                from core.queue_gateway import build_queue_gateway

                payload = json.loads(row["payload"])
                queue_gateway = build_queue_gateway(backend=queue_backend, db=self)
                enqueued, job_id = asyncio.run(
                    queue_gateway.enqueue(site_id=site_id, protocol=None, payload=payload)
                )
                new_task_id = -1
                self.logger.info(
                    "Tarea autorizada publicada en Redis: pending_id=%s job_id=%s enqueued=%s",
                    pending_id,
                    job_id,
                    enqueued,
                )
            else:
                try:
                    cursor.execute(
                        """
                        INSERT INTO tramite_queue (site_id, resource_id, payload)
                        VALUES (?, ?, ?)
                        """,
                        (site_id, resource_id, row["payload"]),
                    )
                    new_task_id = cursor.lastrowid
                except sqlite3.IntegrityError:
                    cursor.execute(
                        """
                        SELECT id
                        FROM tramite_queue
                        WHERE site_id = ?
                          AND resource_id = ?
                          AND status IN ('pending', 'processing')
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (site_id, resource_id),
                    )
                    existing = cursor.fetchone()
                    if not existing:
                        raise
                    new_task_id = int(existing[0])
                    self.logger.info(
                        "Duplicado evitado al mover de pending_authorization_queue a tramite_queue: site_id=%s resource_id=%s (task_id=%s)",
                        site_id,
                        resource_id,
                        new_task_id,
                    )
             
            # Actualizar estado en pending_authorization_queue
            cursor.execute("""
                UPDATE pending_authorization_queue
                SET status = 'moved_to_queue',
                    authorized_by = ?,
                    authorized_at = ?
                WHERE id = ?
            """, (authorized_by, datetime.now().isoformat(), pending_id))
            
            conn.commit()
            self.logger.info(f"Tarea {pending_id} autorizada y movida a tramite_queue como {new_task_id}")
            return new_task_id
            
        except Exception as e:
            self.logger.error(f"Error autorizando tarea {pending_id}: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def reject_pending_authorization(self, pending_id: int, reason: str, rejected_by: str = "system") -> bool:
        """
        Rechaza una tarea pendiente de autorización.
        
        Args:
            pending_id: ID de la tarea
            reason: Motivo del rechazo
            rejected_by: Usuario que rechaza
        
        Returns:
            True si se rechazó correctamente
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE pending_authorization_queue
                SET status = 'rejected',
                    authorized_by = ?,
                    authorized_at = ?,
                    notes = ?
                WHERE id = ? AND status = 'pending'
            """, (rejected_by, datetime.now().isoformat(), reason, pending_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def count_pending_authorizations(self, authorization_type: Optional[str] = None) -> int:
        """Cuenta las tareas pendientes de autorización."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if authorization_type:
                cursor.execute("""
                    SELECT COUNT(*) FROM pending_authorization_queue
                    WHERE status = 'pending' AND authorization_type = ?
                """, (authorization_type,))
            else:
                cursor.execute("""
                    SELECT COUNT(*) FROM pending_authorization_queue
                    WHERE status = 'pending'
                """)
            return cursor.fetchone()[0]
        finally:
            conn.close()
