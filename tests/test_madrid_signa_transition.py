import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from sites.madrid.flows.firma import _entrar_en_signa_desde_prefirma


SIGNA_URL = "https://servcla.madrid.es/SIGNA_WBFIRMAR/solicitarFirma.do"
VERIFY_SELECTOR = "button[name='verificar'][value='1']"


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "visible"
        assert timeout > 0
        if self._selector == VERIFY_SELECTOR and not self._page.signa_selector_visible:
            raise AssertionError("El selector SIGNA no esta visible en el fake")

    async def click(self) -> None:
        if self._page.url_after_click is not None:
            self._page.url = self._page.url_after_click
        if self._page.response_after_click is not None:
            assert "response" in self._page.handlers
            self._page.emit("response", self._page.response_after_click)

    async def count(self) -> int:
        return int(
            self._selector == VERIFY_SELECTOR
            and self._page.signa_selector_visible
        )


class _FakeContext:
    def __init__(self, page: "_FakePage") -> None:
        self.pages = [page]
        self.handlers = {}

    def on(self, event: str, callback) -> None:
        self.handlers[event] = callback

    def remove_listener(self, event: str, callback) -> None:
        if self.handlers.get(event) is callback:
            self.handlers.pop(event)


class _FakeResponse:
    def __init__(self, *, url: str, status: int) -> None:
        self.url = url
        self.status = status


class _FakePage:
    def __init__(
        self,
        *,
        response_after_click: _FakeResponse | None = None,
        signa_selector_visible: bool = True,
        url_after_click: str | None = SIGNA_URL,
    ) -> None:
        self.url = "https://servcla.madrid.es/WFORS_WBWFORS/prefirma"
        self.signa_selector_visible = signa_selector_visible
        self.url_after_click = url_after_click
        self.response_after_click = response_after_click
        self.frames = []
        self.handlers = {}
        self.context = _FakeContext(self)

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def on(self, event: str, callback) -> None:
        self.handlers[event] = callback

    def emit(self, event: str, value) -> None:
        callback = self.handlers.get(event)
        if callback is not None:
            callback(value)

    def remove_listener(self, event: str, callback) -> None:
        if self.handlers.get(event) is callback:
            self.handlers.pop(event)

    def is_closed(self) -> bool:
        return False

    async def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        assert state == "domcontentloaded"
        assert timeout > 0

    async def wait_for_timeout(self, milliseconds: int) -> None:
        await asyncio.sleep(0)


def _config():
    return SimpleNamespace(
        firma_registrar_selector="#btRedireccion",
        default_timeout=100,
        firma_navigation_timeout=100,
        url_signa_firma_contains=SIGNA_URL,
        verificar_documento_selector=VERIFY_SELECTOR,
    )


def test_signa_continues_when_screen_is_ready_without_auxiliary_responses(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = _FakePage()
        with patch(
            "sites.madrid.flows.firma.wait_madrid_requests",
            new=AsyncMock(),
        ):
            result = await _entrar_en_signa_desde_prefirma(
                page,
                _config(),
                screenshot_dir=tmp_path,
            )

        assert result is page
        assert page.handlers == {}
        assert page.context.handlers == {}

    asyncio.run(scenario())


def test_signa_accepts_visible_selector_without_matching_url(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = _FakePage(url_after_click=None)
        with patch(
            "sites.madrid.flows.firma.wait_madrid_requests",
            new=AsyncMock(),
        ):
            result = await _entrar_en_signa_desde_prefirma(
                page,
                _config(),
                screenshot_dir=tmp_path,
            )

        assert result is page

    asyncio.run(scenario())


def test_signa_accepts_matching_url_before_selector_is_visible(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = _FakePage(signa_selector_visible=False)
        with patch(
            "sites.madrid.flows.firma.wait_madrid_requests",
            new=AsyncMock(),
        ):
            result = await _entrar_en_signa_desde_prefirma(
                page,
                _config(),
                screenshot_dir=tmp_path,
            )

        assert result is page

    asyncio.run(scenario())


def test_signa_keeps_explicit_http_errors_fatal(tmp_path: Path) -> None:
    async def scenario() -> None:
        response = _FakeResponse(
            url="https://servcla.madrid.es/WFORS_WBWFORS/guardarDocumentoSigna",
            status=400,
        )
        page = _FakePage(response_after_click=response)

        with patch(
            "sites.madrid.flows.firma.wait_madrid_requests",
            new=AsyncMock(),
        ):
            with pytest.raises(RuntimeError, match="guardarDocumentoSigna.*400"):
                await _entrar_en_signa_desde_prefirma(
                    page,
                    _config(),
                    screenshot_dir=tmp_path,
                )

        assert page.handlers == {}
        assert page.context.handlers == {}

    asyncio.run(scenario())
