import json
import unicodedata
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HTTP_TIMEOUT_SECONDS = 8
POSTAL_PREFIX_TO_PROVINCE: dict[str, str] = {
    "01": "Alava",
    "02": "Albacete",
    "03": "Alicante",
    "04": "Almeria",
    "05": "Avila",
    "06": "Badajoz",
    "07": "Baleares",
    "08": "Barcelona",
    "09": "Burgos",
    "10": "Caceres",
    "11": "Cadiz",
    "12": "Castellon",
    "13": "Ciudad Real",
    "14": "Cordoba",
    "15": "A Coruna",
    "16": "Cuenca",
    "17": "Girona",
    "18": "Granada",
    "19": "Guadalajara",
    "20": "Guipuzcoa",
    "21": "Huelva",
    "22": "Huesca",
    "23": "Jaen",
    "24": "Leon",
    "25": "Lleida",
    "26": "La Rioja",
    "27": "Lugo",
    "28": "Madrid",
    "29": "Malaga",
    "30": "Murcia",
    "31": "Navarra",
    "32": "Ourense",
    "33": "Asturias",
    "34": "Palencia",
    "35": "Las Palmas",
    "36": "Pontevedra",
    "37": "Salamanca",
    "38": "Santa Cruz de Tenerife",
    "39": "Cantabria",
    "40": "Segovia",
    "41": "Sevilla",
    "42": "Soria",
    "43": "Tarragona",
    "44": "Teruel",
    "45": "Toledo",
    "46": "Valencia",
    "47": "Valladolid",
    "48": "Vizcaya",
    "49": "Zamora",
    "50": "Zaragoza",
    "51": "Ceuta",
    "52": "Melilla",
}


def _normalize(text: str) -> str:
    text = text.strip().lower()
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _canonical_admin_name(text: str) -> str:
    value = _normalize(text)
    prefixes = [
        "provincia de ",
        "comunidad de ",
        "comunitat de ",
        "principado de ",
        "region de ",
    ]
    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    aliases = {
        "catalunya": "cataluna",
    }
    return aliases.get(value, value)


def _same_admin_name(a: str, b: str) -> bool:
    return _canonical_admin_name(a) == _canonical_admin_name(b)


def _province_variants(province: str) -> list[str]:
    base = province.strip()
    variants = {base}
    norm = _normalize(base)
    if norm == "cataluna":
        variants.add("Catalunya")
    if norm == "catalunya":
        variants.add("Cataluña")
    return [v for v in variants if v]


def _query_nominatim(params: dict[str, str | int]) -> list[dict]:
    url = f"{NOMINATIM_URL}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "User-Agent": "cartociudad-api/1.0 (contacto: local-dev)",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def _normalize_postal_code(postal_code: str) -> str:
    code = postal_code.strip()
    if len(code) != 5 or not code.isdigit():
        raise HTTPException(status_code=400, detail="El codigo postal debe tener 5 digitos.")
    return code


def get_province_by_postal_code(postal_code: str) -> tuple[str | None, list[str]]:
    code = _normalize_postal_code(postal_code)
    province = POSTAL_PREFIX_TO_PROVINCE.get(code[:2])
    if not province:
        raise HTTPException(status_code=404, detail=f"No se encontro provincia para el codigo postal {code}.")
    return province, [province]


def get_comarca_by_province_and_municipality(province: str, municipality: str) -> str:
    province_clean = province.strip()
    municipality_clean = municipality.strip()
    if not province_clean or not municipality_clean:
        raise HTTPException(status_code=400, detail="Provincia y municipio son obligatorios.")

    try:
        data: list[dict] = []
        for province_variant in _province_variants(province_clean):
            params = {
                "format": "jsonv2",
                "addressdetails": 1,
                "countrycodes": "es",
                "limit": 8,
                "city": municipality_clean,
                "state": province_variant,
            }
            data = _query_nominatim(params)
            if data:
                break

        if not data:
            for province_variant in _province_variants(province_clean):
                params = {
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "countrycodes": "es",
                    "limit": 8,
                    "q": f"{municipality_clean}, {province_variant}, España",
                }
                data = _query_nominatim(params)
                if data:
                    break
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar el servicio de comarca: {exc}.") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Timeout consultando el servicio de comarca.") from exc

    if not isinstance(data, list) or not data:
        raise HTTPException(status_code=404, detail="No se encontraron resultados para provincia y municipio.")

    p_norm = _canonical_admin_name(province_clean)
    m_norm = _normalize(municipality_clean)

    for item in data:
        address = item.get("address", {})
        if not isinstance(address, dict):
            continue

        addr_municipality = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or ""
        )
        province_candidates = [
            str(address.get("province") or ""),
            str(address.get("state") or ""),
            str(address.get("state_district") or ""),
            str(address.get("county") or ""),
        ]
        if m_norm and _normalize(str(addr_municipality)) != m_norm:
            continue
        if p_norm and not any(_same_admin_name(p_norm, candidate) for candidate in province_candidates if candidate):
            continue

        county = str(address.get("county") or "").strip()
        state_district = str(address.get("state_district") or "").strip()

        if county and _normalize(county) != p_norm:
            return county
        if state_district and _normalize(state_district) != p_norm:
            return state_district
        if county:
            return county
        if state_district:
            return state_district

    raise HTTPException(status_code=404, detail="No se pudo determinar la comarca para ese municipio.")
