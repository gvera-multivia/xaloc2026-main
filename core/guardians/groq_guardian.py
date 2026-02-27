from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.address_classifier import classify_address_fallback, classify_addresses_batch_with_ai


@dataclass(frozen=True)
class ResourceContext:
    site_id: str
    protocol: str = ""


class GroqTokenGuardian:
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("groq_guardian")

    @staticmethod
    def _normalize_site(site_id: str) -> str:
        return str(site_id or "").strip().lower()

    @staticmethod
    def _normalize_protocol(protocol: str) -> str:
        return str(protocol or "").strip().upper()

    def can_call_llm(self, context: ResourceContext) -> bool:
        site = self._normalize_site(context.site_id)
        protocol = self._normalize_protocol(context.protocol)
        if site == "madrid":
            return True
        if site == "base_online" and protocol == "P1":
            return True
        return False

    async def classify_batch(
        self,
        *,
        items: list[dict[str, Any]],
        context_by_id: dict[str, ResourceContext],
    ) -> dict[str, dict]:
        if not items:
            return {}

        allowed: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for item in items:
            rid = str(item.get("idRecurso") or "").strip()
            ctx = context_by_id.get(rid)
            if ctx and self.can_call_llm(ctx):
                allowed.append(item)
            else:
                blocked.append(item)

        out: dict[str, dict] = {}
        for item in blocked:
            rid = str(item.get("idRecurso") or "").strip()
            if not rid:
                continue
            out[rid] = classify_address_fallback(str(item.get("direccion_raw") or ""))

        if not allowed:
            return out

        try:
            llm_out = await classify_addresses_batch_with_ai(allowed)
            out.update(llm_out)
            return out
        except Exception as exc:
            self.logger.warning("Groq guardian fallback por error batch LLM: %s", exc)
            for item in allowed:
                rid = str(item.get("idRecurso") or "").strip()
                if not rid:
                    continue
                out[rid] = classify_address_fallback(str(item.get("direccion_raw") or ""))
            return out
