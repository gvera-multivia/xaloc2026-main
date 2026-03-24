from pydantic import BaseModel, Field


class MunicipioItem(BaseModel):
    municipio: str = Field(..., description="Nombre del municipio")
    ine_mun: str = Field(..., description="Código INE del municipio")


class MunicipiosResponse(BaseModel):
    provincia: str = Field(..., description="Provincia consultada")
    municipios: list[MunicipioItem] = Field(..., description="Lista de municipios")
    total: int = Field(..., description="Número total de municipios")


class AddressCandidate(BaseModel):
    address: str = Field(..., description="Dirección completa")
    municipio: str | None = Field(default=None, description="Municipio")
    provincia: str | None = Field(default=None, description="Provincia")
    comunidad_autonoma: str | None = Field(default=None, description="Comunidad autónoma")
    cod_postal: str | None = Field(default=None, description="Código postal")
    lat: float | None = Field(default=None, description="Latitud")
    lng: float | None = Field(default=None, description="Longitud")
    tipo: str | None = Field(default=None, description="Tipo de resultado (portal, vía, municipio...)")


class AddressSearchResponse(BaseModel):
    query: str = Field(..., description="Consulta realizada")
    results: list[AddressCandidate] = Field(..., description="Lista de candidatos")
    total: int = Field(..., description="Número de resultados devueltos")
