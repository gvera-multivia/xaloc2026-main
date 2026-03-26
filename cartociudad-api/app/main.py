from fastapi import FastAPI

from app.api.routes.location import router as location_router
from app.api.routes.maps import router as maps_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cartociudad API",
        description="API para listar y descargar archivos .gpkg de la carpeta MAPAS.",
        version="1.0.0",
    )
    app.include_router(maps_router)
    app.include_router(location_router)
    return app


app = create_app()
