from __future__ import annotations

from types import SimpleNamespace

from sites.adapters.redsara import RedsaraAdapter


def test_resolve_rule_and_destination_code_barcelona() -> None:
    adapter = RedsaraAdapter()
    rule = adapter.resolve_rule_by_organisme("AJUNTAMENT DE BARCELONA - IMH")
    assert rule is not None
    assert rule["destination_code"] == "LA0006797"


def test_resolve_rule_and_destination_code_ctda_leon() -> None:
    adapter = RedsaraAdapter()
    rule = adapter.resolve_rule_by_organisme("CENTRO DE TRATAMIENTO DE DENUNCIAS AUTOMATIZADAS DE LEON")
    assert rule is not None
    assert rule["destination_code"] == "E04753204"
    assert adapter.validate_expediente_for_organisme(
        "CENTRO DE TRATAMIENTO DE DENUNCIAS AUTOMATIZADAS DE LEON",
        "29-048-030.715-7",
    )


def test_resolve_rule_and_destination_code_atib_variants() -> None:
    adapter = RedsaraAdapter()
    variants = [
        "AGENCIA TRIBUTARIA ILLES BALEARS -ATIB",
        "AGENCIA TRIBUTARIA ILLES BALEARS - ATIB",
        "AGENCIA TRIBUTARIA ILLES BALEARS-ATIB",
        "AGENCIA TRIBUTARIA ILLES BALEARS (ATIB)",
        "AGENCIA TRIBUTARIA ILLES BALEARS ATIB",
        "AGENCIA TRIBUTARIA ISLAS BALEARES (ATIB)",
    ]

    for organisme in variants:
        rule = adapter.resolve_rule_by_organisme(organisme)
        assert rule is not None, organisme
        assert rule["destination_code"] == "A04013587"
        assert adapter.validate_expediente_for_organisme(organisme, "25/088283-3")


def test_validate_expediente_by_official_patterns() -> None:
    adapter = RedsaraAdapter()
    assert adapter.validate_expediente_for_organisme("AJUNTAMENT DE BARCELONA", "2026SACR0141800")
    assert adapter.validate_expediente_for_organisme("AJUNTAMENT DE BARCELONA", "26F013176")
    assert adapter.validate_expediente_for_organisme("AJUNTAMENT DE BARCELONA", "2025-1017739")
    assert adapter.validate_expediente_for_organisme("AJUNTAMENT DE BARCELONA", "MU202640555138641")
    assert adapter.validate_expediente_for_organisme(
        "SECTOR DE SEGURIDAD Y MOVILIDAD DEL AYUNTAMIENTO DE BARCELONA", "U8099161"
    )
    assert adapter.validate_expediente_for_organisme(
        "CENTRO DE TRATAMIENTO DE DENUNCIAS AUTOMATIZADAS DE LEON", "50-945-965.632-0"
    )
    assert adapter.validate_expediente_for_organisme(
        "CENTRO DE TRATAMIENTO DE DENUNCIAS AUTOMATIZADAS DE LEON", "28-049-987.915.5"
    )
    assert adapter.validate_expediente_for_organisme("AYUNTAMIENTO DE PALMA DE MALLORCA", "MU 90046663")
    assert adapter.validate_expediente_for_organisme(
        "AGENCIA TRIBUTARIA MUNICIPAL DE ISLAS BALEARES", "25/088283-3"
    )
    assert adapter.validate_expediente_for_organisme(
        "AGENCIA TRIBUTARIA MUNICIPAL DE ISLAS BALEARES", "23/044727-31"
    )
    assert adapter.validate_expediente_for_organisme(
        "AGENCIA TRIBUTARIA MUNICIPAL DE ISLAS BALEARES", "58997165"
    )
    assert adapter.validate_expediente_for_organisme("AGENCIA TRIBUTARIA ILLES BALEARS -ATIB", "23-016775")
    assert adapter.validate_expediente_for_organisme("AJUNTAMENT MIGJORN GRAN", "2025013916")
    assert adapter.validate_expediente_for_organisme("AYUNTAMIENTO DE MOSTOLES", "888249540")
    assert adapter.validate_expediente_for_organisme("AYUNTAMIENTO DE MOSTOLES", "550/2026/MUL")
    assert adapter.validate_expediente_for_organisme("JEFATURA PROVINCIAL DE TRÁFICO DE BARCELONA", "083313177")
    assert not adapter.validate_expediente_for_organisme("AYUNTAMIENTO DE MOSTOLES", "2026SACR0141800")
    assert not adapter.validate_expediente_for_organisme("AYUNTAMIENTO DE MOSTOLES", "550/2026/MULA")
    assert not adapter.validate_expediente_for_organisme("AJUNTAMENT DE BARCELONA", "MU20264055513864")


def test_validate_expediente_sector_barcelona_sarp_8_digits() -> None:
    adapter = RedsaraAdapter()
    assert adapter.validate_expediente_for_organisme(
        "SECTOR DE SEGURIDAD Y MOVILIDAD DEL AYUNTAMIENTO DE BARCELONA",
        "2026SARP90179573",
    )


def test_fetch_candidates_discards_invalid_by_pattern() -> None:
    adapter = RedsaraAdapter()

    resources = [
        SimpleNamespace(
            metadata={
                "idRecurso": 1,
                "Organisme": "AYUNTAMIENTO DE MOSTOLES",
                "Expedient": "888249540",
                "Estado": 0,
                "UsuarioAsignado": "",
            }
        ),
        SimpleNamespace(
            metadata={
                "idRecurso": 2,
                "Organisme": "AYUNTAMIENTO DE MOSTOLES",
                "Expedient": "INVALIDO",
                "Estado": 0,
                "UsuarioAsignado": "",
            }
        ),
    ]

    class _Repo:
        def get_pending_resources(self, *, site_id: str, config: dict, limit: int):
            return resources

    discards: list[dict] = []
    out = adapter.fetch_candidates(
        config={},
        conn_str="",
        authenticated_user=None,
        limit=10,
        on_discard=discards.append,
        resource_repo=_Repo(),
    )
    assert len(out) == 1
    assert out[0]["idRecurso"] == 1
    assert len(discards) == 1
    assert discards[0]["idRecurso"] == 2


def test_subject_exposes_solicit_by_fase(monkeypatch) -> None:
    adapter = RedsaraAdapter()
    monkeypatch.setattr(
        RedsaraAdapter,
        "_load_motivos_config",
        staticmethod(
            lambda: {
                "identificacion": {
                    "asunto": "ASUNTO {expediente}",
                    "expone": "EXPONE {sujeto_recurso}",
                    "solicita": "SOLICITA {expediente}",
                }
            }
        ),
    )
    subject, exposes, solicit = adapter._build_subject_exposes_solicit(
        fase_raw="Identificación del conductor",
        expediente="2026SACR0141800",
        sujeto="JUAN PEREZ",
    )
    assert subject == "ASUNTO 2026SACR0141800"
    assert exposes == "EXPONE JUAN PEREZ"
    assert solicit == "SOLICITA 2026SACR0141800"


def test_document_type_bundle_inference() -> None:
    adapter = RedsaraAdapter()
    bundle = adapter._build_document_type_bundle(
        [
            {"idRecurso": 1, "cliente_nif": "Y2843702L"},
            {"idRecurso": 2, "cliente_nif": "12345678Z"},
            {"idRecurso": 3, "cliente_nif": "B12345678"},
            {"idRecurso": 4, "cliente_nif": "AB1234567"},
        ]
    )
    assert bundle["1"] == "NIE"
    assert bundle["2"] == "NIF"
    assert bundle["3"] == "CIF"
    assert bundle["4"] == "PASAPORTE"
