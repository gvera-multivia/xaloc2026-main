from __future__ import annotations

import asyncio
from pathlib import Path

import core.client_docs_service as svc


async def _fake_docs_builder(**kwargs):
    assert kwargs["payload"]["idRecurso"] == 123
    assert kwargs["strict"] is False
    return [Path("tmp/client_docs/a.pdf")]


def _fake_requires(payload: dict, base_path: str | None):
    assert payload["idRecurso"] == 123
    assert base_path == "/mnt/clientes"
    return (True, "missing AUT")


def test_get_required_client_documents_delegates(monkeypatch) -> None:
    monkeypatch.setattr(svc, "build_required_client_documents_for_payload", _fake_docs_builder)
    result = asyncio.run(
        svc.get_required_client_documents(
            {"idRecurso": 123},
            strict=False,
        )
    )
    assert result == [Path("tmp/client_docs/a.pdf")]


def test_requires_gesdoc_authorization_delegates(monkeypatch) -> None:
    monkeypatch.setattr(svc, "check_requires_gesdoc", _fake_requires)
    result = svc.requires_gesdoc_authorization({"idRecurso": 123}, base_path="/mnt/clientes")
    assert result == (True, "missing AUT")
