# Pipeline 02 — Fuel

Fetches LANDFIRE FBFM40 fuel model raster for the AOI via the LFPS REST API; falls back to a synthetic elevation-band proxy if the API is unavailable.

## Inputs

| File | Description |
|------|-------------|
| `data/input/aoi_metadata.json` | Bounding boxes and grid dimensions |
| `data/topography/elevation.tif` | Required for synthetic fallback — run pipeline 03 first |

## Outputs

| File | Description |
|------|-------------|
| `data/fuel/fuel_clipped.tif` | Fuel codes, EPSG:5070, 30m, aligned to AOI grid |
| `data/fuel/fuel_model_grid.csv` | `row,col,fuel_code` for all valid cells |
| `data/fuel/fuel_metadata.json` | Unique codes, distribution, nodata %, source flag, timestamp |
| `data/fuel/SYNTHETIC_DATA_WARNING.txt` | Present only when synthetic fallback was used |

## Docker image

`wildfire-02_fuel`

## Run standalone

```bash
docker build -t wildfire-02_fuel pipelines/02_fuel
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-02_fuel
```

## Dependencies

Python: `requests`, `rasterio`, `numpy`, `geopandas`
System: none beyond python:3.12-slim

## Known limitations

- The LANDFIRE LFPS API is frequently unavailable; the synthetic fallback assigns FBFM40 codes by elevation band (GR2 < 400 m, TU5 400–800 m, TL3 800–1200 m, TL8 > 1200 m) — not real land cover
- Must run after pipeline 03 if the synthetic fallback may be needed
