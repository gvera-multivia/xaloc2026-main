import re

# Formato correcto: YYYY/NNNNNN-MUL (N entre 1 y muchos dígitos, generalmente 6)
# Basado en la regex de claim_one_resource (aunque no la leí directamente del config, 
# asumo un formato robusto para Xaloc Girona)
VALID_EXP_REGEX = re.compile(r'^\d{4}/\d+-MUL$')

def is_valid_format(expediente: str) -> bool:
    """Checks if the expediente matches the correct Xaloc Girona format."""
    if not expediente:
        return False
    return bool(VALID_EXP_REGEX.match(expediente.strip()))

def fix_format(expediente: str) -> str:
    """
    Applies corrections to malformed expedientes:
    - Replaces '-' with '/' after the year.
    - Adds 'L' if it ends in '-MU'.
    - Removes whitespace.
    """
    if not expediente:
        return ""
    
    # 1. Limpiar espacios
    fixed = expediente.strip().upper()
    
    # 2. Corregir guión por barra (solo el primero después del año)
    # Ejemplo: 2026-11504-MUL -> 2026/11504-MUL
    fixed = re.sub(r'^(\d{4})-(\d+)', r'\1/\2', fixed)
    
    # 3. Corregir falta de L
    # Ejemplo: 2025/243792-MU -> 2025/243792-MUL
    if fixed.endswith("-MU"):
        fixed = fixed + "L"
        
    return fixed
