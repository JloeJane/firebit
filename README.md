# Wildfire Platform

An open-source wildfire modeling platform that ingests geospatial data, runs the [Cell2Fire](https://github.com/fire2a/C2F-W) simulator, and visualizes fire spread and community consequence through a web map.

**Test AOI:** Tuckaleechee Cove / Great Smoky Mountains National Park boundary, Townsend, TN (~50 sq mi).

---

## Prerequisites

- Docker
- GNU Make
- WSL2 (Windows) or Linux/macOS
- Internet access (pipelines 03 and 06 fetch from external APIs)

---

## Quick start

```bash
make all    # run all 10 data + simulation pipelines
make ui     # launch the web map at http://localhost:8001
```

Then open **http://localhost:8001** in your browser.

> **Note:** `make ui` binds to host port 8001. If port 8001 is also occupied, edit the `ui` target in the Makefile and change `-p 8001:8000` to any free port.

---

## Architecture

Ten containerized pipelines run sequentially on a shared `./data` volume. Each pipeline is a Docker image that reads from and writes to `/data`. The Makefile builds and runs them in dependency order.

```
data/
├── input/        ← pipeline 01 (AOI shapefile)
├── topography/   ← pipeline 03 (elevation, slope, aspect)
├── fuel/         ← pipeline 02 (LANDFIRE FBFM40 raster)
├── weather/      ← pipeline 04 (synthetic weather scenario)
├── moisture/     ← pipeline 05 (fuel moisture estimates)
├── assets/       ← pipeline 06 (buildings, roads, infrastructure)
├── grid/         ← pipeline 07 (assembled Cell2Fire inputs)
│                    pipeline 08 (ignition point)
├── simulation/   ← pipeline 09 (Cell2Fire outputs)
├── consequence/  ← pipeline 10 (exposure analysis)
└── output/       ← pipeline 10 (copies for web UI)
```

Pipeline execution order: **01 → 03 → 02 → 04 → 05 → 06 → 07 → 08 → 09 → 10**

(03 runs before 02 because the fuel pipeline's synthetic fallback requires the elevation raster.)

---

## Pipelines

| # | Name | What it does |
|---|------|-------------|
| 01 | [shapefile_ingestion](pipelines/01_shapefile_ingestion/README.md) | Generates Townsend, TN AOI boundary |
| 02 | [fuel](pipelines/02_fuel/README.md) | Fetches LANDFIRE FBFM40 fuel raster (synthetic fallback) |
| 03 | [topography](pipelines/03_topography/README.md) | Fetches USGS 3DEP elevation; derives slope and aspect |
| 04 | [weather](pipelines/04_weather/README.md) | Generates synthetic fire weather scenario |
| 05 | [fuel_moisture](pipelines/05_fuel_moisture/README.md) | Estimates dead and live fuel moisture |
| 06 | [assets](pipelines/06_assets/README.md) | Fetches buildings and roads via OpenStreetMap |
| 07 | [grid_assembly](pipelines/07_grid_assembly/README.md) | Merges all inputs into Cell2Fire-ready grid |
| 08 | [ignition](pipelines/08_ignition/README.md) | Sets the fire ignition point |
| 09 | [cell2fire](pipelines/09_cell2fire/README.md) | Runs Cell2Fire C2F-W simulation; outputs GeoTIFF + GeoJSON |
| 10 | [consequence](pipelines/10_consequence/README.md) | Overlays fire perimeter with assets; computes exposure |
| 11 | [web_ui](pipelines/11_web_ui/README.md) | Serves Leaflet map with fire results |

---

## Makefile targets

| Target | Description |
|--------|-------------|
| `make all` | Build and run pipelines 01–10 in order |
| `make ui` | Build and launch the web UI at http://localhost:8001 |
| `make test` | Run the full validation test suite (23 checks) |
| `make clean` | Delete all pipeline outputs from `data/` |
| `make run-NN` | Run a single pipeline (e.g. `make run-09`) |
| `make build-NN` | Build a single image (e.g. `make build-07_grid_assembly`) |

---

## Configuration

All pipelines read from `.env`. Key variables:

```bash
# AOI bounding box (WGS84)
BBOX_NORTH=35.65
BBOX_SOUTH=35.55
BBOX_EAST=-83.7
BBOX_WEST=-83.83

# Override ignition point (pipeline 08)
# IGNITION_LAT=35.60
# IGNITION_LON=-83.77
```

---

## Typical results (Townsend AOI, default settings)

- **Area burned:** ~277 ha (~685 acres) in 24 simulation hours
- **Ignition:** ridge south of Townsend at 35.56°N, 83.75°W (TL8 fuel)
- **Structures exposed:** ~1 (fire does not reach town in 24 h with default ignition)
- **Simulation:** Cell2Fire C2F-W, Scott & Burgan mode, seed 123

To move the fire closer to Townsend, set `IGNITION_LAT=35.60 IGNITION_LON=-83.77` in `.env` and re-run from pipeline 08.

---

## Known limitations

- **Fuel data is synthetic** — the LANDFIRE LFPS API is frequently unavailable; the fallback assigns fuel codes by elevation band, not real land cover
- **Weather is synthetic** — based on Nov 28 2016 Gatlinburg conditions; not fetched from a live source
- **Single scenario** — one ignition point, one weather condition, one simulation run
- **24-hour simulation window** — fire may not reach populated areas with the default ignition
- **Population estimates** — 2.3 persons/building proxy; no census data
- **Root-owned simulation files** — Cell2Fire runs as root inside its container; `make clean` uses an Alpine container to remove them

---

## Troubleshooting

### GDAL won't install in Docker
Try these base images in order:
1. `ghcr.io/osgeo/gdal:ubuntu-small-3.9.3` (GDAL pre-installed; add `python3-pip`)
2. `python:3.12-slim` with `apt-get install -y libgdal-dev gdal-bin && pip install GDAL==$(gdal-config --version)`
3. `ubuntu:22.04` with `apt-get install -y python3-pip gdal-bin libgdal-dev python3-gdal`

### Cell2Fire won't compile
Common issues:
- Missing Boost: `apt-get install -y libboost-all-dev`
- Missing make: `apt-get install -y build-essential`
- Wrong directory: the Makefile is in `cell2fire/Cell2FireC/`, not the repo root
- Try the fire2a fork: https://github.com/fire2a/C2F-W

### Cell2Fire runs but nothing burns
Common causes:
- Ignition cell is on a non-burnable fuel type (water, urban, barren)
- Fuel model codes don't match what Cell2Fire expects — pipeline 09 reverse-maps sequential codes back to FBFM40 before invoking the binary
- Weather CSV format is wrong (check column names exactly: `Instance,datetime,WS,WD,FireScenario`)
- Fuel moisture is too high (fire won't spread in wet fuel)
- `Fire-Period-Length` is too short (use `1.0` = 1 hour steps)

### Grid alignment errors
Always derive transforms from the same source:
```python
from rasterio.transform import from_bounds
transform = from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)
```
Where `xmin/ymin/xmax/ymax` come from `aoi_metadata.json` (`bbox_5070`) and `ncols/nrows` from `aoi_metadata.json` (`grid_cols/grid_rows`). Never let individual pipelines compute their own bounds — always reference `aoi_metadata.json` as the canonical source.

### Overpass API timeout or rate limit
- Add a 2-second delay between requests
- Reduce bbox size (fetch a slightly smaller area)
- Use a mirror: `https://overpass.kumi.systems/api/interpreter`
- Pipeline 06 falls back to 300 synthetic buildings automatically if the API returns fewer than 10 results

---

## Future roadmap

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full post-MVP roadmap, including:

- Real LANDFIRE and USGS weather (RAWS/HRRR) integration
- Monte Carlo probabilistic fire spread (N simulations → burn probability maps)
- Census block population data
- Fire spread animation in the web UI
- CWPP-style consequence reports
