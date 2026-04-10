from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_CANDIDATES: dict[str, list[Path]] = {
    "worker": [ROOT / "logs" / "worker_out.log"],
    "brain": [ROOT / "logs" / "brain_out.log"],
    "playwright_runner": [ROOT / "logs" / "playwright_runner_out.log"],
    "payload_validator": [
        ROOT / "logs" / "payload_validator_out.log",
        ROOT / "logs" / "payload-validator_out.log",
    ],
    "batcher_dispatcher": [
        ROOT / "logs" / "batcher_dispatcher_out.log",
        ROOT / "logs" / "batcher-dispatcher_out.log",
    ],
}


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


def _collect_logs(limit: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, candidates in LOG_CANDIDATES.items():
        chosen = next((path for path in candidates if path.exists()), None)
        out[name] = {
            "path": str(chosen) if chosen else None,
            "tail": _tail_lines(chosen, limit) if chosen else [],
        }
    return out


def _pg_history(site_id: str, resource_id: int, limit: int) -> dict[str, Any]:
    try:
        import psycopg
        from core.runtime_flags import get_report_pg_dsn
        from psycopg.rows import dict_row
    except Exception as exc:
        return {"items": [], "total": 0, "error": f"import_error: {exc}"}

    dsn = get_report_pg_dsn()
    if not dsn:
        return {"items": [], "total": 0, "error": "missing_pg_dsn"}

    try:
        with psycopg.connect(dsn, connect_timeout=3, row_factory=dict_row) as conn:
            items: list[dict[str, Any]] = []
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        'realtime_task_results' AS source,
                        status,
                        day::text AS day,
                        started_at,
                        ended_at,
                        site_id,
                        resource_id,
                        job_id,
                        protocol,
                        payload,
                        result,
                        NULL::jsonb AS metadata
                    FROM realtime_task_results
                    WHERE site_id = %s AND resource_id = %s
                    ORDER BY COALESCE(ended_at, started_at) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (site_id, resource_id, limit),
                )
                items.extend(cur.fetchall())

                cur.execute(
                    """
                    SELECT
                        'realtime_incidents' AS source,
                        status,
                        day::text AS day,
                        started_at,
                        ended_at,
                        site_id,
                        resource_id,
                        NULL::text AS job_id,
                        NULL::text AS protocol,
                        payload,
                        NULL::jsonb AS result,
                        jsonb_build_object(
                            'incident_type', incident_type,
                            'reason', reason,
                            'expediente', expediente
                        ) AS metadata
                    FROM realtime_incidents
                    WHERE (%s = '' OR site_id = %s) AND resource_id = %s
                    ORDER BY COALESCE(ended_at, started_at) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (site_id, site_id, resource_id, limit),
                )
                items.extend(cur.fetchall())

                cur.execute(
                    """
                    SELECT
                        'jobs' AS source,
                        status,
                        TO_CHAR(COALESCE(queued_at, created_at), 'YYYY-MM-DD') AS day,
                        COALESCE(queued_at, created_at) AS started_at,
                        COALESCE(finished_at, updated_at) AS ended_at,
                        COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), 'unknown') AS site_id,
                        COALESCE(
                            CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$' THEN (payload_json->>'idRecurso')::bigint END,
                            CASE WHEN (payload_json->>'external_resource_id') ~ '^[0-9]+$' THEN (payload_json->>'external_resource_id')::bigint END,
                            CASE WHEN split_part(dedup_key, ':', 2) ~ '^[0-9]+$' THEN split_part(dedup_key, ':', 2)::bigint END
                        ) AS resource_id,
                        job_id,
                        COALESCE(payload_json->>'protocol', payload_json->>'protocolo', split_part(dedup_key, ':', 3)) AS protocol,
                        payload_json AS payload,
                        result_json AS result,
                        jsonb_build_object('dedup_key', dedup_key, 'error_message', error_message) AS metadata
                    FROM jobs
                    WHERE (
                        COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), 'unknown') = %s
                        OR %s = ''
                    )
                    AND COALESCE(
                        CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$' THEN (payload_json->>'idRecurso')::bigint END,
                        CASE WHEN (payload_json->>'external_resource_id') ~ '^[0-9]+$' THEN (payload_json->>'external_resource_id')::bigint END,
                        CASE WHEN split_part(dedup_key, ':', 2) ~ '^[0-9]+$' THEN split_part(dedup_key, ':', 2)::bigint END
                    ) = %s
                    ORDER BY COALESCE(finished_at, updated_at, started_at, queued_at, created_at) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (site_id, site_id, resource_id, limit),
                )
                items.extend(cur.fetchall())

                cur.execute("SELECT to_regclass('public.job_drafts') AS present")
                drafts_present = bool((cur.fetchone() or {}).get("present"))
                if drafts_present:
                    cur.execute(
                        """
                        SELECT
                            'job_drafts' AS source,
                            status,
                            TO_CHAR(COALESCE(dispatched_at, updated_at, created_at), 'YYYY-MM-DD') AS day,
                            created_at AS started_at,
                            COALESCE(dispatched_at, updated_at) AS ended_at,
                            organism_id AS site_id,
                            COALESCE(
                                CASE WHEN external_resource_id ~ '^[0-9]+$' THEN external_resource_id::bigint END,
                                CASE WHEN (normalized_payload_json->>'idRecurso') ~ '^[0-9]+$' THEN (normalized_payload_json->>'idRecurso')::bigint END,
                                CASE WHEN split_part(dedup_key, ':', 2) ~ '^[0-9]+$' THEN split_part(dedup_key, ':', 2)::bigint END
                            ) AS resource_id,
                            COALESCE(job_id, draft_id) AS job_id,
                            job_type AS protocol,
                            normalized_payload_json AS payload,
                            NULL::jsonb AS result,
                            jsonb_build_object('last_error', last_error, 'dedup_key', dedup_key) AS metadata
                        FROM job_drafts
                        WHERE (organism_id = %s OR %s = '')
                        AND COALESCE(
                            CASE WHEN external_resource_id ~ '^[0-9]+$' THEN external_resource_id::bigint END,
                            CASE WHEN (normalized_payload_json->>'idRecurso') ~ '^[0-9]+$' THEN (normalized_payload_json->>'idRecurso')::bigint END,
                            CASE WHEN split_part(dedup_key, ':', 2) ~ '^[0-9]+$' THEN split_part(dedup_key, ':', 2)::bigint END
                        ) = %s
                        ORDER BY COALESCE(dispatched_at, updated_at, created_at) DESC NULLS LAST
                        LIMIT %s
                        """,
                        (site_id, site_id, resource_id, limit),
                    )
                    items.extend(cur.fetchall())

            items.sort(key=lambda item: item.get("ended_at") or item.get("started_at") or "", reverse=True)
            items = items[:limit]
            for item in items:
                for key in ("started_at", "ended_at"):
                    value = item.get(key)
                    if hasattr(value, "isoformat"):
                        item[key] = value.isoformat()
            return {"items": items, "total": len(items)}
    except Exception as exc:
        return {"items": [], "total": 0, "error": str(exc)}


def _job_details(job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    try:
        import psycopg
        from core.runtime_flags import get_report_pg_dsn
        from psycopg.rows import dict_row
    except Exception as exc:
        return {"error": f"import_error: {exc}", "job_id": job_id}

    dsn = get_report_pg_dsn()
    if not dsn:
        return {"error": "missing_pg_dsn", "job_id": job_id}

    try:
        with psycopg.connect(dsn, connect_timeout=3, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, job_id, dedup_key, status, priority, payload_json, result_json,
                           error_message, queued_at, started_at, finished_at, created_at, updated_at
                    FROM jobs
                    WHERE job_id = %s
                    LIMIT 1
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
        if row is None:
            return {"job_id": job_id, "missing": True}
        for key in ("queued_at", "started_at", "finished_at", "created_at", "updated_at"):
            value = row.get(key)
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
        return row
    except Exception as exc:
        return {"error": str(exc), "job_id": job_id}


def _infer_job_ids(history: dict[str, Any]) -> list[str]:
    items = history.get("items") or []
    job_ids = []
    for item in items:
        job_id = str(item.get("job_id") or "").strip()
        if job_id and job_id not in job_ids:
            job_ids.append(job_id)
    return job_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolecta contexto read-only para depurar un fallo runtime de Xaloc.")
    parser.add_argument("--site-id", required=True, help="site_id del caso")
    parser.add_argument("--resource-id", required=True, type=int, help="resource_id / idRecurso del caso")
    parser.add_argument("--job-id", default="", help="job_id opcional")
    parser.add_argument("--history-limit", type=int, default=50, help="maximo de eventos de detalle PG")
    parser.add_argument("--log-lines", type=int, default=120, help="lineas de logs por servicio")
    parser.add_argument("--output", default="", help="ruta opcional donde guardar JSON")
    args = parser.parse_args()

    history = _pg_history(args.site_id, int(args.resource_id), int(args.history_limit))
    inferred_job_ids = _infer_job_ids(history)
    job_id = str(args.job_id or "").strip() or (inferred_job_ids[0] if inferred_job_ids else "")

    payload = {
        "site_id": str(args.site_id).strip(),
        "resource_id": int(args.resource_id),
        "requested_job_id": str(args.job_id or "").strip() or None,
        "resolved_job_id": job_id or None,
        "inferred_job_ids": inferred_job_ids,
        "postgres_history": history,
        "job": _job_details(job_id),
        "logs": _collect_logs(int(args.log_lines)),
        "next_steps": [
            "Correlacionar timestamps entre postgres_history y logs.",
            "Determinar la primera capa donde rompe realmente.",
            "Comparar el hallazgo con core/, services/ y sites/<site_id>/.",
        ],
    }

    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        dst = Path(args.output)
        dst.write_text(rendered, encoding="utf-8")
        print(f"Saved: {dst}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
