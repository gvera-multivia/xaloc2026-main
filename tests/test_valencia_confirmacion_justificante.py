from __future__ import annotations

from pathlib import Path

import pytest

from sites.valencia.data_models import ValenciaTarget
from sites.valencia.flows import confirmacion


class _FakeResponse:
    def __init__(self, body: bytes, *, ok: bool = True, status: int = 200) -> None:
        self.ok = ok
        self.status = status
        self._body = body

    async def body(self) -> bytes:
        return self._body


class _FakeRequestClient:
    def __init__(self) -> None:
        self.last_url: str | None = None

    async def get(self, url: str, timeout: int = 0) -> _FakeResponse:
        self.last_url = url
        _ = timeout
        return _FakeResponse(b"%PDF-1.4\n%fake-pdf\n")


class _FakeContext:
    def __init__(self) -> None:
        self.request = _FakeRequestClient()


class _FakeDownloadWaiter:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeLocator:
    def __init__(self, *, visible: bool = True) -> None:
        self._visible = visible

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def wait_for(self, *, state: str, timeout: int) -> None:
        _ = (state, timeout)
        if not self._visible:
            raise RuntimeError("not visible")
        return None

    async def click(self, *, force: bool = False) -> None:
        _ = force
        # Fuerza el camino de fallback HTTP.
        raise RuntimeError("download event not available")

    async def get_attribute(self, name: str) -> str:
        if name == "onclick":
            return "window.open('/descarga/justificante.pdf','_self')"
        return ""


class _FakePage:
    def __init__(self, *, visible_selector: bool = True) -> None:
        self.context = _FakeContext()
        self.selectors_seen: list[str] = []
        self.visible_selector = visible_selector

    def locator(self, selector: str) -> _FakeLocator:
        self.selectors_seen.append(selector)
        return _FakeLocator(visible=self.visible_selector)

    def expect_download(self, timeout: int = 0) -> _FakeDownloadWaiter:
        _ = timeout
        return _FakeDownloadWaiter()

    async def evaluate(self, script: str, arg=None):
        _ = arg
        if "body_text_head" in script and "data_clickable_url" in script:
            return {
                "ok": True,
                "url": "https://sede.valencia.es/sede/registro/tramites/presentarInstancia/test",
                "title": "Sede Electrónica",
                "body_text_head": "Justificante disponible",
                "candidates": [
                    {
                        "tag": "a",
                        "id": "",
                        "name": "",
                        "text": "Descarga justificante",
                        "href": "/descarga/heuristica.pdf",
                        "onclick": "",
                        "data_clickable_url": "",
                        "visible": True,
                    }
                ],
            }
        raise AssertionError(f"Unexpected evaluate call: {script[:120]}")


@pytest.mark.asyncio
async def test_descargar_justificante_post_firma_uses_id_and_http_fallback(monkeypatch, tmp_path: Path) -> None:
    destino_dir = tmp_path / "destino"
    captured: dict[str, str] = {}

    def _fake_resolve_receipt_dir_from_payload(*, payload: dict, fase_procedimiento=None, base_path=None) -> Path:
        _ = (fase_procedimiento, base_path)
        captured["expediente"] = str(payload.get("expediente") or "")
        return destino_dir

    def _fake_save_receipt_from_tmp(*, tmp_path: Path, destino_dir: Path, filename: str) -> Path:
        destino_dir.mkdir(parents=True, exist_ok=True)
        final = destino_dir / filename
        final.write_bytes(tmp_path.read_bytes())
        tmp_path.unlink(missing_ok=True)
        captured["filename"] = filename
        return final

    monkeypatch.setattr(confirmacion, "resolve_receipt_dir_from_payload", _fake_resolve_receipt_dir_from_payload)
    monkeypatch.setattr(confirmacion, "save_receipt_from_tmp", _fake_save_receipt_from_tmp)

    datos = ValenciaTarget(
        idRecurso=123,
        expediente="2026/EXP-77",
        fase_procedimiento="Sancion",
        payload={"idRecurso": 123, "expediente": "2026/EXP-77", "fase_procedimiento": "Sancion"},
    )
    page = _FakePage()

    out = await confirmacion._descargar_y_guardar_justificante_post_firma(page, datos)

    assert 'input[id="formDescargas:j_id988508038_1_2cd7c38b"]' in page.selectors_seen
    assert page.context.request.last_url == "https://sede.valencia.es/descarga/justificante.pdf"
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
    assert captured["expediente"] == "2026/EXP-77"
    assert captured["filename"] == "JUSTIFICANTE - 2026-EXP-77.pdf"


@pytest.mark.asyncio
async def test_descargar_justificante_post_firma_uses_dom_probe_when_selector_not_visible(monkeypatch, tmp_path: Path) -> None:
    destino_dir = tmp_path / "destino"

    def _fake_resolve_receipt_dir_from_payload(*, payload: dict, fase_procedimiento=None, base_path=None) -> Path:
        _ = (payload, fase_procedimiento, base_path)
        return destino_dir

    def _fake_save_receipt_from_tmp(*, tmp_path: Path, destino_dir: Path, filename: str) -> Path:
        destino_dir.mkdir(parents=True, exist_ok=True)
        final = destino_dir / filename
        final.write_bytes(tmp_path.read_bytes())
        return final

    monkeypatch.setattr(confirmacion, "resolve_receipt_dir_from_payload", _fake_resolve_receipt_dir_from_payload)
    monkeypatch.setattr(confirmacion, "save_receipt_from_tmp", _fake_save_receipt_from_tmp)

    datos = ValenciaTarget(
        idRecurso=124,
        expediente="2026/EXP-78",
        fase_procedimiento="Sancion",
        payload={"idRecurso": 124, "expediente": "2026/EXP-78", "fase_procedimiento": "Sancion"},
    )
    page = _FakePage(visible_selector=False)

    out = await confirmacion._descargar_y_guardar_justificante_post_firma(page, datos)

    assert page.context.request.last_url == "https://sede.valencia.es/descarga/heuristica.pdf"
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
