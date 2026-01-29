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
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error inicializando DB: {e}")
        finally:
            conn.close()

    def get_connection(self) -> sqlite3.Connection:
        """Devuelve una conexión a la base de datos."""
        return sqlite3.connect(self.db_path)

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
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tramite_queue (site_id, protocol, payload)
                VALUES (?, ?, ?)
            """, (site_id, protocol, json.dumps(payload)))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Error insertando tarea: {e}")
            raise
        finally:
            conn.close()

    def get_organismo_config(self) -> Optional[Dict[str, Any]]:
        """
        Recupera la configuración centralizada del organismo.
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM organismo_config WHERE id = 1")
            row = cursor.fetchone()
            if row:
                data = dict(row)
                # Parse JSON fields
                for field in ['http_headers', 'timeouts', 'paths', 'selectors']:
                    if data.get(field):
                        try:
                            data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            data[field] = {}
                return data
            return None
        except Exception as e:
            self.logger.error(f"Error recuperando config: {e}")
            return None
        finally:
            conn.close()
