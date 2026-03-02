from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RedsaraTarget:
    represented_street_type: str
    represented_address: str
    represented_province: str
    represented_city: str
    represented_zip: str
    represented_phone: str
    represented_email: str

    interested_doc_type: str
    interested_doc_number: str
    interested_name: str
    interested_surname1: str
    interested_surname2: str

    interested_street_type: str
    interested_address: str
    interested_province: str
    interested_city: str
    interested_zip: str

    interested_phone: str
    interested_email: str
    email_alert: bool = True

    # Step 2 - Datos de solicitud
    destination_organism_code: str = "LA0007892"
    subject: str = "PRUEBA REDSARA"
    exposes: str = "Texto de prueba para el campo expone."
    solicit: str = "Texto de prueba para el campo solicita."
