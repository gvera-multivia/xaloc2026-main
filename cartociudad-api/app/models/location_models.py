from pydantic import BaseModel, Field


class PostalCodeProvinceResponse(BaseModel):
    codigo_postal: str = Field(..., description="Codigo postal consultado")
    provincia: str | None = Field(default=None, description="Provincia unica si no hay ambiguedad")
    provincias: list[str] = Field(
        default_factory=list,
        description="Lista de provincias candidatas cuando el codigo postal es ambiguo",
    )


class ComarcaResponse(BaseModel):
    provincia: str = Field(..., description="Provincia consultada")
    municipio: str = Field(..., description="Municipio consultado")
    comarca: str = Field(..., description="Comarca resultante")
    source: str = Field(..., description="Origen del dato")

