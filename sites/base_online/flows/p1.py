from __future__ import annotations

import logging
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineAddressData, BaseOnlineP1Data
from sites.base_online.flows.common import rellenar_contacto
from sites.base_online.flows.upload import subir_archivos_por_modal

_SIGLES_PERMESES = {
    "AG", "AL", "AP", "AR", "AU", "AV", "AY", "BJ", "BO", "BR", "CA", "CG", "CH", "CI", "CJ", "CL", "CM",
    "CN", "CO", "CP", "CR", "CS", "CT", "CU", "DE", "DP", "DS", "ED", "EM", "EN", "ER", "ES", "EX", "FC",
    "FN", "GL", "GR", "GV", "HT", "JR", "LD", "LG", "MC", "ML", "MN", "MS", "MT", "MZ", "PB", "PD", "PJ",
    "PQ", "PR", "PS", "PT", "PZ", "QT", "RB", "RC", "RD", "RM", "RP", "RR", "RU", "SA", "SD", "SL", "SN",
    "SU", "TN", "TO", "TR", "UR", "VR", "ZN",
}


def _upper_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value.upper() if value else None


def _norm_spaces(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _formatear_adreca(detall: BaseOnlineAddressData) -> str:
    sigla = (detall.sigla or "").strip().upper()
    if sigla not in _SIGLES_PERMESES:
        raise ValueError(f"P1: 'sigla' invalida: {detall.sigla}")

    calle = (detall.calle or "").strip()
    numero = (detall.numero or "").strip()
    if not calle or not numero:
        raise ValueError("P1: 'calle' y 'numero' son obligatorios.")

    cp = (detall.codigo_postal or "").strip()
    if not cp:
        raise ValueError("P1: 'codigo_postal' es obligatorio.")

    municipio = _upper_or_none(detall.municipio)
    ampliacion_municipio = _upper_or_none(detall.ampliacion_municipio)
    provincia = _upper_or_none(detall.provincia)
    pais = _upper_or_none(detall.pais)

    if not pais:
        raise ValueError("P1: 'pais' es obligatorio.")

    es_espana = pais in {"ESPANA", "ESPA\u00d1A"}
    if es_espana:
        if not municipio:
            raise ValueError("P1: 'municipio' es obligatorio para Espana.")
        if not provincia:
            raise ValueError("P1: 'provincia' es obligatoria para Espana.")
    else:
        if not ampliacion_municipio:
            raise ValueError("P1: 'ampliacion_municipio' es obligatorio fuera de Espana.")

    calle_line = f"{sigla} {calle}, {numero}"
    extra1 = [detall.letra, detall.escala, detall.piso, detall.puerta]
    extra1 = [x.strip() for x in extra1 if x and x.strip()]
    if extra1:
        calle_line += ", " + ", ".join(extra1)
    if detall.ampliacion_calle and detall.ampliacion_calle.strip():
        calle_line += f" {detall.ampliacion_calle.strip()}"

    linea_cp = f"{cp} "
    if es_espana:
        linea_cp += municipio
        if ampliacion_municipio:
            linea_cp += f" {ampliacion_municipio}"
        linea_prov = provincia
    else:
        linea_cp += ampliacion_municipio
        linea_prov = pais

    return f"{calle_line}\n{linea_cp}\n{linea_prov}"


def _address_from_p1_data(data: BaseOnlineP1Data, config: BaseOnlineConfig) -> dict[str, str]:
    info = data.identificacio
    if info.adreca_detall:
        d = info.adreca_detall
        return {
            "pais": _norm_spaces(d.pais or config.defaults.country),
            "provincia": _norm_spaces(d.provincia),
            "municipio": _norm_spaces(d.municipio or d.ampliacion_municipio),
            "cp": _norm_spaces(d.codigo_postal),
            "sigla": _norm_spaces(d.sigla),
            "calle": _norm_spaces(d.calle),
            "numero": _norm_spaces(d.numero),
            "piso": _norm_spaces(d.piso),
            "puerta": _norm_spaces(d.puerta),
            "id_pais": "",
            "id_provincia": "",
            "id_municipio": "",
            "id_cp": "",
            "id_sigla": "",
            "id_vial": "",
        }

    raw = _norm_spaces(info.adreca)
    if not raw:
        raise ValueError("P1: falta direccion (adreca o adreca_detall).")

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    calle_line = lines[0] if lines else raw
    cp_line = lines[1] if len(lines) > 1 else ""
    prov_line = lines[2] if len(lines) > 2 else ""

    m_calle = re.match(r"^(?P<sigla>[A-Z]{2})\s+(?P<calle>.*?)(?:,\s*(?P<num>[^,\s]+))?$", calle_line.upper())
    cp_match = re.search(r"(\d{5})", cp_line)

    return {
        "pais": config.defaults.country,
        "provincia": _norm_spaces(prov_line),
        "municipio": _norm_spaces(re.sub(r"\b\d{5}\b", "", cp_line)),
        "cp": cp_match.group(1) if cp_match else "",
        "sigla": (m_calle.group("sigla") if m_calle else config.defaults.street_type),
        "calle": _norm_spaces(m_calle.group("calle") if m_calle else calle_line),
        "numero": _norm_spaces(m_calle.group("num") if m_calle else ""),
        "piso": "",
        "puerta": "",
        "id_pais": "",
        "id_provincia": "",
        "id_municipio": "",
        "id_cp": "",
        "id_sigla": "",
        "id_vial": "",
    }


async def _install_ajax_tracker(page: Page) -> None:
    await page.evaluate(
        """
        () => {
          if (window.__xalocAjaxTrackerInstalled) return;
          window.__xalocAjaxTrackerInstalled = true;
          window.__xalocAjaxPending = 0;
          window.__xalocAjaxLastChange = Date.now();

          const inc = () => { window.__xalocAjaxPending += 1; window.__xalocAjaxLastChange = Date.now(); };
          const dec = () => {
            window.__xalocAjaxPending = Math.max(0, window.__xalocAjaxPending - 1);
            window.__xalocAjaxLastChange = Date.now();
          };

          const oldOpen = XMLHttpRequest.prototype.open;
          const oldSend = XMLHttpRequest.prototype.send;
          XMLHttpRequest.prototype.open = function(...args) {
            this.__xalocTracked = true;
            return oldOpen.apply(this, args);
          };
          XMLHttpRequest.prototype.send = function(...args) {
            if (this.__xalocTracked) {
              inc();
              this.addEventListener('loadend', dec, { once: true });
            }
            return oldSend.apply(this, args);
          };

          if (window.fetch) {
            const oldFetch = window.fetch;
            window.fetch = (...args) => {
              inc();
              return oldFetch(...args)
                .finally(dec);
            };
          }
        }
        """
    )


async def _wait_ajax_idle(page: Page, timeout_ms: int = 12000, quiet_ms: int = 350) -> None:
    await _install_ajax_tracker(page)
    await page.wait_for_function(
        """
        (quiet) => {
          const p = window.__xalocAjaxPending || 0;
          const t = window.__xalocAjaxLastChange || 0;
          return p === 0 && (Date.now() - t) >= quiet;
        }
        """,
        arg=quiet_ms,
        timeout=timeout_ms,
    )


async def _wait_step2_popup_loaded(page: Page, config: BaseOnlineConfig) -> None:
    await page.wait_for_selector(config.selectors.p1_popup_municipi, state="visible", timeout=config.flow_timeouts.popup_load)
    await page.wait_for_function(
        """
        () => {
          const m = document.querySelector('#form_0\\:llistaMunicipis');
          return !!m && m.options && m.options.length > 1;
        }
        """,
        timeout=config.flow_timeouts.popup_load,
    )


async def _select_option_fuzzy(page: Page, selector: str, desired: str) -> bool:
    value = _norm_spaces(desired)
    if not value:
        return False
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False

    options = await loc.locator("option").all()
    if not options:
        return False

    desired_up = value.upper()

    for opt in options:
        opt_val = _norm_spaces(await opt.get_attribute("value"))
        opt_txt = _norm_spaces(await opt.text_content())
        if opt_val.upper() == desired_up or opt_txt.upper() == desired_up:
            await loc.select_option(value=opt_val)
            await _wait_ajax_idle(page)
            return True

    for opt in options:
        opt_val = _norm_spaces(await opt.get_attribute("value"))
        opt_txt = _norm_spaces(await opt.text_content())
        if desired_up in opt_txt.upper():
            await loc.select_option(value=opt_val)
            await _wait_ajax_idle(page)
            return True

    return False


async def _dump_hidden_address_values(page: Page) -> dict[str, str]:
    ids = [
        "form:AdridVial",
        "form:AdridSigles",
        "form:Adrcarrer",
        "form:Adrcasa",
        "form:AdridPis",
        "form:AdridPorta",
        "form:AdridMunicipi",
        "form:AdridProvincia",
        "form:Adrcp",
        "form:AdridPais",
    ]
    return await page.evaluate(
        """
        (fieldIds) => {
          const out = {};
          for (const id of fieldIds) {
            const el = document.getElementById(id);
            out[id] = el ? String(el.value || '').trim() : '';
          }
          return out;
        }
        """,
        ids,
    )


def _is_address_hidden_valid(hidden_vals: dict[str, str]) -> bool:
    required = [
        "form:AdridSigles",
        "form:Adrcarrer",
        "form:Adrcasa",
        "form:AdridMunicipi",
        "form:AdridProvincia",
        "form:Adrcp",
    ]
    return all(_norm_spaces(hidden_vals.get(k)) for k in required)


def _is_address_validation_error_text(text: str) -> bool:
    t = (text or "").lower()
    return ("adre" in t and "oblig" in t) or ("direccion" in t and "oblig" in t)


async def _has_main_form_address_error(page: Page) -> bool:
    error_candidates = [
        "#form\\:adreca + .error",
        "#form\\:adreca ~ .error",
        ".rf-msg-err",
        ".rich-messages-label",
        ".error",
    ]
    for sel in error_candidates:
        loc = page.locator(sel)
        count = await loc.count()
        if count == 0:
            continue
        for i in range(count):
            txt = _norm_spaces(await loc.nth(i).text_content())
            if _is_address_validation_error_text(txt):
                return True
    body = _norm_spaces(await page.locator("body").inner_text())
    return _is_address_validation_error_text(body)


async def _is_step3_after_continue(page: Page) -> bool:
    btn = page.locator("input[type='submit'][name='form:j_id29'][value='Continuar']").first
    if await btn.count() > 0:
        return True
    return await page.locator("input[type='button'][value='Signar i Presentar']").count() > 0


async def _click_continue_main_step2(page: Page, config: BaseOnlineConfig) -> None:
    btn = page.locator(config.selectors.p1_btn_step2_continuar).first
    await btn.click()
    await _wait_ajax_idle(page)
    await page.wait_for_load_state("domcontentloaded")


async def _set_address_hidden_fields_strategy_a(page: Page, address: dict[str, str], adreca_text: str) -> None:
    payload = {
        "form:AdridVial": address.get("id_vial", ""),
        "form:AdridSigles": address.get("id_sigla") or address.get("sigla", ""),
        "form:Adrcarrer": address.get("calle", ""),
        "form:Adrcasa": address.get("numero", ""),
        "form:AdridPis": address.get("piso", ""),
        "form:AdridPorta": address.get("puerta", ""),
        "form:AdridMunicipi": address.get("id_municipio") or address.get("municipio", ""),
        "form:AdridProvincia": address.get("id_provincia") or address.get("provincia", ""),
        "form:Adrcp": address.get("id_cp") or address.get("cp", ""),
        "form:AdridPais": address.get("id_pais") or address.get("pais", "ESP"),
    }
    await page.evaluate(
        """
        ({ values, adrecaText }) => {
          const fire = (el) => {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
          };

          for (const [id, val] of Object.entries(values)) {
            const el = document.getElementById(id);
            if (!el) continue;
            el.value = val || '';
            fire(el);
          }

          // En BASE hay dos nodos con name/id 'form:adreca' (textarea + hidden).
          // Evitamos querySelector con ':' para no romper por escape CSS.
          const adNodesByName = Array.from(document.getElementsByName('form:adreca') || []);
          if (adNodesByName.length > 0) {
            for (const n of adNodesByName) {
              n.value = adrecaText || '';
              fire(n);
            }
          } else {
            const single = document.getElementById('form:adreca');
            if (single) {
              single.value = adrecaText || '';
              fire(single);
            }
          }
        }
        """,
        {"values": payload, "adrecaText": adreca_text},
    )
    await _wait_ajax_idle(page)


async def _open_address_popup(page: Page, config: BaseOnlineConfig) -> bool:
    selectors = [
        "#imgBuscar",
        "img[onclick*='assistentAdreca']",
        "a[onclick*='popup'][onclick*='adre']",
        "a[onclick*='obr'][onclick*='adre']",
        "input[onclick*='popup'][onclick*='adre']",
        "button[onclick*='popup'][onclick*='adre']",
        "a[title*='adre' i]",
        "button[title*='adre' i]",
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        if await loc.count() == 0:
            continue
        try:
            await loc.click()
            await _wait_ajax_idle(page)
            await page.wait_for_selector(
                config.selectors.popup_step1_ready,
                state="visible",
                timeout=config.flow_timeouts.selector_default,
            )
            return True
        except Exception:
            continue

    try:
        by_txt = page.get_by_role("link", name=re.compile("adre", re.IGNORECASE)).first
        if await by_txt.count() > 0:
            await by_txt.click()
            await _wait_ajax_idle(page)
            await page.wait_for_selector(
                config.selectors.popup_step1_ready,
                state="visible",
                timeout=config.flow_timeouts.selector_default,
            )
            return True
    except Exception:
        return False
    return False


async def _fill_address_popup_step1(page: Page, address: dict[str, str], config: BaseOnlineConfig) -> None:
    pais = address.get("pais") or config.defaults.country
    provincia = address.get("provincia") or ""

    _ = await _select_option_fuzzy(page, config.selectors.p1_popup_pais, pais)
    _ = await _select_option_fuzzy(page, config.selectors.p1_popup_provincia, provincia)

    continuar_candidates = [
        page.get_by_role("button", name=re.compile("continuar", re.IGNORECASE)).first,
        page.locator(config.selectors.popup_continue).first,
    ]
    for btn in continuar_candidates:
        if await btn.count() == 0:
            continue
        await btn.click()
        await _wait_ajax_idle(page)
        break

    await _wait_step2_popup_loaded(page, config)


async def _fill_address_popup_step2(page: Page, address: dict[str, str], config: BaseOnlineConfig) -> None:
    municipio = address.get("municipio") or ""
    cp = address.get("cp") or ""
    sigla = address.get("sigla") or config.defaults.street_type

    if not await _select_option_fuzzy(page, config.selectors.p1_popup_municipi, municipio):
        raise ValueError(f"No se pudo seleccionar municipio en popup: {municipio}")

    await page.wait_for_function(config.scripts.check_cp_loaded, timeout=config.flow_timeouts.popup_load)

    if cp and not await _select_option_fuzzy(page, config.selectors.p1_popup_cp, cp):
        raise ValueError(f"No se pudo seleccionar CP en popup: {cp}")

    _ = await _select_option_fuzzy(page, config.selectors.p1_popup_vies, sigla)

    street_loc = page.locator(config.selectors.p1_popup_nom).first
    if await street_loc.count() == 0:
        raise ValueError("No se encontro campo de calle en popup (#form_0:nom)")
    await street_loc.fill(address.get("calle") or "")

    for field_id, val in [
        (config.selectors.p1_popup_numero, address.get("numero") or ""),
        (config.selectors.p1_popup_pis, address.get("piso") or ""),
        (config.selectors.p1_popup_porta, address.get("puerta") or ""),
    ]:
        loc = page.locator(field_id).first
        if await loc.count() > 0:
            await loc.fill(val)

    validate_candidates = [
        page.get_by_role("button", name=re.compile("adre", re.IGNORECASE)).first,
        page.locator("input[type='submit'][value*='adre' i], button:has-text('Adre')").first,
    ]
    clicked = False
    for btn in validate_candidates:
        if await btn.count() == 0:
            continue
        await btn.click()
        clicked = True
        break
    if not clicked:
        raise ValueError("No se encontro boton 'Adreca valida' en popup")

    await _wait_ajax_idle(page)


async def _try_strategy_a(page: Page, address: dict[str, str], adreca_text: str, config: BaseOnlineConfig) -> bool:
    logging.info("[P1][ADDRESS] Estrategia A: set directo de hidden fields")
    await _set_address_hidden_fields_strategy_a(page, address, adreca_text)

    hidden_before = await _dump_hidden_address_values(page)
    logging.info("[P1][ADDRESS][A] Hidden antes de continuar: %s", hidden_before)

    await _click_continue_main_step2(page, config)

    if await _is_step3_after_continue(page):
        hidden_after = await _dump_hidden_address_values(page)
        logging.info("[P1][ADDRESS][A] OK. Hidden finales: %s", hidden_after)
        return True

    has_error = await _has_main_form_address_error(page)
    hidden_after = await _dump_hidden_address_values(page)
    logging.warning("[P1][ADDRESS][A] Rechazada por servidor. error=%s hidden=%s", has_error, hidden_after)
    return False


async def _try_strategy_b(page: Page, address: dict[str, str], adreca_text: str, config: BaseOnlineConfig) -> bool:
    logging.info("[P1][ADDRESS] Estrategia B: popup asistente de direccion")

    opened = await _open_address_popup(page, config)
    if not opened:
        logging.warning("[P1][ADDRESS][B] No se pudo abrir popup")
        return False

    await _fill_address_popup_step1(page, address, config)
    await _fill_address_popup_step2(page, address, config)

    # Visual sync del textarea (solo visual)
    await page.evaluate(
        """
        (value) => {
          const fire = (el) => {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
          };
          const nodes = Array.from(document.getElementsByName('form:adreca') || []);
          if (nodes.length > 0) {
            for (const el of nodes) {
              try { el.removeAttribute('readonly'); } catch (e) {}
              el.value = value || '';
              fire(el);
            }
          } else {
            const single = document.getElementById('form:adreca');
            if (single) {
              try { single.removeAttribute('readonly'); } catch (e) {}
              single.value = value || '';
              fire(single);
            }
          }
        }
        """,
        adreca_text,
    )

    hidden = await _dump_hidden_address_values(page)
    logging.info("[P1][ADDRESS][B] Hidden tras popup: %s", hidden)

    if not _is_address_hidden_valid(hidden):
        logging.warning("[P1][ADDRESS][B] Hidden incompletos tras popup")

    await _click_continue_main_step2(page, config)

    if await _is_step3_after_continue(page):
        hidden_after = await _dump_hidden_address_values(page)
        logging.info("[P1][ADDRESS][B] OK. Hidden finales: %s", hidden_after)
        return True

    has_error = await _has_main_form_address_error(page)
    logging.warning("[P1][ADDRESS][B] Rechazada por servidor. error=%s", has_error)
    return False


async def fillAddressProtocol1BaseTarragona(page: Page, address: dict[str, str], config: BaseOnlineConfig) -> None:
    """
    Rellena direccion P1 en BASE Tarragona con estrategia A/B:
    - A: set directo de hidden fields + continuar.
    - B: popup asistente + continuar.
    """
    await _install_ajax_tracker(page)

    addr = {k: _norm_spaces(v) for k, v in (address or {}).items()}
    if not addr.get("numero"):
        addr["numero"] = config.defaults.street_number

    adreca_text = ""
    if all(addr.get(k) for k in ("sigla", "calle", "numero", "cp", "municipio", "provincia")):
        adreca_text = f"{addr['sigla']} {addr['calle']}, {addr['numero']}\n{addr['cp']} {addr['municipio']}\n{addr['provincia']}"

    try:
        ok_a = await _try_strategy_a(page, addr, adreca_text, config)
        if ok_a:
            return
    except Exception as e:
        logging.warning("[P1][ADDRESS][A] Error: %s", e)

    ok_b = await _try_strategy_b(page, addr, adreca_text, config)
    if not ok_b:
        raise ValueError("P1: no se pudo establecer una direccion valida con estrategias A/B")


async def _rellenar_contacto(page: Page, data: BaseOnlineP1Data, config: BaseOnlineConfig) -> None:
    await rellenar_contacto(page, data.contacte)

    await page.locator(config.selectors.p1_btn_contacte_continuar).first.click()
    await _wait_ajax_idle(page)
    await page.wait_for_load_state("domcontentloaded")


async def _rellenar_identificacion_conductor(page: Page, data: BaseOnlineP1Data, config: BaseOnlineConfig) -> None:
    info = data.identificacio

    await page.locator(config.selectors.p1_expedient_id_ens).first.fill(info.expedient_id_ens)
    await page.locator(config.selectors.p1_expedient_any).first.fill(info.expedient_any)
    await page.locator(config.selectors.p1_expedient_num).first.fill(info.expedient_num)

    await page.evaluate(
        "typeof actualitzarClauExpedientclau_expedient === 'function' && actualitzarClauExpedientclau_expedient()"
    )
    await _wait_ajax_idle(page)

    await page.locator(config.selectors.p1_num_butlleti).first.fill(info.num_butlleti)
    await page.locator(config.selectors.p1_data_denuncia).first.fill(info.data_denuncia)
    await page.locator(config.selectors.p1_matricula).first.fill(info.matricula)
    await page.locator(config.selectors.p1_identificacio).first.fill(info.identificacio)
    await page.locator(config.selectors.p1_llicencia_conduccio).first.fill(info.llicencia_conduccio)
    await page.locator(config.selectors.p1_nom_complet).first.fill(info.nom_complet)

    address = _address_from_p1_data(data, config)
    await fillAddressProtocol1BaseTarragona(page, address, config)

    # Si estamos aqui, ya estamos en el paso 3
    archivos = list(data.archivos_adjuntos or [])
    if not archivos:
        raise ValueError("P1: falta 'archivos_adjuntos' (al menos 1 archivo).")
    await subir_archivos_por_modal(page, archivos)

    await page.locator(config.selectors.p1_btn_step3_continuar).first.click()
    await _wait_ajax_idle(page)
    await page.wait_for_load_state("domcontentloaded")

    boton_firma = page.locator(config.selectors.p1_btn_signar_presentar).first
    if await boton_firma.count() > 0:
        logging.info("[P1] Pantalla 'Signar i Presentar' detectada (no se pulsa en modo demo).")


async def ejecutar_p1(page: Page, data: BaseOnlineP1Data, config: BaseOnlineConfig | None = None) -> None:
    cfg = config or BaseOnlineConfig()
    logging.info("[P1] Rellenando pantalla 1 (contacto)...")
    await _rellenar_contacto(page, data, cfg)
    logging.info("[P1] Rellenando pantalla 2 (identificacion conductor + direccion robusta)...")
    try:
        await _rellenar_identificacion_conductor(page, data, cfg)
    except PlaywrightTimeoutError as e:
        raise ValueError(f"P1 timeout en flujo de direccion/continuar: {e}") from e


# Validacion manual rapida (local):
# 1) Ejecutar un P1 con datos reales de municipio+cp+sigla.
# 2) Ver logs: debe indicar Estrategia A o fallback B.
# 3) Confirmar que llega a pantalla con boton 'Signar i Presentar'.
# 4) Si A falla por validacion, B debe abrir popup, seleccionar municipio+CP y continuar.
