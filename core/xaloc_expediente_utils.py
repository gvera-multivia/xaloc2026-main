import re

# Formatos aceptados:
# 1. YYYY/NNNNNN-MUL o YYYY/NNNNNN-SAD
# 2. YYYY-NNNNNN-APR
# 3. NNNNNNNNNN (10 dígitos exactos, como 1098266110)
VALID_EXP_REGEX = re.compile(r'^(\d{4}/\d+(?:-(?:MUL|SAD))?|\d{4}-\d+-APR|\d{10})$')

def is_valid_format(expediente: str) -> bool:
    """Checks if the expediente matches the correct Xaloc format."""
    if not expediente:
        return False
    # El .strip() elimina posibles espacios accidentales antes de validar
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
    
    # 1. Limpiar espacios y pasar a mayúsculas
    fixed = expediente.strip().upper()
    
    # 2. Corregir guión por barra (solo si parece el formato YYYY-NNNN)
    # Ejemplo: 2026-11504-MUL -> 2026/11504-MUL
    # Si es 1098266110, esta regex no hará nada al no haber guion
    fixed = re.sub(r'^(\d{4})-(\d+)', r'\1/\2', fixed)
    
    # 3. Corregir falta de L en sufijos
    if fixed.endswith("-MU"):
        fixed = fixed + "L"
        
    return fixed