from fastapi import APIRouter, Query

from app.models.location_models import ComarcaResponse, PostalCodeProvinceResponse
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

