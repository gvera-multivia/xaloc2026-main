#!/usr/bin/env python
"""
init_brain_config.py - Script de inicialización de configuración del Brain.

Este script:
1. Lee el archivo organismo_config.json
2. Inserta las configuraciones en la tabla organismo_config de SQLite
3. Verifica que la base de datos esté correctamente inicializada

Uso:
    python init_brain_config.py [--db-path db/xaloc_database.db]
"""

import argparse
import json
import sys
from pathlib import Path

from core.sqlite_db import SQLiteDatabase


def load_config_from_json(json_path: Path) -> list[dict]:
    """Carga las configuraciones desde el archivo JSON."""
    if not json_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return data.get("configs", [])


def init_brain_config(db_path: str, config_file: str = "organismo_config.json", *, upsert: bool = True):
    """Inicializa la configuración del brain en SQLite."""
    print("=" * 60)
    print("BRAIN INITIALIZER")
    print("=" * 60)
    
    # Cargar configuraciones desde JSON
    config_path = Path(config_file)
    print(f"\n> Loading config from: {config_path}")
    
    try:
        configs = load_config_from_json(config_path)
        print(f"OK Found {len(configs)} configs")
    except Exception as e:
        print(f"ERROR loading configs: {e}")
        return 1
    
    # Conectar a la base de datos
    print(f"\n> Connecting to SQLite: {db_path}")
    db = SQLiteDatabase(db_path)
    
    # Insertar configuraciones
    print("\n> Inserting configs...")
    inserted = 0
    skipped = 0
    
    for config in configs:
        site_id = config.get("site_id")
        try:
            if upsert:
                config_id = db.upsert_organismo_config(config)
                status = "ACTIVE" if config.get("active") else "INACTIVE"
                print(f"  {status} {site_id:20} -> ID {config_id} (upsert)")
                inserted += 1
            else:
                # Intentar insertar
                config_id = db.insert_organismo_config(config)
                status = "ACTIVE" if config.get("active") else "INACTIVE"
                print(f"  {status} {site_id:20} -> ID {config_id}")
                inserted += 1
        except Exception as e:
            # Si ya existe, saltarlo
            if "UNIQUE constraint failed" in str(e):
                print(f"  EXISTS  {site_id:20} (skipped)")
                skipped += 1
            else:
                print(f"  ERROR   {site_id:20} -> {e}")
    
    # Resumen
    print("\n" + "=" * 60)
    print(f"SUMMARY:")
    print(f"   Insertadas: {inserted}")
    print(f"   Saltadas:   {skipped}")
    print(f"   Total:      {len(configs)}")
    print("=" * 60)
    
    # Verificar configuraciones activas
    print("\n> Verifying active configs...")
    active_configs = db.get_active_organismo_configs()
    
    if active_configs:
        print(f"\nActive configs ({len(active_configs)}):")
        for cfg in active_configs:
            print(f"  - {cfg['site_id']}")
            print(f"    - Organismo: {cfg['query_organisme']}")
            print(f"    - TExp: {cfg['filtro_texp']}")
            print(f"    - Regex: {cfg['regex_expediente']}")
    else:
        print("\nWARN  No active configs")
    
    print("\nDone\n")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Inicializa la configuración del Brain Orchestrator"
    )
    parser.add_argument(
        "--db-path",
        default="db/xaloc_database.db",
        help="Ruta al archivo SQLite"
    )
    parser.add_argument(
        "--config-file",
        default="organismo_config.json",
        help="Ruta al archivo JSON de configuración"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--upsert",
        action="store_true",
        help="Actualiza/crea configs (default)",
    )
    group.add_argument(
        "--no-upsert",
        action="store_true",
        help="Solo inserta; si existe, se salta",
    )

    args = parser.parse_args()

    upsert = True
    if args.no_upsert:
        upsert = False

    return init_brain_config(args.db_path, args.config_file, upsert=upsert)


if __name__ == "__main__":
    sys.exit(main())
