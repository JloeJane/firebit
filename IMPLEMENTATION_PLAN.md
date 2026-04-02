# Wildfire Modeling Platform — Implementation Plan

## Project Overview

An open-source wildfire modeling platform that ingests a user-provided shapefile (area of interest), fetches public geospatial data, and runs Cell2Fire simulations to model fire spread and community consequence. Built as a set of containerized pipelines orchestrated via Makefile on a shared data volume.

**MVP Scope:** Single-scenario mode (one shapefile + one ignition point + one weather condition → fire spread map + consequence report). Designed to scale to Monte Carlo batch mode.

**Test AOI:** Tuckaleechee Cove to Great Smoky Mountains National Park boundary (~50 sq mi), centered near Townsend, TN.

**Bounding Box (approx):**
- North: 35.65° / South: 35.52° / East: -83.65° / West: -83.86°
- Grid at 30m resolution: ~1,400 × 1,400 cells (~2M cells)

---

## Repository Structure

```
wildfire-platform/
├── Makefile                          # Top-level orchestrator
├── IMPLEMENTATION_PLAN.md            # This file
├── docker-compose.yml                # Optional: for future parallel runs
├── .env                              # Shared config (AOI bbox, resolution, paths)
├── data/                             # Shared data volume (mounted by all containers)
│   ├── input/                        # User-provided shapefiles
│   ├── fuel/                         # Fuel pipeline outputs
│   ├── topography/                   # Topography pipeline outputs
│   ├── weather/                      # Weather pipeline outputs
│   ├── moisture/                     # Fuel moisture pipeline outputs
│   ├── assets/                       # Assets pipeline outputs
│   ├── grid/                         # Assembled Cell2Fire input
│   ├── simulation/                   # Cell2Fire outputs
│   ├── consequence/                  # Consequence analysis outputs
│   └── output/                       # Final deliverables (GeoJSON, reports)
├── pipelines/
│   ├── 01_shapefile_ingestion/
│   │   ├── README.md                 # Auto-generated pipeline docs
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── ingest.py
│   ├── 02_fuel/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── fetch_fuel.py
│   ├── 03_topography/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── fetch_topo.py
│   ├── 04_weather/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── fetch_weather.py
│   ├── 05_fuel_moisture/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── calc_moisture.py
│   ├── 06_assets/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── fetch_assets.py
│   ├── 07_grid_assembly/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── assemble_grid.py
│   ├── 08_ignition/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── set_ignition.py
│   ├── 09_cell2fire/
│   │   ├── README.md
│   │   ├── Dockerfile            # Includes C++ build of Cell2Fire
│   │   └── src/
│   │       └── run_simulation.py
│   ├── 10_consequence/
│   │   ├── README.md
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       └── analyze.py
│   └── 11_web_ui/
│       ├── README.md
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── src/
│       │   └── app.py            # FastAPI + Leaflet
│       └── templates/
│           └── index.html
└── tests/
    ├── test_shapefile.py
    ├── test_fuel.py
    └── ...
```

---

## Shared Configuration (.env)

All pipelines read from a common `.env` file mounted into each container. This is the single source of truth for AOI parameters, resolution, and file paths.

```bash
# .env
AOI_SHAPEFILE=data/input/townsend_aoi.shp
TARGET_CRS=EPSG:5070
GRID_RESOLUTION=30
BBOX_NORTH=35.65
BBOX_SOUTH=35.52
BBOX_EAST=-83.65
BBOX_WEST=-83.86

# Data directories (relative to mount point)
DATA_DIR=/data
FUEL_DIR=/data/fuel
TOPO_DIR=/data/topography
WEATHER_DIR=/data/weather
MOISTURE_DIR=/data/moisture
ASSETS_DIR=/data/assets
GRID_DIR=/data/grid
SIM_DIR=/data/simulation
CONSEQUENCE_DIR=/data/consequence
OUTPUT_DIR=/data/output
```

---

## Makefile (Top-Level Orchestrator)

The Makefile builds and runs each pipeline container sequentially. Each target depends on the previous pipeline's completion. All containers mount `./data` as `/data`.

```makefile
.PHONY: all clean build run-01 run-02 run-03 run-04 run-05 run-06 run-07 run-08 run-09 run-10 ui

DOCKER_RUN = docker run --rm --env-file .env -v $(PWD)/data:/data

all: run-01 run-02 run-03 run-04 run-05 run-06 run-07 run-08 run-09 run-10
	@echo "=== Full pipeline complete ==="

build-%:
	docker build -t wildfire-$* pipelines/$*

run-01: build-01_shapefile_ingestion
	@echo "=== Step 1: Shapefile Ingestion ==="
	$(DOCKER_RUN) wildfire-01_shapefile_ingestion

run-02: build-02_fuel
	@echo "=== Step 2: Fuel Pipeline ==="
	$(DOCKER_RUN) wildfire-02_fuel

run-03: build-03_topography
	@echo "=== Step 3: Topography Pipeline ==="
	$(DOCKER_RUN) wildfire-03_topography

run-04: build-04_weather
	@echo "=== Step 4: Weather Pipeline ==="
	$(DOCKER_RUN) wildfire-04_weather

run-05: build-05_fuel_moisture
	@echo "=== Step 5: Fuel Moisture Pipeline ==="
	$(DOCKER_RUN) wildfire-05_fuel_moisture

run-06: build-06_assets
	@echo "=== Step 6: Assets Pipeline ==="
	$(DOCKER_RUN) wildfire-06_assets

run-07: build-07_grid_assembly
	@echo "=== Step 7: Grid Assembly ==="
	$(DOCKER_RUN) wildfire-07_grid_assembly

run-08: build-08_ignition
	@echo "=== Step 8: Ignition ==="
	$(DOCKER_RUN) wildfire-08_ignition

run-09: build-09_cell2fire
	@echo "=== Step 9: Cell2Fire Simulation ==="
	$(DOCKER_RUN) wildfire-09_cell2fire

run-10: build-10_consequence
	@echo "=== Step 10: Consequence Analysis ==="
	$(DOCKER_RUN) wildfire-10_consequence

ui: build-11_web_ui
	@echo "=== Launching Web UI on http://localhost:8000 ==="
	docker run --rm --env-file .env -v $(PWD)/data:/data -p 8000:8000 wildfire-11_web_ui

clean:
	rm -rf data/fuel/* data/topography/* data/weather/* data/moisture/*
	rm -rf data/assets/* data/grid/* data/simulation/* data/consequence/* data/output/*
```

---

## Pipeline Implementation Steps

Each pipeline section below describes: what it does, inputs/outputs, implementation details, the Dockerfile, and what the auto-generated README.md should contain.

---

### Step 1: Shapefile Ingestion (`01_shapefile_ingestion`)

**Purpose:** Accept a user-provided shapefile, validate it, reproject to a common CRS, compute the bounding box, and write a standardized AOI file that all downstream pipelines consume.

**Inputs:**
- User shapefile placed in `data/input/` (`.shp` + `.shx` + `.dbf` + `.prj`)
- For MVP: we generate a test shapefile for the Townsend AOI

**Outputs:**
- `data/input/aoi_reprojected.shp` — AOI polygon in EPSG:5070 (Conus Albers)
- `data/input/aoi_metadata.json` — bounding box, area, CRS, cell count estimate

**Implementation:**
1. If no shapefile exists, generate the Townsend test AOI programmatically using shapely (polygon covering Tuckaleechee Cove to park boundary)
2. Read shapefile with geopandas
3. Validate geometry (is it a polygon? is it valid? fix with `.buffer(0)` if needed)
4. Reproject to EPSG:5070
5. Compute bounding box in both EPSG:5070 (for grid creation) and EPSG:4326 (for data fetches that need lat/lon)
6. Estimate grid dimensions at 30m resolution
7. Write reprojected shapefile and metadata JSON

**Key dependencies:** `geopandas`, `shapely`, `pyproj`, `fiona`

**Dockerfile base:** `python:3.12-slim` + GDAL system libs

**README.md auto-documents:**
- Generated AOI coordinates and area
- CRS used
- Grid dimensions
- Timestamp of generation

**⚠️ DEV NOTE:** The test AOI is hardcoded for Townsend. For production, this pipeline should accept any arbitrary shapefile and dynamically compute everything. The `.env` bbox values should be WRITTEN by this pipeline, not read — they exist as fallbacks only.

---

### Step 2: Fuel Pipeline (`02_fuel`)

**Purpose:** Fetch LANDFIRE FBFM40 (Scott & Burgan 40 fuel model) raster data for the AOI, clip to boundary, and produce a fuel model grid.

**Inputs:**
- `data/input/aoi_metadata.json` (bounding box in EPSG:4326 for LANDFIRE API)
- `data/input/aoi_reprojected.shp` (for clipping)

**Outputs:**
- `data/fuel/fuel_raw.tif` — raw LANDFIRE tile(s)
- `data/fuel/fuel_clipped.tif` — clipped and reprojected to EPSG:5070 at 30m
- `data/fuel/fuel_model_grid.csv` — cell ID × fuel model code lookup
- `data/fuel/fuel_metadata.json` — fuel types present, distribution stats

**Implementation:**
1. Read AOI metadata for bbox
2. Download LANDFIRE FBFM40 data via LANDFIRE Product Service (LPS) REST API or direct GeoTIFF download from https://landfire.gov/
3. If API is unavailable/slow, fall back to pre-downloaded national tiles and clip locally
4. Reproject to EPSG:5070 using rasterio
5. Clip to AOI boundary using rasterio.mask
6. Resample to exactly 30m resolution if needed (nearest neighbor — fuel codes are categorical)
7. Export fuel model code per cell as CSV (row, col, fuel_code)
8. Generate metadata: unique fuel types present, % coverage per type, nodata percentage

**Key dependencies:** `rasterio`, `geopandas`, `requests`, `numpy`

**Dockerfile base:** `python:3.12-slim` + `libgdal-dev`

**⚠️ DEV NOTE (FUTURE):** LANDFIRE updates every 2 years. For operational use, cache tiles and check timestamps. The fuel model codes map to Rothermel parameters via the Scott & Burgan lookup tables — that translation happens in grid assembly (Step 7), not here. This pipeline just delivers the raw fuel codes.

**⚠️ DEV NOTE (FUTURE):** For higher accuracy, consider ingesting local fuel survey data or custom fuel maps if available from TN Division of Forestry. These would override LANDFIRE in areas where local data exists.

---

### Step 3: Topography Pipeline (`03_topography`)

**Purpose:** Fetch USGS 3DEP elevation data, derive slope and aspect, and produce topographic grids aligned to the fuel grid.

**Inputs:**
- `data/input/aoi_metadata.json`
- `data/input/aoi_reprojected.shp`

**Outputs:**
- `data/topography/elevation.tif` — DEM in EPSG:5070 at 30m
- `data/topography/slope.tif` — slope in degrees
- `data/topography/aspect.tif` — aspect in degrees from north
- `data/topography/topo_metadata.json` — elevation range, mean slope, etc.

**Implementation:**
1. Read AOI metadata for bbox in EPSG:4326
2. Fetch elevation data from USGS 3DEP via the National Map API (`/3DEPElevation/ImageServer/exportImage`) or the `py3dep` Python package
3. Reproject to EPSG:5070 at 30m resolution (bilinear interpolation — elevation is continuous)
4. Clip to AOI
5. Derive slope using `numpy` gradient calculation or `richdem` library:
   - `slope = arctan(sqrt(dz/dx² + dz/dy²))` converted to degrees
6. Derive aspect using `numpy`:
   - `aspect = arctan2(-dz/dy, dz/dx)` converted to degrees from north (0-360)
7. Validate alignment with fuel grid (same origin, resolution, dimensions)
8. Write metadata: min/max/mean elevation, slope distribution, dominant aspects

**Key dependencies:** `rasterio`, `numpy`, `py3dep` or `requests`, `geopandas`

**Dockerfile base:** `python:3.12-slim` + `libgdal-dev`

**⚠️ DEV NOTE:** Grid alignment with the fuel raster is CRITICAL. Use `rasterio.warp.reproject` with the fuel raster as the template (match transform, width, height exactly). Off-by-one pixel errors here will cause Cell2Fire to crash or produce garbage.

---

### Step 4: Weather Pipeline (`04_weather`)

**Purpose:** Provide weather scenario inputs (wind speed, wind direction, temperature, relative humidity) for the simulation.

**Inputs:**
- `data/input/aoi_metadata.json`

**Outputs:**
- `data/weather/weather_scenario.json` — single weather scenario
- `data/weather/weather_grid.csv` — Cell2Fire-compatible weather stream file (if spatially varying)
- `data/weather/weather_metadata.json` — source description, timestamp

**Implementation (MVP — synthetic data):**
1. Generate a plausible fire weather scenario for the Townsend area:
   ```json
   {
     "wind_speed_kmh": 20,
     "wind_direction_deg": 225,
     "temperature_c": 32,
     "relative_humidity_pct": 15,
     "scenario_name": "hot_dry_southwest_wind",
     "source": "synthetic_mvp",
     "notes": "Represents a typical late-fall fire weather day similar to Nov 2016 conditions"
   }
   ```
2. Write Cell2Fire weather stream format (CSV with hourly rows if needed — MVP uses constant conditions)
3. Write metadata documenting that this is synthetic

**Key dependencies:** `json`, `csv` (stdlib only for MVP)

**Dockerfile base:** `python:3.12-slim` (no GDAL needed for MVP)

**⚠️ DEV NOTE (CRITICAL — IMMEDIATE POST-MVP):** This is the first pipeline to upgrade after POC. Real weather must come from:
- **Historical scenario mode:** gridMET or RAWS station data. Fetch from https://www.raws.dri.edu/ or https://www.climatologylab.org/gridmet.html for the AOI. Build distributions of fire weather days to sample from.
- **Forecast mode:** NOAA HRRR (3km, hourly) or RTMA. Use `herbie` Python package to fetch GRIB2 files, extract wind/temp/RH fields, reproject and clip to AOI.
- **Real-time mode:** Stream from RAWS API or NOAA web services.

The weather format must match Cell2Fire's expected input: CSV with columns `Instance,datetime,WS,WD,TMP,RH` where WS is km/h and WD is degrees.

---

### Step 5: Fuel Moisture Pipeline (`05_fuel_moisture`)

**Purpose:** Estimate dead and live fuel moisture content values for the simulation scenario.

**Inputs:**
- `data/weather/weather_scenario.json`
- `data/fuel/fuel_metadata.json` (to know which fuel types need moisture values)

**Outputs:**
- `data/moisture/fuel_moisture.json` — moisture values by fuel class
- `data/moisture/moisture_metadata.json`

**Implementation (MVP — derived from weather scenario):**
1. Read weather scenario (temp, RH)
2. Estimate dead fuel moisture using simplified Nelson model or lookup tables:
   - 1-hour fuels: approximate from temperature and RH using equilibrium moisture content (EMC) equations
   - 10-hour fuels: EMC + lag factor
   - 100-hour fuels: EMC + larger lag
3. Set live fuel moisture based on season (for MVP, hardcode late-fall values):
   - Live herbaceous: 30% (cured)
   - Live woody: 60%
4. Output format:
   ```json
   {
     "dead_1hr_pct": 4,
     "dead_10hr_pct": 6,
     "dead_100hr_pct": 10,
     "live_herb_pct": 30,
     "live_woody_pct": 60,
     "source": "derived_from_weather_mvp"
   }
   ```

**Key dependencies:** `numpy` (for EMC calculation), `json`

**Dockerfile base:** `python:3.12-slim`

**⚠️ DEV NOTE (FUTURE):** For real operations:
- Dead fuel moisture: use the National Fuel Moisture Database (NFMD) station observations nearest to AOI, or run the full Nelson dead fuel moisture model with hourly weather
- Live fuel moisture: use MODIS/VIIRS NDVI as a proxy — greenness correlates with live moisture. The `lfmc` Python package provides gridded estimates.
- Consider spatially varying moisture across the AOI (north vs south facing slopes dry differently)

---

### Step 6: Assets & Exposure Pipeline (`06_assets`)

**Purpose:** Fetch building footprints, population data, and critical infrastructure within the AOI for consequence analysis.

**Inputs:**
- `data/input/aoi_metadata.json`
- `data/input/aoi_reprojected.shp`

**Outputs:**
- `data/assets/buildings.geojson` — building footprints within AOI
- `data/assets/population_grid.tif` — population density raster aligned to simulation grid
- `data/assets/infrastructure.geojson` — roads, power lines, etc.
- `data/assets/assets_metadata.json` — total building count, population estimate

**Implementation:**
1. **Buildings:** Download Microsoft Building Footprints for Tennessee from GitHub releases (GeoJSON format). Filter to AOI bbox, clip to boundary. If too slow, use OpenStreetMap Overpass API as fallback.
2. **Population:** Fetch Census block-level population from Census Bureau TIGERweb API or use gridded WorldPop data. Rasterize to 30m grid aligned with fuel/topo.
3. **Infrastructure:** Query OpenStreetMap Overpass API for roads (`highway=*`), power lines (`power=line`), and other critical features within AOI bbox.
4. Reproject all vector data to EPSG:5070
5. Write metadata: total buildings, estimated population, infrastructure counts

**Key dependencies:** `geopandas`, `requests`, `rasterio`, `shapely`, `osmnx` (for OSM data)

**Dockerfile base:** `python:3.12-slim` + `libgdal-dev`

**⚠️ DEV NOTE:** Microsoft Building Footprints for Tennessee is a ~500MB download but only needs to happen once. Cache the state file in `data/assets/cache/` and filter from cache on subsequent runs. For production, use a proper spatial database (PostGIS) instead of file-based filtering.

---

### Step 7: Grid Assembly (`07_grid_assembly`)

**Purpose:** Merge all pipeline outputs into a single Cell2Fire-compatible input grid. This is the critical integration point where alignment issues surface.

**Inputs:**
- `data/fuel/fuel_clipped.tif`
- `data/topography/elevation.tif`
- `data/topography/slope.tif`
- `data/topography/aspect.tif`
- `data/weather/weather_scenario.json`
- `data/moisture/fuel_moisture.json`

**Outputs:**
- `data/grid/fuels.asc` — ASCII grid of fuel model codes (Cell2Fire input)
- `data/grid/elevation.asc` — ASCII grid of elevation values
- `data/grid/slope.asc` — ASCII grid of slope values (if Cell2Fire variant supports it)
- `data/grid/grid_metadata.json` — dimensions, resolution, origin, CRS, cell count
- `data/grid/Weather.csv` — Cell2Fire weather stream file
- `data/grid/fuel_moisture.csv` — fuel moisture content file

**Implementation:**
1. Load all rasters and verify alignment:
   - Same CRS (EPSG:5070)
   - Same resolution (30m)
   - Same dimensions (rows × cols)
   - Same origin (upper-left corner coordinates)
   - If any mismatch: reproject/resample the misaligned raster to match the fuel grid as reference
2. Convert fuel raster to ASCII grid format (.asc) that Cell2Fire expects:
   ```
   ncols 1400
   nrows 1400
   xllcorner <x>
   yllcorner <y>
   cellsize 30
   NODATA_value -9999
   <row data...>
   ```
3. Convert elevation to ASCII grid
4. Map fuel model codes to Cell2Fire fuel type IDs:
   - Cell2Fire uses Scott & Burgan fuel model numbers directly if configured for Rothermel/US mode
   - Generate the fuel data lookup file mapping code → Rothermel parameters (rate of spread coefficients, etc.)
5. Format weather into Cell2Fire Weather.csv:
   ```csv
   Instance,datetime,WS,WD,TMP,RH
   1,2026-01-01_00:00,20,225,32,15
   ```
6. Format fuel moisture into Cell2Fire-compatible CSV
7. Write grid metadata

**Key dependencies:** `rasterio`, `numpy`, `pandas`

**Dockerfile base:** `python:3.12-slim` + `libgdal-dev`

**⚠️ DEV NOTE (CRITICAL):** This is where most bugs will live. Common failure modes:
- Off-by-one pixel alignment between fuel and topo grids
- NODATA cells in one layer but not another (need consistent masking)
- Fuel codes that Cell2Fire doesn't recognize (map LANDFIRE codes to Cell2Fire's expected codes)
- Weather CSV format is very particular — wrong column order or units will silently produce garbage

**⚠️ DEV NOTE:** Cell2Fire was originally built for the Canadian FBP system. For US fuel models (Scott & Burgan / Rothermel), you need the Cell2Fire fork that supports US fuel models, or you need to provide the Rothermel parameter lookup table. Check https://github.com/cell2fire/Cell2Fire and look for the `--final-grid` and `--fuel-model` flags. The `cell2fire/Cell2FireC` C++ source may need modification.

---

### Step 8: Ignition Service (`08_ignition`)

**Purpose:** Define the fire ignition point(s) for the simulation.

**Inputs:**
- `data/input/aoi_metadata.json`
- `data/grid/grid_metadata.json`

**Outputs:**
- `data/grid/Ignitions.csv` — Cell2Fire ignition file (cell IDs to ignite)
- `data/grid/ignition_metadata.json` — lat/lon of ignition point, cell ID, rationale

**Implementation (MVP):**
1. Accept ignition point as either:
   - Environment variable (`IGNITION_LAT`, `IGNITION_LON`) for user-specified
   - Default: place ignition on a ridge south of Townsend (simulating fire spreading from park toward town), approximately 35.56°N, -83.75°W
2. Convert lat/lon to EPSG:5070
3. Map to grid cell ID: `cell_id = row * ncols + col`
4. Write Cell2Fire Ignitions.csv:
   ```csv
   Year,Ncell
   1,<cell_id>
   ```
5. Write metadata with the point location and which fuel type it falls in

**Key dependencies:** `pyproj`, `rasterio` (for coordinate → cell mapping), `json`

**Dockerfile base:** `python:3.12-slim`

**⚠️ DEV NOTE (FUTURE):** For probabilistic mode, this service should:
- Sample ignition points from the FPA FOD (Fire Program Analysis Fire-Occurrence Database) historical ignition density
- Weight by fuel type and current weather conditions
- Generate N ignition scenarios for Monte Carlo batches

---

### Step 9: Cell2Fire Simulation (`09_cell2fire`)

**Purpose:** Run the Cell2Fire fire spread simulator on the assembled grid.

**Inputs:**
- `data/grid/fuels.asc`
- `data/grid/elevation.asc`
- `data/grid/Weather.csv`
- `data/grid/fuel_moisture.csv` (if supported by the Cell2Fire variant)
- `data/grid/Ignitions.csv`

**Outputs:**
- `data/simulation/Grids/` — per-timestep fire spread grids (which cells burned at each hour)
- `data/simulation/Messages/` — cell-to-cell fire propagation log
- `data/simulation/summary.json` — total area burned, simulation duration, ROS stats
- `data/simulation/fire_perimeter_final.geojson` — final burn scar as vector polygon

**Implementation:**
1. Clone and build Cell2Fire C++ from source inside Docker:
   ```dockerfile
   FROM ubuntu:22.04
   RUN apt-get update && apt-get install -y g++ make python3 python3-pip git libboost-all-dev
   RUN git clone https://github.com/cell2fire/Cell2Fire.git /opt/cell2fire
   WORKDIR /opt/cell2fire/cell2fire/Cell2FireC
   RUN make
   ```
2. Python wrapper script that:
   - Reads grid metadata to construct Cell2Fire command-line arguments
   - Executes Cell2Fire:
     ```bash
     ./Cell2FireC \
       --input-instance-folder /data/grid/ \
       --output-folder /data/simulation/ \
       --ignitions \
       --sim-years 1 \
       --nsims 1 \
       --grids \
       --final-grid \
       --weather rows \
       --nweathers 1 \
       --Fire-Period-Length 1.0 \
       --output-messages \
       --ROS-CV 0.0 \
       --seed 123
     ```
   - Parses Cell2Fire output grids into GeoTIFF format using grid metadata (origin, resolution, CRS)
   - Converts final burn scar to GeoJSON polygon
   - Computes summary statistics: total cells burned, total area (ha), max ROS observed
3. Write outputs

**Key dependencies:** Cell2Fire C++ binary, `numpy`, `rasterio`, `shapely`, `geopandas` (for GeoJSON conversion)

**Dockerfile base:** `ubuntu:22.04` (needs C++ toolchain)

**⚠️ DEV NOTE (CRITICAL):** Cell2Fire has multiple forks and versions. The main repository (`cell2fire/Cell2Fire`) was built for the Canadian FBP system. For US Scott & Burgan fuel models, you may need:
- The `fire2a/fire2a-lib` fork which has better US fuel model support
- OR: provide a custom fuel parameter file that maps FBFM40 codes to Rothermel spread model parameters
- Test with a simple 100×100 synthetic grid first before running the full 1400×1400 AOI

**⚠️ DEV NOTE:** Cell2Fire output grids are numbered sequentially (Grid1.csv, Grid2.csv...). Each is a matrix of 0/1 (unburned/burned) or fire arrival time. The wrapper must georeference these using the grid metadata.

---

### Step 10: Consequence Analysis (`10_consequence`)

**Purpose:** Overlay fire spread results with asset data to quantify impact.

**Inputs:**
- `data/simulation/fire_perimeter_final.geojson`
- `data/simulation/Grids/` (for time-of-arrival analysis)
- `data/assets/buildings.geojson`
- `data/assets/population_grid.tif`
- `data/assets/infrastructure.geojson`

**Outputs:**
- `data/consequence/exposed_buildings.geojson` — buildings within burn perimeter
- `data/consequence/consequence_summary.json`:
  ```json
  {
    "total_area_burned_ha": 1200,
    "total_area_burned_acres": 2965,
    "structures_exposed": 147,
    "estimated_population_at_risk": 892,
    "infrastructure_exposed": {
      "road_segments": 23,
      "power_line_segments": 8
    },
    "fire_arrival_to_first_structure_hrs": 3.2
  }
  ```
- `data/consequence/burn_probability.tif` — (for future Monte Carlo: probability each cell burns)
- `data/output/consequence_report.json` — final formatted report

**Implementation:**
1. Load final fire perimeter polygon
2. Spatial join: buildings within or intersecting burn perimeter
3. For each exposed building, calculate fire arrival time (from time-of-arrival grid)
4. Sum population within burned cells from population grid
5. Intersect infrastructure lines with burn perimeter
6. Compute summary statistics
7. Write all outputs

**Key dependencies:** `geopandas`, `rasterio`, `shapely`, `numpy`

**Dockerfile base:** `python:3.12-slim` + `libgdal-dev`

---

### Step 11: Web UI (`11_web_ui`)

**Purpose:** Serve a browser-based map showing the AOI, fire spread, and consequence results.

**Inputs:**
- All files in `data/output/` and `data/consequence/`
- `data/input/aoi_reprojected.shp`
- `data/simulation/fire_perimeter_final.geojson`

**Outputs:**
- Web application at `http://localhost:8000`

**Implementation:**
1. FastAPI backend:
   - `GET /` — serves Leaflet map HTML
   - `GET /api/aoi` — returns AOI polygon as GeoJSON
   - `GET /api/fire-perimeter` — returns fire perimeter as GeoJSON
   - `GET /api/buildings/exposed` — returns exposed buildings as GeoJSON
   - `GET /api/summary` — returns consequence summary JSON
   - `GET /api/grids/{timestep}` — returns fire spread grid at timestep as GeoJSON (for animation)
2. Leaflet frontend:
   - OpenStreetMap or USGS topo basemap
   - Layers: AOI boundary (blue outline), fire perimeter (red fill, semi-transparent), exposed buildings (orange markers), ignition point (flame icon)
   - Sidebar: consequence summary stats
   - Optional: time slider to animate fire spread across timesteps
3. All data read from the shared `/data` volume — no database needed

**Key dependencies:** `fastapi`, `uvicorn`, `geopandas`, `shapely`

**Dockerfile base:** `python:3.12-slim`

---

## Implementation Order & Milestones

### Phase 1: Foundation (Estimated: 2-3 days)
- [ ] Create repo structure and Makefile
- [ ] Implement Step 1 (Shapefile Ingestion) — generate Townsend test AOI
- [ ] Implement Step 3 (Topography) — simplest real data fetch
- [ ] Verify Docker build/run cycle works end-to-end

### Phase 2: Core Data (Estimated: 3-4 days)
- [ ] Implement Step 2 (Fuel) — LANDFIRE data fetch and processing
- [ ] Implement Step 4 (Weather) — synthetic scenario
- [ ] Implement Step 5 (Fuel Moisture) — derived from weather
- [ ] Implement Step 7 (Grid Assembly) — merge and validate alignment
- [ ] Test with a small 100×100 sub-grid before full AOI

### Phase 3: Simulation (Estimated: 3-4 days)
- [ ] Implement Step 9 (Cell2Fire) — build C++ in Docker, test on synthetic grid
- [ ] Implement Step 8 (Ignition) — set test ignition point
- [ ] Run first successful simulation on Townsend AOI
- [ ] Debug grid alignment / fuel model compatibility issues (expect this to take time)

### Phase 4: Output & Visualization (Estimated: 2-3 days)
- [ ] Implement Step 6 (Assets) — building footprints and population
- [ ] Implement Step 10 (Consequence) — overlay and statistics
- [ ] Implement Step 11 (Web UI) — Leaflet map with all layers
- [ ] End-to-end run: `make all && make ui`

### Phase 5: Polish & Documentation (Estimated: 1-2 days)
- [ ] Auto-generate README.md in each pipeline directory
- [ ] Error handling and logging for all pipelines
- [ ] Test with different ignition points
- [ ] Document known limitations and next steps

**Total estimated MVP timeline: 11-16 days**

---

## Known Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cell2Fire US fuel model compatibility | Simulation won't run | Test with Canadian FBP first to prove pipeline works, then adapt fuel codes. Have fire2a fork as backup. |
| LANDFIRE API downtime/rate limits | Fuel pipeline blocks | Pre-download Tennessee tile as fallback, cache in data/fuel/cache/ |
| Grid alignment off-by-one errors | Garbage simulation results | Always use fuel grid as reference template for all other rasters. Add pixel-level alignment validation in grid assembly. |
| Cell2Fire C++ build issues in Docker | Simulation container fails | Pin to a known-good commit hash. Include build test in Dockerfile. |
| Microsoft Building Footprints too large | Assets pipeline OOM | Pre-filter by state, then spatial index. Or use OSM buildings as lighter alternative. |
| 16GB RAM constraint with Docker overhead | OOM during simulation | Monitor with `docker stats`. Reduce grid resolution to 60m as fallback. |

---

## Future Enhancements (Post-MVP)

1. **Monte Carlo mode:** Run N simulations with varied weather/ignition → burn probability maps
2. **Real weather integration:** RAWS/HRRR/gridMET pipelines
3. **Live fuel moisture from satellite:** MODIS/VIIRS NDVI integration
4. **Irregular grid (Voronoi):** Higher resolution at WUI, coarser in homogeneous forest
5. **Orchestration upgrade:** Airflow/Prefect for parallel pipeline execution
6. **Database backend:** PostGIS for spatial queries, Redis for caching
7. **Multi-scenario comparison UI:** Side-by-side maps for different wind/ignition scenarios
8. **CWPP report generation:** Auto-generate Community Wildfire Protection Plan documents from outputs
9. **Dollar-value damage estimates:** Integrate county assessor property values
10. **Evacuation time modeling:** Combine fire arrival times with road network analysis
