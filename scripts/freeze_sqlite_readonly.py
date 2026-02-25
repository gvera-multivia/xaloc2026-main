from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path


def freeze_sqlite(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"No existe SQLite DB: {path}")

    current_mode = path.stat().st_mode
    readonly_mode = current_mode & ~(stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH)
    path.chmod(readonly_mode)

    wal = path.with_suffix(path.suffix + "-wal")
    shm = path.with_suffix(path.suffix + "-shm")
    for sidecar in (wal, shm):
        if sidecar.exists():
            side_mode = sidecar.stat().st_mode
            sidecar.chmod(side_mode & ~(stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH))


def main() -> None:
    parser = argparse.ArgumentParser(description="Congela un SQLite en modo read-only (backup temporal).")
    parser.add_argument("--db", default=os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db"), help="Ruta al archivo SQLite")
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    freeze_sqlite(db_path)
    print(f"SQLite congelada en read-only: {db_path}")
    print("Recuerda activar SQLITE_WRITES_ENABLED=0 en los servicios que compartan esta DB.")


if __name__ == "__main__":
    main()
