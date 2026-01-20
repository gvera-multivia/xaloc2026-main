def clean_text(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.split())

def refine_candidates(candidates: list) -> list:
    """
    Refine or filter candidates received from JS.
    """
    # For now, just pass through.
    return candidates

def get_best_selector(candidates: list) -> str:
    """
    Returns the 'best' selector string for code generation.
    Strategy: Role > Label > Placeholder > Text > CSS > XPath
    """
    if not candidates:
        return "page.locator('unknown')"

    # Order of preference
    # 1. getByRole
    # 2. getByLabel
    # 3. getByPlaceholder
    # 4. text

    for kind in ['getByRole', 'getByLabel', 'getByPlaceholder', 'text']:
        for c in candidates:
            if c['kind'] == kind:
                val = c['value'].replace("'", "\\'")
                if kind == 'getByRole':
                    return f"page.get_by_role('{val}')"
                elif kind == 'getByLabel':
                    return f"page.get_by_label('{val}')"
                elif kind == 'getByPlaceholder':
                    return f"page.get_by_placeholder('{val}')"
                elif kind == 'text':
                    return f"page.get_by_text('{val}')"

    # Fallback to CSS/XPath
    for c in candidates:
        if c['kind'] == 'css':
             val = c['value'].replace('"', '\\"')
             return f"page.locator(\"{val}\")"

    for c in candidates:
        if c['kind'] == 'xpath':
            val = c['value'].replace('"', '\\"')
            return f"page.locator(\"{val}\")"

    return "page.locator('unknown')"
