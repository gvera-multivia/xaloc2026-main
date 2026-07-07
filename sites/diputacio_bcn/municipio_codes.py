from __future__ import annotations

import re
import unicodedata
from typing import Any


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _norm(value: Any) -> str:
    txt = _clean(value).upper()
    if not txt:
        return ""
    txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
    txt = re.sub(r"[^A-Z0-9]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


MUNICIPIO_TO_CODE: dict[str, str] = {
    "SABADELL": "186",
    "CASTELLDEFELS": "055",
    "SANT CUGAT DEL VALLES": "204",
    "HOSPITALET DE LLOBREGAT": "100",
    "L HOSPITALET DE LLOBREGAT": "100",
    "VILANOVA I LA GELTRU": "308",
    "BADALONA": "015",
    "MATARO": "120",
    "CORNELLA DE LLOBREGAT": "072",
    "VIC": "299",
    "RUBI": "183",
    "VILADECANS": "302",
    "CALELLA": "035",
    "ARENYS DE MAR": "006",
    "SITGES": "270",
    "VILASSAR DE MAR": "217",
    "MASNOU": "117",
    "EL MASNOU": "117",
    "PREMIA DE MAR": "171",
    "CERDANYOLA DEL VALLES": "266",
    "MOLINS DE REI": "122",
    "MONTGAT": "125",
    "GRANOLLERS": "096",
    "IGUALADA": "101",
    "SANT FELIU DE LLOBREGAT": "210",
    "SANT JOAN DESPI": "216",
    "SANT JUST DESVERN": "219",
    "SANT BOI DE LLOBREGAT": "199",
    "SANT BOI DEL LLOBREGAT": "199",
    "PINEDA DE MAR": "162",
    "ESPARREGUERA": "075",
    "GAVA": "088",
    "SANT VICENC DE MONTALT": "264",
    "MOLLET DEL VALLES": "123",
    "BARBERA DEL VALLES": "252",
    "VILAFRANCA DEL PENEDES": "306",
    "MALGRAT DE MAR": "109",
    "CARDEDEU": "045",
    "SANT ANDREU DE LA BARCA": "195",
    "CALDES DE MONTBUI": "033",
    "CALDES DE ESTRAC": "032",
    "CALDES D ESTRAC": "032",
    "LA GARRIGA": "087",
    "SANT VICENC DELS HORTS": "263",
    "MATADEPERA": "119",
    "ALELLA": "003",
    "MONTCADA I REIXAC": "124",
    "MONTMELO": "134",
    "CABRERA DE MAR": "029",
    "CUBELLES": "073",
    "SANTA PERPETUA DE MOGODA": "260",
    "SANT PERE DE RIBES": "231",
    "VILANOVA DEL CAMI": "303",
    "SANT ANDREU DE LLAVANERES": "196",
    "PALAFOLLS": "154",
    "PREMIA DE DALT": "230",
    "CANOVELLES": "040",
    "TORELLO": "285",
    "VALLIRANA": "296",
    "TEIA": "281",
    "TORRELLES DE LLOBREGAT": "289",
    "SANT POL DE MAR": "235",
    "LA LLAGOSTA": "104",
    "PALAU SOLITA I PLEGAMANS": "155",
    "MARTORELL": "113",
    "LES FRANQUESES DEL VALLES": "085",
    "OLESA DE MONTSERRAT": "146",
    "D OLESA DE MONTSERRAT": "146",
    "ARGENTONA": "009",
    "TIANA": "282",
    "SANT FELIU DE CODINES": "209",
    "ARENYS DE MUNT": "007",
    "BADIA DEL VALLES": "312",
    "MANLLEU": "111",
    "MANRESA": "113",
    "PIERA": "160",
    "LLINARS DEL VALLES": "105",
    "GIRONELLA": "091",
    "SANT ANTONI DE VILAMAJOR": "197",
    "CABRILS": "030",
    "LA PALMA DE CERVELLO": "313",
    "BERGA": "022",
    "PAPIOL": "157",
    "EL PAPIOL": "157",
    "VILANOVA DEL VALLES": "310",
    "SANT QUIRZE DEL VALLES": "238",
    "SANT VICENC DE CASTELLET": "262",
    "SANT JOAN DE VILATORRADA": "225",
    "SANT CLIMENT DE LLOBREGAT": "203",
    "CANET DE MAR": "039",
    "CASTELLAR DEL VALLES": "050",
    "MOIA": "137",
    "MONTORNES DEL VALLES": "135",
    "PALLEJA": "156",
    "PARETS DEL VALLES": "158",
    "LA ROCA DEL VALLES": "180",
    "TORDERA": "284",
    "ULLASTRELL": "290",
    "SANTA COLOMA DE CERVELLO": "244",
    "SANTA COLOMA DE GRAMENET": "245",
    "SANTA COLOMA DE GRAMANET": "245",
    "SANTA EULALIA DE RONCANA": "248",
    "SANT CELONI": "201",
    "POLINYA": "166",
    "VACARISSES": "291",
    "RODA DE TER": "182",
    "VILASSAR DE DALT": "213",
    "CANYELLES": "042",
    "COLLBATO": "068",
}

KNOWN_CODES = set(MUNICIPIO_TO_CODE.values())


def resolve_codmuni(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""

    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 5 and digits.startswith("08"):
        digits = digits[-3:]
    if digits:
        code = digits.zfill(3)[-3:]
        if code in KNOWN_CODES:
            return code

    key = _norm(raw)
    if not key:
        return ""
    if key in MUNICIPIO_TO_CODE:
        return MUNICIPIO_TO_CODE[key]

    for prefix in ("EL ", "LA ", "L "):
        if key.startswith(prefix):
            stripped = key[len(prefix) :].strip()
            if stripped in MUNICIPIO_TO_CODE:
                return MUNICIPIO_TO_CODE[stripped]

    return ""
