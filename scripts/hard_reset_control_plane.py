#!/usr/bin/env python
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_COMPOSE_FILE = ROOT_DIR / "infra" / "docker" / "docker-compose.microservices.yml"


def _compose_base_cmd(env_file: Path, compose_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
    ]


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"Command failed: {' '.join(cmd)}"
        raise RuntimeError(msg)
    return proc


def _exec_postgres(env_file: Path, compose_file: Path, sql: str) -> str:
    cmd = _compose_base_cmd(env_file, compose_file) + [
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "xaloc",
        "-d",
        "xaloc",
        "-v",
        "ON_ERROR_STOP=1",
        "-At",
        "-c",
        sql,
    ]
    proc = _run(cmd, check=True)
    return (proc.stdout or "").strip()


def _exec_redis(env_file: Path, compose_file: Path, shell: str) -> str:
    cmd = _compose_base_cmd(env_file, compose_file) + [
        "exec",
        "-T",
        "redis",
        "sh",
        "-lc",
        shell,
    ]
    proc = _run(cmd, check=True)
    return (proc.stdout or "").strip()


def _pause_runtime_controls(env_file: Path, compose_file: Path) -> None:
    sql = """
    INSERT INTO process_runtime_controls (process_name, desired_state, reason, updated_at)
    VALUES
      ('brain', 'stopped', 'hard_reset_control_plane', NOW()),
      ('worker', 'stopped', 'hard_reset_control_plane', NOW())
    ON CONFLICT (process_name) DO UPDATE
      SET desired_state = EXCLUDED.desired_state,
          reason = EXCLUDED.reason,
          updated_at = NOW();
    """
    _exec_postgres(env_file, compose_file, sql)


def _resume_runtime_controls(env_file: Path, compose_file: Path) -> None:
    sql = """
    INSERT INTO process_runtime_controls (process_name, desired_state, reason, updated_at)
    VALUES
      ('brain', 'running', 'hard_reset_control_plane_resume', NOW()),
      ('worker', 'running', 'hard_reset_control_plane_resume', NOW())
    ON CONFLICT (process_name) DO UPDATE
      SET desired_state = EXCLUDED.desired_state,
          reason = EXCLUDED.reason,
          updated_at = NOW();
    """
    _exec_postgres(env_file, compose_file, sql)


def _clear_redis_plane(env_file: Path, compose_file: Path) -> None:
    # Streams
    _exec_redis(
        env_file,
        compose_file,
        "redis-cli DEL candidates validated jobs dlq:candidates dlq:validated dlq:jobs >/dev/null",
    )
    # Dedupe keys
    _exec_redis(
        env_file,
        compose_file,
        "keys=$(redis-cli --scan --pattern 'dedupe:resource:*'); if [ -n \"$keys\" ]; then echo \"$keys\" | xargs -r redis-cli DEL >/dev/null; fi",
    )


def _cancel_active_pg(env_file: Path, compose_file: Path, *, clear_pending_auth: bool, clear_pauses: bool, clear_blocked: bool) -> str:
    sql_parts = [
        """
        UPDATE jobs
           SET status = 'cancelled',
               error_message = COALESCE(NULLIF(error_message,''), 'hard_reset_control_plane'),
               finished_at = COALESCE(finished_at, NOW()),
               updated_at = NOW()
         WHERE status IN ('queued', 'processing');
        """,
        """
        UPDATE job_drafts
           SET status = 'cancelled',
               last_error = COALESCE(NULLIF(last_error,''), 'hard_reset_control_plane'),
               updated_at = NOW()
         WHERE status IN ('validated_pending_batch', 'dispatched', 'dedup_active');
        """,
    ]

    if clear_pending_auth:
        sql_parts.append(
            """
            UPDATE pending_authorization_queue
               SET status = 'cancelled',
                   notes = COALESCE(NULLIF(notes,''), 'hard_reset_control_plane'),
                   updated_at = NOW()
             WHERE status = 'pending';
            """
        )

    if clear_pauses:
        sql_parts.append("DELETE FROM site_processing_pauses;")
        sql_parts.append("DELETE FROM resource_processing_pauses;")

    if clear_blocked:
        sql_parts.append("DELETE FROM blocked_resources;")

    sql_parts.append(
        """
        SELECT
          (SELECT COUNT(*) FROM jobs WHERE status IN ('queued','processing')) AS active_jobs_after,
          (SELECT COUNT(*) FROM job_drafts WHERE status IN ('validated_pending_batch','dispatched','dedup_active')) AS active_drafts_after,
          (SELECT COUNT(*) FROM pending_authorization_queue WHERE status='pending') AS pending_auth_after;
        """
    )
    return _exec_postgres(env_file, compose_file, "\n".join(sql_parts))


def _wipe_history_pg(env_file: Path, compose_file: Path) -> None:
    sql = """
    TRUNCATE TABLE events RESTART IDENTITY CASCADE;
    TRUNCATE TABLE job_artifacts RESTART IDENTITY CASCADE;
    TRUNCATE TABLE job_attempts RESTART IDENTITY CASCADE;
    TRUNCATE TABLE job_drafts RESTART IDENTITY CASCADE;
    TRUNCATE TABLE jobs RESTART IDENTITY CASCADE;
    """
    _exec_postgres(env_file, compose_file, sql)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hard reset de control-plane (Redis streams + estados activos PG)."
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Ruta a .env")
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE_FILE), help="Ruta a docker-compose")
    parser.add_argument("--yes", action="store_true", help="Ejecuta sin confirmacion interactiva")
    parser.add_argument("--keep-paused", action="store_true", help="No reanudar brain/worker al final")
    parser.add_argument("--no-clear-pending-auth", action="store_true", help="No cerrar pending_authorization_queue")
    parser.add_argument("--no-clear-pauses", action="store_true", help="No limpiar pausas de procesamiento")
    parser.add_argument("--clear-blocked", action="store_true", help="Limpiar blacklist blocked_resources")
    parser.add_argument("--wipe-history", action="store_true", help="Borrado destructivo del historico jobs/job_drafts/job_attempts/events")
    args = parser.parse_args()

    env_file = Path(args.env_file).resolve()
    compose_file = Path(args.compose_file).resolve()
    if not env_file.exists():
        print(f"[ERROR] No existe env file: {env_file}", file=sys.stderr)
        return 1
    if not compose_file.exists():
        print(f"[ERROR] No existe compose file: {compose_file}", file=sys.stderr)
        return 1

    if not args.yes:
        print("Se va a hacer HARD RESET del control-plane.")
        print("- Pausar brain/worker en PG runtime controls")
        print("- Limpiar Redis streams: candidates/validated/jobs/dlq:* + dedupe:resource:*")
        print("- Cancelar jobs activos y drafts activos en PostgreSQL")
        if not args.no_clear_pending_auth:
            print("- Rechazar pending auth pendientes")
        if args.wipe_history:
            print("- BORRAR historico completo de jobs/job_drafts/job_attempts/events/artifacts")
        confirm = input("Escribe 'RESET' para continuar: ").strip()
        if confirm != "RESET":
            print("[ABORT] Cancelado por usuario.")
            return 2

    try:
        print("[STEP] Pausando runtime controls brain/worker...")
        _pause_runtime_controls(env_file, compose_file)

        print("[STEP] Limpiando Redis streams + dedupe keys...")
        _clear_redis_plane(env_file, compose_file)

        print("[STEP] Cancelando estados activos en PostgreSQL...")
        summary = _cancel_active_pg(
            env_file,
            compose_file,
            clear_pending_auth=not args.no_clear_pending_auth,
            clear_pauses=not args.no_clear_pauses,
            clear_blocked=args.clear_blocked,
        )
        print(f"[INFO] Summary (active_jobs_after|active_drafts_after|pending_auth_after): {summary or '(sin salida)'}")

        if args.wipe_history:
            print("[STEP] Borrando historico PostgreSQL...")
            _wipe_history_pg(env_file, compose_file)

        if not args.keep_paused:
            print("[STEP] Reanudando runtime controls brain/worker...")
            _resume_runtime_controls(env_file, compose_file)

        print("[OK] Hard reset de control-plane completado.")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
