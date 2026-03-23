from __future__ import annotations

import re
import unicodedata

HEURISTIC_MIN_SCORE = 60

PROVINCE_ALIASES = {
    "la coruna": "a coruna",
    "coruna": "a coruna",
    "gerona": "girona",
    "lerida": "lleida",
    "guipuzcoa": "gipuzkoa",
    "guipuzcua": "gipuzkoa",
    "gipuzcoa": "gipuzkoa",
    "vizcaya": "bizkaia",
    "vizkaya": "bizkaia",
    "san sebastian": "donostia / san sebastian",
    "vitoria": "vitoria / gasteiz",
    "baleares": "illes balears",
    "islas baleares": "illes balears",
    "mallorca": "illes balears",
    "palma de mallorca": "illes balears",
}

CITY_ALIASES = {
    # Errores frecuentes en origen de datos
    "fornells de la seva": "fornells de la selva",
    "palau solita i plegamas": "palau-solita i plegamans",
    "palau solita i plegamans": "palau-solita i plegamans",
    "palau-solita i plegamas": "palau-solita i plegamans",
    "hospitalet del llobregat": "hospitalet de llobregat, l'",
    "hospitalet de llobregat": "hospitalet de llobregat, l'",
    "puerto de sagunto": "sagunto/sagunt",
    "san andres de la barca": "sant andreu de la barca",
    "ibiza": "eivissa",
    "eivissa": "eivissa",
}

# Patrones para variaciones frecuentes no cubiertas por alias exacto.
# Se evalúan sobre texto ya normalizado (sin tildes, en minúsculas).
CITY_ALIAS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^fornells de la se[vb]a$"), "fornells de la selva"),
    (re.compile(r"^palau[\s-]+solita\s+[iy]\s+plegama(?:s|ns)$"), "palau-solita i plegamans"),
    (re.compile(r"^(puerto|port)[\s-]+de[\s-]+sagunto$"), "sagunto/sagunt"),
    (re.compile(r"^san[\s-]+andres[\s-]+de[\s-]+la[\s-]+barca$"), "sant andreu de la barca"),
]


def _normalize_py(raw: str | None) -> str:
    text = unicodedata.normalize("NFD", (raw or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.lower().strip().split())


def normalize_province_alias(raw: str | None) -> str:
    n = _normalize_py(raw)
    return PROVINCE_ALIASES.get(n, raw or "")


def normalize_city_alias(raw: str | None) -> str:
    raw_text = str(raw or "").strip()
    n = _normalize_py(raw_text)
    if not n:
        return raw_text

    # 1) Si viene formato "NUCLEO - MUNICIPIO", nos quedamos con el municipio.
    # Ej.: "BELLAVISTA - LES FRANQUESES DEL VALLES"
    split_parts = re.split(r"\s+-\s+", raw_text, maxsplit=1)
    candidate = split_parts[1].strip() if len(split_parts) == 2 and split_parts[1].strip() else raw_text

    # 2) Pasar articulo inicial al final: "Les X" -> "X, Les"
    # Sirve para combos oficiales de tipo "Franqueses del Valles, Les".
    m = re.match(r"^\s*(?P<article>les|la|el|los|las)\s+(?P<body>.+?)\s*$", candidate, flags=re.IGNORECASE)
    if m:
        article = m.group("article").strip().capitalize()
        body = m.group("body").strip()
        candidate = f"{body}, {article}"
        if _normalize_py(body) == "franqueses del valles" and article.lower() == "les":
            candidate = "Franqueses del Valles, Les"
    else:
        # 2.b) Articulo apostrofado inicial: "L'Hospitalet ..." -> "Hospitalet ..., L'"
        m = re.match(r"^\s*(?P<article>l['’])\s*(?P<body>.+?)\s*$", candidate, flags=re.IGNORECASE)
        if m:
            body = m.group("body").strip()
            body_norm = _normalize_py(body)
            if body_norm in {"hospitalet del llobregat", "hospitalet de llobregat"}:
                candidate = "Hospitalet de Llobregat, L'"
            else:
                candidate = f"{body}, L'"

    candidate_norm = _normalize_py(candidate)

    # Prioridad 1: alias exacto (candidate y raw para compatibilidad).
    exact = CITY_ALIASES.get(candidate_norm) or CITY_ALIASES.get(n)
    if exact:
        return exact

    # Prioridad 2: alias por patrón.
    for pattern, replacement in CITY_ALIAS_PATTERNS:
        if pattern.match(candidate_norm):
            return replacement

    return candidate


def _js_heuristic_core() -> str:
    return """
        const ABBR = {
            'c/': 'calle',
            'c.': 'calle',
            'cl': 'calle',
            'av': 'avenida',
            'av.': 'avenida',
            'avda': 'avenida',
            'avda.': 'avenida',
            'pz': 'plaza',
            'pz.': 'plaza',
            'plz': 'plaza',
            'plz.': 'plaza',
            'pto': 'puerto',
            'pto.': 'puerto',
            'pg': 'paseo',
            'pg.': 'paseo',
            'ps': 'paseo',
            'ps.': 'paseo',
        }

        const normalize = (raw) => {
            const value = (raw || '')
                .normalize('NFD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .toLowerCase()
                .replace(/[,'’.;:()/_-]/g, ' ')
                .replace(/\\s+/g, ' ')
                .trim()
            if (!value) return ''
            const tokens = value.split(' ').filter(Boolean).map((t) => ABBR[t] || t)
            return tokens.join(' ')
        }

        const normalizeSorted = (raw) => {
            const n = normalize(raw)
            if (!n) return ''
            return n.split(' ').filter(Boolean).sort().join(' ')
        }

        const score = (labelRaw, targetRaw) => {
            const label = normalize(labelRaw)
            const target = normalize(targetRaw)
            const labelSorted = normalizeSorted(labelRaw)
            const targetSorted = normalizeSorted(targetRaw)
            const tokenOverlap = (l, t) => {
                const lt = l.split(' ').filter(w => w.length > 2)
                const tt = t.split(' ').filter(w => w.length > 2)
                if (!lt.length || !tt.length) return 0
                let common = 0
                for (const tok of tt) {
                    if (lt.some(w => w === tok || w.startsWith(tok) || tok.startsWith(w))) common++
                }
                return Math.round((common / Math.max(lt.length, tt.length)) * 72)
            }
            if (!label || !target) return -1
            if (label === target) return 100
            if (labelSorted === targetSorted) return 98
            if (label.startsWith(target)) return 92
            if (target.startsWith(label)) return 88
            if (label.includes(target)) return 80
            if (target.includes(label)) return 76
            const overlap = tokenOverlap(label, target)
            if (overlap >= 60) return overlap
            return 0
        }
    """


def select_option_heuristic_js(min_score: int = HEURISTIC_MIN_SCORE) -> str:
    return f"""({{ sid, text }}) => {{
        {_js_heuristic_core()}
        const escaped = sid.replace(/\\./g, '\\\\.')
        const selectEl = document.querySelector(`dnt-select#${{escaped}}`)
        if (!selectEl) return {{ clicked: false, bestScore: -1, bestLabel: '' }}
        const options = Array.from(selectEl.querySelectorAll('dnt-option'))

        let bestOpt = null
        let bestScore = -1
        let bestLabel = ''
        for (const opt of options) {{
            const optionDiv = opt.shadowRoot?.querySelector('[role="option"]')
            const label = (optionDiv?.textContent || '').replace(/\\s+/g, ' ').trim()
            const s = score(label, text)
            if (s > bestScore) {{
                bestScore = s
                bestOpt = opt
                bestLabel = label
            }}
        }}

        if (!bestOpt || bestScore < {min_score}) {{
            return {{ clicked: false, bestScore, bestLabel }}
        }}

        const optionDiv = bestOpt.shadowRoot?.querySelector('[role="option"]')
        if (!optionDiv) return {{ clicked: false, bestScore, bestLabel }}
        optionDiv.click()
        return {{ clicked: true, bestScore, bestLabel }}
    }}"""


def verify_selected_input_js(min_score: int = HEURISTIC_MIN_SCORE) -> str:
    return f"""({{ sid, text }}) => {{
        {_js_heuristic_core()}
        const escaped = sid.replace(/\\./g, '\\\\.')
        const selectEl = document.querySelector(`dnt-select#${{escaped}}`)
        const input = selectEl?.shadowRoot
            ?.querySelector('dnt-input')
            ?.shadowRoot
            ?.querySelector('input.dnt-input__inner')
        if (!input) return false
        const iv = (input.value || '').trim()
        return score(iv, text) >= {min_score}
    }}"""
