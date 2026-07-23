from __future__ import annotations

from pathlib import Path

import pytest

from sites.xaloc_girona.flows import descarga_justificante as mod


class _FakeButton:
    def __init__(self, href: str):
        self.href = href

    async def wait_for(self, *, state: str, timeout: int) -> None:
        return None

    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def get_attribute(self, name: str) -> str:
        if name == "href":
            return self.href
        return ""


class _FakeLocator:
    def __init__(self, button: _FakeButton | None):
        self._button = button

    @property
    def first(self):
        return self

    async def wait_for(self, *, state: str, timeout: int) -> None:
        if self._button is None:
            raise TimeoutError("not found")

    async def scroll_into_view_if_needed(self) -> None:
        if self._button is None:
            raise TimeoutError("not found")
        await self._button.scroll_into_view_if_needed()

    async def get_attribute(self, name: str) -> str:
        if self._button is None:
            return ""
        return await self._button.get_attribute(name)


class _FakePage:
    url = "https://seu.xalocgirona.cat/final"

    def __init__(self):
        self.selectors: list[str] = []

    def locator(self, selector: str):
        self.selectors.append(selector)
        if "Visualitzar" in selector or "Visualizar" in selector:
            return _FakeLocator(_FakeButton("/justificant.pdf"))
        return _FakeLocator(None)


@pytest.mark.asyncio
async def test_descargar_reg_uses_visualitzar_justificant_when_descarregar_is_absent(monkeypatch, tmp_path: Path) -> None:
    async def _fake_download(_page, url: str, destino: Path) -> None:
        assert url == "https://seu.xalocgirona.cat/justificant.pdf"
        destino.write_bytes(b"%PDF-1.7\n" + (b"0" * 2000))

    monkeypatch.setattr(mod, "_descargar_pdf_desde_url", _fake_download)
    page = _FakePage()
    destino = tmp_path / "justificante.pdf"

    await mod._descargar_pdf_reg_desde_boton(page, destino)

    assert destino.exists()
    assert any("Descarregar" in selector for selector in page.selectors)
    assert any("Visualitzar" in selector for selector in page.selectors)
