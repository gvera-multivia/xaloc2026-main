import decimal
import json
import os
import sys

# Añadir el directorio raíz al path para importar core
sys.path.append(os.getcwd())

from core.sqlite_db import SQLiteDatabase

def test_decimal_serialization():
    db_path = "db/test_decimal.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    db = SQLiteDatabase(db_path)
    
    # Payload con Decimal (lo que causaba el error)
    payload = {
        "idRecurso": decimal.Decimal("89157"),
        "amount": decimal.Decimal("120.50"),
        "description": "Test decimal task"
    }
    
    print(f"Intentando insertar payload con Decimal: {payload}")
    
    try:
        task_id = db.insert_task("test_site", "P1", payload)
        print(f"SUCCESS: Tarea insertada con ID {task_id}")
        
        # Verificar que se puede leer de vuelta (como float)
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT payload FROM tramite_queue WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        saved_payload = json.loads(row[0])
        print(f"Payload recuperado: {saved_payload}")
        
        if isinstance(saved_payload["idRecurso"], (int, float)):
            print("VERIFICATION SUCCESS: idRecurso recuperado como número.")
        else:
            print(f"ERROR: idRecurso recuperado como {type(saved_payload['idRecurso'])}")
            
    except TypeError as e:
        print(f"FAILED serialization: {e}")
    except Exception as e:
        print(f"ERROR unexpected: {e}")
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

if __name__ == "__main__":
    test_decimal_serialization()
