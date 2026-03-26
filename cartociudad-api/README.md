# Cartociudad API

API en FastAPI para listar y descargar archivos `.gpkg` desde la carpeta `MAPAS`.

## Estructura

```text
.
├─ app/
│  ├─ api/
│  │  └─ routes/
│  │     └─ maps.py
│  ├─ models/
│  │  └─ map_models.py
│  ├─ services/
│  │  └─ map_service.py
│  └─ main.py
├─ main.py
└─ MAPAS/
```

## Instalacion

```bash
pip install -r requirements.txt
```

## Ejecutar

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Docker

Build y run directo:

```bash
docker build -t cartociudad-api .
docker run --rm -p 8000:8000 --name cartociudad-api cartociudad-api
```

Con Docker Compose:

```bash
docker compose up --build
```

## Endpoints

- `GET /health`: estado basico del servicio.
- `GET /maps`: lista todos los `.gpkg`.
- `GET /maps?q=mad`: filtra por texto.
- `GET /maps/{map_name}`: descarga un mapa (`madrid` o `madrid.gpkg`).
- `GET /location/postal-code/{codigo_postal}`: devuelve provincia (o varias candidatas) para el codigo postal.
- `GET /location/comarca?provincia=...&municipio=...`: devuelve la comarca para provincia y municipio (consulta externa por geocodificacion).

Documentacion interactiva:

- `http://localhost:8000/docs`
