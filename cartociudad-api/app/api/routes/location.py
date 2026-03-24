from fastapi import APIRouter, Query

from app.models.cartociudad_models import AddressSearchResponse, MunicipiosResponse
from app.models.location_models import ComarcaResponse, PostalCodeProvinceResponse
from app.services.cartociudad_service import get_municipalities, search_address
from app.services.location_service import (
    get_comarca_by_province_and_municipality,
    get_province_by_postal_code,
)


router = APIRouter(prefix="/location", tags=["location"])


@router.get("/postal-code/{codigo_postal}", response_model=PostalCodeProvinceResponse)
def get_province_from_postal_code(codigo_postal: str) -> PostalCodeProvinceResponse:
    province, provinces = get_province_by_postal_code(codigo_postal)
    return PostalCodeProvinceResponse(codigo_postal=codigo_postal, provincia=province, provincias=provinces)


@router.get("/comarca", response_model=ComarcaResponse)
def get_comarca(
    provincia: str = Query(..., description="Nombre de la provincia"),
    municipio: str = Query(..., description="Nombre del municipio"),
) -> ComarcaResponse:
    comarca = get_comarca_by_province_and_municipality(provincia, municipio)
    return ComarcaResponse(provincia=provincia, municipio=municipio, comarca=comarca, source="nominatim")


@router.get("/municipios/{provincia}", response_model=MunicipiosResponse)
def get_municipios(provincia: str) -> MunicipiosResponse:
    municipios = get_municipalities(provincia)
    return MunicipiosResponse(provincia=provincia, municipios=municipios, total=len(municipios))


@router.get("/direccion", response_model=AddressSearchResponse)
def buscar_direccion(
    q: str = Query(..., description="Dirección a buscar (ej: 'Calle Mayor 1 Madrid')"),
    limit: int = Query(default=10, ge=1, le=50, description="Número máximo de resultados"),
) -> AddressSearchResponse:
    results = search_address(q, limit)
    return AddressSearchResponse(query=q, results=results, total=len(results))

