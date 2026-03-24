import json
import sqlite3
import unicodedata
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException

from app.models.cartociudad_models import AddressCandidate, MunicipioItem

MAPAS_DIR = Path(__file__).parent.parent.parent / "MAPAS"
CARTOCIUDAD_CANDIDATES_URL = "https://www.cartociudad.es/geocoder/api/geocoder/candidates"
HTTP_TIMEOUT_SECONDS = 8

# Mapeo de nombre de provincia normalizado → nombre de fichero .gpkg
PROVINCE_TO_FILE: dict[str, str] = {
    "alava": "alava",
    "araba": "alava",
    "albacete": "albacete",
    "alicante": "alicante",
    "almeria": "almeria",
    "asturias": "asturias",
    "oviedo": "asturias",
    "avila": "avila",
    "badajoz": "badajoz",
    "baleares": "baleares",
    "illes balears": "baleares",
    "islas baleares": "baleares",
    "barcelona": "barcelona",
    "burgos": "burgos",
    "caceres": "caceres",
    "cadiz": "cadiz",
    "cantabria": "cantabria",
    "castellon": "castellon",
    "castello": "castellon",
    "ceuta": "ceuta",
    "ciudad real": "ciudad_real",
    "cordoba": "cordoba",
    "cuenca": "cuenca",
    "girona": "girona",
    "gerona": "girona",
    "granada": "granada",
    "guadalajara": "guadalajara",
    "guipuzcoa": "guipuzcoa",
    "gipuzkoa": "guipuzcoa",
    "huelva": "huelva",
    "huesca": "huesca",
    "jaen": "jaen",
    "la rioja": "la_rioja",
    "rioja": "la_rioja",
    "las palmas": "las_palmas",
    "leon": "leon",
    "lleida": "lleida",
    "lerida": "lleida",
    "lugo": "lugo",
    "madrid": "madrid",
    "malaga": "malaga",
    "melilla": "melilla",
    "murcia": "murcia",
    "navarra": "navarra",
    "navarre": "navarra",
    "ourense": "orense",
    "orense": "orense",
    "palencia": "palencia",
    "pontevedra": "pontevedra",
    "salamanca": "salamanca",
    "segovia": "segovia",
    "sevilla": "sevilla",
    "soria": "soria",
    "tarragona": "tarragona",
    "tenerife": "tenerife",
    "santa cruz de tenerife": "tenerife",
    "teruel": "teruel",
    "toledo": "toledo",
    "valencia": "valencia",
    "valladolid": "valladolid",
    "vizcaya": "vizcaya",
    "bizkaia": "vizcaya",
    "zamora": "zamora",
    "zaragoza": "zaragoza",
    "a coruna": "a_coruna",
    "coruna": "a_coruna",
    "la coruna": "a_coruna",
}


def _normalize(text: str) -> str:
    text = text.strip().lower()
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _province_to_gpkg(province: str) -> Path:
    key = _normalize(province)
    filename = PROVINCE_TO_FILE.get(key)
    if not filename:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró fichero para la provincia '{province}'. "
                   f"Provincias disponibles: {', '.join(sorted(set(PROVINCE_TO_FILE.values())))}",
        )
    path = MAPAS_DIR / f"{filename}.gpkg"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Fichero de datos no encontrado: {filename}.gpkg")
    return path


def get_municipalities(province: str) -> list[MunicipioItem]:
    gpkg_path = _province_to_gpkg(province)
    con = sqlite3.connect(str(gpkg_path))
    try:
        rows = con.execute(
            "SELECT DISTINCT municipio, ine_mun FROM portalpk_publi ORDER BY municipio"
        ).fetchall()
    finally:
        con.close()
    return [MunicipioItem(municipio=row[0], ine_mun=row[1]) for row in rows if row[0]]


def search_address(query: str, limit: int = 10) -> list[AddressCandidate]:
    if not query.strip():
        raise HTTPException(status_code=400, detail="El parámetro 'q' no puede estar vacío.")
    limit = min(max(1, limit), 50)
    params = {"q": query.strip(), "limit": limit}
    url = f"{CARTOCIUDAD_CANDIDATES_URL}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "User-Agent": "cartociudad-api/1.0 (contacto: local-dev)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Error contactando CartoCiudad: {exc}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Timeout consultando CartoCiudad.") from exc

    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        results.append(AddressCandidate(
            address=item.get("address", ""),
            municipio=item.get("muni") or item.get("poblacion"),
            provincia=item.get("province"),
            comunidad_autonoma=item.get("comunidadAutonoma"),
            cod_postal=item.get("postalCode"),
            lat=item.get("lat"),
            lng=item.get("lng"),
            tipo=item.get("type"),
        ))
    return results
