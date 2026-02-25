#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import psycopg

from core.runtime_flags import get_report_pg_dsn


@dataclass(frozen=True)
class CleanupScope:
    site_id: str | None
    resource_id: int | None


def _build_where(scope: CleanupScope) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if scope.site_id:
        clauses.append("lower(btrim(site_id)) = lower(btrim(%s))")
        params.append(scope.site_id)
    if scope.resource_id is not None:
        clauses.append("resource_id = %s")
        params.append(int(scope.resource_id))
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _print_summary(conn: psycopg.Connection, scope: CleanupScope) -> None:
    where_sql, params = _build_where(scope)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY lower(btrim(site_id)), resource_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM pending_authorization_queue
                {where_sql}
            )
            SELECT
                (SELECT count(*) FROM pending_authorization_queue {where_sql}) AS total_rows,
                count(*) FILTER (WHERE rn > 1) AS duplicate_rows
            FROM ranked
            """,
            params + params,
        )
        row = cur.fetchone()
        total_rows = int(row[0] or 0)
        duplicate_rows = int(row[1] or 0)
    print(f"[INFO] total_rows={total_rows} duplicate_rows={duplicate_rows}")


def _print_sample_duplicates(conn: psycopg.Connection, scope: CleanupScope, limit: int) -> None:
    where_sql, params = _build_where(scope)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    site_id,
                    resource_id,
                    status,
                    created_at,
                    updated_at,
                    row_number() OVER (
                        PARTITION BY lower(btrim(site_id)), resource_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM pending_authorization_queue
                {where_sql}
            )
            SELECT id, site_id, resource_id, status, created_at, updated_at, rn
            FROM ranked
            WHERE rn > 1
            ORDER BY site_id, resource_id, created_at DESC, id DESC
            LIMIT %s
            """,
            params + [int(limit)],
        )
        rows = cur.fetchall()
    if not rows:
        print("[INFO] No hay duplicados para mostrar.")
        return
    print("[INFO] Muestra de duplicados (se eliminarian):")
    for r in rows:
        print(
            f"  id={r[0]} site_id={r[1]} resource_id={r[2]} status={r[3]} "
            f"created_at={r[4]} updated_at={r[5]} rn={r[6]}"
        )


def _delete_duplicates(conn: psycopg.Connection, scope: CleanupScope) -> int:
    where_sql, params = _build_where(scope)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY lower(btrim(site_id)), resource_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM pending_authorization_queue
                {where_sql}
            )
            DELETE FROM pending_authorization_queue p
            USING ranked r
            WHERE p.id = r.id
              AND r.rn > 1
            """,
            params,
        )
        deleted = int(cur.rowcount or 0)
    conn.commit()
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Limpia duplicados en pending_authorization_queue conservando la fila "
            "mas reciente por (site_id normalizado, resource_id)."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Aplica borrado real. Sin esto es dry-run.")
    parser.add_argument("--site-id", type=str, default=None, help="Filtra por site_id (opcional).")
    parser.add_argument("--resource-id", type=int, default=None, help="Filtra por resource_id (opcional).")
    parser.add_argument("--sample-limit", type=int, default=30, help="Cuantos duplicados mostrar en preview.")
    args = parser.parse_args()

    dsn = get_report_pg_dsn()
    if not dsn:
        print("[ERROR] REPORT_PG_DSN/PG_DSN no configurado.")
        return 1

    scope = CleanupScope(
        site_id=(args.site_id or "").strip() or None,
        resource_id=args.resource_id,
    )

    with psycopg.connect(dsn) as conn:
        _print_summary(conn, scope)
        _print_sample_duplicates(conn, scope, limit=max(1, int(args.sample_limit)))
        if not args.apply:
            print("[DRY-RUN] Sin cambios. Usa --apply para borrar duplicados.")
            return 0
        deleted = _delete_duplicates(conn, scope)
        print(f"[OK] Filas duplicadas eliminadas: {deleted}")
        _print_summary(conn, scope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

