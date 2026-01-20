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
    Strategy: ID > Name > Label > Text > CSS > XPath
    """
    if not candidates:
        return "page.locator('unknown')"

    # Priority order for new format
    for c in candidates:
        kind = c.get('kind', '')
        value = c.get('value', '')
        selector = c.get('selector', '')
        
        if not value:
            continue
            
        # Escape quotes in value
        safe_value = str(value).replace("'", "\\'").replace('"', '\\"')
        
        if kind == 'id':
            return f'page.locator("#{safe_value}")'
        elif kind == 'name':
            return f'page.locator("[name=\\"{safe_value}\\"]")'
    
    # Second priority: label/text
    for c in candidates:
        kind = c.get('kind', '')
        value = c.get('value', '')
        
        if not value:
            continue
            
        safe_value = str(value).replace("'", "\\'")
        
        if kind == 'label':
            return f"page.get_by_label('{safe_value}')"
        elif kind == 'text':
            return f"page.get_by_text('{safe_value}')"

    # Legacy format support (getByRole, etc.)
    for kind in ['getByRole', 'getByLabel', 'getByPlaceholder']:
        for c in candidates:
            if c.get('kind') == kind:
                val = str(c.get('value', '')).replace("'", "\\'")
                if kind == 'getByRole':
                    return f"page.get_by_role('{val}')"
                elif kind == 'getByLabel':
                    return f"page.get_by_label('{val}')"
                elif kind == 'getByPlaceholder':
                    return f"page.get_by_placeholder('{val}')"

    # Fallback to CSS/XPath
    for c in candidates:
        if c.get('kind') == 'css':
            val = str(c.get('value', '')).replace('"', '\\"')
            if val:
                return f'page.locator("{val}")'

    for c in candidates:
        if c.get('kind') == 'xpath':
            val = str(c.get('value', '')).replace('"', '\\"')
            if val:
                return f'page.locator("{val}")'

    return "page.locator('unknown')"

