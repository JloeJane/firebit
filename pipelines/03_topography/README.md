# Pipeline 03 — Topography

Fetches USGS 3DEP 1/3 arc-second elevation for the AOI via the National Map API, reprojects to EPSG:5070 at 30 m resolution, and derives slope and aspect rasters.

## Inputs

| File | Description |
|------|-------------|
| `data/input/aoi_metadata.json` | Bounding boxes (EPSG:4326 + EPSG:5070) and grid dimensions |

## Outputs

| File | Description |
|------|-------------|
| `data/topography/elevation_raw.tif` | Raw GeoTIFF from USGS 3DEP in EPSG:4326 |
| `data/topography/elevation.tif` | Elevation (m), EPSG:5070, 30m, aligned to AOI grid |
| `data/topography/slope.tif` | Slope in degrees (0–90), same grid |
| `data/topography/aspect.tif` | Aspect in degrees from north (0–360), same grid |
| `data/topography/topo_metadata.json` | Elevation range, mean slope, grid info, timestamp |

## Docker image

`wildfire-03_topography`

## Run standalone

```bash
docker build -t wildfire-03_topography pipelines/03_topography
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-03_topography
```

## Dependencies

Python: `requests`, `rasterio`, `numpy`, `scipy`
System: none beyond python:3.12-slim

## Known limitations

- Requires internet access to `elevation.nationalmap.gov` at runtime
