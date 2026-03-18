from __future__ import annotations

from sites.atc.flows.formulario import (
    _is_csv_result_ready,
    _is_identification_dom_ready,
    _is_post_validate_ui_ready,
)


def test_atc_identification_dom_not_ready_while_loading() -> None:
    assert _is_identification_dom_ready(
        {
            "radioCount": 0,
            "hasThirdNif": False,
            "hasThirdName": False,
            "loading": True,
        }
    ) is False


def test_atc_identification_dom_ready_when_radios_exist_and_loading_finished() -> None:
    assert _is_identification_dom_ready(
        {
            "radioCount": 2,
            "hasThirdNif": False,
            "hasThirdName": False,
            "loading": False,
        }
    ) is True


def test_atc_identification_dom_ready_when_fields_already_present() -> None:
    assert _is_identification_dom_ready(
        {
            "radioCount": 0,
            "hasThirdNif": True,
            "hasThirdName": True,
            "loading": False,
        }
    ) is True


def test_atc_post_validate_ui_not_ready_while_loading() -> None:
    assert _is_post_validate_ui_ready(
        {
            "loading": True,
            "hasCheckbox": False,
        }
    ) is False


def test_atc_post_validate_ui_ready_when_checkbox_exists() -> None:
    assert _is_post_validate_ui_ready(
        {
            "loading": False,
            "hasCheckbox": True,
        }
    ) is True


def test_atc_csv_result_not_ready_while_loading() -> None:
    assert _is_csv_result_ready(
        {
            "loading": True,
            "hasCsvRejectedModal": False,
            "continueEnabled": False,
            "singleSelectableCheckbox": False,
        }
    ) is False


def test_atc_csv_result_ready_when_continue_enabled() -> None:
    assert _is_csv_result_ready(
        {
            "loading": False,
            "hasCsvRejectedModal": False,
            "continueEnabled": True,
            "singleSelectableCheckbox": False,
        }
    ) is True


def test_atc_csv_result_ready_when_single_checkbox_needs_selection() -> None:
    assert _is_csv_result_ready(
        {
            "loading": False,
            "hasCsvRejectedModal": False,
            "continueEnabled": False,
            "singleSelectableCheckbox": True,
        }
    ) is True
