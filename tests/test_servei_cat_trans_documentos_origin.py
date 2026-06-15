from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(os.getcwd())

import sites.servei_cat_trans.flows.documentos as documentos_mod
from sites.servei_cat_trans.flows.documentos import (
    _assert_expected_uploads_present,
    _build_slot_upload_plan,
    _find_special_upload_slot,
    _read_input_file_names,
    _sanitize_upload_filename,
    _select_files_by_origin,
    _upload_with_retry,
    run_documentos,
)


def _mk(path: Path) -> Path:
    path.write_bytes(b"ok")
    return path


def test_select_files_by_origin_prefers_xvia_resource_and_acreditacion_path(tmp_path: Path) -> None:
    recurso = _mk(tmp_path / "recurso_xvia.pdf")
    adj = _mk(tmp_path / "adjunto_xvia.pdf")
    aut = _mk(tmp_path / "autorizacion_cliente.pdf")
    dni = _mk(tmp_path / "dni_cliente.pdf")

    files = [recurso, adj, aut, dni]
    payload = {
        "xvia_recurso_path": str(recurso),
        "xvia_attachment_paths": [str(adj)],
        "acreditacion_path": str(aut),
        "required_client_doc_paths": [str(aut), str(dni)],
    }

    recurso_sel, aut_sel, rest = _select_files_by_origin(files, payload)

    assert recurso_sel == recurso
    assert aut_sel == aut
    assert rest == [adj, dni]


def test_select_files_by_origin_fallbacks_to_required_client_docs(tmp_path: Path) -> None:
    recurso = _mk(tmp_path / "recurso_xvia.pdf")
    aut = _mk(tmp_path / "aut_cliente.pdf")
    files = [recurso, aut]
    payload = {
        "xvia_recurso_path": str(recurso),
        "required_client_doc_paths": [str(aut)],
    }

    recurso_sel, aut_sel, rest = _select_files_by_origin(files, payload)

    assert recurso_sel == recurso
    assert aut_sel == aut
    assert rest == []


def test_sanitize_upload_filename_replaces_invalid_characters() -> None:
    raw = "AUTORIZACIÓN?*<>:\"/\\|%#@!.pdf"
    clean = _sanitize_upload_filename(raw)
    assert clean.endswith(".pdf")
    assert "?" not in clean
    assert "*" not in clean
    assert "/" not in clean


def test_slot_plan_puts_authorization_in_last_slot_even_with_gaps(tmp_path: Path) -> None:
    recurso = _mk(tmp_path / "recurso.pdf")
    extra = _mk(tmp_path / "extra.pdf")
    auth = _mk(tmp_path / "auth.pdf")
    slots = ["slot1", "slot2", "slot3", "slot4", "slot5"]

    plan = _build_slot_upload_plan(
        doc_slots=slots,
        recurso=recurso,
        middle_files=[extra],
        autorizacion=auth,
    )

    assert plan[0] == (recurso, "slot1")
    assert plan[1] == (extra, "slot2")
    assert plan[2] == (auth, "slot5")


@pytest.mark.asyncio
async def test_read_input_file_names_returns_normalized_names() -> None:
    class _Scope:
        async def evaluate(self, _script, input_id):
            assert input_id == "slot1"
            return {"exists": True, "count": 1, "names": ["Mi Archivo.PDF"]}

    names = await _read_input_file_names(_Scope(), "slot1")
    assert names == ["mi archivo.pdf"]


@pytest.mark.asyncio
async def test_assert_expected_uploads_present_raises_when_slot_missing() -> None:
    class _Scope:
        async def evaluate(self, _script, input_id):
            if input_id == "slot_ok":
                return {"exists": True, "count": 1, "names": ["recurso.pdf"]}
            return {"exists": True, "count": 0, "names": []}

    with pytest.raises(RuntimeError, match="verificacion final de adjuntos fallida"):
        await _assert_expected_uploads_present(
            _Scope(),
            expected_by_slot={
                "slot_ok": "recurso.pdf",
                "slot_missing": "autorizacion.pdf",
            },
        )


@pytest.mark.asyncio
async def test_find_special_upload_slot_detects_acreditacion_by_container_text() -> None:
    class _Scope:
        async def evaluate(self, _script, payload):
            assert payload["inputIds"] == ["slot0", "slot1", "slot2"]
            assert "acredit" in payload["tokens"]
            return "slot2"

    found = await _find_special_upload_slot(
        _Scope(),
        input_ids=["slot0", "slot1", "slot2"],
        label_tokens=["acredit", "represent"],
    )

    assert found == "slot2"


@pytest.mark.asyncio
async def test_upload_with_retry_retries_until_success(monkeypatch, tmp_path: Path) -> None:
    file_path = _mk(tmp_path / "autorizacion.pdf")
    calls: list[int] = []

    async def _fake_upload(_scope, input_id, target_path):
        calls.append(len(calls) + 1)
        assert input_id == "slot-special"
        assert target_path == file_path
        return len(calls) >= 2

    monkeypatch.setattr(documentos_mod, "_upload_to_input", _fake_upload)

    class _Scope:
        async def wait_for_timeout(self, _ms):
            return None

    ok = await _upload_with_retry(_Scope(), "slot-special", file_path, attempts=3)

    assert ok is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_documentos_raises_when_no_files_to_upload() -> None:
    page = object()
    config = SimpleNamespace(upload_inputs_timeout_ms=1000)
    datos = SimpleNamespace(archivos_para_subir=[], payload={}, idRecurso=123, tipo_persona="fisica")

    with pytest.raises(RuntimeError, match="no hay archivos para subir"):
        await run_documentos(page, config, datos)


@pytest.mark.asyncio
async def test_run_documentos_raises_when_file_inputs_not_detected(monkeypatch, tmp_path: Path) -> None:
    recurso = _mk(tmp_path / "recurso.pdf")
    aut = _mk(tmp_path / "autorizacion.pdf")
    fake_scope = object()

    async def _fake_dismiss(_scope) -> None:
        return None

    async def _fake_wait_form_scope(_page, timeout_ms):
        return fake_scope

    async def _fake_wait_file_input_ids(_scope, timeout_ms):
        return ["only-one-input"]

    monkeypatch.setattr(documentos_mod, "dismiss_cookie_banner_if_present", _fake_dismiss)
    monkeypatch.setattr(documentos_mod, "wait_form_scope", _fake_wait_form_scope)
    monkeypatch.setattr(documentos_mod, "_wait_file_input_ids", _fake_wait_file_input_ids)

    page = object()
    config = SimpleNamespace(upload_inputs_timeout_ms=1000)
    datos = SimpleNamespace(
        archivos_para_subir=[recurso, aut],
        payload={},
        idRecurso=456,
        tipo_persona="fisica",
    )

    with pytest.raises(RuntimeError, match="no se detectaron inputs file suficientes"):
        await run_documentos(page, config, datos)


@pytest.mark.asyncio
async def test_run_documentos_raises_when_more_attachments_than_slots(monkeypatch, tmp_path: Path) -> None:
    recurso = _mk(tmp_path / "recurso.pdf")
    aut = _mk(tmp_path / "autorizacion.pdf")
    extra1 = _mk(tmp_path / "extra1.pdf")
    extra2 = _mk(tmp_path / "extra2.pdf")
    extra3 = _mk(tmp_path / "extra3.pdf")
    extra4 = _mk(tmp_path / "extra4.pdf")

    async def _fake_dismiss(_scope) -> None:
        return None

    monkeypatch.setattr(documentos_mod, "dismiss_cookie_banner_if_present", _fake_dismiss)

    page = object()
    config = SimpleNamespace(upload_inputs_timeout_ms=1000)
    datos = SimpleNamespace(
        archivos_para_subir=[recurso, extra1, extra2, extra3, extra4, aut],
        payload={
            "xvia_recurso_path": str(recurso),
            "acreditacion_path": str(aut),
        },
        idRecurso=789,
        tipo_persona="fisica",
    )

    with pytest.raises(RuntimeError, match="hay mas adjuntos que slots disponibles"):
        await run_documentos(page, config, datos)


@pytest.mark.asyncio
async def test_run_documentos_allows_optional_escritura_overflow(monkeypatch, tmp_path: Path) -> None:
    recurso = _mk(tmp_path / "recurso.pdf")
    aut = _mk(tmp_path / "autorizacion.pdf")
    extra1 = _mk(tmp_path / "extra1.pdf")
    extra2 = _mk(tmp_path / "extra2.pdf")
    extra3 = _mk(tmp_path / "extra3.pdf")
    escritura = _mk(tmp_path / "ESCRITURA B10694883.pdf")

    async def _fake_dismiss(_scope) -> None:
        return None

    async def _fake_wait_form_scope(_page, timeout_ms):
        return _Scope()

    async def _fake_wait_file_input_ids(_scope, timeout_ms):
        return ["uploader", "slot1", "slot2", "slot3", "slot4", "slot5", "slot_special"]

    async def _fake_upload_with_retry(_scope, _input_id, _file_path, *, attempts=3):
        return True

    async def _fake_assert_expected(_scope, *, expected_by_slot):
        return None

    class _Scope:
        async def evaluate(self, _script, payload):
            if isinstance(payload, dict) and "inputIds" in payload:
                return "slot_special"
            return {"exists": True, "count": 1, "names": ["ok.pdf"]}

    monkeypatch.setattr(documentos_mod, "dismiss_cookie_banner_if_present", _fake_dismiss)
    monkeypatch.setattr(documentos_mod, "wait_form_scope", _fake_wait_form_scope)
    monkeypatch.setattr(documentos_mod, "_wait_file_input_ids", _fake_wait_file_input_ids)
    monkeypatch.setattr(documentos_mod, "_upload_with_retry", _fake_upload_with_retry)
    monkeypatch.setattr(documentos_mod, "_assert_expected_uploads_present", _fake_assert_expected)

    page = object()
    config = SimpleNamespace(upload_inputs_timeout_ms=1000)
    datos = SimpleNamespace(
        archivos_para_subir=[recurso, extra1, extra2, extra3, escritura, aut],
        payload={
            "xvia_recurso_path": str(recurso),
            "acreditacion_path": str(aut),
        },
        idRecurso=790,
        tipo_persona="fisica",
    )

    result = await run_documentos(page, config, datos)

    assert result is page
