import sqlite3
import os

def clear_queues():
    db_path = "db/xaloc_database.db"
    if not os.path.exists(db_path):
        print(f"La base de datos {db_path} no existe.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. Limpiar cola normal
        cursor.execute("DELETE FROM tramite_queue")
        print("✓ Cola 'tramite_queue' vaciada.")
        
        # 2. Limpiar cola de autorizaciones pendientes
        cursor.execute("DELETE FROM pending_authorization_queue")
        print("✓ Cola 'pending_authorization_queue' vaciada.")
        
        # 3. Resetear contadores de ID (opcional)
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('tramite_queue', 'pending_authorization_queue')")
        
        conn.commit()
        print("\n✨ Todas las colas han sido limpiadas correctamente.")
    except Exception as e:
        print(f"Error limpiando colas: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    clear_queues()
