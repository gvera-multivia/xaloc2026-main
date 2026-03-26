from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.append(os.getcwd())

from sites.servei_cat_trans.flows.documentos import _select_files_by_origin


def _write_file(path: Path, size_bytes: int) -> Path:
    path.write_bytes(b"a" * size_bytes)
    return path


def test_select_by_origin_uses_xvia_recurso_and_client_auth(tmp_path: Path) -> None:
    recurso_xvia = _write_file(tmp_path / "RECURSO EXP - 111.pdf", 100_000)
    xvia_adj = _write_file(tmp_path / "adjunto_xvia.pdf", 50_000)
    autorizacion = _write_file(tmp_path / "autorizacion.pdf", 30_000)

    recurso, autoriz, rest = _select_files_by_origin(
        [recurso_xvia, xvia_adj, autorizacion],
        {
            "xvia_recurso_path": str(recurso_xvia),
            "xvia_attachment_paths": [str(xvia_adj)],
            "required_client_doc_paths": [str(autorizacion)],
        },
    )

    assert recurso == recurso_xvia
    assert autoriz == autorizacion
    assert rest == [xvia_adj]


def test_select_by_origin_fallback_without_metadata(tmp_path: Path) -> None:
    recurso_xvia = _write_file(tmp_path / "RECURSO EXP - 222.pdf", 80_000)
    autorizacion = _write_file(tmp_path / "acreditacion_representacion.pdf", 20_000)

    recurso, autoriz, rest = _select_files_by_origin([recurso_xvia, autorizacion], {})

    assert recurso == recurso_xvia
    assert autoriz == autorizacion
    assert rest == []
