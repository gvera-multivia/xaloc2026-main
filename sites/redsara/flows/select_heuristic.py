from __future__ import annotations

import unicodedata

HEURISTIC_MIN_SCORE = 60

PROVINCE_ALIASES = {
    "la coruna": "a coruna",
    "coruna": "a coruna",
    "gerona": "girona",
    "lerida": "lleida",
    "san sebastian": "donostia / san sebastian",
    "vitoria": "vitoria / gasteiz",
    "baleares": "illes balears",
}


def _normalize_py(raw: str | None) -> str:
    text = unicodedata.normalize("NFD", (raw or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.lower().strip().split())


def normalize_province_alias(raw: str | None) -> str:
    n = _normalize_py(raw)
    return PROVINCE_ALIASES.get(n, raw or "")


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
                .replace(/[,.;:()/_-]/g, ' ')
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
