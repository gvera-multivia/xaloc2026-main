from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from core.date_normalization import business_today
from services.brain_claim.app import BrainClaimService


class _FakeAdapter:
    def __init__(
        self,
        *,
        site_id: str,
        priority: int,
        candidates: list[dict[str, Any]],
        events: list[str],
    ) -> None:
        self.site_id = site_id
        self.priority = priority
        self.candidates = candidates
        self.events = events
        self.fetch_limits: list[int] = []

    def fetch_candidates(self, *, limit: int, **_: Any) -> list[dict[str, Any]]:
        self.events.append(f"fetch:{self.site_id}")
        self.fetch_limits.append(limit)
        return [dict(candidate) for candidate in self.candidates[:limit]]

    async def ensure_claimed(self, _service: BrainClaimService, candidate: dict[str, Any]) -> bool:
        self.events.append(f"claim:{candidate['idRecurso']}")
        return True

    async def build_payloads(self, candidates: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
        candidate = candidates[0]
        return [
            {
                "idRecurso": candidate["idRecurso"],
                "expediente": candidate["Expedient"],
            }
        ]


class _FakeAdminStore:
    @staticmethod
    def get_blocked_resource_ids(**_: Any) -> set[int]:
        return set()

    @staticmethod
    def is_resource_blocked(**_: Any) -> bool:
        return False


class _FakeRuntimeStore:
    def __init__(
        self,
        *,
        active_resource_ids: set[int] | None = None,
        terminal_failed_resource_ids: set[int] | None = None,
    ) -> None:
        self.active_resource_ids = set(active_resource_ids or set())
        self.terminal_failed_resource_ids = set(terminal_failed_resource_ids or set())
        self.repaired_submission_dates: list[tuple[str, int, str]] = []

    def purge_completed_resources_from_operational_tables(self) -> dict[str, int]:
        return {"deleted_total": 0}

    def mark_over_attempt_active_jobs_dead(self, **_: Any) -> dict[str, int]:
        return {"jobs_marked": 0, "blocks_upserted": 0}

    def is_site_processing_paused(self, **_: Any) -> bool:
        return False

    def get_paused_resource_ids(self, **_: Any) -> set[int]:
        return set()

    def get_active_job_resource_ids(self, **kwargs: Any) -> set[int]:
        return set(kwargs.get("resource_ids") or set()) & self.active_resource_ids

    def is_resource_processing_paused(self, **_: Any) -> bool:
        return False

    def recover_stale_queued_job_for_resource(self, **_: Any) -> dict[str, Any]:
        return {"recovered": False}

    def has_active_job_for_resource(self, **kwargs: Any) -> bool:
        return int(kwargs.get("resource_id") or 0) in self.active_resource_ids

    def has_terminal_failed_job_for_resource(self, **kwargs: Any) -> bool:
        return int(kwargs.get("resource_id") or 0) in self.terminal_failed_resource_ids

    def repair_active_job_submission_date(self, **kwargs: Any) -> int:
        self.repaired_submission_dates.append(
            (
                str(kwargs.get("site_id") or ""),
                int(kwargs.get("resource_id") or 0),
                str(kwargs.get("submission_date_iso") or ""),
            )
        )
        return 1


class _FakeStreams:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish_json(self, *, payload: dict[str, Any], **_: Any) -> str:
        self.published.append(payload)
        return str(len(self.published))


def _candidate(resource_id: int, submission_date: str | None) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "idRecurso": resource_id,
        "Expedient": f"EXP-{resource_id}",
        "Estado": 0,
    }
    if submission_date is not None:
        candidate["fpresentacion"] = submission_date
    return candidate


def _make_service(
    *,
    adapters: list[_FakeAdapter],
    max_claims: int,
    site_limits: dict[str, int] | None = None,
    active_resource_ids: set[int] | None = None,
    terminal_failed_resource_ids: set[int] | None = None,
) -> BrainClaimService:
    service = BrainClaimService.__new__(BrainClaimService)
    service.adapters = {adapter.site_id: adapter for adapter in adapters}
    service.max_claims = max_claims
    service.admin_store = _FakeAdminStore()
    service.runtime_store = _FakeRuntimeStore(
        active_resource_ids=active_resource_ids,
        terminal_failed_resource_ids=terminal_failed_resource_ids,
    )
    service.realtime_store = SimpleNamespace(clear_incident=lambda **_: None)
    service.streams = _FakeStreams()
    service.resource_repo = object()
    service.consultor_repo = object()
    service.consultor_repo_light = object()
    service.full_payload_sites = set()
    service.sqlserver_conn_str = "unused"
    service.authenticated_user = None
    service.active_job_stale_seconds = 100
    service.candidates_stream = "candidates"
    service._last_configured_sites_signature = None

    limits = site_limits or {}
    service.get_active_configs = lambda: [
        {
            "site_id": adapter.site_id,
            "login_url": "https://example.invalid/login",
            "claim_limit_per_tick": limits.get(adapter.site_id),
        }
        for adapter in adapters
    ]
    service.is_still_claimable_in_db = lambda _resource_id: True
    service._hydrate_candidates_batch_for_payload = lambda **_: {}
    service._record_incident = lambda **_: None

    async def _noop_session(*_: Any, **__: Any) -> None:
        return None

    async def _reserve(**_: Any) -> bool:
        return True

    async def _not_recovered(**_: Any) -> bool:
        return False

    service.init_session = _noop_session
    service.close_session = _noop_session
    service._reserve_claim_slot_with_stale_recovery = _reserve
    service._recover_claim_slot_for_reopened_resource = _not_recovered
    service._release_claim_slot = _noop_session
    return service


def test_run_tick_claims_mixed_organisms_in_global_submission_date_order() -> None:
    today = business_today()
    events: list[str] = []
    early_site = _FakeAdapter(
        site_id="early_site",
        priority=0,
        events=events,
        candidates=[
            _candidate(1, (today + timedelta(days=1)).isoformat()),
            _candidate(2, None),
            _candidate(3, (today - timedelta(days=1)).isoformat()),
        ],
    )
    late_site = _FakeAdapter(
        site_id="late_site",
        priority=99,
        events=events,
        candidates=[
            _candidate(4, (today - timedelta(days=2)).isoformat()),
            _candidate(5, today.isoformat()),
            _candidate(6, (today + timedelta(days=2)).isoformat()),
        ],
    )
    service = _make_service(adapters=[early_site, late_site], max_claims=6)

    stats = asyncio.run(service.run_tick())

    assert events[:2] == ["fetch:early_site", "fetch:late_site"]
    assert [event for event in events if event.startswith("claim:")] == [
        "claim:5",
        "claim:3",
        "claim:4",
        "claim:1",
        "claim:6",
        "claim:2",
    ]
    assert stats["claimed"] == 6
    assert stats["published_candidates"] == 6


def test_run_tick_global_limit_does_not_let_earlier_organism_win() -> None:
    today = business_today()
    events: list[str] = []
    early_site = _FakeAdapter(
        site_id="early_site",
        priority=0,
        events=events,
        candidates=[_candidate(10, (today + timedelta(days=1)).isoformat())],
    )
    late_site = _FakeAdapter(
        site_id="late_site",
        priority=99,
        events=events,
        candidates=[_candidate(20, today.isoformat())],
    )
    service = _make_service(adapters=[early_site, late_site], max_claims=1)

    stats = asyncio.run(service.run_tick())

    assert events == ["fetch:early_site", "fetch:late_site", "claim:20"]
    assert stats["claimed"] == 1
    assert service.streams.published[0]["external_resource_id"] == "20"
    assert service.streams.published[0]["raw_payload"]["fecpres"] == today.isoformat()


def test_run_tick_enforces_site_limit_after_global_sort() -> None:
    today = business_today()
    events: list[str] = []
    capped_site = _FakeAdapter(
        site_id="capped_site",
        priority=0,
        events=events,
        candidates=[
            _candidate(30, (today - timedelta(days=1)).isoformat()),
            _candidate(31, today.isoformat()),
        ],
    )
    other_site = _FakeAdapter(
        site_id="other_site",
        priority=1,
        events=events,
        candidates=[_candidate(40, (today - timedelta(days=2)).isoformat())],
    )
    service = _make_service(
        adapters=[capped_site, other_site],
        max_claims=3,
        site_limits={"capped_site": 1},
    )

    stats = asyncio.run(service.run_tick())

    assert capped_site.fetch_limits == [3]
    assert [event for event in events if event.startswith("claim:")] == ["claim:31", "claim:40"]
    assert stats["claimed"] == 2


def test_run_tick_repairs_submission_date_for_active_job_before_dedup_skip() -> None:
    today = business_today()
    events: list[str] = []
    site = _FakeAdapter(
        site_id="site_a",
        priority=0,
        events=events,
        candidates=[_candidate(50, None)],
    )
    service = _make_service(
        adapters=[site],
        max_claims=1,
        active_resource_ids={50},
    )
    service._hydrate_candidates_batch_for_payload = lambda **_: {
        50: {"fpresentacion": today.isoformat()}
    }

    stats = asyncio.run(service.run_tick())

    assert stats["claimed"] == 0
    assert service.streams.published == []
    assert [event for event in events if event.startswith("claim:")] == []
    assert service.runtime_store.repaired_submission_dates == [
        ("site_a", 50, today.isoformat())
    ]


def test_run_tick_skips_terminal_failed_resource_before_claim() -> None:
    today = business_today()
    events: list[str] = []
    site = _FakeAdapter(
        site_id="site_a",
        priority=0,
        events=events,
        candidates=[_candidate(60, today.isoformat())],
    )
    service = _make_service(
        adapters=[site],
        max_claims=1,
        terminal_failed_resource_ids={60},
    )

    stats = asyncio.run(service.run_tick())

    assert stats["claimed"] == 0
    assert service.streams.published == []
    assert [event for event in events if event.startswith("claim:")] == []
