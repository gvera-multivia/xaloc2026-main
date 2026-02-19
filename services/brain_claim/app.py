from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import uuid
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

from core.redis_client import get_redis_client
from core.sqlite_db import SQLiteDatabase
from core.sqlserver_utils import build_sqlserver_connection_string
from core.xvia_auth import create_authenticated_session_in_place
from shared.queue import RedisStreamsClient
from sites.adapters import MadridAdapter, XalocAdapter, BaseOnlineAdapter, AyuntaPalmaAdapter
from sites.adapters.site_adapter import SiteAdapter

load_dotenv()

logger = logging.getLogger("brain_claim_service")


class BrainClaimService:
    def __init__(self):
        self.db = SQLiteDatabase()
        self.sqlserver_conn_str = build_sqlserver_connection_string()
        self.redis = get_redis_client()
        if self.redis is None:
            raise RuntimeError("Redis requerido para brain-claim-service (REDIS_ENABLED=1, REDIS_URL).")
        self.streams = RedisStreamsClient(self.redis, logger=logger)
        self.candidates_stream = (os.getenv("CANDIDATES_STREAM_KEY") or "candidates").strip() or "candidates"
        self.max_claims = int((os.getenv("BRAIN_CLAIM_MAX_PER_TICK") or "500").strip() or "500")
        self.sync_interval = int((os.getenv("BRAIN_CLAIM_SYNC_SECONDS") or "30").strip() or "30")

        self.adapters: dict[str, SiteAdapter] = {
            "madrid": MadridAdapter(),
            "xaloc_girona": XalocAdapter(),
            "base_online": BaseOnlineAdapter(),
            "ayunta_palma": AyuntaPalmaAdapter(),
        }
        self.session: Optional[aiohttp.ClientSession] = None
        self.authenticated_user: Optional[str] = None
        self.asignar_url = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"

    @staticmethod
    def _extract_csrf_token(html: str) -> Optional[str]:
        if not html:
            return None
        patterns = [
            r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']',
            r'value=["\']([^"\']+)["\'][^>]*name=["\']_token["\']',
            r'"_token"\s*:\s*"([^"]+)"',
            r"'_token'\s*:\s*'([^']+)'",
        ]
        for pattern in patterns:
            m = re.search(pattern, html, flags=re.IGNORECASE)
            if m:
                token = (m.group(1) or "").strip()
                if token:
                    return token
        return None

    async def init_session(self, login_url: str) -> None:
        if self.session is not None:
            return
        cookie_jar = aiohttp.CookieJar(unsafe=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Referer": login_url,
            "Origin": "http://www.xvia-grupoeuropa.net",
            "Connection": "keep-alive",
        }
        self.session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar)
        await create_authenticated_session_in_place(
            self.session,
            os.getenv("XVIA_EMAIL"),
            os.getenv("XVIA_PASSWORD"),
            login_url,
        )
        self.authenticated_user = await self.get_authenticated_username()

    async def get_authenticated_username(self) -> Optional[str]:
        if not self.session:
            return None
        try:
            async with self.session.get("http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home") as resp:
                html = await resp.text()
                match = re.search(r'<i class="fa fa-user-circle"[^>]*></i>\s*([^<]+)', html)
                if match:
                    return (match.group(1) or "").strip() or None
        except Exception:
            return None
        return None

    async def close_session(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    def verify_claim_in_db(self, id_recurso: int) -> bool:
        import pyodbc

        try:
            conn = pyodbc.connect(self.sqlserver_conn_str)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT Estado, UsuarioAsignado
                FROM Recursos.RecursosExp
                WHERE idRecurso = ?
                """,
                (id_recurso,),
            )
            row = cursor.fetchone()
            conn.close()
            if not row:
                return False
            estado, usuario = row
            usuario_db = str(usuario or "").strip()
            expected = str(self.authenticated_user or "").strip()
            return bool(estado == 1 and usuario_db == expected)
        except Exception:
            return False

    async def post_claim_resource(self, id_recurso: int) -> bool:
        if not self.session:
            return False
        try:
            async with self.session.get(
                "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
            ) as resp:
                html = await resp.text()
                csrf_token = self._extract_csrf_token(html)
                if not csrf_token:
                    return False
            form_data = {"_token": csrf_token, "id": str(id_recurso), "recursosSel": "0"}
            async with self.session.post(self.asignar_url, data=form_data) as resp:
                return resp.status in (200, 302, 303)
        except Exception:
            return False

    async def claim_resource_with_retries(
        self,
        *,
        id_recurso: int,
        expediente: str,
        retries: int = 5,
        delays_seconds: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0),
    ) -> bool:
        ok_post = await self.post_claim_resource(id_recurso)
        if not ok_post:
            return False
        for attempt in range(max(1, retries)):
            if self.verify_claim_in_db(id_recurso):
                return True
            await asyncio.sleep(delays_seconds[min(attempt, len(delays_seconds) - 1)])
        return False

    def get_active_configs(self) -> list[dict[str, Any]]:
        return self.db.get_active_organismo_configs()

    async def run_tick(self) -> dict[str, Any]:
        stats = {"claimed": 0, "published_candidates": 0, "errors": 0}
        configs = {cfg["site_id"]: cfg for cfg in self.get_active_configs()}
        remaining = self.max_claims

        for site_id, adapter in sorted(self.adapters.items(), key=lambda x: x[1].priority):
            if remaining <= 0:
                break
            config = configs.get(site_id)
            if not config:
                continue
            try:
                await self.init_session(config["login_url"])
                candidates = adapter.fetch_candidates(
                    config=config,
                    conn_str=self.sqlserver_conn_str,
                    authenticated_user=self.authenticated_user,
                    limit=remaining,
                    on_discard=None,
                )
                for cand in candidates:
                    if remaining <= 0:
                        break
                    rid_raw = cand.get("idRecurso")
                    try:
                        rid = int(rid_raw)
                    except Exception:
                        continue
                    if self.db.is_resource_blocked(site_id=site_id, resource_id=rid):
                        continue
                    expediente = str(cand.get("Expedient") or "").strip()
                    ok = await adapter.ensure_claimed(self, cand)
                    if not ok:
                        stats["errors"] += 1
                        continue
                    stats["claimed"] += 1
                    remaining -= 1

                    trace_id = str(uuid.uuid4())
                    candidate_payload = {
                        "candidate_id": str(uuid.uuid4()),
                        "organism_id": site_id,
                        "external_resource_id": str(rid),
                        "raw_payload": json.loads(json.dumps(cand, default=str)),
                        "claimed_at": cand.get("claimed_at") or "",
                        "trace_id": trace_id,
                        "expediente": expediente,
                    }
                    await self.streams.publish_json(
                        stream=self.candidates_stream,
                        payload=candidate_payload,
                        maxlen=int((os.getenv("CANDIDATES_STREAM_MAXLEN") or "200000").strip() or "200000"),
                    )
                    stats["published_candidates"] += 1
            except Exception as exc:
                logger.exception("[%s] fallo en run_tick claim-only: %s", site_id, exc)
                stats["errors"] += 1
            finally:
                await self.close_session()
        return stats

    async def run_forever(self) -> None:
        shutdown = asyncio.Event()

        def _signal_handler():
            shutdown.set()

        loop = asyncio.get_running_loop()
        if os.name != "nt":
            try:
                loop.add_signal_handler(signal.SIGTERM, _signal_handler)
                loop.add_signal_handler(signal.SIGINT, _signal_handler)
            except NotImplementedError:
                pass

        while not shutdown.is_set():
            try:
                stats = await self.run_tick()
                logger.info("[brain-claim] stats=%s", stats)
            except Exception as exc:
                logger.exception("Error run_forever brain-claim: %s", exc)
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self.sync_interval)
            except asyncio.TimeoutError:
                pass


async def _main_async() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [brain-claim] %(levelname)s %(message)s")
    svc = BrainClaimService()
    await svc.run_forever()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()

