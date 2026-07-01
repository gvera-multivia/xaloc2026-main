import re

# Formatos aceptados:
# 1. YY/NNNNNNNN-D
# 2. YYYY/NNNNNN-MUL o YYYY/NNNNNN-SAD
# 3. YYYY/NNNNNN-APR o YYYY-NNNNNN-APR
# 4. NNNNNNNNNN (10 digitos exactos, como 1098266110)
# 5. NNNNNNNNNNNN (12 digitos exactos, como 000038101604, 000042269999)
# 6. NNNNNNNNNNNNN (13 digitos exactos, como 0448640179907)
# 7. YYYY-L-NNNNNNNN (nuevos expedientes alfanumericos de Xaloc, p.ej. 2026-Z-00464013)
VALID_EXP_REGEX = re.compile(
    r"^(?:"
    r"\d{2}/\d{8}-\d|"
    r"\d{4}/\d+(?:-(?:MUL|SAD|APR))?|"
    r"\d{4}-\d+-APR|"
    r"\d{4}-\d+-\d|"
    r"\d{10}|"
    r"\d{12}|"
    r"\d{13}|"
    r"\d{4}-[A-Z]-\d{8}"
    r")$"
)


def is_valid_format(expediente: str) -> bool:
    """Checks if the expediente matches the correct Xaloc format."""
    if not expediente:
        return False
    return bool(VALID_EXP_REGEX.match(expediente.strip()))


def fix_format(expediente: str) -> str:
    """
    Applies corrections to malformed expedientes:
    - Reconstructs compact YYNNNNNNNND -> YY/NNNNNNNN-D.
    - Replaces '-' with '/' after the year.
    - Adds 'L' if it ends in '-MU'.
    - Removes whitespace and trailing punctuation.
    """
    if not expediente:
        return ""

    fixed = expediente.strip().upper()
    fixed = re.sub(r"[.\s]+$", "", fixed)

    if re.fullmatch(r"\d{11}", fixed):
        return f"{fixed[:2]}/{fixed[2:10]}-{fixed[10]}"

    if not re.match(r"^\d{4}-\d+-\d$", fixed):
        fixed = re.sub(r"^(\d{4})-(\d+)", r"\1/\2", fixed)

    if fixed.endswith("-MU"):
        fixed = fixed + "L"

    return fixed
