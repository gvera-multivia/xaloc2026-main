from __future__ import annotations

import os
import sys

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency
    psycopg = None

from core.realtime_store import PostgresConfig, PostgresRealtimeStore


def _env(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


def _build_app_dsn() -> str:
    host = _env("REPORT_PG_HOST", "127.0.0.1")
    port = _env("REPORT_PG_PORT", "5432")
    dbname = _env("REPORT_PG_DB", "xaloc_realtime")
    user = _env("REPORT_PG_USER", "xaloc_app")
    password = _env("REPORT_PG_PASSWORD", "xaloc_app_2026")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _bootstrap_db_and_role(admin_dsn: str, app_db: str, app_user: str, app_password: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
            role_exists = cur.fetchone() is not None
            if not role_exists:
                cur.execute(f'CREATE ROLE "{app_user}" LOGIN PASSWORD %s', (app_password,))
            else:
                cur.execute(f'ALTER ROLE "{app_user}" WITH LOGIN PASSWORD %s', (app_password,))

            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (app_db,))
            db_exists = cur.fetchone() is not None
            if not db_exists:
                cur.execute(f'CREATE DATABASE "{app_db}" OWNER "{app_user}"')
            else:
                cur.execute(f'ALTER DATABASE "{app_db}" OWNER TO "{app_user}"')

            cur.execute(f'GRANT ALL PRIVILEGES ON DATABASE "{app_db}" TO "{app_user}"')


def main() -> int:
    if psycopg is None:
        print("ERROR: falta psycopg. Instala con: pip install psycopg[binary]")
        return 1

    app_db = _env("REPORT_PG_DB", "xaloc_realtime")
    app_user = _env("REPORT_PG_USER", "xaloc_app")
    app_password = _env("REPORT_PG_PASSWORD", "xaloc_app_2026")
    app_dsn = _build_app_dsn()
    admin_dsn = (os.getenv("REPORT_PG_ADMIN_DSN") or "").strip()

    if admin_dsn:
        _bootstrap_db_and_role(
            admin_dsn=admin_dsn,
            app_db=app_db,
            app_user=app_user,
            app_password=app_password,
        )
        print("OK: usuario/base PostgreSQL verificados.")
    else:
        print("INFO: REPORT_PG_ADMIN_DSN no definido; se asume que usuario/base ya existen.")

    store = PostgresRealtimeStore(config=PostgresConfig(dsn=app_dsn))
    store.ensure_schema()
    print("OK: esquema realtime creado/verificado.")
    print("REPORT_PG_DSN=" + app_dsn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

