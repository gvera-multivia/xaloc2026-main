from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psycopg

from core.runtime_flags import get_report_pg_dsn


class PgAdminStore:
    XALOC_REGEX_EXPEDIENTE_CURRENT = r"^(\d{4}/\d+(?:-(?:MUL|SAD|APR))?|\d{4}-\d+-APR|\d{10})$"
    XALOC_REGEX_EXPEDIENTE_LEGACY = (
        r"^\d{4}/\d{6}-MUL$",
        r"^\d{4}/\d+-MUL$",
        r"^\d{4}/\d+(?:-MUL)?$",
        r"^\d{4}/\d+(?:-(?:MUL|SAD))?$",
    )

    def __init__(self, dsn: str, logger: Optional[logging.Logger] = None):
        self.dsn = dsn
        self.logger = logger or logging.getLogger("pg_admin_store")
        self._has_claim_limit_col_cache: Optional[bool] = None

    @classmethod
    def from_env(cls, logger: Optional[logging.Logger] = None) -> "PgAdminStore":
        dsn = get_report_pg_dsn()
        if not dsn:
            raise RuntimeError("REPORT_PG_DSN/PG_DSN es obligatorio para PgAdminStore.")
        return cls(dsn=dsn, logger=logger)

    def _conn(self):
        return psycopg.connect(self.dsn)

    def _has_claim_limit_column(self) -> bool:
        if self._has_claim_limit_col_cache is not None:
            return self._has_claim_limit_col_cache
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'organismo_config'
                          AND column_name = 'claim_limit_per_tick'
                        LIMIT 1
                        """
                    )
                    self._has_claim_limit_col_cache = cur.fetchone() is not None
        except Exception:
            self._has_claim_limit_col_cache = False
        return bool(self._has_claim_limit_col_cache)

    @staticmethod
    def _load_json_configs(json_path: str) -> list[dict[str, Any]]:
        path = Path(json_path)
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        configs = raw.get("configs") if isinstance(raw, dict) else None
        if not isinstance(configs, list):
            return []
        return [cfg for cfg in configs if isinstance(cfg, dict)]

    def is_resource_blocked(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM blocked_resources
                    WHERE resource_id = %s
                    LIMIT 1
                    """,
                    (int(resource_id),),
                )
                return cur.fetchone() is not None

    def get_blocked_resource_ids(self, *, site_id: str, resource_ids: list[int]) -> set[int]:
        ids = sorted({int(x) for x in (resource_ids or [])})
        if not ids:
            return set()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT resource_id
                    FROM blocked_resources
                    WHERE resource_id = ANY(%s)
                    """,
                    (ids,),
                )
                rows = cur.fetchall()
        return {int(row[0]) for row in rows if row and row[0] is not None}

    def list_blocked_resources(self, *, site_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if site_id:
                    cur.execute(
                        """
                        SELECT site_id, resource_id, reason, source, screenshot_url, created_at, updated_at
                        FROM blocked_resources
                        WHERE site_id = %s
                        ORDER BY created_at DESC
                        """,
                        (str(site_id),),
                    )
                else:
                    cur.execute(
                        """
                        SELECT site_id, resource_id, reason, source, screenshot_url, created_at, updated_at
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
                "screenshot_url": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
                "updated_at": row[6].isoformat() if row[6] else None,
            }
            for row in rows
        ]

    def block_resource(self, *, site_id: str, resource_id: int, reason: str | None = None, source: str | None = None, screenshot_url: str | None = None) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO blocked_resources (site_id, resource_id, reason, source, screenshot_url, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (site_id, resource_id) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        source = EXCLUDED.source,
                        screenshot_url = EXCLUDED.screenshot_url,
                        updated_at = NOW()
                    """,
                    (str(site_id), int(resource_id), reason, source, screenshot_url),
                )
            conn.commit()

    def unblock_resource(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_resources WHERE resource_id = %s",
                    (int(resource_id),),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def list_organismo_configs(self) -> list[dict[str, Any]]:
        has_claim_limit = self._has_claim_limit_column()
        claim_select = "claim_limit_per_tick" if has_claim_limit else "NULL::integer AS claim_limit_per_tick"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, site_id, query_organisme, filtro_texp, regex_expediente,
                           login_url, recursos_url, {claim_select}, active, last_sync_at, created_at, updated_at
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
                "claim_limit_per_tick": int(row[7]) if row[7] is not None else None,
                "active": bool(row[8]),
                "last_sync_at": row[9].isoformat() if row[9] else None,
                "created_at": row[10].isoformat() if row[10] else None,
                "updated_at": row[11].isoformat() if row[11] else None,
            }
            for row in rows
        ]

    def get_active_organismo_configs(self) -> list[dict[str, Any]]:
        has_claim_limit = self._has_claim_limit_column()
        claim_select = "claim_limit_per_tick" if has_claim_limit else "NULL::integer AS claim_limit_per_tick"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT site_id, query_organisme, filtro_texp, regex_expediente, login_url, recursos_url, {claim_select}
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
                "claim_limit_per_tick": int(row[6]) if row[6] is not None else None,
            }
            for row in rows
        ]

    def get_organismo_config(self, site_id: str) -> Optional[dict[str, Any]]:
        has_claim_limit = self._has_claim_limit_column()
        claim_select = "claim_limit_per_tick" if has_claim_limit else "NULL::integer AS claim_limit_per_tick"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, site_id, query_organisme, filtro_texp, regex_expediente,
                           login_url, recursos_url, {claim_select}, active, last_sync_at, created_at, updated_at
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
            "claim_limit_per_tick": int(row[7]) if row[7] is not None else None,
            "active": bool(row[8]),
            "last_sync_at": row[9].isoformat() if row[9] else None,
            "created_at": row[10].isoformat() if row[10] else None,
            "updated_at": row[11].isoformat() if row[11] else None,
        }

    def update_organismo_config(self, *, site_id: str, updates: dict[str, Any]) -> bool:
        allowed = {
            "query_organisme",
            "filtro_texp",
            "regex_expediente",
            "login_url",
            "recursos_url",
            "claim_limit_per_tick",
            "active",
            "last_sync_at",
        }
        clean = {k: v for k, v in (updates or {}).items() if k in allowed}
        if not self._has_claim_limit_column():
            clean.pop("claim_limit_per_tick", None)
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
        has_claim_limit = self._has_claim_limit_column()
        with self._conn() as conn:
            with conn.cursor() as cur:
                if has_claim_limit:
                    cur.execute(
                        """
                        INSERT INTO organismo_config (
                            site_id, query_organisme, filtro_texp, regex_expediente,
                            login_url, recursos_url, claim_limit_per_tick, active, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (site_id) DO UPDATE SET
                            query_organisme = EXCLUDED.query_organisme,
                            filtro_texp = EXCLUDED.filtro_texp,
                            regex_expediente = EXCLUDED.regex_expediente,
                            login_url = EXCLUDED.login_url,
                            recursos_url = EXCLUDED.recursos_url,
                            claim_limit_per_tick = EXCLUDED.claim_limit_per_tick,
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
                            int(config["claim_limit_per_tick"]) if config.get("claim_limit_per_tick") is not None else None,
                            bool(config.get("active", True)),
                        ),
                    )
                else:
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
        try:
            configs = self._load_json_configs(json_path)
            if not configs:
                return 0
            inserted = 0
            for cfg in configs:
                site_id = str(cfg.get("site_id") or "").strip()
                if not site_id:
                    continue
                self.upsert_organismo_config(cfg)
                inserted += 1
            return inserted
        except Exception as exc:
            self.logger.warning("No se pudo sembrar organismo_config en PG: %s", exc)
            return 0

    def seed_missing_organismo_configs(self, json_path: str = "organismo_config.json") -> list[str]:
        try:
            configs = self._load_json_configs(json_path)
            if not configs:
                return []
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT site_id FROM organismo_config")
                    existing = {str(row[0]).strip() for row in cur.fetchall() if row and row[0]}
            inserted: list[str] = []
            for cfg in configs:
                site_id = str(cfg.get("site_id") or "").strip()
                if not site_id or site_id in existing:
                    continue
                self.upsert_organismo_config(cfg)
                inserted.append(site_id)
                existing.add(site_id)
            return inserted
        except Exception as exc:
            self.logger.warning("No se pudo sincronizar site_id faltantes de organismo_config en PG: %s", exc)
            return []

    def upgrade_xaloc_regex_expediente(self) -> int:
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE organismo_config
                           SET regex_expediente = %s,
                               updated_at = NOW()
                         WHERE site_id = 'xaloc_girona'
                           AND regex_expediente = ANY(%s)
                        """,
                        (self.XALOC_REGEX_EXPEDIENTE_CURRENT, list(self.XALOC_REGEX_EXPEDIENTE_LEGACY)),
                    )
                    updated = int(cur.rowcount or 0)
                conn.commit()
            return updated
        except Exception as exc:
            self.logger.warning("No se pudo actualizar regex_expediente de xaloc_girona en PG: %s", exc)
            return 0
