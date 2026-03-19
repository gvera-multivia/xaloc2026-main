from __future__ import annotations

import pytest

from sites.terrassa.flows.documentos import _analyze_upload_state, _resolve_upload_index, _submission_has_started


def test_analyze_upload_state_requires_name_recorded_outside_active_block() -> None:
    analysis = _analyze_upload_state(
        before_state={"outside_mentions": 0},
        current_state={
            "outside_mentions": 0,
            "visible_indices": [1, 2],
            "block_present": True,
            "form_present": True,
            "file_present": True,
            "file_count": 1,
            "desc_value": "Recurso",
            "selected_type": "Al-legacio",
        },
        upload_index=1,
        used_indices={1},
        expected_desc="Recurso",
        expected_type="Al-legacio",
    )

    assert analysis["has_fresh_block"] is True
    assert analysis["has_name_outside_block"] is False
    assert analysis["confirmed"] is False


def test_analyze_upload_state_confirms_when_new_block_is_visible_and_name_registered() -> None:
    analysis = _analyze_upload_state(
        before_state={"outside_mentions": 0},
        current_state={
            "outside_mentions": 1,
            "visible_indices": [1, 2],
            "block_present": True,
            "form_present": True,
            "file_present": True,
            "file_count": 1,
            "desc_value": "Recurso",
            "selected_type": "Al-legacio",
        },
        upload_index=1,
        used_indices={1},
        expected_desc="Recurso",
        expected_type="Al-legacio",
    )

    assert analysis["has_fresh_block"] is True
    assert analysis["has_name_outside_block"] is True
    assert analysis["confirmed"] is True
    assert analysis["recycled_current_block"] is False


def test_analyze_upload_state_accepts_recycled_block_only_after_real_confirmation() -> None:
    analysis = _analyze_upload_state(
        before_state={"outside_mentions": 0},
        current_state={
            "outside_mentions": 1,
            "visible_indices": [1],
            "block_present": True,
            "form_present": True,
            "file_present": True,
            "file_count": 0,
            "desc_value": "",
            "selected_type": "",
        },
        upload_index=1,
        used_indices={1},
        expected_desc="Autorizacion",
        expected_type="Autoritzacio",
    )

    assert analysis["has_fresh_block"] is False
    assert analysis["recycled_current_block"] is True
    assert analysis["confirmed"] is True


def test_analyze_upload_state_accepts_same_block_when_name_is_already_registered_outside() -> None:
    analysis = _analyze_upload_state(
        before_state={"outside_mentions": 0},
        current_state={
            "outside_mentions": 1,
            "visible_indices": [1],
            "block_present": True,
            "form_present": True,
            "file_present": True,
            "file_count": 1,
            "desc_value": "AUTORIZACION 52595424J SF",
            "selected_type": "Autorització",
        },
        upload_index=1,
        used_indices={1},
        expected_desc="AUTORIZACION 52595424J SF",
        expected_type="Autorització",
    )

    assert analysis["same_block_registered"] is True
    assert analysis["confirmed"] is True


def test_analyze_upload_state_accepts_same_block_when_type_label_differs_but_name_is_registered() -> None:
    analysis = _analyze_upload_state(
        before_state={"outside_mentions": 0},
        current_state={
            "outside_mentions": 1,
            "visible_indices": [1],
            "block_present": True,
            "form_present": True,
            "file_present": True,
            "file_count": 1,
            "desc_value": "AUTORIZACION B55475057 SF",
            "selected_type": "Autorització",
        },
        upload_index=1,
        used_indices={1},
        expected_desc="AUTORIZACION B55475057 SF",
        expected_type="Autoritza",
    )

    assert analysis["has_name_outside_block"] is True
    assert analysis["same_block_registered"] is True
    assert analysis["confirmed"] is True


def test_submission_has_started_detects_no_activity() -> None:
    started = _submission_has_started(
        before_state={
            "iframe_src": "",
            "outside_mentions": 0,
            "file_count": 1,
            "visible_indices": [0],
            "block_present": True,
            "form_present": True,
            "file_present": True,
        },
        current_state={
            "iframe_src": "",
            "outside_mentions": 0,
            "file_count": 1,
            "visible_indices": [0],
            "block_present": True,
            "form_present": True,
            "file_present": True,
        },
    )

    assert started is False


def test_submission_has_started_detects_iframe_or_dom_progress() -> None:
    started = _submission_has_started(
        before_state={
            "iframe_src": "",
            "outside_mentions": 0,
            "file_count": 1,
            "visible_indices": [0],
            "block_present": True,
            "form_present": True,
            "file_present": True,
        },
        current_state={
            "iframe_src": "/tramits/upload-ok",
            "outside_mentions": 0,
            "file_count": 1,
            "visible_indices": [0],
            "block_present": True,
            "form_present": True,
            "file_present": True,
        },
    )

    assert started is True


class _FakePage:
    async def wait_for_timeout(self, _ms: int) -> None:
        return None


@pytest.mark.asyncio
async def test_resolve_upload_index_raises_if_only_used_blocks_remain(monkeypatch) -> None:
    async def _only_used_blocks(_page):
        return []

    monkeypatch.setattr("sites.terrassa.flows.documentos._visible_upload_indices", _only_used_blocks)

    with pytest.raises(RuntimeError, match="no hay bloques de subida libres"):
        await _resolve_upload_index(
            _FakePage(),
            preferred_index=1,
            used_indices={1},
            timeout_ms=600,
        )


@pytest.mark.asyncio
async def test_resolve_upload_index_reuses_visible_block_after_timeout(monkeypatch) -> None:
    async def _only_used_blocks(_page):
        return [1]

    monkeypatch.setattr("sites.terrassa.flows.documentos._visible_upload_indices", _only_used_blocks)

    upload_index = await _resolve_upload_index(
        _FakePage(),
        preferred_index=2,
        used_indices={0, 1},
        timeout_ms=600,
    )

    assert upload_index == 1


@pytest.mark.asyncio
async def test_resolve_upload_index_prefers_requested_visible_block_when_reusing(monkeypatch) -> None:
    async def _preferred_visible(_page):
        return [1, 2]

    monkeypatch.setattr("sites.terrassa.flows.documentos._visible_upload_indices", _preferred_visible)

    upload_index = await _resolve_upload_index(
        _FakePage(),
        preferred_index=2,
        used_indices={1, 2},
        timeout_ms=600,
    )

    assert upload_index == 2
