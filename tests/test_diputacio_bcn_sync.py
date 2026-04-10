from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.diputacio_bcn.flows._sync import click_and_wait


class _FakeLocator:
    def __init__(self) -> None:
        self.clicked = False
        self.first = self

    async def wait_for(self, state: str, timeout: int) -> None:
        return None

    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def click(self, timeout: int) -> None:
        self.clicked = True

    async def count(self) -> int:
        return 1

    async def is_visible(self) -> bool:
        return self.clicked


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.test/start"
        self._target = _FakeLocator()

    def locator(self, selector: str) -> _FakeLocator:
        return self._target

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        return None

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


@pytest.mark.asyncio
async def test_click_and_wait_completes_when_url_matches() -> None:
    page = _FakePage()
    trigger = _FakeLocator()

    async def _click(timeout: int) -> None:
        trigger.clicked = True
        page.url = "https://example.test/next"

    trigger.click = _click  # type: ignore[method-assign]

    await click_and_wait(page, trigger, url_patterns=["**/next"])

    assert trigger.clicked is True


@pytest.mark.asyncio
async def test_click_and_wait_completes_when_selector_becomes_visible() -> None:
    page = _FakePage()
    trigger = _FakeLocator()

    async def _click(timeout: int) -> None:
        trigger.clicked = True
        page._target.clicked = True

    trigger.click = _click  # type: ignore[method-assign]

    await click_and_wait(page, trigger, visible_selectors=["#target"])

    assert trigger.clicked is True
