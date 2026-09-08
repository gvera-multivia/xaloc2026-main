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


def test_madrid_final_submit_uses_controlled_helper():
    source = _function_source("ejecutar_formulario_madrid")

    assert "page = await _continuar_formulario_controlado(page, config)" in source
    assert "page.click(config.continuar_formulario_selector)" not in source


def test_madrid_final_submit_retry_is_single_and_recoverable():
    source = _function_source("_continuar_formulario_controlado")

    assert "for intento in (1, 2):" in source
    assert "_recuperar_formulario_tras_access_denied" in source
    assert "except MadridFormularioAccessDenied" in source


def test_madrid_select_does_not_reselect_current_value():
    source = _function_source("_seleccionar_opcion")

    guard = "ya seleccionado, no se fuerza change"
    assert guard in source
    assert source.index(guard) < source.index("select_option(label=valor")


def test_madrid_final_submit_stabilization_does_not_force_blur():
    source = _function_source("_esperar_formulario_estable_antes_submit")

    assert ".blur(" not in source
