# Pipeline 01 — Shapefile Ingestion

Generates a Townsend, TN area-of-interest shapefile from a hardcoded bounding box (no user shapefile is accepted yet) and reprojects it to EPSG:5070, producing the AOI metadata consumed by all downstream pipelines.

## Inputs

| File | Description |
|------|-------------|
| none | AOI is generated programmatically from a hardcoded bbox |

## Outputs

| File | Description |
|------|-------------|
| `data/input/townsend_aoi.shp` | AOI polygon in EPSG:4326 |
| `data/input/aoi_reprojected.shp` | AOI reprojected to EPSG:5070 (Conus Albers Equal Area) |
| `data/input/aoi_metadata.json` | Bounding boxes, area, grid dimensions, CRS info, timestamp |

## Docker image

`wildfire-01_shapefile_ingestion`

## Run standalone

```bash
docker build -t wildfire-01_shapefile_ingestion pipelines/01_shapefile_ingestion
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-01_shapefile_ingestion
```

## Dependencies

Python: `geopandas`, `shapely`, `pyproj`
System: none beyond python:3.12-slim

## Known limitations

- AOI is hardcoded for Townsend, TN; user-provided shapefiles are not yet supported
