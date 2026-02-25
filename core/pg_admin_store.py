from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psycopg

from core.runtime_flags import get_report_pg_dsn


class PgAdminStore:
    def __init__(self, dsn: str, logger: Optional[logging.Logger] = None):
        self.dsn = dsn
        self.logger = logger or logging.getLogger("pg_admin_store")

    @classmethod
    def from_env(cls, logger: Optional[logging.Logger] = None) -> "PgAdminStore":
        dsn = get_report_pg_dsn()
        if not dsn:
            raise RuntimeError("REPORT_PG_DSN/PG_DSN es obligatorio para PgAdminStore.")
        return cls(dsn=dsn, logger=logger)

    def _conn(self):
        return psycopg.connect(self.dsn)

    def is_resource_blocked(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM blocked_resources
                    WHERE site_id = %s AND resource_id = %s
                    LIMIT 1
                    """,
                    (str(site_id), int(resource_id)),
                )
                return cur.fetchone() is not None

    def list_blocked_resources(self, *, site_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if site_id:
                    cur.execute(
                        """
                        SELECT site_id, resource_id, reason, source, created_at, updated_at
                        FROM blocked_resources
                        WHERE site_id = %s
                        ORDER BY created_at DESC
                        """,
                        (str(site_id),),
                    )
                else:
                    cur.execute(
                        """
                        SELECT site_id, resource_id, reason, source, created_at, updated_at
                        FROM blocked_resources
                        ORDER BY created_at DESC
                        """
                    )
                rows = cur.fetchall()
        return [
            {
                "site_id": row[0],
                "resource_id": int(row[1]),
                "reason": row[2],
                "source": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
                "updated_at": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ]

    def block_resource(self, *, site_id: str, resource_id: int, reason: str | None = None, source: str | None = None) -> None:
        with self._conn() as conn:
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
                    (str(site_id), int(resource_id), reason, source),
                )
            conn.commit()

    def unblock_resource(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_resources WHERE site_id = %s AND resource_id = %s",
                    (str(site_id), int(resource_id)),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def list_organismo_configs(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, site_id, query_organisme, filtro_texp, regex_expediente,
                           login_url, recursos_url, active, last_sync_at, created_at, updated_at
                    FROM organismo_config
                    ORDER BY site_id ASC
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "site_id": row[1],
                "query_organisme": row[2],
                "filtro_texp": row[3],
                "regex_expediente": row[4],
                "login_url": row[5],
                "recursos_url": row[6],
                "active": bool(row[7]),
                "last_sync_at": row[8].isoformat() if row[8] else None,
                "created_at": row[9].isoformat() if row[9] else None,
                "updated_at": row[10].isoformat() if row[10] else None,
            }
            for row in rows
        ]

    def get_active_organismo_configs(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT site_id, query_organisme, filtro_texp, regex_expediente, login_url, recursos_url
                    FROM organismo_config
                    WHERE active = TRUE
                    ORDER BY site_id ASC
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "site_id": row[0],
                "query_organisme": row[1],
                "filtro_texp": row[2],
                "regex_expediente": row[3],
                "login_url": row[4],
                "recursos_url": row[5],
            }
            for row in rows
        ]

    def get_organismo_config(self, site_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, site_id, query_organisme, filtro_texp, regex_expediente,
                           login_url, recursos_url, active, last_sync_at, created_at, updated_at
                    FROM organismo_config
                    WHERE site_id = %s
                    LIMIT 1
                    """,
                    (str(site_id),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "site_id": row[1],
            "query_organisme": row[2],
            "filtro_texp": row[3],
            "regex_expediente": row[4],
            "login_url": row[5],
            "recursos_url": row[6],
            "active": bool(row[7]),
            "last_sync_at": row[8].isoformat() if row[8] else None,
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
        }

    def update_organismo_config(self, *, site_id: str, updates: dict[str, Any]) -> bool:
        allowed = {
            "query_organisme",
            "filtro_texp",
            "regex_expediente",
            "login_url",
            "recursos_url",
            "active",
            "last_sync_at",
        }
        clean = {k: v for k, v in (updates or {}).items() if k in allowed}
        if not clean:
            return False
        fields: list[str] = []
        params: list[Any] = []
        for key, value in clean.items():
            fields.append(f"{key} = %s")
            params.append(value)
        fields.append("updated_at = %s::timestamptz")
        params.append(datetime.now().isoformat())
        params.append(str(site_id))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE organismo_config SET {', '.join(fields)} WHERE site_id = %s",
                    tuple(params),
                )
                updated = cur.rowcount > 0
            conn.commit()
        return updated

    def upsert_organismo_config(self, config: dict[str, Any]) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO organismo_config (
                        site_id, query_organisme, filtro_texp, regex_expediente,
                        login_url, recursos_url, active, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (site_id) DO UPDATE SET
                        query_organisme = EXCLUDED.query_organisme,
                        filtro_texp = EXCLUDED.filtro_texp,
                        regex_expediente = EXCLUDED.regex_expediente,
                        login_url = EXCLUDED.login_url,
                        recursos_url = EXCLUDED.recursos_url,
                        active = EXCLUDED.active,
                        updated_at = NOW()
                    """,
                    (
                        str(config.get("site_id") or ""),
                        str(config.get("query_organisme") or ""),
                        str(config.get("filtro_texp") or ""),
                        str(config.get("regex_expediente") or ""),
                        str(config.get("login_url") or ""),
                        str(config.get("recursos_url") or ""),
                        bool(config.get("active", True)),
                    ),
                )
            conn.commit()

    def seed_organismo_config_if_empty(self, json_path: str = "organismo_config.json") -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM organismo_config")
                count = int(cur.fetchone()[0] or 0)
        if count > 0:
            return 0
        path = Path(json_path)
        if not path.exists():
            return 0
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            configs = raw.get("configs") if isinstance(raw, dict) else None
            if not isinstance(configs, list):
                return 0
            inserted = 0
            for cfg in configs:
                if not isinstance(cfg, dict):
                    continue
                site_id = str(cfg.get("site_id") or "").strip()
                if not site_id:
                    continue
                self.upsert_organismo_config(cfg)
                inserted += 1
            return inserted
        except Exception as exc:
            self.logger.warning("No se pudo sembrar organismo_config en PG: %s", exc)
            return 0
