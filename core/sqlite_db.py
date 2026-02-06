"""
Módulo de base de datos SQLite para la cola de trámites.
"""
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

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
            schema_path = Path("db/schema.sql")
            if schema_path.exists():
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = f.read()
                conn.executescript(schema)
            else:
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

        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_tramite_queue_site_resource
            ON tramite_queue(site_id, resource_id)
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
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_authorization_site_resource
                ON pending_authorization_queue(site_id, resource_id)
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

            cursor.execute("""
                SELECT id, site_id, protocol, payload
                FROM tramite_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
            """)
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
                params.append(json.dumps(result))

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
            """, (site_id, protocol, resource_id, json.dumps(payload)))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if resource_id is None:
                raise
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM tramite_queue WHERE site_id = ? AND resource_id = ? ORDER BY id DESC LIMIT 1",
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
    # MÉTODOS PARA ORGANISMO_CONFIG
    # ==========================================================================

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
            """, (site_id, resource_id, json.dumps(payload), authorization_type, reason))
            conn.commit()
            self.logger.info(f"Tarea añadida a pending_authorization_queue: {cursor.lastrowid} (tipo: {authorization_type})")
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if resource_id is None:
                raise
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM pending_authorization_queue WHERE site_id = ? AND resource_id = ? ORDER BY id DESC LIMIT 1",
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
            
            # Insertar en tramite_queue
            cursor.execute("""
                INSERT INTO tramite_queue (site_id, resource_id, payload)
                VALUES (?, ?, ?)
            """, (row['site_id'], row['resource_id'], row['payload']))
            new_task_id = cursor.lastrowid
            
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
