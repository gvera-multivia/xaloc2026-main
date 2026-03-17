from __future__ import annotations

import asyncio
from pathlib import Path

import core.client_documentation as docs


def test_build_required_client_documents_uses_single_output_label(monkeypatch) -> None:
    class _Identity:
        is_company = False

    captured: dict = {}

    def _fake_identity(_payload: dict):
        return _Identity()

    def _fake_select_required_client_documents(*, output_label: str, **kwargs):
        captured["output_label"] = output_label
        captured["kwargs"] = kwargs
        return docs.SelectedClientDocuments(
            files_to_upload=[Path("tmp/client_docs/a.pdf")],
            covered_terms=[],
            missing_terms=[],
        )

    monkeypatch.setattr(docs, "client_identity_from_payload", _fake_identity)
    monkeypatch.setattr(docs, "resolve_client_docs_base_path", lambda: Path("."))
    monkeypatch.setattr(docs, "get_ruta_cliente_documentacion", lambda *_args, **_kwargs: Path("."))
    monkeypatch.setattr(docs, "select_required_client_documents", _fake_select_required_client_documents)

    result = asyncio.run(
        docs.build_required_client_documents_for_payload(
            payload={"idRecurso": 102224},
            output_label="102224",
            strict=True,
        )
    )

    assert result == [Path("tmp/client_docs/a.pdf")]
    assert captured["output_label"] == "102224"
    assert "output_label" not in captured["kwargs"]


def test_check_requires_gesdoc_falls_back_to_db_identity(monkeypatch, tmp_path: Path) -> None:
    class _Identity:
        is_company = True

    def _raise_payload_identity(_payload: dict):
        raise docs.RequiredClientDocumentsError("Falta razon social para persona JURIDICA.")

    monkeypatch.setattr(docs, "client_identity_from_payload", _raise_payload_identity)
    monkeypatch.setattr(docs, "build_sqlserver_connection_string", lambda: "DRIVER=stub")
    monkeypatch.setattr(docs, "client_identity_from_db", lambda *_args, **_kwargs: _Identity())
    monkeypatch.setattr(docs, "resolve_client_docs_base_path", lambda: tmp_path)
    monkeypatch.setattr(docs, "get_ruta_cliente_documentacion", lambda *_args, **_kwargs: tmp_path)

    requires, reason = docs.check_requires_gesdoc({"numclient": 8781, "cliente_tipo": 2})

    assert requires is True
    assert "No se pudo inferir identidad del cliente" not in str(reason)
