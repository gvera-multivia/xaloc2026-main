#!/usr/bin/env python
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from core.sqlite_db import SQLiteDatabase
from core.sqlserver_utils import build_sqlserver_connection_string
from core.brain.orchestrator import BrainOrchestrator
from core.process_launcher import setup_asyncio_policy

# Load env vars
load_dotenv()

def main():
    setup_asyncio_policy()
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [BRAIN] - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/brain.log", encoding="utf-8")
        ]
    )

    parser = argparse.ArgumentParser(
        description="Brain Orchestrator - Gestor de recursos Xvia"
    )
    parser.add_argument(
        "--once", 
        action="store_true",
        help="Ejecutar un solo ciclo y salir"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No realizar cambios en las bases de datos"
    )
    parser.add_argument(
        "--sqlite-db",
        default=os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db"),
        help="Ruta al archivo SQLite"
    )
    
    args = parser.parse_args()
    
    XVIA_EMAIL = os.getenv("XVIA_EMAIL")
    XVIA_PASSWORD = os.getenv("XVIA_PASSWORD")

    if not XVIA_EMAIL or not XVIA_PASSWORD:
        logging.error("XVIA_EMAIL y XVIA_PASSWORD deben estar definidos en .env")
        sys.exit(1)
    
    db = SQLiteDatabase(args.sqlite_db)
    conn_str = build_sqlserver_connection_string()
    
    orchestrator = BrainOrchestrator(
        sqlite_db=db,
        sqlserver_conn_str=conn_str,
        dry_run=args.dry_run
    )
    
    if args.once:
        stats = asyncio.run(orchestrator.run_tick())
        print(f"Ciclo completado: {stats}")
    else:
        asyncio.run(orchestrator.run_forever())

if __name__ == "__main__":
    main()
