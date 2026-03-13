from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any

from core.domain import ResourceDomain
from core.repositories import ResourceRepository

from .normalizer import normalize_resource_row


class ConsultorService:
    """
    Compatibility-mode consultor facade.
    Slice 2 goal: no behavior change for existing adapters.
    """

    def __init__(
        self,
        *,
        conn_str: str,
        logger: logging.Logger | None = None,
        repository: ResourceRepository | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("consultor_service")
        self.repository = repository or ResourceRepository(conn_str=conn_str, logger=self.logger)

    def get_pending_resources(
        self,
        *,
        site_id: str,
        config: dict[str, Any],
        limit: int,
        include_canonical: bool = True,
    ) -> list[ResourceDomain]:
        resources = self.repository.get_pending_resources(site_id=site_id, config=config, limit=limit)
        if not resources:
            return []

        out: list[ResourceDomain] = []
        for item in resources:
            metadata = dict(item.metadata or {})

            canonical = None
            if include_canonical:
                canonical = normalize_resource_row(site_id=site_id, row=metadata)
                metadata["__canonical_v1"] = {
                    "site_id": canonical.site_id,
                    "resource": canonical.resource,
                    "client": canonical.client,
                    "vehicle": canonical.vehicle,
                    "attachments": canonical.attachments,
                    "meta": canonical.meta,
                }

            out.append(replace(item, metadata=metadata))
        return out


class ConsultorResourceRepositoryAdapter:
    """
    Adapter that exposes `get_pending_resources` with the same contract
    expected by existing adapters (`resource_repo` argument).
    """

    def __init__(self, consultor: ConsultorService):
        self.consultor = consultor

    def get_pending_resources(self, *, site_id: str, config: dict[str, Any], limit: int) -> list[ResourceDomain]:
        return self.consultor.get_pending_resources(
            site_id=site_id,
            config=config,
            limit=limit,
            include_canonical=True,
        )
