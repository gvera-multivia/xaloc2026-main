from sites.redsara.flows.formulario import _classify_sign_result_from_text


def test_sign_result_success_when_step4_gone() -> None:
    result = _classify_sign_result_from_text(
        step4_present=False,
        detail_loaded=False,
        modal_visible=False,
        modal_text="",
    )
    assert result == "success"


def test_sign_result_unmarshalling_timeout() -> None:
    result = _classify_sign_result_from_text(
        step4_present=True,
        detail_loaded=False,
        modal_visible=True,
        modal_text="Unmarshalling Error: Read timed out",
    )
    assert result == "unmarshalling_timeout"


def test_sign_result_autofirma_not_found() -> None:
    result = _classify_sign_result_from_text(
        step4_present=True,
        detail_loaded=False,
        modal_visible=True,
        modal_text="ApplicationNotFoundException",
    )
    assert result == "autofirma_not_found"


def test_sign_result_other_error() -> None:
    result = _classify_sign_result_from_text(
        step4_present=True,
        detail_loaded=False,
        modal_visible=True,
        modal_text="Error inesperado del servidor",
    )
    assert result == "other_error"


def test_sign_result_success_when_modal_says_signed_ok() -> None:
    result = _classify_sign_result_from_text(
        step4_present=True,
        detail_loaded=False,
        modal_visible=True,
        modal_text="El registro se ha firmado correctamente",
    )
    assert result == "success"
