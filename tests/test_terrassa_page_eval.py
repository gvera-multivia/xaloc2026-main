from __future__ import annotations

import pytest
from playwright.async_api import Error as PlaywrightError

from sites.terrassa.flows._page_eval import evaluate_with_nav_retry


class _FakePage:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.load_state_calls = 0
        self.timeout_calls: list[int] = []
        self.evaluate_calls = 0

    async def evaluate(self, _script: str, _arg: object | None = None):
        self.evaluate_calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def wait_for_load_state(self, _state: str, timeout: int) -> None:
        self.load_state_calls += 1
        self.timeout_calls.append(timeout)

    async def wait_for_timeout(self, timeout: int) -> None:
        self.timeout_calls.append(timeout)


@pytest.mark.asyncio
async def test_evaluate_with_nav_retry_retries_on_destroyed_context() -> None:
    page = _FakePage(
        [
            PlaywrightError("Page.evaluate: Execution context was destroyed, most likely because of a navigation"),
            {"ok": True},
        ]
    )

    result = await evaluate_with_nav_retry(page, "() => ({ ok: true })", attempts=3, settle_ms=10)

    assert result == {"ok": True}
    assert page.evaluate_calls == 2
    assert page.load_state_calls == 1
    assert 10 in page.timeout_calls


@pytest.mark.asyncio
async def test_evaluate_with_nav_retry_does_not_swallow_other_errors() -> None:
    page = _FakePage([PlaywrightError("Something else failed")])

    with pytest.raises(PlaywrightError, match="Something else failed"):
        await evaluate_with_nav_retry(page, "() => false", attempts=3)

    assert page.evaluate_calls == 1
    assert page.load_state_calls == 0
