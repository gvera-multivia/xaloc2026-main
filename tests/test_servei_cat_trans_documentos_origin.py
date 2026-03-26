from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.append(os.getcwd())

from sites.servei_cat_trans.flows.documentos import (
    _build_slot_upload_plan,
    _sanitize_upload_filename,
    _select_files_by_origin,
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
