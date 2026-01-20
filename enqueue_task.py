import argparse
import json
import sys
from pathlib import Path
from core.sqlite_db import SQLiteDatabase

def main():
    parser = argparse.ArgumentParser(description="Encolar una nueva tarea en la DB.")
    parser.add_argument("--site", required=True, help="ID del sitio (madrid, base_online, xaloc_girona)")
    parser.add_argument("--protocol", help="Protocolo o subproceso (P1, P2, P3...)")
    parser.add_argument("--payload", required=True, help="JSON string con los datos o ruta a un archivo .json")

    args = parser.parse_args()

    # Parsear payload
    try:
        if args.payload.endswith(".json") and Path(args.payload).exists():
            with open(args.payload, "r", encoding="utf-8") as f:
                payload = json.load(f)
        else:
            payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        print(f"Error parseando JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error leyendo payload: {e}")
        sys.exit(1)

    db = SQLiteDatabase()
    try:
        task_id = db.insert_task(args.site, args.protocol, payload)
        print(f"Tarea insertada con éxito. ID: {task_id}")
        print(f"Site: {args.site}")
        print(f"Protocol: {args.protocol}")
        print(f"Payload keys: {list(payload.keys())}")
    except Exception as e:
        print(f"Error al insertar tarea: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
