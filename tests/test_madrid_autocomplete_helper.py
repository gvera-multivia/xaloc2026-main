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


def test_madrid_autocomplete_wrapper_delegates_to_click_only():
    source = _function_source("_seleccionar_sugerencia_jquery_ui")
    first_return = "return await _seleccionar_sugerencia_jquery_ui_click_only"

    assert first_return in source
    assert "ul.ui-autocomplete" not in source
    assert "keyboard.press" not in source


def test_madrid_autocomplete_does_not_force_tab_after_selection():
    source = _function_source("_rellenar_input_con_autocomplete")

    assert 'press("Tab")' not in source
    assert "keyboard.press" not in source


def test_madrid_final_submit_uses_controlled_helper():
    source = _function_source("ejecutar_formulario_madrid")

    assert "page = await _continuar_formulario_controlado(page, config)" in source
    assert "page.click(config.continuar_formulario_selector)" not in source


def test_madrid_final_submit_has_no_automatic_retry():
    source = _function_source("_continuar_formulario_controlado")

    assert "for intento" not in source
    assert "_recuperar_formulario_tras_access_denied" not in _source()
    assert "intento=1" in source


def test_madrid_select_does_not_reselect_current_value():
    source = _function_source("_seleccionar_opcion")

    guard = "ya seleccionado, no se fuerza change"
    assert guard in source
    assert source.index(guard) < source.index("select_option(label=valor")


def test_madrid_final_submit_stabilization_does_not_force_blur():
    source = _function_source("_esperar_formulario_estable_antes_submit")

    assert ".blur(" not in source


def test_madrid_final_submit_requires_attachments_screen():
    source = _function_source("_click_continuar_formulario_una_vez")

    assert "_validar_salida_a_adjuntos(page, config, dialogs)" in source
    assert "Madrid formulario Continuar intento=%s completado" in source
    assert source.index("_validar_salida_a_adjuntos(page, config, dialogs)") < source.index(
        "Madrid formulario Continuar intento=%s completado"
    )


def test_madrid_final_submit_captures_dialogs_and_validation_messages():
    source = _source()

    assert "MadridFormularioValidationError" in source
    assert "page.on(\"dialog\", _on_dialog)" in source
    assert "page.remove_listener(\"dialog\", _on_dialog)" in source
    assert "madrid_formulario_validacion.png" in source
