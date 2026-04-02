# Pipeline 11 — Web UI

Serves a FastAPI + Leaflet dark-theme web map showing the AOI boundary, fire perimeter, all buildings, exposed buildings, ignition point, and a consequence summary sidebar.

## Inputs

| File | Description |
|------|-------------|
| `data/input/aoi_reprojected.shp` | AOI boundary from pipeline 01 |
| `data/output/fire_perimeter.geojson` | Fire perimeter from pipeline 10 |
| `data/output/exposed_buildings.geojson` | Exposed buildings from pipeline 10 |
| `data/assets/buildings.geojson` | All buildings from pipeline 06 |
| `data/grid/ignition_metadata.json` | Ignition point coordinates from pipeline 08 |
| `data/output/consequence_summary.json` | Consequence summary from pipeline 10 |

## Outputs

| File | Description |
|------|-------------|
| web app at port 8000 | Leaflet map served over HTTP |

## Docker image

`wildfire-11_web_ui`

## Run standalone

```bash
docker build -t wildfire-11_web_ui pipelines/11_web_ui
docker run --rm --env-file .env -v $(pwd)/data:/data -p 8001:8000 wildfire-11_web_ui
```

Use host port 8001 (as shown) if port 8000 is already occupied. Then open http://localhost:8001.

Via the Makefile:

```bash
make ui        # production mode — baked image, cache rebuilt at startup
make ui-dev    # dev mode — see below
```

## Development (live reload)

In dev mode, `src/` and `templates/` are bind-mounted into the container and uvicorn runs with `--reload`. Any save to `app.py` or `index.html` takes effect within a second — no rebuild or container restart needed.

```bash
make ui-dev
```

Or directly:

```bash
docker run --rm --env-file .env \
  -v $(pwd)/data:/data \
  -v $(pwd)/pipelines/11_web_ui/src:/app/src \
  -v $(pwd)/pipelines/11_web_ui/templates:/app/templates \
  -p 8001:8000 \
  wildfire-11_web_ui \
  uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

Note: the timestep GeoJSON cache is rebuilt on every reload. With 25 frames this is fast, but expect a brief pause after each `app.py` save.

## Dependencies

Python: `fastapi`, `uvicorn`, `geopandas`, `shapely`, `rasterio`, `numpy`, `pyproj`
System: `libgdal-dev`, `gdal-bin` (python:3.12-slim base image)

## Known limitations

- All GeoJSON endpoints return an empty FeatureCollection if the upstream file does not yet exist
- Fire animation panel is hidden if `data/simulation/grids/` is empty (run pipeline 09 first)
