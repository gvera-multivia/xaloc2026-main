from __future__ import annotations

from typing import Optional


class SiteAdapter:
    site_id: str
    priority: int

    def __init__(self, *, site_id: str, priority: int):
        self.site_id = site_id
        self.priority = priority

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
    ) -> list[dict]:
        raise NotImplementedError

    async def ensure_claimed(self, orchestrator: "BrainOrchestrator", candidate: dict) -> bool:
        estado = int(candidate.get("Estado") or 0)
        if estado == 1:
            return True
        return await orchestrator.claim_resource_with_retries(
            id_recurso=int(candidate["idRecurso"]),
            expediente=str(candidate.get("Expedient") or ""),
        )

    async def build_payloads(self, candidates: list[dict]) -> list[dict]:
        raise NotImplementedError
