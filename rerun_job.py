#!/usr/bin/env python
"""
rerun_job.py - Utilidad para reenviar un job a la cola (cambiar estado a 'pending').
"""

import argparse
import sys
import os
from pathlib import Path

# Añadir el raíz del proyecto al path
sys.path.append(os.getcwd())

from core.sqlite_db import SQLiteDatabase

def rerun_job(task_id: int, db_path: str = "db/xaloc_database.db"):
    db = SQLiteDatabase(db_path)
    
    # Comprobar si existe
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM tramite_queue WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    
    if not row:
        print(f"Error: No se encontró la tarea con ID {task_id}")
        conn.close()
        return False
    
    print(f"Tarea found: ID={row[0]}, Status actual={row[1]}")
    
    # Actualizar a pending
    cursor.execute("""
        UPDATE tramite_queue 
        SET status = 'pending', 
            processed_at = NULL, 
            error_log = NULL, 
            attempts = 0 
        WHERE id = ?
    """, (task_id,))
    
    conn.commit()
    print(f"SUCCESS: Tarea {task_id} marcada como 'pending'. El worker la procesará en breve.")
    conn.close()
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-ejecuta un job de xaloc")
    parser.add_argument("id", type=int, help="ID de la tarea en la tabla tramite_queue")
    parser.add_argument("--db", type=str, default="db/xaloc_database.db", help="Ruta a la base de datos SQLite")
    
    args = parser.parse_args()
    rerun_job(args.id, args.db)
