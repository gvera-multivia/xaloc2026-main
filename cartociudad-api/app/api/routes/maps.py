from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.models.map_models import HealthResponse, MapsListResponse
from app.services.map_service import find_gpkg, get_mapas_dir_exists, list_gpkg_names


router = APIRouter(tags=["maps"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", mapas_dir_exists=get_mapas_dir_exists())


@router.get("/maps", response_model=MapsListResponse)
def list_maps(q: str | None = Query(default=None, description="Filtro opcional por nombre")) -> MapsListResponse:
    names = list_gpkg_names(query=q)
    return MapsListResponse(count=len(names), maps=names)


@router.get("/maps/{map_name}")
def download_map(map_name: str) -> FileResponse:
    path = find_gpkg(map_name)
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/geopackage+sqlite3",
    )

