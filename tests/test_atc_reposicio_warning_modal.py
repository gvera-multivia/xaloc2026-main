from __future__ import annotations

import pytest

from sites.atc.flows import documentos


class _FakePage:
    async def wait_for_timeout(self, _ms: int) -> None:
        return None


def test_atc_reposicio_warning_button_text_matches_expected_variants() -> None:
    assert documentos._is_reposicio_warning_button_text("Sí, vull continuar amb aquest motiu")
    assert documentos._is_reposicio_warning_button_text("Si vull continuar amb aquest motiu")
    assert not documentos._is_reposicio_warning_button_text("Cancelar")


@pytest.mark.asyncio
async def test_atc_confirm_reposicio_warning_modal_returns_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter(
        [
            {"visibleDialogCount": 1, "visibleDialogs": ["advertencia"], "buttons": ["si vull continuar"], "loading": False},
            {"visibleDialogCount": 0, "visibleDialogs": [], "buttons": [], "loading": False},
        ]
    )

    async def _fake_collect(_page):
        return next(states)

    async def _fake_click(_page):
        return True

    monkeypatch.setattr(documentos, "_collect_reposicio_warning_state", _fake_collect)
    monkeypatch.setattr(documentos, "_click_reposicio_warning_button", _fake_click)

    await documentos._confirm_reposicio_warning_modal(_FakePage())


@pytest.mark.asyncio
async def test_atc_confirm_reposicio_warning_modal_allows_absence_of_modal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_collect(_page):
        return {"visibleDialogCount": 0, "visibleDialogs": [], "buttons": [], "loading": False}

    async def _fake_click(_page):
        raise AssertionError("no click expected")

    monkeypatch.setattr(documentos, "_collect_reposicio_warning_state", _fake_collect)
    monkeypatch.setattr(documentos, "_click_reposicio_warning_button", _fake_click)

    await documentos._confirm_reposicio_warning_modal(_FakePage())
