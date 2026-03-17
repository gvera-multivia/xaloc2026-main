from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any

from dotenv import load_dotenv


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.consultor import ConsultorResourceRepositoryAdapter, ConsultorService
from core.pg_admin_store import PgAdminStore
from core.pg_runtime_store import PgRuntimeStore
from core.repositories import ResourceRepository
from core.sqlserver_utils import build_sqlserver_connection_string
from services.brain_claim.processable_validator import validate_candidate
from sites.adapters import (
    AyuntaPalmaAdapter,
    BaseOnlineAdapter,
    MadridAdapter,
    RedsaraAdapter,
    TerrassaAdapter,
    XalocAdapter,
)
from sites.adapters.site_adapter import SiteAdapter


@dataclass
class SiteMetrics:
    site_id: str
    configured_limit: int
    fetched_candidates: int
    discarded_in_fetch: int
    blocked_prefetch_count: int
    paused_prefetch_count: int
    active_jobs_prefetch_count: int
    processable_after_prefetch: int
    hydrated_resources: int
    payloads_built: int
    fetch_light_ms: float
    prefetch_pg_ms: float
    validate_ms: float
    hydrate_full_ms: float
    build_payloads_ms: float
    total_site_ms: float
    errors: int


def _build_adapters() -> dict[str, SiteAdapter]:
    return {
        "madrid": MadridAdapter(),
        "xaloc_girona": XalocAdapter(),
        "base_online": BaseOnlineAdapter(),
        "ayunta_palma": AyuntaPalmaAdapter(),
        "redsara": RedsaraAdapter(),
        "terrassa": TerrassaAdapter(),
    }


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


async def _run_site_probe(
    *,
    site_id: str,
    adapter: SiteAdapter,
    config: dict[str, Any],
    sql_conn_str: str,
    admin_store: PgAdminStore,
    runtime_store: PgRuntimeStore,
    consultor_light: ConsultorResourceRepositoryAdapter,
    resource_repo: ResourceRepository,
    authenticated_user: str | None,
    limit: int,
    hydrate_limit: int,
) -> SiteMetrics:
    site_t0 = time.perf_counter()
    fetch_light_ms = 0.0
    prefetch_pg_ms = 0.0
    validate_ms = 0.0
    hydrate_full_ms = 0.0
    build_payloads_ms = 0.0
    discarded_in_fetch = 0
    errors = 0

    def _on_discard(_: dict[str, Any]) -> None:
        nonlocal discarded_in_fetch
        discarded_in_fetch += 1

    t0 = time.perf_counter()
    candidates = adapter.fetch_candidates(
        config=config,
        conn_str=sql_conn_str,
        authenticated_user=authenticated_user,
        limit=limit,
        on_discard=_on_discard,
        resource_repo=consultor_light,
    )
    fetch_light_ms = (time.perf_counter() - t0) * 1000.0

    parsed_candidates: list[tuple[int, dict[str, Any]]] = []
    for cand in candidates:
        rid = _parse_resource_id(cand.get("idRecurso"))
        if rid is None:
            continue
        parsed_candidates.append((rid, cand))

    candidate_ids = sorted({rid for rid, _ in parsed_candidates})

    t0 = time.perf_counter()
    blocked_ids = admin_store.get_blocked_resource_ids(site_id=site_id, resource_ids=candidate_ids)
    paused_ids = runtime_store.get_paused_resource_ids(site_id=site_id, resource_ids=candidate_ids)
    active_job_ids = runtime_store.get_active_job_resource_ids(site_id=site_id, resource_ids=candidate_ids)
    prefetch_pg_ms = (time.perf_counter() - t0) * 1000.0

    processable: list[tuple[int, dict[str, Any]]] = []
    t0 = time.perf_counter()
    for rid, cand in parsed_candidates:
        try:
            validation = validate_candidate(
                site_id=site_id,
                candidate=cand,
                runtime_store=runtime_store,
                admin_store=admin_store,
                is_blocked=(rid in blocked_ids),
                is_resource_paused=(rid in paused_ids),
            )
            if not validation.processable:
                continue
            if rid in active_job_ids:
                continue
            processable.append((rid, cand))
        except Exception:
            errors += 1
    validate_ms = (time.perf_counter() - t0) * 1000.0

    finalists = processable[: max(0, hydrate_limit)]
    finalists_ids = [rid for rid, _ in finalists]

    hydrated_by_id: dict[int, dict[str, Any]] = {}
    if finalists_ids:
        t0 = time.perf_counter()
        hydrated = resource_repo.get_resources_by_ids(site_id=site_id, resource_ids=finalists_ids)
        for item in hydrated:
            meta = dict(item.metadata or {})
            rid = _parse_resource_id(meta.get("idRecurso"))
            if rid is not None:
                hydrated_by_id[rid] = meta
        hydrate_full_ms = (time.perf_counter() - t0) * 1000.0

    payload_input: list[dict[str, Any]] = []
    for rid, cand in finalists:
        merged = dict(cand)
        full = hydrated_by_id.get(rid)
        if full:
            merged.update(full)
        payload_input.append(merged)

    payloads: list[dict[str, Any]] = []
    if payload_input:
        t0 = time.perf_counter()
        try:
            payloads = await adapter.build_payloads(payload_input, on_discard=_on_discard)
        except Exception:
            errors += 1
            payloads = []
        build_payloads_ms = (time.perf_counter() - t0) * 1000.0

    total_site_ms = (time.perf_counter() - site_t0) * 1000.0
    return SiteMetrics(
        site_id=site_id,
        configured_limit=limit,
        fetched_candidates=len(candidates),
        discarded_in_fetch=discarded_in_fetch,
        blocked_prefetch_count=len(blocked_ids),
        paused_prefetch_count=len(paused_ids),
        active_jobs_prefetch_count=len(active_job_ids),
        processable_after_prefetch=len(processable),
        hydrated_resources=len(hydrated_by_id),
        payloads_built=len(payloads),
        fetch_light_ms=round(fetch_light_ms, 2),
        prefetch_pg_ms=round(prefetch_pg_ms, 2),
        validate_ms=round(validate_ms, 2),
        hydrate_full_ms=round(hydrate_full_ms, 2),
        build_payloads_ms=round(build_payloads_ms, 2),
        total_site_ms=round(total_site_ms, 2),
        errors=errors,
    )


async def _async_main(args: argparse.Namespace) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [benchmark] %(levelname)s %(message)s")
    logger = logging.getLogger("benchmark")

    sql_conn_str = build_sqlserver_connection_string()
    admin_store = PgAdminStore.from_env(logger=logger)
    runtime_store = PgRuntimeStore.from_env(logger=logger)
    resource_repo = ResourceRepository(conn_str=sql_conn_str, logger=logger)
    consultor = ConsultorService(conn_str=sql_conn_str, logger=logger, repository=resource_repo)
    consultor_light = ConsultorResourceRepositoryAdapter(consultor, retrieval_profile="light")
    adapters = _build_adapters()

    configured = {cfg["site_id"]: cfg for cfg in admin_store.get_active_organismo_configs()}
    selected_sites = args.sites or sorted(configured.keys())
    selected_sites = [s for s in selected_sites if s in configured and s in adapters]
    if args.max_sites > 0:
        selected_sites = selected_sites[: args.max_sites]

    if not selected_sites:
        print("No hay sedes activas seleccionadas para benchmark.")
        return 2

    all_metrics: list[SiteMetrics] = []
    total_t0 = time.perf_counter()
    for site_id in selected_sites:
        cfg = dict(configured[site_id] or {})
        site_limit_cfg = cfg.get("claim_limit_per_tick")
        site_limit = args.limit
        if site_limit_cfg not in (None, "", "null"):
            try:
                site_limit = min(site_limit, int(site_limit_cfg))
            except Exception:
                pass
        site_limit = max(1, site_limit)
        logger.info("Benchmark site=%s limit=%s hydrate_limit=%s", site_id, site_limit, args.hydrate_limit)
        try:
            metrics = await _run_site_probe(
                site_id=site_id,
                adapter=adapters[site_id],
                config=cfg,
                sql_conn_str=sql_conn_str,
                admin_store=admin_store,
                runtime_store=runtime_store,
                consultor_light=consultor_light,
                resource_repo=resource_repo,
                authenticated_user=args.authenticated_user,
                limit=site_limit,
                hydrate_limit=args.hydrate_limit,
            )
            all_metrics.append(metrics)
        except Exception as exc:
            logger.exception("Fallo benchmark para site=%s: %s", site_id, exc)
            all_metrics.append(
                SiteMetrics(
                    site_id=site_id,
                    configured_limit=site_limit,
                    fetched_candidates=0,
                    discarded_in_fetch=0,
                    blocked_prefetch_count=0,
                    paused_prefetch_count=0,
                    active_jobs_prefetch_count=0,
                    processable_after_prefetch=0,
                    hydrated_resources=0,
                    payloads_built=0,
                    fetch_light_ms=0.0,
                    prefetch_pg_ms=0.0,
                    validate_ms=0.0,
                    hydrate_full_ms=0.0,
                    build_payloads_ms=0.0,
                    total_site_ms=0.0,
                    errors=1,
                )
            )

    total_ms = round((time.perf_counter() - total_t0) * 1000.0, 2)

    summary = {
        "sites": [asdict(m) for m in all_metrics],
        "totals": {
            "sites_count": len(all_metrics),
            "fetched_candidates": sum(m.fetched_candidates for m in all_metrics),
            "processable_after_prefetch": sum(m.processable_after_prefetch for m in all_metrics),
            "hydrated_resources": sum(m.hydrated_resources for m in all_metrics),
            "payloads_built": sum(m.payloads_built for m in all_metrics),
            "errors": sum(m.errors for m in all_metrics),
            "total_elapsed_ms": total_ms,
        },
    }

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
        logger.info("Resultado guardado en %s", args.output_json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark de eficiencia del flujo brain (light fetch -> prefetch supervision -> hydrate full finalistas -> build payloads)."
    )
    parser.add_argument(
        "--site",
        dest="sites",
        action="append",
        default=[],
        help="Site a medir (repetible). Si se omite, usa todos los activos.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max candidatos por site para fetch_light (default: 200).",
    )
    parser.add_argument(
        "--hydrate-limit",
        type=int,
        default=50,
        help="Max finalistas a hidratar/build payload por site (default: 50).",
    )
    parser.add_argument(
        "--max-sites",
        type=int,
        default=0,
        help="Limita numero de sites procesados (0 = sin limite).",
    )
    parser.add_argument(
        "--authenticated-user",
        default=None,
        help="Usuario XVIA para aplicar filtros de estado=1 en adapters (opcional).",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Ruta opcional para guardar salida JSON.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
