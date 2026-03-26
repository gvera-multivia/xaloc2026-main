from __future__ import annotations

import pytest

from core.worker_execution import task_orchestrator
from core.worker_execution.models import ProcessOutcome


def test_ensure_diputacio_codmuni_uses_cliente_municipio_for_orgt() -> None:
    payload = {
        "organismo": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
        "cliente_municipio": "SABADELL",
    }
    err = task_orchestrator._ensure_diputacio_codmuni(payload)  # type: ignore[attr-defined]
    assert err is None
    assert payload.get("codmuni") == "186"


def test_ensure_diputacio_codmuni_errors_for_orgt_without_municipio() -> None:
    payload = {
        "organismo": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
    }
    err = task_orchestrator._ensure_diputacio_codmuni(payload)  # type: ignore[attr-defined]
    assert isinstance(err, str)
    assert "falta 'codmuni'" in err


@pytest.mark.asyncio
async def test_process_task_diputacio_fails_without_justificante_and_skips_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_download_document_and_attachments(**kwargs):
        return []

    async def _fake_append(payload, archivos_para_subir, *, site_id=None):
        return archivos_para_subir

    async def _fake_browser_flow(*, site_id, protocol, payload, archivos_para_subir):
        return ProcessOutcome(
            success=True,
            payload_updates={
                "diputacio_justificante_descargado": False,
            },
        )

    mark_complete_calls: list[int] = []

    async def _fake_mark_complete(_session, payload):
        mark_complete_calls.append(int(payload["idRecurso"]))
        return True

    monkeypatch.setattr(task_orchestrator, "download_document_and_attachments", _fake_download_document_and_attachments)
    monkeypatch.setattr(task_orchestrator, "_append_required_client_docs", _fake_append)
    monkeypatch.setattr(task_orchestrator, "use_remote_playwright_runner", lambda: False)
    monkeypatch.setattr(task_orchestrator, "execute_browser_flow", _fake_browser_flow)
    monkeypatch.setattr(task_orchestrator, "mark_resource_complete", _fake_mark_complete)

    payload = {
        "idRecurso": 103317,
        "numclient": 1,
        "cliente_nombre": "Juan",
        "cliente_apellido1": "Perez",
        "expediente": "541999/25",
        "cliente_municipio": "SABADELL",
    }
    outcome = await task_orchestrator.process_task(
        task_id=103317,
        site_id="diputacio_bcn",
        protocol=None,
        payload=payload,
        auth_session=object(),
    )

    assert outcome.success is False
    assert "justificante" in str(outcome.error or "").lower()
    assert payload.get("codmuni") == "186"
    assert mark_complete_calls == []


@pytest.mark.asyncio
async def test_process_task_diputacio_marks_complete_when_justificante_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_download_document_and_attachments(**kwargs):
        return []

    async def _fake_append(payload, archivos_para_subir, *, site_id=None):
        return archivos_para_subir

    async def _fake_browser_flow(*, site_id, protocol, payload, archivos_para_subir):
        return ProcessOutcome(
            success=True,
            payload_updates={
                "diputacio_justificante_descargado": True,
                "diputacio_justificante_path": "tmp/diputacio_bcn/justificantes/103318/recibo.pdf",
            },
        )

    mark_complete_calls: list[int] = []

    async def _fake_mark_complete(_session, payload):
        mark_complete_calls.append(int(payload["idRecurso"]))
        return True

    monkeypatch.setattr(task_orchestrator, "download_document_and_attachments", _fake_download_document_and_attachments)
    monkeypatch.setattr(task_orchestrator, "_append_required_client_docs", _fake_append)
    monkeypatch.setattr(task_orchestrator, "use_remote_playwright_runner", lambda: False)
    monkeypatch.setattr(task_orchestrator, "execute_browser_flow", _fake_browser_flow)
    monkeypatch.setattr(task_orchestrator, "mark_resource_complete", _fake_mark_complete)

    payload = {
        "idRecurso": 103318,
        "numclient": 1,
        "cliente_nombre": "Juan",
        "cliente_apellido1": "Perez",
        "expediente": "542000/25",
        "cliente_municipio": "SABADELL",
    }
    outcome = await task_orchestrator.process_task(
        task_id=103318,
        site_id="diputacio_bcn",
        protocol=None,
        payload=payload,
        auth_session=object(),
    )

    assert outcome.success is True
    assert payload.get("codmuni") == "186"
    assert mark_complete_calls == [103318]


@pytest.mark.asyncio
async def test_process_task_diputacio_marks_complete_when_only_justificante_path_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_download_document_and_attachments(**kwargs):
        return []

    async def _fake_append(payload, archivos_para_subir, *, site_id=None):
        return archivos_para_subir

    async def _fake_browser_flow(*, site_id, protocol, payload, archivos_para_subir):
        return ProcessOutcome(
            success=True,
            payload_updates={
                "diputacio_justificante_descargado": False,
                "diputacio_justificante_path": "tmp/diputacio_bcn/justificantes/103319/recibo.pdf",
            },
        )

    mark_complete_calls: list[int] = []

    async def _fake_mark_complete(_session, payload):
        mark_complete_calls.append(int(payload["idRecurso"]))
        return True

    monkeypatch.setattr(task_orchestrator, "download_document_and_attachments", _fake_download_document_and_attachments)
    monkeypatch.setattr(task_orchestrator, "_append_required_client_docs", _fake_append)
    monkeypatch.setattr(task_orchestrator, "use_remote_playwright_runner", lambda: False)
    monkeypatch.setattr(task_orchestrator, "execute_browser_flow", _fake_browser_flow)
    monkeypatch.setattr(task_orchestrator, "mark_resource_complete", _fake_mark_complete)

    payload = {
        "idRecurso": 103319,
        "numclient": 1,
        "cliente_nombre": "Juan",
        "cliente_apellido1": "Perez",
        "expediente": "542001/25",
        "cliente_municipio": "SABADELL",
    }
    outcome = await task_orchestrator.process_task(
        task_id=103319,
        site_id="diputacio_bcn",
        protocol=None,
        payload=payload,
        auth_session=object(),
    )

    assert outcome.success is True
    assert mark_complete_calls == [103319]
