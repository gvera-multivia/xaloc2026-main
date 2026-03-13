from __future__ import annotations

import os

# Centralized operational contact defaults used across sites/adapters.
DEFAULT_CONTACT_EMAIL = "info@xvia-serviciosjuridicos.com"
DEFAULT_CONTACT_MOBILE = "722761154"
DEFAULT_CONTACT_PHONE_FIXED = "932531411"


def get_default_contact_email(*, uppercase: bool = False) -> str:
    value = (os.getenv("XVIA_DEFAULT_CONTACT_EMAIL") or "").strip() or DEFAULT_CONTACT_EMAIL
    return value.upper() if uppercase else value


def get_default_contact_mobile() -> str:
    return (os.getenv("XVIA_DEFAULT_CONTACT_MOBILE") or "").strip() or DEFAULT_CONTACT_MOBILE


def get_default_contact_phone_fixed() -> str:
    return (os.getenv("XVIA_DEFAULT_CONTACT_PHONE_FIXED") or "").strip() or DEFAULT_CONTACT_PHONE_FIXED
