from __future__ import annotations

import asyncio

from sites.adapters.xaloc_girona import XalocAdapter


def test_xaloc_payload_uses_cliente_razon_social_when_empresa_empty() -> None:
    adapter = XalocAdapter()
    row = {
        "idRecurso": 102116,
        "idExp": 50123,
        "Expedient": "2026/00001",
        "numclient": 8781,
        "SujetoRecurso": "EDIFRED",
        "FaseProcedimiento": "Alegaciones",
        "cliente_tipo": 2,
        "cif": "B17901505",
        "nifempresa": "B17901505",
        "Empresa": "",
        "Nombrefiscal": "",
        "cliente_razon_social": "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL",
        "adjuntos": [],
    }

    payloads = asyncio.run(adapter.build_payloads([row]))
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["empresa"] == "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL"
    assert payload["cliente_razon_social"] == "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL"
    assert payload["mandatario"]["tipo_persona"] == "JURIDICA"
    assert payload["mandatario"]["razon_social"] == "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL"
