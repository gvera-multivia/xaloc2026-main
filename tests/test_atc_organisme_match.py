from __future__ import annotations

import os
import sys

sys.path.append(os.getcwd())

from sites.adapters.atc import AtcAdapter


def test_atc_accepts_cataluna_catalunya_and_accented_variants() -> None:
    accepted = [
        "AGENCIA TRIBUTARIA AUTONOMICA DE CATALUÑA",
        "AGENCIA TRIBUTARIA AUTONOMICA DE CATALUNYA",
        "AGÈNCIA TRIBUTARIA DE CATALUÑA",
        "AGENCIA TRIBUTARIA DE CATALUNA",
        "Subdirección / AGÈNCIA TRIBUTARIA DE CATALUNYA / Oficina",
    ]

    for organism in accepted:
        assert AtcAdapter._is_target_organisme(organism), organism


def test_atc_rejects_other_tax_agencies() -> None:
    rejected = [
        "AGENCIA TRIBUTARIA MUNICIPAL DE ISLAS BALEARES",
        "AGENCIA ESTATAL DE ADMINISTRACION TRIBUTARIA",
        "TRIBUTOS DEL AYUNTAMIENTO DE MADRID",
    ]

    for organism in rejected:
        assert not AtcAdapter._is_target_organisme(organism), organism


def test_atc_merge_query_organisme_adds_missing_catalunya_variants() -> None:
    merged = AtcAdapter._merge_query_organisme("%AGENCIA TRIBUTARIA AUTONOMICA DE CATALUÑA%")

    assert "%AGENCIA TRIBUTARIA AUTONOMICA DE CATALUÑA%" in merged
    assert "%AGENCIA TRIBUTARIA DE CATALUÑA%" in merged
    assert "%AGÈNCIA TRIBUTARIA DE CATALUÑA%" in merged
