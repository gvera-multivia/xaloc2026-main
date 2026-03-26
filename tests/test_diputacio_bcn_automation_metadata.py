from __future__ import annotations

from pathlib import Path

import pytest

from sites.diputacio_bcn import automation as dipu_automation
from sites.diputacio_bcn.automation import DiputacioBcnAutomation
from sites.diputacio_bcn.config import DiputacioBcnConfig
from sites.diputacio_bcn.data_models import DiputacioBcnTarget


class _FakePage:
    async def screenshot(self, path, full_page=True):
        Path(path).write_bytes(b"fake")


@pytest.mark.asyncio
async def test_diputacio_automation_exports_justificante_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def _noop_step(page, config, datos):
        return page

    async def _presentmul_step(page, config, datos):
        datos.payload["diputacio_justificante_descargado"] = True
        datos.payload["diputacio_justificante_path"] = "/mnt/clientes/X/JUSTIFICANTE - TEST.pdf"
        datos.payload["diputacio_justificante_artifact_path"] = "tmp/diputacio_bcn/justificantes/1/recibo.pdf"
        return page

    monkeypatch.setattr(dipu_automation, "run_login", _noop_step)
    monkeypatch.setattr(dipu_automation, "run_formulario", _noop_step)
    monkeypatch.setattr(dipu_automation, "run_documentos", _noop_step)
    monkeypatch.setattr(dipu_automation, "run_confirmacion", _noop_step)
    monkeypatch.setattr(dipu_automation, "run_presentmul_pas2", _presentmul_step)

    cfg = DiputacioBcnConfig()
    cfg.dir_screenshots = tmp_path / "screenshots"
    cfg.dir_logs = tmp_path / "logs"
    cfg.navegador.perfil_path = tmp_path / "profiles"
    cfg.ensure_directories()

    bot = DiputacioBcnAutomation(cfg)
    bot.page = _FakePage()
    datos = DiputacioBcnTarget(idRecurso=1, expediente="EXP-1", payload={"idRecurso": 1})

    shot = await bot.ejecutar_flujo_completo(datos)

    assert Path(shot).exists()
    assert bot.last_flow_metadata["diputacio_justificante_descargado"] is True
    assert bot.last_flow_metadata["diputacio_justificante_path"] == "/mnt/clientes/X/JUSTIFICANTE - TEST.pdf"
    assert (
        bot.last_flow_metadata["diputacio_justificante_artifact_path"]
        == "tmp/diputacio_bcn/justificantes/1/recibo.pdf"
    )
