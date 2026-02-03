from __future__ import annotations

import re
import unicodedata
from typing import Any

from playwright.async_api import Page


def _normalizar_texto(texto: str) -> str:
    if texto is None:
        return ""

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def elegir_mejor_sugerencia(sugerencias: list[str], valor_introducido: str) -> str | None:
    """
    El endpoint de BDC devuelve una lista de sugerencias (texto).
    Esta función elige la que mejor encaja con lo tecleado.
    """

    if not sugerencias:
        return None

    return elegir_mejor_sugerencia_con_tipo(sugerencias, valor_introducido, tipo_via=None)


def elegir_mejor_sugerencia_con_tipo(
    sugerencias: list[str],
    valor_introducido: str,
    *,
    tipo_via: str | None,
) -> str | None:
    objetivo = _normalizar_texto(valor_introducido)
    objetivo_tokens = [t for t in objetivo.split(" ") if t]
    tipo_norm = _normalizar_texto(tipo_via or "")

    mejor = sugerencias[0]
    mejor_score = -10_000
    for s in sugerencias:
        sn = _normalizar_texto(s)
        score = 0

        if objetivo and objetivo in sn:
            score += 20

        if objetivo_tokens:
            score += sum(2 for tok in objetivo_tokens if tok in sn)

        if tipo_norm:
            # Formato observado: "CHAMBERI  [PLAZA]"
            if f"[{tipo_norm}]" in sn:
                score += 8
            elif tipo_norm in sn:
                score += 2

        score -= int(len(sn) / 20)

        if score > mejor_score:
            mejor = s
            mejor_score = score

    return mejor


def sugerencias_desde_response(resp: dict[str, Any]) -> list[str]:
    """
    La respuesta observada es un JSON tipo:
    { "CHAMBERI  [PLAZA]": "CHAMBERI  [PLAZA]", ... }
    """

    if not isinstance(resp, dict):
        return []

    items = []
    for k in resp.keys():
        if isinstance(k, str) and k.strip():
            items.append(k.strip())
    return items


async def bdc_sugerencias_desde_pagina(
    page: Page,
    *,
    elemento: str,
    valor: str,
    recarga_bdc: bool = True,
    endpoint_path: str = "/WFORS_WBWFORS/formClientServlet",
) -> dict[str, Any]:
    """
    Llama al endpoint de BDC usando el mismo contexto del navegador (cookies/session)
    y construye `mapaIdName` a partir de los campos `#formDesigner` con clases `formula2_*`.

    Nota: este endpoint suele requerir sesión activa; por eso se hace desde Playwright.
    """

    payload = {
        "recargaBDC": "true" if recarga_bdc else "false",
        "elemento": elemento,
        "valor": valor,
        "endpoint_path": endpoint_path,
    }

    return await page.evaluate(
        """
        async ({ recargaBDC, elemento, valor, endpoint_path }) => {
          const mapa = [];
          const root = document.querySelector('#formDesigner') || document;
          const fields = root.querySelectorAll('input, select, textarea');

          for (const el of fields) {
            if (!el.className || typeof el.className !== 'string') continue;

            const classList = el.className.split(/\\s+/).filter(Boolean);
            const formulaClass = classList.find((c) => c.startsWith('formula2_'));
            if (!formulaClass) continue;

            let key = formulaClass.slice('formula2_'.length);

            // Caso observado: textarea con clase extra "expone" acaba en payload como "GESTION_MULTAS_EXPONE expone"
            if (classList.includes('expone')) {
              key = `${key} expone`;
            }

            let v = null;
            if (!el.disabled) {
              if (el.tagName === 'INPUT') {
                const type = (el.getAttribute('type') || '').toLowerCase();
                if (type === 'checkbox') {
                  v = el.checked ? 'true' : 'false';
                } else if (type === 'radio') {
                  v = el.checked ? (el.value ?? '') : '';
                } else {
                  v = el.value ?? '';
                }
              } else {
                v = el.value ?? '';
              }
            }

            const ariaReq = (el.getAttribute('aria-required') || '').toLowerCase() === 'true';
            if ((ariaReq || el.required) && (v === '' || v == null)) {
              v = '##_REQUIRED_##';
            }

            mapa.push([key, v]);
          }

          const body = new URLSearchParams();
          body.set('recargaBDC', recargaBDC);
          body.set('elemento', elemento);
          body.set('valor', valor);
          body.set('mapaIdName', JSON.stringify(mapa));

          const resp = await fetch(endpoint_path, {
            method: 'POST',
            headers: {
              'accept': 'application/json, text/javascript, */*; q=0.01',
              'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
              'x-requested-with': 'XMLHttpRequest',
            },
            body: body.toString(),
            credentials: 'same-origin',
          });

          if (!resp.ok) {
            const txt = await resp.text().catch(() => '');
            throw new Error(`BDC ${resp.status}: ${txt.slice(0, 500)}`);
          }

          return await resp.json();
        }
        """,
        payload,
    )
