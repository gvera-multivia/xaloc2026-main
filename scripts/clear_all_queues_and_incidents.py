#!/usr/bin/env python
from __future__ import annotations

import argparse
import subprocess
import sys


QUEUE_SERVICES = [
    "xaloc-brain-claim",
    "xaloc-payload-validator",
    "xaloc-batcher-dispatcher",
    "xaloc-worker-orchestrator",
]


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{msg}")
    return (proc.stdout or "").strip()


def stop_services() -> None:
    run(["docker", "stop", *QUEUE_SERVICES])


def start_services() -> None:
    run(["docker", "start", *QUEUE_SERVICES])


def clear_redis_streams_and_keys() -> None:
    run(
        [
            "docker",
            "exec",
            "xaloc-redis",
            "redis-cli",
            "DEL",
            "candidates",
            "validated",
            "jobs",
            "dlq:candidates",
            "dlq:validated",
            "dlq:jobs",
        ]
    )
    run(
        [
            "docker",
            "exec",
            "xaloc-redis",
            "sh",
            "-lc",
            "redis-cli --scan --pattern 'dedupe:resource:*' | xargs -r redis-cli DEL >/dev/null; "
            "redis-cli --scan --pattern 'brain-claim:resource:*' | xargs -r redis-cli DEL >/dev/null; "
            "echo done",
        ]
    )


def clear_postgres_active_queue_and_incidents() -> None:
    sql = (
        "BEGIN; "
        "UPDATE jobs "
        "SET status='cancelled', "
        "error_message=COALESCE(NULLIF(error_message,''), 'manual_clear_all_queues'), "
        "finished_at=COALESCE(finished_at, NOW()), "
        "updated_at=NOW() "
        "WHERE status IN ('queued','processing'); "
        "UPDATE job_drafts "
        "SET status='cancelled', "
        "last_error=COALESCE(NULLIF(last_error,''), 'manual_clear_all_queues'), "
        "updated_at=NOW() "
        "WHERE status IN ('validated_pending_batch','dispatched','dedup_active'); "
        "UPDATE pending_authorization_queue "
        "SET status='cancelled', "
        "notes=COALESCE(NULLIF(notes,''), 'manual_clear_all_queues'), "
        "updated_at=NOW() "
        "WHERE status='pending'; "
        "DELETE FROM realtime_incidents; "
        "DELETE FROM incident_locks; "
        "COMMIT;"
    )
    run(
        [
            "docker",
            "exec",
            "xaloc-postgres",
            "psql",
            "-U",
            "xaloc",
            "-d",
            "xaloc",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ]
    )


def verify() -> str:
    sql = (
        "SELECT "
        "(SELECT COUNT(*) FROM jobs WHERE status IN ('queued','processing')) AS active_jobs, "
        "(SELECT COUNT(*) FROM job_drafts WHERE status IN ('validated_pending_batch','dispatched','dedup_active')) AS active_drafts, "
        "(SELECT COUNT(*) FROM pending_authorization_queue WHERE status='pending') AS pending_auth, "
        "(SELECT COUNT(*) FROM realtime_incidents) AS incidents;"
    )
    summary = run(
        [
            "docker",
            "exec",
            "xaloc-postgres",
            "psql",
            "-U",
            "xaloc",
            "-d",
            "xaloc",
            "-t",
            "-A",
            "-c",
            sql,
        ]
    ).strip()
    streams = run(
        [
            "docker",
            "exec",
            "xaloc-redis",
            "sh",
            "-lc",
            "echo -n candidates=; redis-cli XLEN candidates; "
            "echo -n validated=; redis-cli XLEN validated; "
            "echo -n jobs=; redis-cli XLEN jobs; "
            "echo -n dlq:candidates=; redis-cli XLEN dlq:candidates; "
            "echo -n dlq:validated=; redis-cli XLEN dlq:validated; "
            "echo -n dlq:jobs=; redis-cli XLEN dlq:jobs",
        ]
    ).strip()
    return f"pg={summary}\nredis={streams}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Vaciar colas e incidencias en Docker (PG + Redis).")
    parser.add_argument(
        "--stop-services",
        action="store_true",
        help="Parar servicios de cola antes de limpiar (recomendado para que no se repueble).",
    )
    parser.add_argument(
        "--start-services",
        action="store_true",
        help="Arrancar servicios de cola al finalizar.",
    )
    args = parser.parse_args()

    try:
        if args.stop_services:
            stop_services()

        clear_redis_streams_and_keys()
        clear_postgres_active_queue_and_incidents()

        if args.start_services:
            start_services()

        print(verify())
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
