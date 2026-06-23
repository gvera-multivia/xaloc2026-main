from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.append(os.getcwd())

import core.worker_execution.document_fetcher as fetcher_mod


class _FakeResponse:
    def __init__(self, *, status: int, url: str, body: bytes, content_type: str = "text/html; charset=UTF-8") -> None:
        self.status = status
        self.url = url
        self._body = body
        self.headers = {"content-type": content_type}

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, bool]] = []

    def get(self, url: str, allow_redirects: bool = True):
        self.calls.append((url, allow_redirects))
        if not self._responses:
            raise AssertionError("No fake responses left")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_download_primary_pdf_bytes_reauths_on_login_html(monkeypatch) -> None:
    session = _FakeSession(
        [
            _FakeResponse(
                status=200,
                url="http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/login",
                body=b"<!doctype html><html><head><title>XVia</title><meta name=\"csrf-token\" content=\"abc\"></head></html>",
            ),
            _FakeResponse(
                status=200,
                url="http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/111331",
                body=b"%PDF-1.5\n%fake\n",
                content_type="application/pdf",
            ),
        ]
    )
    reauth_calls: list[int] = []

    async def _fake_reauth(_session) -> bool:
        reauth_calls.append(1)
        return True

    monkeypatch.setattr(fetcher_mod, "_reauth_xvia_session", _fake_reauth)

    content = await fetcher_mod._download_primary_pdf_bytes(
        target_url="http://example.test/pdf/111331",
        auth_session=session,
    )

    assert content.startswith(b"%PDF")
    assert len(reauth_calls) == 1
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_download_primary_pdf_bytes_raises_precise_error_on_non_pdf_html(monkeypatch) -> None:
    session = _FakeSession(
        [
            _FakeResponse(
                status=200,
                url="http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/111331",
                body=b"<!doctype html><html><body>Error temporal del servidor</body></html>",
            ),
        ]
    )

    async def _fake_reauth(_session) -> bool:
        return False

    monkeypatch.setattr(fetcher_mod, "_reauth_xvia_session", _fake_reauth)

    with pytest.raises(RuntimeError, match="El archivo descargado no es un PDF valido|Sesion invalida o expirada"):
        await fetcher_mod._download_primary_pdf_bytes(
            target_url="http://example.test/pdf/111331",
            auth_session=session,
        )
