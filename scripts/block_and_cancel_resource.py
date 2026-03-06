#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg


@dataclass
class OperationResult:
    resource_id: int
    blocked: bool
    queue_cancelled: int
    drafts_cancelled: int


def _parse_ids(raw_values: Iterable[str]) -> list[int]:
    out: list[int] = []
    for raw in raw_values:
        for chunk in str(raw or "").split(","):
            text = chunk.strip()
            if not text:
                continue
            out.append(int(text))
    if not out:
        raise ValueError("Debes indicar al menos un idRecurso.")
    return out


def _get_dsn() -> str:
    dsn = (os.getenv("REPORT_PG_DSN") or os.getenv("PG_DSN") or "").strip()
    if dsn:
        return dsn

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            txt = line.strip()
            if not txt or txt.startswith("#") or "=" not in txt:
                continue
            key, value = txt.split("=", 1)
            k = key.strip()
            if k in {"REPORT_PG_DSN", "PG_DSN"}:
                dsn = value.strip().strip("\"").strip("'")
                if dsn:
                    return dsn

    if not dsn:
        raise RuntimeError("PG_DSN/REPORT_PG_DSN no disponible en entorno.")
    return dsn


def _block_and_cancel(
    conn: psycopg.Connection,
    *,
    site_id: str,
    resource_id: int,
    reason: str,
    source: str,
) -> OperationResult:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO blocked_resources (site_id, resource_id, reason, source, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (site_id, resource_id) DO UPDATE SET
                reason = EXCLUDED.reason,
                source = EXCLUDED.source,
                updated_at = NOW()
            """,
            (site_id, int(resource_id), reason, source),
        )

        cur.execute(
            """
            WITH target AS (
                SELECT id
                FROM jobs
                WHERE status IN ('queued', 'processing')
                  AND COALESCE(payload_json->>'site_id', NULLIF(split_part(dedup_key,':',1), ''), 'unknown') = %s
                  AND COALESCE(
                        CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$'
                            THEN (payload_json->>'idRecurso')::bigint END,
                        CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$'
                            THEN ((payload_json->>'idRecurso')::numeric)::bigint END,
                        CASE WHEN NULLIF(split_part(dedup_key,':',2), 'none') ~ '^[0-9]+$'
                            THEN split_part(dedup_key,':',2)::bigint END,
                        CASE WHEN NULLIF(split_part(dedup_key,':',2), 'none') ~ '^[0-9]+\\.0+$'
                            THEN (split_part(dedup_key,':',2)::numeric)::bigint END
                  ) = %s
            )
            UPDATE jobs j
            SET status = 'cancelled',
                error_message = COALESCE(NULLIF(j.error_message, ''), 'cancelled_by_manual_blacklist'),
                finished_at = COALESCE(j.finished_at, NOW()),
                updated_at = NOW()
            FROM target t
            WHERE j.id = t.id
            """,
            (site_id, int(resource_id)),
        )
        cancelled = int(cur.rowcount or 0)

        cur.execute(
            """
            UPDATE job_drafts
            SET status = 'cancelled',
                last_error = COALESCE(NULLIF(last_error, ''), 'cancelled_by_manual_blacklist'),
                updated_at = NOW()
            WHERE status IN ('validated_pending_batch', 'dispatched', 'dedup_active')
              AND COALESCE(normalized_payload_json->>'site_id', NULLIF(split_part(dedup_key,':',1), ''), 'unknown') = %s
              AND (
                    dedup_key LIKE (%s || ':' || %s || ':%%')
                 OR normalized_payload_json->>'idRecurso' IN (%s, (%s || '.0'))
                 OR external_resource_id = %s
              )
            """,
            (site_id, site_id, str(int(resource_id)), str(int(resource_id)), str(int(resource_id)), str(int(resource_id))),
        )
        drafts_cancelled = int(cur.rowcount or 0)

    return OperationResult(
        resource_id=int(resource_id),
        blocked=True,
        queue_cancelled=cancelled,
        drafts_cancelled=drafts_cancelled,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bloquea uno o varios idRecurso y los saca de cola activa (queued/processing)."
    )
    parser.add_argument(
        "resource_ids",
        nargs="+",
        help="idRecurso (admite varios y/o formato CSV, p.ej. 91216 91577 o 91216,91577)",
    )
    parser.add_argument("--site-id", default="redsara", help="site_id destino (default: redsara)")
    parser.add_argument("--reason", default="Bloqueo manual", help="Motivo para blocked_resources")
    parser.add_argument("--source", default="manual", help="Source para blocked_resources")
    args = parser.parse_args()

    site_id = str(args.site_id or "").strip()
    if not site_id:
        raise ValueError("site_id no puede estar vacio.")

    ids = _parse_ids(args.resource_ids)
    dsn = _get_dsn()

    results: list[OperationResult] = []
    with psycopg.connect(dsn) as conn:
        for rid in ids:
            results.append(
                _block_and_cancel(
                    conn,
                    site_id=site_id,
                    resource_id=rid,
                    reason=str(args.reason or "").strip() or "Bloqueo manual",
                    source=str(args.source or "").strip() or "manual",
                )
            )
        conn.commit()

    print(f"site_id={site_id}")
    for item in results:
        print(
            f"idRecurso={item.resource_id} blocked={item.blocked} "
            f"queue_cancelled={item.queue_cancelled} drafts_cancelled={item.drafts_cancelled}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
