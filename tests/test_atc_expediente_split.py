from __future__ import annotations

import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sites.adapters.atc import AtcAdapter
from sites.atc.controller import AtcController


def test_atc_adapter_uses_first_expediente_chunk_when_space_present() -> None:
    adapter = AtcAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 103444,
                    "idExp": 9001,
                    "numclient": 123,
                    "Expedient": "20250001462212 BLOQUE_EXTRA",
                    "FaseProcedimiento": "Recurso",
                    "Procedim": "RECURSO DE REPOSICION",
                    "ExpedientePublicacion": "CSV123",
                    "Nombrefiscal": "CLIENTE TEST",
                }
            ]
        )
    )
    assert len(payloads) == 1
    assert payloads[0]["expediente"] == "20250001462212"


def test_atc_controller_map_data_uses_first_expediente_chunk_when_space_present() -> None:
    controller = AtcController()
    mapped = controller.map_data(
        {
            "idRecurso": 103444,
            "Expedient": "20250001462212 SEGUNDA_PARTE",
            "csv_acto": "CSV123",
            "procedim": "RECURSO DE REPOSICION",
            "Nombrefiscal": "CLIENTE TEST",
            "nifempresa": "B12345678",
        }
    )
    assert mapped["expediente"] == "20250001462212"
