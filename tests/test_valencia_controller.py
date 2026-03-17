from __future__ import annotations

from sites.valencia.controller import ValenciaController


def test_valencia_controller_disables_autofirma_auto_open_for_inprocess_signing() -> None:
    controller = ValenciaController()

    cfg = controller.create_config(headless=True)

    assert cfg.autofirma_auto_open is False
