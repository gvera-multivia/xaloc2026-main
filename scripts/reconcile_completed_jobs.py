from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass

import psycopg
import pyodbc
import redis.asyncio as redis

from core.sqlserver_utils import build_sqlserver_connection_string


@dataclass(frozen=True)
class ActiveJob:
    job_id: str
    resource_id: int
    status: str


def _resource_id_expression() -> str:
    return """
        COALESCE(
            CASE
                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+(\\.0+)?$'
                    THEN ((payload_json->>'idRecurso')::numeric)::bigint
                ELSE NULL
            END,
            CASE
                WHEN split_part(dedup_key, ':', 2) ~ '^[0-9]+(\\.0+)?$'
                    THEN (split_part(dedup_key, ':', 2)::numeric)::bigint
                ELSE NULL
            END
        )
    """


def _verify_completed_in_sqlserver(resource_ids: list[int]) -> dict[int, tuple[int, object]]:
    placeholders = ",".join("?" for _ in resource_ids)
    query = f"""
        SELECT idRecurso, Estado, FUsuarioCompletado
        FROM Recursos.RecursosExp
        WHERE idRecurso IN ({placeholders})
    """
    with pyodbc.connect(build_sqlserver_connection_string(), autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(query, resource_ids)
        rows = {int(row[0]): (int(row[1]), row[2]) for row in cur.fetchall()}

    not_completed = [
        resource_id
        for resource_id in resource_ids
        if resource_id not in rows
        or not (rows[resource_id][0] == 2 or rows[resource_id][1] is not None)
    ]
    if not_completed:
        raise RuntimeError(
            "SQL Server no confirma como completados los recursos: "
            + ", ".join(str(resource_id) for resource_id in not_completed)
        )
    return rows


def _load_active_jobs(*, site_id: str, resource_ids: list[int]) -> list[ActiveJob]:
    dsn = (os.getenv("REPORT_PG_DSN") or "").strip()
    if not dsn:
        raise RuntimeError("REPORT_PG_DSN no esta configurado")
    resource_expr = _resource_id_expression()
    query = f"""
        SELECT job_id, {resource_expr} AS resource_id, status
        FROM jobs
        WHERE status IN ('queued', 'processing', 'in_progress')
          AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = %s
          AND {resource_expr} = ANY(%s)
        ORDER BY updated_at DESC
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (site_id, resource_ids))
            return [
                ActiveJob(job_id=str(row[0]), resource_id=int(row[1]), status=str(row[2]))
                for row in cur.fetchall()
            ]


async def _load_stream_messages(job_ids: set[str]) -> dict[str, list[str]]:
    client = redis.from_url(
        (os.getenv("REDIS_URL") or "redis://redis:6379/0").strip(),
        decode_responses=True,
    )
    try:
        found = {job_id: [] for job_id in job_ids}
        for message_id, fields in await client.xrange("jobs", min="-", max="+"):
            job_id = str(fields.get("job_id") or "")
            if job_id in found:
                found[job_id].append(str(message_id))
        return found
    finally:
        await client.aclose()


def _cancel_jobs(jobs: list[ActiveJob]) -> list[str]:
    dsn = (os.getenv("REPORT_PG_DSN") or "").strip()
    cancelled: list[str] = []
    reason = (
        "cancelled_after_external_completion: SQL Server Estado=2; "
        "source=manual_xvia_reconciliation"
    )
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for job in jobs:
                cur.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled',
                        error_message = %s,
                        finished_at = COALESCE(finished_at, NOW()),
                        updated_at = NOW()
                    WHERE job_id = %s
                      AND status = 'queued'
                    RETURNING job_id
                    """,
                    (reason, job.job_id),
                )
                row = cur.fetchone()
                if row:
                    cancelled.append(str(row[0]))
        if len(cancelled) != len(jobs):
            raise RuntimeError(
                f"La cancelacion no cubrio todos los jobs: {len(cancelled)}/{len(jobs)}"
            )
        conn.commit()
    return cancelled


async def _delete_stream_messages(messages: dict[str, list[str]]) -> list[str]:
    client = redis.from_url(
        (os.getenv("REDIS_URL") or "redis://redis:6379/0").strip(),
        decode_responses=True,
    )
    deleted: list[str] = []
    try:
        for message_ids in messages.values():
            for message_id in message_ids:
                await client.xack("jobs", "worker_group", message_id)
                if await client.xdel("jobs", message_id):
                    deleted.append(message_id)
        return deleted
    finally:
        await client.aclose()


async def run(*, site_id: str, resource_ids: list[int], apply: bool) -> None:
    completed = _verify_completed_in_sqlserver(resource_ids)
    jobs = _load_active_jobs(site_id=site_id, resource_ids=resource_ids)
    processing = [job for job in jobs if job.status != "queued"]
    if processing:
        raise RuntimeError(f"Hay jobs en ejecucion; se aborta: {processing}")

    found_resources = {job.resource_id for job in jobs}
    missing_jobs = sorted(set(resource_ids) - found_resources)
    messages = await _load_stream_messages({job.job_id for job in jobs})
    missing_messages = [job.job_id for job in jobs if not messages.get(job.job_id)]

    print(f"SQL Server completados: {sorted(completed)}")
    print(f"Jobs activos: {jobs}")
    print(f"Recursos sin job activo: {missing_jobs}")
    print(f"Mensajes Redis: {messages}")
    if missing_messages:
        raise RuntimeError(f"Jobs activos sin mensaje Redis: {missing_messages}")
    if not apply:
        print("Inspeccion completada. Usa --apply para cancelar y retirar los mensajes.")
        return

    cancelled = _cancel_jobs(jobs)
    deleted = await _delete_stream_messages(messages)
    print(f"Jobs cancelados: {cancelled}")
    print(f"Mensajes Redis eliminados: {deleted}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcilia jobs activos cuyos recursos ya constan completados en SQL Server."
    )
    parser.add_argument("resource_ids", nargs="+", type=int)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(
            site_id=str(args.site_id).strip(),
            resource_ids=sorted(set(args.resource_ids)),
            apply=bool(args.apply),
        )
    )


if __name__ == "__main__":
    main()
