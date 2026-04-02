# Pipeline 06 — Assets

Fetches buildings and roads within the AOI from OpenStreetMap via the Overpass API; falls back to 300 synthetic buildings concentrated around Townsend valley if the API is unavailable or returns fewer than 10 buildings.

## Inputs

| File | Description |
|------|-------------|
| `data/input/aoi_metadata.json` | Bounding box used to query Overpass |

## Outputs

| File | Description |
|------|-------------|
| `data/assets/buildings.geojson` | Building footprints in EPSG:5070 |
| `data/assets/population.geojson` | Building centroids with estimated population |
| `data/assets/infrastructure.geojson` | Roads and power lines |
| `data/assets/assets_metadata.json` | Building count, source flag, timestamp |

## Docker image

`wildfire-06_assets`

## Run standalone

```bash
docker build -t wildfire-06_assets pipelines/06_assets
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-06_assets
```

## Dependencies

Python: `requests`, `geopandas`, `shapely`
System: none beyond python:3.12-slim

## Known limitations

- Population is estimated at 2.3 persons per building — no census data is used
- Buildings may be flagged `synthetic_mvp` in metadata if the Overpass API times out
- No animation or dynamic querying — the AOI is fixed to Townsend, TN
