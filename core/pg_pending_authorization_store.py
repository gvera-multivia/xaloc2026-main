from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg

from core.runtime_flags import get_report_pg_dsn


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PgPendingAuthorizationStore:
    def __init__(self, dsn: str, logger: Optional[logging.Logger] = None):
        self.dsn = dsn
        self.logger = logger or logging.getLogger("pg_pending_authorization_store")

    @classmethod
    def from_env(cls, logger: Optional[logging.Logger] = None) -> "PgPendingAuthorizationStore":
        dsn = get_report_pg_dsn()
        if not dsn:
            raise RuntimeError("REPORT_PG_DSN/PG_DSN es obligatorio para pending authorization.")
        return cls(dsn=dsn, logger=logger)

    def _conn(self):
        return psycopg.connect(self.dsn)

    @staticmethod
    def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _resource_id_from_payload(payload: dict[str, Any]) -> int:
        rid_raw = payload.get("idRecurso")
        if rid_raw is None:
            rid_raw = payload.get("external_resource_id")
        if rid_raw is None:
            raise ValueError("payload sin idRecurso/external_resource_id para pending authorization.")
        try:
            return int(rid_raw)
        except Exception as exc:
            raise ValueError("resource_id invalido en payload para pending authorization.") from exc

    def insert_pending_authorization(
        self,
        *,
        site_id: str,
        payload: dict[str, Any],
        authorization_type: str = "gesdoc",
        reason: str | None = None,
    ) -> int:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        payload_norm = self._normalize_payload(payload)
        resource_id = self._resource_id_from_payload(payload_norm)
        auth_type = (authorization_type or "").strip() or "gesdoc"
        now = _utc_now_iso()

        with self._conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO pending_authorization_queue (
                            site_id, resource_id, payload_json, authorization_type, reason, status, created_at, updated_at
                        )
                        VALUES (%s, %s, %s::jsonb, %s, %s, 'pending', %s::timestamptz, %s::timestamptz)
                        RETURNING id
                        """,
                        (
                            site,
                            int(resource_id),
                            json.dumps(payload_norm, ensure_ascii=False),
                            auth_type,
                            (reason or "").strip() or None,
                            now,
                            now,
                        ),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    return int(row[0])
                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                    with conn.cursor() as cur_dedup:
                        cur_dedup.execute(
                            """
                            SELECT id
                            FROM pending_authorization_queue
                            WHERE site_id = %s
                              AND resource_id = %s
                              AND status = 'pending'
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (site, int(resource_id)),
                        )
                        row = cur_dedup.fetchone()
                        if not row:
                            raise
                        return int(row[0])

    def list_pending_authorizations(self, *, authorization_type: str | None = None) -> list[dict[str, Any]]:
        auth_type = (authorization_type or "").strip() or None
        with self._conn() as conn:
            with conn.cursor() as cur:
                if auth_type:
                    cur.execute(
                        """
                        SELECT id, site_id, resource_id, payload_json, authorization_type, reason,
                               status, created_at, updated_at, notes
                        FROM pending_authorization_queue
                        WHERE status = 'pending'
                          AND authorization_type = %s
                        ORDER BY created_at ASC
                        """,
                        (auth_type,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, site_id, resource_id, payload_json, authorization_type, reason,
                               status, created_at, updated_at, notes
                        FROM pending_authorization_queue
                        WHERE status = 'pending'
                        ORDER BY created_at ASC
                        """
                    )
                rows = cur.fetchall()
        return [
            {
                "id": int(row[0]),
                "site_id": str(row[1]),
                "resource_id": int(row[2]) if row[2] is not None else None,
                "payload": row[3] if isinstance(row[3], dict) else {},
                "authorization_type": row[4],
                "reason": row[5],
                "status": row[6],
                "created_at": row[7].isoformat() if row[7] else None,
                "updated_at": row[8].isoformat() if row[8] else None,
                "notes": row[9],
            }
            for row in rows
        ]

    def count_pending_authorizations(self, *, authorization_type: str | None = None) -> int:
        auth_type = (authorization_type or "").strip() or None
        with self._conn() as conn:
            with conn.cursor() as cur:
                if auth_type:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM pending_authorization_queue
                        WHERE status = 'pending'
                          AND authorization_type = %s
                        """,
                        (auth_type,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM pending_authorization_queue
                        WHERE status = 'pending'
                        """
                    )
                row = cur.fetchone()
                return int(row[0] if row and row[0] is not None else 0)

    def get_pending_authorization(self, *, pending_id: int) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, site_id, resource_id, payload_json, authorization_type, reason, status, created_at
                    FROM pending_authorization_queue
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (int(pending_id),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "site_id": str(row[1]),
            "resource_id": int(row[2]) if row[2] is not None else None,
            "payload": row[3] if isinstance(row[3], dict) else {},
            "authorization_type": row[4],
            "reason": row[5],
            "status": row[6],
            "created_at": row[7].isoformat() if row[7] else None,
        }

    def mark_pending_as_moved_to_queue(
        self,
        *,
        pending_id: int,
        authorized_by: str,
        notes: str | None = None,
    ) -> bool:
        user = (authorized_by or "").strip() or "dashboard"
        now = _utc_now_iso()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pending_authorization_queue
                    SET status = 'moved_to_queue',
                        authorized_by = %s,
                        authorized_at = %s::timestamptz,
                        notes = %s,
                        updated_at = %s::timestamptz
                    WHERE id = %s
                      AND status = 'pending'
                    """,
                    (user, now, (notes or "").strip() or None, now, int(pending_id)),
                )
                changed = cur.rowcount > 0
            conn.commit()
        return bool(changed)

    def reject_pending_authorization(
        self,
        *,
        pending_id: int,
        reason: str,
        rejected_by: str = "dashboard",
    ) -> bool:
        user = (rejected_by or "").strip() or "dashboard"
        reason_value = (reason or "").strip()
        if not reason_value:
            raise ValueError("reason es obligatorio.")
        now = _utc_now_iso()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pending_authorization_queue
                    SET status = 'rejected',
                        authorized_by = %s,
                        authorized_at = %s::timestamptz,
                        notes = %s,
                        updated_at = %s::timestamptz
                    WHERE id = %s
                      AND status = 'pending'
                    """,
                    (user, now, reason_value, now, int(pending_id)),
                )
                changed = cur.rowcount > 0
            conn.commit()
        return bool(changed)
