# Pipeline 09 — Cell2Fire Simulation

Runs the fire2a/C2F-W Cell2Fire simulator in Scott & Burgan mode on the assembled grid from pipeline 07, then post-processes raw CSV outputs to GeoTIFF timestep grids, a burn-scar raster, and a GeoJSON fire perimeter.

## Inputs

| File | Description |
|------|-------------|
| `data/grid/fuels.asc` | Sequential fuel code grid from pipeline 07 |
| `data/grid/elevation.asc` | Elevation grid from pipeline 07 |
| `data/grid/Weather.csv` | 24-hour weather from pipeline 07 |
| `data/grid/Ignitions.csv` | Ignition cell from pipeline 08 |
| `data/grid/fuel_lookup.csv` | Sequential → FBFM40 reverse mapping |

## Outputs

| File | Description |
|------|-------------|
| `data/simulation/burn_scar.tif` | Final burn scar as GeoTIFF |
| `data/simulation/fire_perimeter_final.geojson` | Vectorised fire perimeter |
| `data/simulation/summary.json` | Simulation summary (cells burned, area, duration) |
| `data/simulation/grids/grid_t000..024.tif` | Per-timestep burn state GeoTIFFs |
| `data/simulation/Grids/` | Raw Cell2Fire ForestGrid CSV outputs |
| `data/simulation/Messages/` | Cell2Fire propagation message logs |

## Docker image

`wildfire-09_cell2fire`

## Run standalone

```bash
docker build -t wildfire-09_cell2fire pipelines/09_cell2fire
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-09_cell2fire
```

Pass `--test` to run a synthetic 50×50 validation grid without requiring upstream data:

```bash
docker run --rm wildfire-09_cell2fire --test
```

## Dependencies

Python: `rasterio`, `numpy`, `geopandas`, `shapely`
System: `g++`, `make`, `libboost-dev`, `libtiff-dev` (ubuntu:22.04 base image — includes C++ build)

## Known limitations

- Simulation runs 24 hours only
- Output files are owned by root because the container runs as root; use `make clean` to remove them
- Fuel codes in `fuels.asc` are sequential (pipeline 07 format); this pipeline reverse-maps them to FBFM40 before invoking Cell2Fire
