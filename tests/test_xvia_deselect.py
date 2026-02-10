import os
import sys
import pytest

sys.path.append(os.getcwd())

from core.xvia_deselect import deselect_resource


class _FakeResponse:
    def __init__(self, *, status: int, text_value: str = ""):
        self.status = status
        self._text_value = text_value

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self._text_value


class _FakeSession:
    def __init__(self, *, get_response: _FakeResponse, post_response: _FakeResponse):
        self._get_response = get_response
        self._post_response = post_response
        self.post_calls: list[dict] = []

    def get(self, url: str):  # noqa: ARG002
        return self._get_response

    def post(self, url: str, data: dict):
        self.post_calls.append({"url": url, "data": data})
        return self._post_response


@pytest.mark.asyncio
async def test_deselect_resource_success() -> None:
    html = '<input name="_token" value="csrf-123" />'
    session = _FakeSession(
        get_response=_FakeResponse(status=200, text_value=html),
        post_response=_FakeResponse(status=302),
    )

    ok = await deselect_resource(session, 555)
    assert ok is True
    assert len(session.post_calls) == 1
    sent_data = session.post_calls[0]["data"]
    assert sent_data["id"] == "555"
    assert sent_data["recurso_id"] == "555"
    assert sent_data["_token"] == "csrf-123"


@pytest.mark.asyncio
async def test_deselect_resource_missing_token() -> None:
    session = _FakeSession(
        get_response=_FakeResponse(status=200, text_value="<html></html>"),
        post_response=_FakeResponse(status=302),
    )

    ok = await deselect_resource(session, 999)
    assert ok is False
    assert session.post_calls == []
