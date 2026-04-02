# Pipeline 10 — Consequence Analysis

Spatially overlays the fire perimeter against buildings and infrastructure to compute structures exposed, population at risk, and fire arrival time to the first structure using per-timestep burn grids.

## Inputs

| File | Description |
|------|-------------|
| `data/simulation/fire_perimeter_final.geojson` | Final fire perimeter from pipeline 09 |
| `data/simulation/summary.json` | Simulation summary from pipeline 09 |
| `data/simulation/grids/*.tif` | Per-timestep burn state GeoTIFFs from pipeline 09 |
| `data/assets/buildings.geojson` | Building footprints from pipeline 06 |
| `data/assets/population.geojson` | Building centroids with population estimates from pipeline 06 |
| `data/assets/infrastructure.geojson` | Roads and power lines from pipeline 06 |
| `data/grid/grid_metadata.json` | Grid georeferencing info from pipeline 07 |

## Outputs

| File | Description |
|------|-------------|
| `data/consequence/exposed_buildings.geojson` | Buildings within the burn perimeter |
| `data/consequence/consequence_summary.json` | Full consequence report (structures, population, arrival time) |
| `data/output/consequence_summary.json` | Copy for web UI |
| `data/output/exposed_buildings.geojson` | Copy for web UI |
| `data/output/fire_perimeter.geojson` | Copy for web UI |

## Docker image

`wildfire-10_consequence`

## Run standalone

```bash
docker build -t wildfire-10_consequence pipelines/10_consequence
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-10_consequence
```

## Dependencies

Python: `geopandas`, `rasterio`, `shapely`, `numpy`
System: none beyond python:3.12-slim

## Known limitations

- With the default ignition point (ridge south of Townsend), only approximately 1 structure is exposed within the 24-hour simulation
- Population figures are estimates (2.3 persons/building) inherited from pipeline 06 — no census data
