from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import uuid
import sys
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

from core.redis_client import get_redis_client
from core.pg_admin_store import PgAdminStore
from core.pg_runtime_store import PgRuntimeStore
from core.realtime_store import build_realtime_store
from core.consultor import ConsultorResourceRepositoryAdapter, ConsultorService
from core.repositories import ResourceRepository
from core.sqlserver_utils import build_sqlserver_connection_string
from core.xvia_auth import create_authenticated_session_in_place
from shared.queue import RedisStreamsClient
from sites.adapters import (
    MadridAdapter,
    XalocAdapter,
    BaseOnlineAdapter,
    AyuntaPalmaAdapter,
    RedsaraAdapter,
    TerrassaAdapter,
    ValenciaAdapter,
    AtcAdapter,
    DiputacioBcnAdapter,
)
from sites.adapters.site_adapter import SiteAdapter
from services.brain_claim.processable_validator import validate_candidate

load_dotenv()

logger = logging.getLogger("brain_claim_service")


def _setup_brain_claim_logging() -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    stable_log_path = logs_dir / "brain_out.log"

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.INFO)

    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass

    formatter = logging.Formatter("%(asctime)s [brain-claim] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(stable_log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class BrainClaimService:
    def __init__(self):
        self.admin_store = PgAdminStore.from_env(logger=logger)
        self.runtime_store = PgRuntimeStore.from_env(logger=logger)
        seeded = self.admin_store.seed_organismo_config_if_empty()
        if seeded:
            logger.info("[brain-claim] seeded organismo_config en PG: %s", seeded)
        inserted_missing = self.admin_store.seed_missing_organismo_configs()
        if inserted_missing:
            logger.info("[brain-claim] sincronizados site_id faltantes en PG: %s", ", ".join(sorted(inserted_missing)))
        self.sqlserver_conn_str = build_sqlserver_connection_string()
        self.resource_repo = ResourceRepository(conn_str=self.sqlserver_conn_str, logger=logger)
        self.consultor = ConsultorService(conn_str=self.sqlserver_conn_str, logger=logger, repository=self.resource_repo)
        self.consultor_repo = ConsultorResourceRepositoryAdapter(self.consultor, retrieval_profile="full")
        self.consultor_repo_light = ConsultorResourceRepositoryAdapter(self.consultor, retrieval_profile="light")
        # Sites que deben consultar perfil full en fetch inicial.
        # Default conservador: all (prioriza calidad de datos frente a ahorro de query).
        full_sites_env = (os.getenv("BRAIN_CLAIM_FULL_PAYLOAD_SITES") or "all").strip().lower()
        self.full_payload_sites: set[str] = set()
        if full_sites_env != "all":
            self.full_payload_sites = {s.strip().lower() for s in full_sites_env.split(",") if s.strip()}
        self.realtime_store = build_realtime_store(logger=logger)
        self.redis = get_redis_client()
        if self.redis is None:
            raise RuntimeError("Redis requerido para brain-claim-service (REDIS_ENABLED=1, REDIS_URL).")
        self.streams = RedisStreamsClient(self.redis, logger=logger)
        self.candidates_stream = (os.getenv("CANDIDATES_STREAM_KEY") or "candidates").strip() or "candidates"
        self.max_claims = int((os.getenv("BRAIN_CLAIM_MAX_PER_TICK") or "500").strip() or "500")
        self.sync_interval = int((os.getenv("BRAIN_CLAIM_SYNC_SECONDS") or "60").strip() or "60")
        self.claim_dedupe_ttl_seconds = int(
            (os.getenv("BRAIN_CLAIM_DEDUPE_TTL_SECONDS") or "7200").strip() or "7200"
        )
        self.enable_claim_dedupe_stale_recovery = (
            (os.getenv("BRAIN_CLAIM_ENABLE_STALE_RECOVERY") or "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.active_job_stale_seconds = int(
            (os.getenv("BRAIN_ACTIVE_JOB_STALE_SECONDS") or "28800").strip() or "28800"
        )

        self.adapters: dict[str, SiteAdapter] = {
            "madrid": MadridAdapter(),
            "xaloc_girona": XalocAdapter(),
            "base_online": BaseOnlineAdapter(),
            "ayunta_palma": AyuntaPalmaAdapter(),
            "redsara": RedsaraAdapter(),
            "terrassa": TerrassaAdapter(),
            "valencia": ValenciaAdapter(),
            "atc": AtcAdapter(),
            "diputacio_bcn": DiputacioBcnAdapter(),
        }
        if full_sites_env == "all":
            self.full_payload_sites = set(self.adapters.keys())
        logger.info("[brain-claim] full payload sites=%s", sorted(self.full_payload_sites))
        self.session: Optional[aiohttp.ClientSession] = None
        self.authenticated_user: Optional[str] = None
        self.asignar_url = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"
        self._last_configured_sites_signature: Optional[str] = None
        self._csrf_token: Optional[str] = None
        self._csrf_token_fetched_at: float = 0.0
        self._csrf_token_ttl_seconds = int((os.getenv("XVIA_CSRF_TTL_SECONDS") or "300").strip() or "300")

    @staticmethod
    def _site_claim_limit_from_config(config: dict[str, Any]) -> int | None:
        raw = (config or {}).get("claim_limit_per_tick")
        if raw in (None, "", "null"):
            return None
        try:
            value = int(raw)
        except Exception:
            return None
        return value if value > 0 else None

    @staticmethod
    def _parse_resource_id(value: Any) -> int | None:
        try:
            return int(value)
        except Exception:
            try:
                rid_float = float(str(value).strip())
                if not rid_float.is_integer():
                    return None
                return int(rid_float)
            except Exception:
                return None

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
        self._csrf_token = None
        self._csrf_token_fetched_at = 0.0

    async def _get_csrf_token(self, *, force_refresh: bool = False) -> Optional[str]:
        if not self.session:
            return None
        now = time.monotonic()
        if (
            not force_refresh
            and self._csrf_token
            and (now - self._csrf_token_fetched_at) <= max(30, self._csrf_token_ttl_seconds)
        ):
            return self._csrf_token
        try:
            async with self.session.get(
                "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
            ) as resp:
                html = await resp.text()
                csrf_token = self._extract_csrf_token(html)
                if not csrf_token:
                    return None
                self._csrf_token = csrf_token
                self._csrf_token_fetched_at = now
                return csrf_token
        except Exception:
            return None

    def _hydrate_candidates_batch_for_payload(
        self,
        *,
        site_id: str,
        resource_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        ids = sorted({int(rid) for rid in (resource_ids or [])})
        if not ids:
            return {}
        try:
            items = self.resource_repo.get_resources_by_ids(site_id=site_id, resource_ids=ids)
            hydrated: dict[int, dict[str, Any]] = {}
            for item in items:
                meta = dict(item.metadata or {})
                rid = self._parse_resource_id(meta.get("idRecurso"))
                if rid is None:
                    continue
                hydrated[rid] = meta
            return hydrated
        except Exception as exc:
            logger.warning(
                "[%s] fallo hidratando batch para payload (ids=%s): %s",
                site_id,
                len(ids),
                exc,
            )
            return {}

    def verify_claim_in_db(self, id_recurso: int) -> bool:
        import pyodbc

        try:
            with pyodbc.connect(self.sqlserver_conn_str, autocommit=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT Estado, UsuarioAsignado, FUsuarioCompletado
                        FROM Recursos.RecursosExp
                        WHERE idRecurso = ?
                        """,
                        (id_recurso,),
                    )
                    row = cursor.fetchone()
            if not row:
                return False
            estado, usuario, _f_usuario_completado = row
            usuario_db = str(usuario or "").strip()
            expected = str(self.authenticated_user or "").strip()
            return bool(estado == 1 and usuario_db == expected)
        except Exception:
            return False

    def is_still_claimable_in_db(self, id_recurso: int) -> bool:
        """
        Revalida contra SQL Server, justo antes de reclamar/publicar, para evitar
        carreras entre fetch y claim.
        """
        import pyodbc

        try:
            with pyodbc.connect(self.sqlserver_conn_str, autocommit=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT Estado, UsuarioAsignado, FUsuarioCompletado
                        FROM Recursos.RecursosExp
                        WHERE idRecurso = ?
                        """,
                        (id_recurso,),
                    )
                    row = cursor.fetchone()
            if not row:
                return False
            estado, usuario, _f_usuario_completado = row
            # En SQL hay casos reabiertos con FUsuarioCompletado historico pero Estado=0.
            # La fuente de verdad para claim es Estado/UsuarioAsignado.
            # Reclamable nuevo.
            if int(estado or 0) == 0:
                return True
            # Si ya esta reclamado, solo vale si lo tiene el usuario autenticado.
            if int(estado or 0) == 1:
                return str(usuario or "").strip() == str(self.authenticated_user or "").strip()
            return False
        except Exception:
            return False

    async def post_claim_resource(self, id_recurso: int) -> bool:
        if not self.session:
            return False
        try:
            csrf_token = await self._get_csrf_token(force_refresh=False)
            if not csrf_token:
                return False
            form_data = {"_token": csrf_token, "id": str(id_recurso), "recursosSel": "0"}
            async with self.session.post(self.asignar_url, data=form_data) as resp:
                if resp.status in (200, 302, 303):
                    return True
                if resp.status in (401, 403, 419):
                    csrf_token = await self._get_csrf_token(force_refresh=True)
                    if not csrf_token:
                        return False
                    form_data["_token"] = csrf_token
                    async with self.session.post(self.asignar_url, data=form_data) as retry_resp:
                        return retry_resp.status in (200, 302, 303)
                return False
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

    @staticmethod
    def _claim_dedupe_key(*, site_id: str, resource_id: int) -> str:
        return f"brain-claim:resource:{site_id}:{int(resource_id)}"

    async def _reserve_claim_slot(self, *, site_id: str, resource_id: int) -> bool:
        key = self._claim_dedupe_key(site_id=site_id, resource_id=resource_id)
        try:
            ok = await self.redis.set(key, "1", ex=self.claim_dedupe_ttl_seconds, nx=True)
            return bool(ok)
        except Exception as exc:
            logger.warning(
                "[%s] no se pudo aplicar dedupe claim para idRecurso=%s: %s",
                site_id,
                resource_id,
                exc,
            )
            return True

    async def _reserve_claim_slot_with_stale_recovery(self, *, site_id: str, resource_id: int) -> bool:
        reserved = await self._reserve_claim_slot(site_id=site_id, resource_id=resource_id)
        if reserved:
            return True

        # Evita bucles de reclaim cada tick: por defecto NO reciclamos la dedupe key
        # si ya existe. Solo se habilita con BRAIN_CLAIM_ENABLE_STALE_RECOVERY=1.
        if not self.enable_claim_dedupe_stale_recovery:
            return False

        # If there is no active queued/processing job, the claim dedupe key is stale.
        if self.runtime_store.has_active_job_for_resource(site_id=site_id, resource_id=resource_id):
            return False

        await self._release_claim_slot(site_id=site_id, resource_id=resource_id)
        reserved_after_release = await self._reserve_claim_slot(site_id=site_id, resource_id=resource_id)
        if reserved_after_release:
            logger.warning(
                "[%s] dedupe-claim stale recuperado para idRecurso=%s (sin job activo).",
                site_id,
                resource_id,
            )
            return True
        return False

    async def _release_claim_slot(self, *, site_id: str, resource_id: int) -> None:
        key = self._claim_dedupe_key(site_id=site_id, resource_id=resource_id)
        try:
            await self.redis.delete(key)
        except Exception:
            pass

    def get_active_configs(self) -> list[dict[str, Any]]:
        return self.admin_store.get_active_organismo_configs()

    def _record_incident(
        self,
        *,
        site_id: str,
        error_code: str,
        description: str,
        candidate: dict[str, Any],
    ) -> None:
        resource_id: int | None = None
        rid_raw = candidate.get("idRecurso")
        if rid_raw is not None:
            try:
                resource_id = int(rid_raw)
            except Exception:
                resource_id = None
        expediente = str(candidate.get("Expedient") or "").strip()
        payload = {"candidate": json.loads(json.dumps(candidate, default=str))}
        created = False
        try:
            created = self.realtime_store.record_incident_once(
                site_id=site_id,
                incident_type=error_code,
                reason=description,
                resource_id=resource_id,
                expediente=expediente,
                payload=payload,
                error_code=error_code,
                status="NEW",
                screenshot_path=None,
            )
        except Exception as exc:
            logger.warning("[%s] No se pudo registrar incidencia %s: %s", site_id, error_code, exc)
            return

        if not created:
            return

    async def run_tick(self) -> dict[str, Any]:
        stats = {"claimed": 0, "published_candidates": 0, "incidents_logged": 0, "errors": 0}
        configs = {cfg["site_id"]: cfg for cfg in self.get_active_configs()}
        configured_sites = sorted(configs.keys())
        configured_sig = "|".join(configured_sites)
        if configured_sig != self._last_configured_sites_signature:
            logger.info("[brain-claim] site_id activos en organismo_config: %s", configured_sites or [])
            missing_cfg = sorted([site_id for site_id in self.adapters.keys() if site_id not in configs])
            if missing_cfg:
                logger.warning(
                    "[brain-claim] adapters sin config activa en PG (no se ejecutan): %s",
                    missing_cfg,
                )
            self._last_configured_sites_signature = configured_sig
        remaining = self.max_claims

        for site_id, adapter in sorted(self.adapters.items(), key=lambda x: x[1].priority):
            if remaining <= 0:
                break
            config = configs.get(site_id)
            if not config:
                continue
            site_limit = self._site_claim_limit_from_config(config)
            site_claimed = 0
            if self.runtime_store.is_site_processing_paused(site_id=site_id):
                continue
            try:
                await self.init_session(config["login_url"])
                def _on_discard(item: dict[str, Any]) -> None:
                    error_code = str(item.get("tipo_incidencia") or "SITE_RULE_DISCARDED").strip() or "SITE_RULE_DISCARDED"
                    reason = str(item.get("motivo") or "Recurso descartado por regla de negocio/sede.").strip()
                    self._record_incident(
                        site_id=str(item.get("site_id") or site_id),
                        error_code=error_code,
                        description=reason,
                        candidate=item,
                    )
                    stats["incidents_logged"] += 1

                candidates = adapter.fetch_candidates(
                    config=config,
                    conn_str=self.sqlserver_conn_str,
                    authenticated_user=self.authenticated_user,
                    limit=min(remaining, site_limit) if site_limit is not None else remaining,
                    on_discard=_on_discard,
                    resource_repo=(self.consultor_repo if site_id in self.full_payload_sites else self.consultor_repo_light),
                )
                parsed_candidates: list[tuple[int, dict[str, Any]]] = []
                for cand in candidates:
                    rid = self._parse_resource_id(cand.get("idRecurso"))
                    if rid is None:
                        continue
                    parsed_candidates.append((rid, cand))

                candidate_ids = sorted({rid for rid, _ in parsed_candidates})
                blocked_ids: set[int] = set()
                paused_ids: set[int] = set()
                active_job_ids: set[int] = set()
                if candidate_ids:
                    try:
                        blocked_ids = self.admin_store.get_blocked_resource_ids(site_id=site_id, resource_ids=candidate_ids)
                    except Exception as exc:
                        logger.warning("[%s] fallo prefetch blocked ids: %s", site_id, exc)
                    try:
                        paused_ids = self.runtime_store.get_paused_resource_ids(site_id=site_id, resource_ids=candidate_ids)
                    except Exception as exc:
                        logger.warning("[%s] fallo prefetch paused ids: %s", site_id, exc)
                    try:
                        active_job_ids = self.runtime_store.get_active_job_resource_ids(site_id=site_id, resource_ids=candidate_ids)
                    except Exception as exc:
                        logger.warning("[%s] fallo prefetch active job ids: %s", site_id, exc)

                hydration_prefetch_window = max(
                    1,
                    int((os.getenv("BRAIN_PAYLOAD_HYDRATE_PREFETCH_WINDOW") or "25").strip() or "25"),
                )
                hydrated_payload_cache: dict[int, dict[str, Any]] = {}

                for idx, (rid, cand) in enumerate(parsed_candidates):
                    if remaining <= 0:
                        break
                    if site_limit is not None and site_claimed >= site_limit:
                        break
                    if not self.is_still_claimable_in_db(rid):
                        logger.info("[%s] descartado idRecurso=%s por no estar reclamable en SQL Server (revalidacion).", site_id, rid)
                        continue
                    validation = validate_candidate(
                        site_id=site_id,
                        candidate=cand,
                        runtime_store=self.runtime_store,
                        admin_store=self.admin_store,
                        is_blocked=(rid in blocked_ids),
                        is_resource_paused=(rid in paused_ids),
                    )
                    if not validation.processable:
                        error_code = str(validation.error_code or "NOT_PROCESSABLE")
                        reason = str(validation.description or "Recurso no procesable por validación previa.")
                        self._record_incident(site_id=site_id, error_code=error_code, description=reason, candidate=cand)
                        stats["incidents_logged"] += 1
                        logger.info("[%s] idRecurso=%s no procesable: %s - %s", site_id, rid, error_code, reason)
                        continue
                    has_active_job = rid in active_job_ids
                    if has_active_job:
                        recovery = self.runtime_store.recover_stale_queued_job_for_resource(
                            site_id=site_id,
                            resource_id=rid,
                            stale_seconds=self.active_job_stale_seconds,
                            reason_prefix="brain_claim_stale_queued_guard",
                        )
                        if recovery.get("recovered"):
                            logger.warning(
                                "[%s] stale queued recuperado para idRecurso=%s job_id=%s age=%ss (threshold=%ss).",
                                site_id,
                                rid,
                                recovery.get("job_id"),
                                recovery.get("age_seconds"),
                                recovery.get("threshold_seconds"),
                            )
                            active_job_ids.discard(rid)
                            has_active_job = False

                    if has_active_job:
                        logger.info(
                            "[%s] descartado idRecurso=%s por job activo en cola (queued/processing).",
                            site_id,
                            rid,
                        )
                        continue
                    if not await self._reserve_claim_slot_with_stale_recovery(site_id=site_id, resource_id=rid):
                        logger.info(
                            "[%s] dedupe-claim activo para idRecurso=%s; se omite republicacion.",
                            site_id,
                            rid,
                        )
                        continue

                    keep_claim_slot = False
                    try:
                        expediente = str(cand.get("Expedient") or "").strip()
                        ok = await adapter.ensure_claimed(self, cand)
                        if not ok:
                            stats["errors"] += 1
                            continue
                        stats["claimed"] += 1
                        remaining -= 1
                        site_claimed += 1

                        if rid not in hydrated_payload_cache:
                            window_ids: list[int] = []
                            for future_rid, _future_cand in parsed_candidates[idx : idx + hydration_prefetch_window]:
                                if future_rid not in hydrated_payload_cache:
                                    window_ids.append(future_rid)
                            hydrated_batch = self._hydrate_candidates_batch_for_payload(
                                site_id=site_id,
                                resource_ids=window_ids or [rid],
                            )
                            hydrated_payload_cache.update(hydrated_batch)

                        candidate_for_payload = dict(cand or {})
                        full_data = hydrated_payload_cache.get(rid)
                        if full_data:
                            # No pisar datos utiles del candidate con vacios durante hidratacion.
                            for key, value in full_data.items():
                                if value in (None, "", []):
                                    continue
                                candidate_for_payload[key] = value
                        payloads = await adapter.build_payloads([candidate_for_payload], on_discard=_on_discard)
                        if not payloads:
                            logger.warning(
                                "[%s] idRecurso=%s reclamado pero descartado por adapter.build_payloads (payload invalido).",
                                site_id,
                                rid,
                            )
                            continue

                        for payload in payloads:
                            trace_id = str(uuid.uuid4())
                            rid_payload = payload.get("idRecurso")
                            try:
                                rid_payload_int = int(rid_payload) if rid_payload is not None else rid
                            except Exception:
                                rid_payload_int = rid
                            candidate_payload = {
                                "candidate_id": str(uuid.uuid4()),
                                "organism_id": site_id,
                                "external_resource_id": str(rid_payload_int),
                                "raw_payload": json.loads(json.dumps(payload, default=str)),
                                "claimed_at": payload.get("claimed_at") or cand.get("claimed_at") or "",
                                "trace_id": trace_id,
                                "expediente": str(payload.get("expediente") or expediente),
                            }
                            await self.streams.publish_json(
                                stream=self.candidates_stream,
                                payload=candidate_payload,
                                maxlen=int((os.getenv("CANDIDATES_STREAM_MAXLEN") or "200000").strip() or "200000"),
                            )
                            stats["published_candidates"] += 1
                            keep_claim_slot = True
                            try:
                                self.realtime_store.clear_incident(
                                    site_id=site_id,
                                    resource_id=rid_payload_int,
                                    incident_type="SITE_RULE_DISCARDED",
                                )
                            except Exception:
                                pass
                    finally:
                        if not keep_claim_slot:
                            await self._release_claim_slot(site_id=site_id, resource_id=rid)
            except Exception as exc:
                logger.exception("[%s] fallo en run_tick claim-only: %s", site_id, exc)
                stats["errors"] += 1
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
                if not self.runtime_store.is_process_enabled(process_name="brain"):
                    try:
                        await asyncio.wait_for(shutdown.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        pass
                    continue
                stats = await self.run_tick()
                logger.info("[brain-claim] stats=%s", stats)
            except Exception as exc:
                logger.exception("Error run_forever brain-claim: %s", exc)
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self.sync_interval)
            except asyncio.TimeoutError:
                pass


async def _main_async() -> None:
    _setup_brain_claim_logging()
    svc = BrainClaimService()
    await svc.run_forever()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
