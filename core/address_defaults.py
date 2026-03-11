from __future__ import annotations

import os

# Shared corporate representative postal address defaults.
DEFAULT_REPRESENTATIVE_STREET_TYPE = "RONDA"
DEFAULT_REPRESENTATIVE_STREET_NAME = "GENERAL MITRE"
DEFAULT_REPRESENTATIVE_STREET_FULL = "GENERAL MITRE 169"
DEFAULT_REPRESENTATIVE_NUMBER = "169"
DEFAULT_REPRESENTATIVE_CITY = "BARCELONA"
DEFAULT_REPRESENTATIVE_PROVINCE = "BARCELONA"
DEFAULT_REPRESENTATIVE_COUNTRY = "ESPANA"
DEFAULT_REPRESENTATIVE_ZIP = "08022"


def get_representative_street_type() -> str:
    return (os.getenv("XVIA_REP_STREET_TYPE") or "").strip() or DEFAULT_REPRESENTATIVE_STREET_TYPE


def get_representative_street_name() -> str:
    return (os.getenv("XVIA_REP_STREET_NAME") or "").strip() or DEFAULT_REPRESENTATIVE_STREET_NAME


def get_representative_street_full() -> str:
    return (os.getenv("XVIA_REP_STREET_FULL") or "").strip() or DEFAULT_REPRESENTATIVE_STREET_FULL


def get_representative_number() -> str:
    return (os.getenv("XVIA_REP_NUMBER") or "").strip() or DEFAULT_REPRESENTATIVE_NUMBER


def get_representative_city() -> str:
    return (os.getenv("XVIA_REP_CITY") or "").strip() or DEFAULT_REPRESENTATIVE_CITY


def get_representative_province() -> str:
    return (os.getenv("XVIA_REP_PROVINCE") or "").strip() or DEFAULT_REPRESENTATIVE_PROVINCE


def get_representative_country() -> str:
    return (os.getenv("XVIA_REP_COUNTRY") or "").strip() or DEFAULT_REPRESENTATIVE_COUNTRY


def get_default_country_es_ascii() -> str:
    return (os.getenv("XVIA_DEFAULT_COUNTRY_ASCII") or "").strip() or "ESPANA"


def get_default_country_es_label() -> str:
    return (os.getenv("XVIA_DEFAULT_COUNTRY_LABEL") or "").strip() or "ESPAÑA"


def get_representative_zip() -> str:
    return (os.getenv("XVIA_REP_ZIP") or "").strip() or DEFAULT_REPRESENTATIVE_ZIP
