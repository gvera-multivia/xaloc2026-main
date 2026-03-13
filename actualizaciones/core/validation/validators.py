import re
from typing import Optional

def validate_nif(nif: str) -> tuple[bool, Optional[str]]:
    """
    Valida un NIF (DNI) o NIE español.
    Retorna (True, None) si es válido, (False, "mensaje de error") si no.
    """
    nif = nif.upper().strip()
    if not nif:
        return False, "El NIF no puede estar vacío"

    # NIF: 8 números + 1 letra
    # NIE: X, Y, Z + 7 números + 1 letra
    if not re.match(r"^[0-9XYZ][0-9]{7}[A-Z]$", nif):
        return False, "Formato de NIF/NIE inválido"

    mapping = "TRWAGMYFPDXBNJZSQVHLCKE"
    
    if nif[0] in "XYZ":
        prefix = {"X": "0", "Y": "1", "Z": "2"}[nif[0]]
        num_str = prefix + nif[1:-1]
    else:
        num_str = nif[:-1]
    
    try:
        num = int(num_str)
    except ValueError:
        return False, "El NIF debe contener solo números"
        
    expected_letter = mapping[num % 23]
    if nif[-1] != expected_letter:
        return False, f"Letra de control incorrecta. Se esperaba '{expected_letter}'"
    
    return True, None

def validate_dirty_address(street: str, number: str) -> tuple[bool, Optional[str]]:
    """
    Detecta si la calle contiene números pero el campo número está vacío.
    Ej: Calle = 'Gran Via 44', Numero = '' -> False
    """
    street = street.strip()
    number = number.strip()
    
    if not number and re.search(r"\d", street):
        return False, "Detección de 'Dirección Sucia': La calle contiene números pero el campo número está vacío"
    
    return True, None

def validate_postal_code(cp: str) -> tuple[bool, Optional[str]]:
    """Valida que el código postal tenga 5 dígitos."""
    cp = cp.strip()
    if not re.match(r"^\d{5}$", cp):
        return False, "El código postal debe tener exactamente 5 dígitos"
    return True, None

def validate_phone_es(phone: str) -> tuple[bool, Optional[str]]:
    """Valida un teléfono español (6, 7, 8 o 9 + 8 dígitos)."""
    phone = re.sub(r"\s+", "", str(phone))
    if not re.match(r"^[6789]\d{8}$", phone):
        return False, "Formato de teléfono español inválido (debe empezar por 6, 7, 8 o 9 y tener 9 dígitos)"
    return True, None

def validate_email(email: str) -> tuple[bool, Optional[str]]:
    """Valida el formato del email."""
    email = email.strip()
    # Regex básica para cumplimiento razonable
    if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
        return False, "Formato de correo electrónico inválido"
    return True, None

def validate_plate_spain(plate: str) -> tuple[bool, Optional[str]]:
    """Valida formato de matrícula española (NNNNLLL o antiguo)."""
    plate = re.sub(r"\s+", "", plate.upper())
    # Moderno: 1234BBB (sin vocales, sin Q)
    if re.match(r"^\d{4}[BCDFGHJKLMNPQRSTVWXYZ]{3}$", plate):
        return True, None
    # Antiguo: GI-1234-AZ o GI1234AZ
    if re.match(r"^[A-Z]{1,2}\d{4}[A-Z]{0,2}$", plate):
        return True, None
    
    return False, "Formato de matrícula española inválido"
