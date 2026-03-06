from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Optional


class SiteAdapter:
    site_id: str
    priority: int

    DiscardCallback = Callable[[dict[str, Any]], None]

    def __init__(self, *, site_id: str, priority: int):
        self.site_id = site_id
        self.priority = priority

    @staticmethod
    def _normalize_user_identity(value: Any) -> str:
        text = str(value or "")
        text = text.replace("\u00a0", " ")
        text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
        text = text.casefold()
        text = re.sub(r"\s+", " ", text).strip()
        # Quitar ruido no alfanumerico para tolerar variantes visuales.
        text = re.sub(r"[^a-z0-9 ]+", "", text)
        return text

    @classmethod
    def _same_user_identity(cls, left: Any, right: Any) -> bool:
        return cls._normalize_user_identity(left) == cls._normalize_user_identity(right)

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
        on_discard: Optional[DiscardCallback] = None,
        resource_repo: Any | None = None,
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

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[DiscardCallback] = None,
    ) -> list[dict]:
        raise NotImplementedError
