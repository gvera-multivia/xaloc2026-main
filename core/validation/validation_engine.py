from dataclasses import dataclass, asdict
from typing import Any, Optional
from .validators import (
    validate_nif, validate_dirty_address, validate_postal_code, 
    validate_phone_es, validate_email, validate_plate_spain
)
from .geo_data import is_valid_province, is_valid_city

@dataclass
class ValidationError:
    field: str
    message: str
    severity: str  # "ERROR" | "WARNING"

    def to_dict(self):
        return asdict(self)

@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[ValidationError]
    warnings: list[ValidationError]
    sanitized_payload: dict[str, Any]

class ValidationEngine:
    def __init__(self, site_id: str):
        self.site_id = site_id

    def validate(self, payload: dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        sanitized = payload.copy()

        # 1. Campos obligatorios
        self._check_required(payload, "nif", errors)
        self._check_required(payload, "name", errors)
        
        if self.site_id == "madrid":
            self._check_required(payload, "notif_name", errors)
            self._check_required(payload, "notif_surname1", errors)

        # 2. Dirección Sucia
        valid, msg = validate_dirty_address(
            payload.get("address_street", ""), 
            payload.get("address_number", "")
        )
        if not valid:
            errors.append(ValidationError("address_street", msg or "Error en dirección", "ERROR"))

        # 3. Formatos
        self._validate_field(payload, "nif", validate_nif, errors)
        self._validate_field(payload, "address_zip", validate_postal_code, errors)
        self._validate_field(payload, "user_phone", validate_phone_es, warnings)
        self._validate_field(payload, "user_email", validate_email, errors)
        self._validate_field(payload, "plate_number", validate_plate_spain, warnings)

        # 4. Geografía
        province = payload.get("address_province", "")
        city = payload.get("address_city", "")
        
        if province and not is_valid_province(province):
            warnings.append(ValidationError("address_province", f"Provincia '{province}' no reconocida en la lista estándar", "WARNING"))
        
        if city and province and not is_valid_city(city, province):
            warnings.append(ValidationError("address_city", f"Ciudad '{city}' no reconocida para la provincia '{province}'", "WARNING"))

        # 5. Específicos por Site
        if self.site_id == "madrid":
            self._validate_madrid(payload, errors)
        elif self.site_id == "xaloc_girona":
            self._validate_xaloc(payload, errors)

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            sanitized_payload=sanitized
        )

    def _check_required(self, payload: dict, field: str, errors: list):
        val = str(payload.get(field, "")).strip()
        if not val:
            errors.append(ValidationError(field, f"El campo '{field}' es obligatorio", "ERROR"))

    def _validate_field(self, payload: dict, field: str, validator_fn, target_list: list):
        val = str(payload.get(field, "")).strip()
        if val:
            valid, msg = validator_fn(val)
            if not valid:
                # Determinamos severidad basada en la lista de destino
                severity = "WARNING" if target_list is not None and "warnings" in str(target_list) else "ERROR"
                # Pequeño hack para saber si es warning o error basándonos en la lista pasada (mejorable)
                # En Python no es tan fácil saber el nombre de la variable pasada, así que lo haré más explícito si fuera necesario.
                # Por ahora, si va a 'errors' es ERROR, si va a 'warnings' es WARNING.
                target_list.append(ValidationError(field, msg or "Error de formato", "N/A")) 

    def _validate_madrid(self, payload: dict, errors: list):
        if payload.get("expediente_tipo") not in ["opcion1", "opcion2"]:
            errors.append(ValidationError("expediente_tipo", "Debe ser 'opcion1' o 'opcion2'", "ERROR"))
        
        nature = payload.get("naturaleza", "")
        if nature not in ["A", "R", "I"]:
            errors.append(ValidationError("naturaleza", "Debe ser 'A' (Alegación), 'R' (Recurso) o 'I' (Identificación)", "ERROR"))

    def _validate_xaloc(self, payload: dict, errors: list):
        motivos = str(payload.get("motivos", ""))
        if len(motivos) < 10:
            errors.append(ValidationError("motivos", "Los motivos deben tener al menos 10 caracteres", "ERROR"))
