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

## Dependencies

Python: `fastapi`, `uvicorn`, `geopandas`, `shapely`
System: none beyond python:3.12-slim

## Known limitations

- Read-only — no user interaction beyond map pan/zoom and layer toggle
- Per-timestep fire spread animation is not implemented; only the final perimeter is displayed
- All GeoJSON endpoints return an empty FeatureCollection if the upstream file does not yet exist
