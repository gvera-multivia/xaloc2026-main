"""
Worker desatendido: procesa tareas desde SQLite sin interacción por consola.

Flujo:
- Lee una tarea 'pending' de db/xaloc_database.db
- La marca como 'processing' (claim atómico)
- Ejecuta el site con Playwright (perfil persistente)
- Marca 'completed' o 'failed' guardando screenshot/error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from core.site_registry import get_site, get_site_controller


SCHEMA_FALLBACK = """\
CREATE TABLE IF NOT EXISTS tramite_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    protocol TEXT,
    payload JSON NOT NULL,
    status TEXT DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    screenshot_path TEXT,
    error_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _configure_logging(*, log_file: Path | None) -> None:
    handlers: list[logging.Handler] = []
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    handlers.append(sh)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        handlers.append(fh)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        root.addHandler(h)

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")


def _ensure_db(conn: sqlite3.Connection, schema_path: Path) -> None:
    if schema_path.exists():
        schema = schema_path.read_text(encoding="utf-8")
    else:
        schema = SCHEMA_FALLBACK
    conn.executescript(schema)
    conn.commit()


def _connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resolve_under_base(path_value: str, base_dir: Path) -> Path:
    p = Path(path_value)
    return p if p.is_absolute() else (base_dir / p)


def _claim_next_task(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """
    Reclama una tarea de forma atómica (SQLite).
    Deja status='processing' y attempts += 1.
    """
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        """
        SELECT id, site_id, protocol, payload, attempts
        FROM tramite_queue
        WHERE status = 'pending'
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        conn.rollback()
        return None

    conn.execute(
        "UPDATE tramite_queue SET status='processing', attempts=attempts+1 WHERE id=?",
        (row["id"],),
    )
    conn.commit()
    return row


def _build_target(controller: Any, *, protocol: str | None, payload: dict[str, Any]) -> Any:
    mapper = getattr(controller, "map_data", None)
    kwargs = mapper(payload) if callable(mapper) else payload

    create_target = getattr(controller, "create_target", None) or getattr(controller, "create_demo_data", None)
    if not callable(create_target):
        raise RuntimeError(f"Controller sin create_target/create_demo_data: {type(controller).__name__}")

    if protocol is not None:
        kwargs = dict(kwargs)
        kwargs.setdefault("protocol", protocol)

    return create_target(**kwargs)


async def _process_one(
    *,
    db_path: Path,
    schema_path: Path,
    profile_dir: Path,
    headless: bool,
) -> bool:
    conn = _connect_db(db_path)
    try:
        _ensure_db(conn, schema_path)
        task = _claim_next_task(conn)
        if not task:
            return False

        task_id = int(task["id"])
        site_id = str(task["site_id"])
        protocol = task["protocol"]
        payload_raw = str(task["payload"])

        logging.info(f"Procesando tarea id={task_id} site_id={site_id} protocol={protocol or '-'}")

        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except Exception as e:
            error_text = f"InvalidPayloadJSON: {e}"
            conn.execute(
                "UPDATE tramite_queue SET status='failed', error_log=? WHERE id=?",
                (error_text, task_id),
            )
            conn.commit()
            return True

        controller = get_site_controller(site_id)
        config = controller.create_config(headless=headless)
        config.navegador.perfil_path = profile_dir

        target = _build_target(controller, protocol=protocol, payload=payload)

        AutomationCls = get_site(site_id)

        screenshot_path: str | None = None
        try:
            bot = AutomationCls(config)
            async with bot:
                screenshot_path = await bot.ejecutar_flujo_completo(target)
        except Exception as e:
            error_text = f"{type(e).__name__}: {e}"
            logging.exception(f"Error en tarea id={task_id}")
            try:
                if "bot" in locals():
                    err_shot = await bot.capture_error_screenshot(f"{site_id}_{task_id}_error.png")
                    if err_shot:
                        conn.execute(
                            "UPDATE tramite_queue SET screenshot_path=? WHERE id=?",
                            (str(err_shot), task_id),
                        )
            except Exception:
                pass
            conn.execute(
                "UPDATE tramite_queue SET status='failed', error_log=? WHERE id=?",
                (error_text, task_id),
            )
            conn.commit()
            return True

        conn.execute(
            "UPDATE tramite_queue SET status='completed', screenshot_path=? WHERE id=?",
            (screenshot_path, task_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Xaloc 2026 - Worker desatendido (SQLite + Playwright)")
    parser.add_argument("--db", default="db/xaloc_database.db", help="Ruta al archivo .db")
    parser.add_argument("--schema", default="db/schema.sql", help="Ruta al schema SQL")
    parser.add_argument("--profile-dir", default=os.getenv("XALOC_WORKER_PROFILE", "profiles/edge_worker"))
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--log-file", default="logs/worker.log", help="Ruta del log del worker")
    parser.add_argument("--once", action="store_true", help="Procesa como máximo 1 tarea y sale")

    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument("--headless", action="store_true", help="Forzar headless")
    headless_group.add_argument("--no-headless", action="store_true", help="Forzar visible (debug)")

    args = parser.parse_args()

    base_dir = _base_dir()

    log_file = _resolve_under_base(args.log_file, base_dir) if args.log_file else None
    _configure_logging(log_file=log_file)

    db_path = _resolve_under_base(args.db, base_dir)
    schema_path = _resolve_under_base(args.schema, base_dir)
    profile_dir = _resolve_under_base(args.profile_dir, base_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    headless = True
    if args.no_headless:
        headless = False
    if args.headless:
        headless = True

    logging.info(f"Worker iniciado | db={db_path} | profile={profile_dir} | headless={headless}")

    while True:
        did_work = await _process_one(
            db_path=db_path,
            schema_path=schema_path,
            profile_dir=profile_dir,
            headless=headless,
        )
        if args.once:
            return 0
        if not did_work:
            await asyncio.sleep(max(1, int(args.poll_seconds)))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
