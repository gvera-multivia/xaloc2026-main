from __future__ import annotations

import asyncio
from types import SimpleNamespace

from services.brain_claim.app import BrainClaimService


def test_recover_claim_slot_for_reopened_resource_reclaims_when_sql_says_claimable() -> None:
    service = BrainClaimService.__new__(BrainClaimService)
    service.runtime_store = SimpleNamespace(
        has_active_job_for_resource=lambda *, site_id, resource_id: False
    )
    service.is_still_claimable_in_db = lambda resource_id: True

    released: list[tuple[str, int]] = []

    async def fake_release(*, site_id: str, resource_id: int) -> None:
        released.append((site_id, resource_id))

    async def fake_reserve(*, site_id: str, resource_id: int) -> bool:
        return True

    service._release_claim_slot = fake_release
    service._reserve_claim_slot = fake_reserve

    recovered = asyncio.run(
        service._recover_claim_slot_for_reopened_resource(site_id="madrid", resource_id=12345)
    )

    assert recovered is True
    assert released == [("madrid", 12345)]


def test_recover_claim_slot_for_reopened_resource_does_not_reclaim_with_active_job() -> None:
    service = BrainClaimService.__new__(BrainClaimService)
    service.runtime_store = SimpleNamespace(
        has_active_job_for_resource=lambda *, site_id, resource_id: True
    )
    service.is_still_claimable_in_db = lambda resource_id: True

    async def fake_release(*, site_id: str, resource_id: int) -> None:
        raise AssertionError("should not release dedupe key when job is active")

    async def fake_reserve(*, site_id: str, resource_id: int) -> bool:
        raise AssertionError("should not reserve dedupe key when job is active")

    service._release_claim_slot = fake_release
    service._reserve_claim_slot = fake_reserve

    recovered = asyncio.run(
        service._recover_claim_slot_for_reopened_resource(site_id="madrid", resource_id=12345)
    )

    assert recovered is False
