from __future__ import annotations

import asyncio

import sites.adapters.redsara as redsara_mod
from sites.adapters.redsara import RedsaraAdapter


async def _fake_docs_builder(*args, **kwargs):
    return []


def test_redsara_payload_uses_nombrefiscal_when_cliente_razon_social_empty(monkeypatch) -> None:
    adapter = RedsaraAdapter()
    monkeypatch.setattr(redsara_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(redsara_mod, "build_sqlserver_connection_string", lambda: "unused")

    row = {
        "idRecurso": 102116,
        "idExp": 4201,
        "Expedient": "888249540",
        "Organisme": "AYUNTAMIENTO DE MOSTOLES",
        "TExp": 2,
        "Estado": 0,
        "numclient": 8781,
        "SujetoRecurso": "EDIFRED",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
        "cliente_tipo": 2,
        "cif": "B17901505",
        "cliente_nif": "",
        "cliente_nif_empresa": "B17901505",
        "cliente_nombre": "",
        "cliente_apellido1": "",
        "cliente_apellido2": "",
        "cliente_razon_social": "",
        "Nombrefiscal": "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL",
        "cliente_domicilio": "CALLE MAYOR",
        "cliente_cp": "28931",
        "cliente_municipio": "MOSTOLES",
        "cliente_provincia": "MADRID",
        "cliente_email": "info@edifred.test",
        "cliente_tel1": "910000001",
        "cliente_tel2": "",
        "cliente_movil": "600000002",
        "adjuntos": [],
    }

    payloads = asyncio.run(adapter.build_payloads([row]))
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["razon_social"] == "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL"
    assert payload["cliente_razon_social"] == "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL"
    assert payload["empresa"] == "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL"
