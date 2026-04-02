# Pipeline 08 — Ignition

Converts a lat/lon ignition point (default: 35.56°N, 83.75°W — a ridge south of Townsend) to a Cell2Fire 1-based cell ID; searches outward for the nearest burnable cell if the target cell is non-burnable.

## Inputs

| File | Description |
|------|-------------|
| `data/grid/grid_metadata.json` | Grid dimensions, origin, and cell size |
| `data/grid/fuels.asc` | Fuel code grid used to validate burnability |

## Outputs

| File | Description |
|------|-------------|
| `data/grid/Ignitions.csv` | Cell2Fire ignition file (`Year,Ncell` with 1-based cell ID) |
| `data/grid/ignition_metadata.json` | Lat/lon, projected coordinates, cell row/col/id, fuel type |

## Docker image

`wildfire-08_ignition`

## Run standalone

```bash
docker build -t wildfire-08_ignition pipelines/08_ignition
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-08_ignition
```

## Dependencies

Python: `pyproj`, `numpy`
System: none beyond python:3.12-slim

## Known limitations

- Default ignition point is fixed; override with `IGNITION_LAT` and `IGNITION_LON` environment variables
- With the default ignition point (ridge south of town), fire does not reach Townsend within the 24-hour simulation window
