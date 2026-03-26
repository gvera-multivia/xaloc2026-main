from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service status")
    mapas_dir_exists: bool = Field(..., description="Whether MAPAS directory exists")


class MapsListResponse(BaseModel):
    count: int = Field(..., ge=0, description="Number of maps returned")
    maps: list[str] = Field(default_factory=list, description="Map file names")

