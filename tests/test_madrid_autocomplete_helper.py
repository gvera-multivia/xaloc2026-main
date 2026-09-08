from pathlib import Path


FORMULARIO = Path("sites/madrid/flows/formulario.py")


def _source() -> str:
    return FORMULARIO.read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    source = _source()
    marker = f"async def {name}("
    start = source.index(marker)
    next_def = source.find("\nasync def ", start + len(marker))
    next_sync_def = source.find("\ndef ", start + len(marker))
    candidates = [idx for idx in [next_def, next_sync_def] if idx != -1]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def test_madrid_autocomplete_effective_helper_is_click_only():
    source = _function_source("_seleccionar_sugerencia_jquery_ui_click_only")

    assert "keyboard.press" not in source
    assert "ArrowDown" not in source
    assert "Enter" not in source
    assert "_click_sugerencia_autocomplete" in source


def test_madrid_autocomplete_wrapper_delegates_before_old_body():
    source = _function_source("_seleccionar_sugerencia_jquery_ui")
    first_return = "return await _seleccionar_sugerencia_jquery_ui_click_only"

    assert first_return in source
    assert source.index(first_return) < source.index("ul.ui-autocomplete")


def test_madrid_autocomplete_tab_only_after_valid_selection():
    source = _function_source("_rellenar_input_con_autocomplete")

    assert "if seleccionado:" in source
    assert "if seleccionado or not sugerencia_objetivo" not in source
