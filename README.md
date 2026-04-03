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
├── weather/      ← pipeline 04 (HRRR weather; 24-hour hourly rows)
├── moisture/     ← pipeline 05 (fuel moisture estimates)
├── assets/       ← pipeline 06 (buildings, roads, infrastructure)
├── grid/         ← pipeline 07 (assembled Cell2Fire inputs)
│                    pipeline 08 (ignition point)
├── simulation/   ← pipeline 09 (Cell2Fire outputs)
├── consequence/  ← pipeline 10 (exposure analysis)
└── output/       ← pipeline 10 (copies for web UI)
```

Pipeline execution order: **01 → 03 → 02 → 04 → 05 → 06 → 07 → 08 → 09 → 10**

(03 runs before 02 to ensure the AOI raster dimensions are established before fuel reprojection.)

---

## Pipelines

| # | Name | What it does |
|---|------|-------------|
| 01 | [shapefile_ingestion](pipelines/01_shapefile_ingestion/README.md) | Generates Townsend, TN AOI boundary |
| 02 | [fuel](pipelines/02_fuel/README.md) | Fetches LANDFIRE FBFM40 fuel raster via LFPS v2 API |
| 03 | [topography](pipelines/03_topography/README.md) | Fetches USGS 3DEP elevation; derives slope and aspect |
| 04 | [weather](pipelines/04_weather/README.md) | Fetches real NOAA HRRR analysis via herbie; IEM ASOS fallback |
| 05 | [fuel_moisture](pipelines/05_fuel_moisture/README.md) | Dead moisture from real weather via Nelson (1984) EMC; live moisture hardcoded |
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
| `make all` | Build and run pipelines 01–10 in order (pipeline 04 fetches live HRRR data) |
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

- **Data vintage does not track simulation date** — the platform fetches the most recent available data for each source regardless of the scenario date. For example, the default scenario simulates the 2016 Gatlinburg fire using 2022 LANDFIRE fuel data. For accurate historical reconstruction, every data source should be pinned to the year of the event: fuel (LANDFIRE LF{YYYY}), weather (HRRR archive — already date-specific), topography (3DEP is largely static), and assets (OSM historical snapshots are not available). A future improvement would accept a `SIMULATION_YEAR` variable and request the matching LANDFIRE version from the LFPS API.
- **Live fuel moisture is climatological** — dead fuel moisture (1hr/10hr/100hr) is derived from real HRRR weather via Nelson (1984) EMC. Live fuel moisture is fixed at 30% herb / 60% woody, which is defensible for a late-November cured-vegetation scenario but wrong for spring or summer dates. A future improvement would pull live moisture from WFAS NFMD RAWS observations.
- **Weather is a single centroid point** — HRRR analysis is extracted at the AOI centroid (35.60°N, 83.77°W) at 3 km resolution. The model does not capture sub-km ridge/valley wind channeling in the Smokies. All 24 weather rows use the same spatial point; terrain-driven wind variation across the AOI is not represented.
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
- Pipeline 06 uses whatever OSM returns — if buildings are 0, consequence analysis will report 0 exposed structures

---

## Future roadmap

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for full prioritization. Summary:

**Next (Phase 6B.5):**
- Multi-scenario comparison UI (side-by-side Leaflet maps; baseline / high-wind / wind-shift scenarios pre-baked)

**Data quality:**
- `SIMULATION_YEAR` env variable — pin LANDFIRE version, OSM snapshot, and other sources to the event year
- Live fuel moisture from WFAS NFMD RAWS observations (currently climatological estimate)
- Spatially distributed weather (per-cell wind from terrain model, not single centroid point)

**Later:** Census population, evacuation time modeling, Voronoi grid, orchestration upgrade

**Post-post MVP:** Monte Carlo probabilistic burn maps
