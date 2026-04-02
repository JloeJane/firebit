# Pipeline 07 — Grid Assembly

Validates raster alignment across all upstream inputs, remaps LANDFIRE FBFM40 fuel codes to Cell2Fire sequential codes (1–40), and writes the ASC grids and CSV files required by the Cell2Fire simulator.

## Inputs

| File | Description |
|------|-------------|
| `data/fuel/fuel_clipped.tif` | FBFM40 fuel codes from pipeline 02 |
| `data/topography/elevation.tif` | Elevation raster from pipeline 03 |
| `data/weather/Weather.csv` | 24-hour weather from pipeline 04 |
| `data/moisture/fuel_moisture.json` | Fuel moisture percentages from pipeline 05 |

## Outputs

| File | Description |
|------|-------------|
| `data/grid/fuels.asc` | ASCII grid of Cell2Fire sequential fuel codes (1–40; 0 = non-burnable) |
| `data/grid/elevation.asc` | ASCII grid of elevation in metres |
| `data/grid/Weather.csv` | Cell2Fire weather stream (copied from pipeline 04) |
| `data/grid/FuelMoistureContent.csv` | Per-fuel-type moisture percentages for Cell2Fire |
| `data/grid/fuel_lookup.csv` | FBFM40 → Cell2Fire sequential code mapping table |
| `data/grid/grid_metadata.json` | Grid dimensions, CRS, cell counts, alignment status |

## Docker image

`wildfire-07_grid_assembly`

## Run standalone

```bash
docker build -t wildfire-07_grid_assembly pipelines/07_grid_assembly
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-07_grid_assembly
```

## Dependencies

Python: `rasterio`, `numpy`, `geopandas`
System: none beyond python:3.12-slim

## Known limitations

- Pipeline hard-fails (exit 1) if any input rasters have mismatched CRS, dimensions, or origin — fix alignment in pipelines 02 and 03 before retrying
- `fuel_lookup.csv` maps FBFM40 → sequential codes; pipeline 09 reverse-maps back to FBFM40 before invoking Cell2Fire
- Fuel codes not present in the FBFM40 lookup are mapped to 0 (non-burnable) with a warning
