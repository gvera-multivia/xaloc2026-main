from pathlib import Path

from fastapi import HTTPException


BASE_DIR = Path(__file__).resolve().parents[2]
MAPAS_DIR = BASE_DIR / "MAPAS"


def get_mapas_dir_exists() -> bool:
    return MAPAS_DIR.is_dir()


def safe_map_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise HTTPException(status_code=400, detail="El nombre no puede estar vacio.")
    if "/" in clean or "\\" in clean or ".." in clean:
        raise HTTPException(status_code=400, detail="Nombre de archivo invalido.")
    return clean


def find_gpkg(name: str) -> Path:
    safe_name = safe_map_name(name)
    filename = safe_name if safe_name.lower().endswith(".gpkg") else f"{safe_name}.gpkg"
    file_path = MAPAS_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"No existe el mapa '{filename}'.")
    return file_path


def list_gpkg_names(query: str | None = None) -> list[str]:
    if not MAPAS_DIR.is_dir():
        raise HTTPException(status_code=500, detail=f"No existe la carpeta {MAPAS_DIR}.")

    files = sorted(MAPAS_DIR.glob("*.gpkg"), key=lambda p: p.name.lower())
    names = [f.name for f in files]
    if query:
        token = query.lower().strip()
        names = [n for n in names if token in n.lower()]
    return names

