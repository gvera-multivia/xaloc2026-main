from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.worker_execution import browser_executor
from core.worker_execution.models import ProcessOutcome


@pytest.mark.asyncio
async def test_execute_browser_flow_passes_runner_files_to_terrassa(monkeypatch, tmp_path: Path) -> None:
    runner_file = tmp_path / "runner_recurso.pdf"
    runner_file.write_bytes(b"%PDF-1.7\n")
    captured: dict[str, object] = {}

    class _Controller:
        def create_config(self, *, headless: bool):
            return SimpleNamespace(navegador=SimpleNamespace(perfil_path=None))

        def map_data(self, payload: dict):
            return {
                "expediente": payload["expediente"],
                "document_number": payload["document_number"],
                "nombre": payload["nombre"],
                "fecha_infraccion": payload["fecha_infraccion"],
                "matricula": payload["matricula"],
                "alegaciones": payload["alegaciones"],
                "observaciones": payload["observaciones"],
                "archivos": ["stale-from-main-container.pdf"],
            }

        def create_target(self, **kwargs):
            captured["archivos"] = kwargs.get("archivos")
            return SimpleNamespace()

    class _Automation:
        def __init__(self, config):
            self.config = config
            self.last_flow_metadata = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def ejecutar_flujo_completo(self, datos):
            return "ok.png"

    monkeypatch.setattr(browser_executor, "get_site_controller", lambda _site_id: _Controller())
    monkeypatch.setattr(browser_executor, "get_site", lambda _site_id: _Automation)

    outcome = await browser_executor.execute_browser_flow(
        site_id="terrassa",
        protocol="denuncia",
        payload={
            "expediente": "RC60323951",
            "document_number": "12345678Z",
            "nombre": "MERCEDES",
            "fecha_infraccion": "01/01/2026",
            "matricula": "1234ABC",
            "alegaciones": "Alegaciones",
            "observaciones": "Observaciones",
        },
        archivos_para_subir=[runner_file],
    )

    assert isinstance(outcome, ProcessOutcome)
    assert outcome.success is True
    assert captured["archivos"] == [runner_file]
