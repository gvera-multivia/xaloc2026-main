from __future__ import annotations

from pathlib import Path

import core.authorization_fetcher as fetcher


def test_find_authorization_in_tmp_empresa_picks_latest_embedded_timestamp(
    monkeypatch, tmp_path: Path
) -> None:
    sedes = tmp_path / "SEDES"
    sedes.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fetcher, "TMP_PDF_SEDES_PATH", sedes)

    numclient = 39699
    names = [
        f"Autoriza_Empresa_20230826144326_{numclient}.pdf",
        f"Autoriza_Empresa_20241125141357_{numclient}.pdf",
        f"Autoriza_Empresa_20240327125442_{numclient}.pdf",
    ]
    for name in names:
        (sedes / name).write_text("x", encoding="utf-8")

    selected = fetcher.find_authorization_in_tmp(numclient=numclient, client_type="empresa")

    assert selected is not None
    assert selected.name == f"Autoriza_Empresa_20241125141357_{numclient}.pdf"


def test_find_authorization_in_tmp_empresa_keeps_solo_pattern(
    monkeypatch, tmp_path: Path
) -> None:
    sedes = tmp_path / "SEDES"
    sedes.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fetcher, "TMP_PDF_SEDES_PATH", sedes)

    numclient = 50000
    expected = sedes / f"Autoriza_Empresa_solo_20250102101010_{numclient}.pdf"
    expected.write_text("x", encoding="utf-8")

    selected = fetcher.find_authorization_in_tmp(numclient=numclient, client_type="empresa")

    assert selected == expected
