# ELMFIRE Integration — Implementation Plan & Claude Code Prompts

## Overview

This phase replaces C2FSB as the primary simulation engine with ELMFIRE, integrates WindNinja for terrain-adjusted wind, and expands LANDFIRE data fetching to include all canopy layers. After this phase, the platform has crown fire, spotting, spatially varying wind, and built-in Monte Carlo — making validation against real fires (Phase 8) meaningful.

**Why ELMFIRE over C2FSB:**
- Crown fire initiation and spread (Van Wagner + Rothermel crown)
- Ember/spotting transport (Lagrangian particle model)
- Spatially varying wind input (direct WindNinja GeoTIFF ingestion)
- Built-in Monte Carlo with burn probability output
- Native LANDFIRE input format
- Built-in validation tools with historical fire perimeter access
- Open source (EPL 2.0), commercially usable
- Used operationally for most large US fires via Pyrecast

**What changes from the existing pipeline:**

| Pipeline | Change |
|---|---|
| 01_shapefile_ingestion | No change |
| 02_fuel | Expand to fetch all 8 LANDFIRE layers (add CC, CH, CBH, CBD) |
| 03_topography | No change (ELMFIRE reads same DEM/slope/aspect) |
| 04_weather | Add gridMET historical fetch + hourly RAWS support (deferred — existing Weather.csv is sufficient for MVP; WindNinja reads speed/direction from it) |
| 04b_windninja (NEW) | WindNinja terrain-adjusted wind grids |
| 05_fuel_moisture | Upgrade to gridMET-derived or keep for MVP |
| 06_assets | No change |
| 07_grid_assembly | Rewrite to produce ELMFIRE GeoTIFF inputs instead of C2FSB ASCII |
| 08_ignition | Update to write ELMFIRE ignition format |
| 09_elmfire (NEW) | Replace 09_cell2fire with ELMFIRE Docker container |
| 09_cell2fire | Keep as secondary engine option |
| 10_consequence | No change (reads same fire_perimeter_final.geojson) |
| 11_web_ui | Minor update for crown fire layer display |

## New Directory Structure

```
pipelines/
├── 02_fuel/                    # UPDATED: fetches 8 LANDFIRE bands
├── 04_weather/                 # UPDATED: gridMET historical support
├── 04b_windninja/              # NEW: terrain-adjusted wind grids
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── README.md
│   └── src/
│       └── run_windninja.py
├── 07_grid_assembly/           # UPDATED: produces ELMFIRE-format GeoTIFFs
├── 08_ignition/                # UPDATED: ELMFIRE ignition format
├── 09_elmfire/                 # NEW: primary simulation engine
│   ├── Dockerfile
│   ├── README.md
│   └── src/
│       └── run_simulation.py
├── 09_cell2fire/               # KEPT: secondary engine for surface-fire scenarios
```

## ELMFIRE Input Requirements

From the ELMFIRE documentation, it needs these GeoTIFF rasters:

**Fuels/Topography (single-band, 16-bit integer):**
- `asp.tif` — aspect in degrees
- `cbd.tif` — canopy bulk density (units: 100 × kg/m³)
- `cbh.tif` — canopy base height (units: 10 × meters)
- `cc.tif` — canopy cover (percent)
- `ch.tif` — canopy height (units: 10 × meters)
- `dem.tif` — elevation in meters
- `fbfm40.tif` — Scott & Burgan 40 fuel model codes
- `slp.tif` — slope in degrees
- `adj.tif` — surface spread rate adjustment factor (32-bit float, default 1.0 everywhere)
- `phi.tif` — initial level set field (32-bit float, encodes ignition location)

**Weather (single or multiband, 32-bit float):**
- `ws.tif` — wind speed (mph at 20ft)
- `wd.tif` — wind direction (degrees)
- `m1.tif` — 1-hr dead fuel moisture (percent)
- `m10.tif` — 10-hr dead fuel moisture (percent)
- `m100.tif` — 100-hr dead fuel moisture (percent)

Live fuel moisture specified as scalar values in elmfire.data config.

**Configuration:**
- `elmfire.data` — Fortran namelist file controlling simulation parameters

## Makefile Updates

```makefile
# Engine selection (default: elmfire)
ENGINE ?= elmfire

# WindNinja (optional, improves wind accuracy)
WINDNINJA ?= off

run-sim:
ifeq ($(ENGINE),elmfire)
	@echo "=== Simulation: ELMFIRE ==="
	$(DOCKER_RUN) wildfire-09_elmfire
else
	@echo "=== Simulation: C2FSB ==="
	$(DOCKER_RUN) wildfire-09_cell2fire
endif

run-04b: build-04b_windninja
	@echo "=== Step 4b: WindNinja Wind Fields ==="
	$(DOCKER_RUN) wildfire-04b_windninja

run-sim-c2fsb:
	@echo "=== Simulation: C2FSB ==="
	$(DOCKER_RUN) wildfire-09_cell2fire

# Full pipeline with ELMFIRE
all-elmfire: run-01 run-02 run-03 run-04 run-04b run-05 run-06 run-07 run-08 run-sim run-10
	@echo "=== Full ELMFIRE pipeline complete ==="

# Full pipeline with C2FSB (original)
# Note: make all still uses C2FSB via run-09; all-c2fsb is an explicit alias
all-c2fsb: run-01 run-02 run-03 run-04 run-05 run-06 run-07 run-08 run-sim-c2fsb run-10
	@echo "=== Full C2FSB pipeline complete ==="
```

---

## Claude Code Prompts

### Prompt E.0 — Scaffold New Pipelines

```
Read IMPLEMENTATION_PLAN.md and the existing repo structure.

We are integrating ELMFIRE as the primary simulation engine. Create the following new directories:

1. pipelines/04b_windninja/src/
2. pipelines/09_elmfire/src/

Add .gitkeep files. Do NOT create Dockerfiles or Python files yet.

Update the Makefile to add:
- ENGINE variable (default: elmfire)
- run-04b target for WindNinja
- run-sim target that selects engine based on ENGINE variable
- all-elmfire target that runs: run-01, run-02, run-03, run-04, run-04b, run-05, run-06, run-07, run-08, run-sim, run-10
- Keep all existing C2FSB targets working

Create .env additions:
  ELMFIRE_SIMULATION_HOURS=24
  WINDNINJA_ENABLED=true
  ELMFIRE_CROWN_FIRE=1
  ELMFIRE_ENABLE_SPOTTING=true
```

### Tests for E.0:
```bash
test -d pipelines/04b_windninja/src && echo "PASS" || echo "FAIL"
test -d pipelines/09_elmfire/src && echo "PASS" || echo "FAIL"
grep -q "ENGINE" Makefile && echo "PASS: ENGINE var" || echo "FAIL"
grep -q "run-04b" Makefile && echo "PASS: WindNinja target" || echo "FAIL"
grep -q "run-sim" Makefile && echo "PASS: run-sim target" || echo "FAIL"
```

---

### Prompt E.1 — Expand Fuel Pipeline for Canopy Layers

```
NOTE: The existing fetch_fuel.py uses the LANDFIRE REST API via requests. This prompt replaces
that with the landfire Python package. It is a full rewrite of the fetch logic, not an extension.
The landfire package has been validated separately and works without auth.

Read IMPLEMENTATION_PLAN.md. The existing 02_fuel pipeline fetches only FBFM40 from LANDFIRE.

Update pipelines/02_fuel to also fetch the four canopy layers needed by ELMFIRE:
- Canopy Cover (CC)
- Canopy Height (CH) 
- Canopy Base Height (CBH)
- Canopy Bulk Density (CBD)

Use the landfire Python package. Update the request to include all layers:

```python
from landfire import Landfire

bbox = "<from aoi_metadata.json>"
lf = Landfire(bbox=bbox, resample_res=30)

# LF 2023 layer codes (verify with ProductSearch if these don't work)
lf.request_data(
    layers=[
        "240FBFM40",   # fuel models
        "240CC",       # canopy cover
        "240CH",       # canopy height
        "240CBH",      # canopy base height
        "240CBD",      # canopy bulk density
    ],
    output_path="/data/fuel/landfire_all_layers.zip"
)
```

After downloading, the zip contains a multi-band GeoTIFF. Extract individual bands:
- Band mapping depends on the order requested — inspect with gdalinfo
- Save each as a separate GeoTIFF:
  data/fuel/fbfm40.tif
  data/fuel/cc.tif
  data/fuel/ch.tif
  data/fuel/cbh.tif
  data/fuel/cbd.tif

All must be reprojected to EPSG:5070 at 30m resolution, clipped to AOI, aligned with the topography grid (same transform, dimensions).

IMPORTANT: LANDFIRE canopy layers have specific unit conventions:
- CC: percent (0-100)
- CH: 10 × meters (so a value of 150 means 15.0 meters)
- CBH: 10 × meters
- CBD: 100 × kg/m³ (so a value of 25 means 0.25 kg/m³)
ELMFIRE expects these exact units. Do NOT convert them.

Update fuel_metadata.json to include canopy layer statistics.
Update README.md.

Rebuild and test:
  docker build -t wildfire-02_fuel pipelines/02_fuel
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-02_fuel
```

### Tests for E.1:
```bash
docker build -t wildfire-02_fuel pipelines/02_fuel && echo "PASS: Build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-02_fuel && echo "PASS: Ran" || echo "FAIL"

for f in fbfm40.tif cc.tif ch.tif cbh.tif cbd.tif; do
    test -f "data/fuel/$f" && echo "PASS: $f" || echo "FAIL: $f missing"
done

# Alignment check — all fuel layers must match topography
python3 -c "
import rasterio
ref = rasterio.open('data/topography/elevation.tif')
for f in ['fbfm40.tif', 'cc.tif', 'ch.tif', 'cbh.tif', 'cbd.tif']:
    with rasterio.open(f'data/fuel/{f}') as src:
        ok = src.width == ref.width and src.height == ref.height and src.crs == ref.crs
        print(f'  {f}: {\"PASS\" if ok else \"FAIL\"} ({src.width}x{src.height})')
ref.close()
"
```

---

### Prompt E.2 — ELMFIRE Docker Build + Tutorial Test

```
IMPORTANT: Build ELMFIRE and verify it works before wiring it into the pipeline.

1. Create pipelines/09_elmfire/Dockerfile:

   ELMFIRE requires a Fortran compiler (Intel or gfortran), GDAL, and Python 3.
   
   Check the ELMFIRE getting started guide: https://elmfire.io/getting_started.html
   
   The GitHub repo already has CI workflows that build Docker images. Check:
   https://github.com/lautenberger/elmfire/actions
   
   APPROACH A (preferred): See if there's a pre-built Docker image.
   Check if lautenberger publishes to GitHub Container Registry (ghcr.io) or Docker Hub.
   If a pre-built image exists, use it as the base:
     FROM ghcr.io/lautenberger/elmfire:latest
   
   APPROACH B: Build from source.
   FROM ubuntu:22.04
   
   Install: gfortran, make, gdal-bin, libgdal-dev, python3, python3-pip, git, wget
   
   Clone: git clone https://github.com/lautenberger/elmfire.git /opt/elmfire
   
   Build ELMFIRE:
     cd /opt/elmfire
     # Check for Makefile or build instructions
     # The binary is typically built with: make -f Makefile.local
     # or there may be a build script
   
   Install Python dependencies:
     pip3 install grpcio grpcio-tools google-api-python-client python-dateutil numpy rasterio geopandas shapely
   
   Set ELMFIRE_BASE_DIR environment variable:
     ENV ELMFIRE_BASE_DIR=/opt/elmfire
   
   APPROACH C: If compilation fails, check if ELMFIRE requires the Intel Fortran compiler (ifort/ifx).
   If so, try gfortran first. If that doesn't work, the Intel oneAPI HPC toolkit is free:
     wget https://apt.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS.PUB
     apt-key add GPG-PUB-KEY-INTEL-SW-PRODUCTS.PUB
     echo "deb https://apt.repos.intel.com/oneapi all main" > /etc/apt/sources.list.d/oneAPI.list
     apt-get update && apt-get install -y intel-oneapi-compiler-fortran

2. Create pipelines/09_elmfire/src/run_simulation.py — test script:

   FIRST: Run ELMFIRE's built-in Tutorial 01 (constant wind, flat terrain):
   
   cd /opt/elmfire/tutorials/01-constant_wind
   ./01-run.sh
   
   Check if output files were created. If yes, print "ELMFIRE TUTORIAL 01 PASSED".
   
   THEN: Run Tutorial 03 (real-world fuel/terrain):
   This one uses CloudFire microservices to fetch LANDFIRE data.
   
   cd /opt/elmfire/tutorials/03-real_world_fuel_terrain  
   ./01-run.sh
   
   This requires network access for the CloudFire gRPC call.
   Check outputs. If yes, print "ELMFIRE TUTORIAL 03 PASSED".
   
   Print the directory listing of outputs so we can see what ELMFIRE produces.
   
   IMPORTANT: Before running tutorials, inspect the repo structure:
     ls -la /opt/elmfire/
     ls -la /opt/elmfire/tutorials/
     ls -la /opt/elmfire/build/ (or wherever the binary ends up)
     cat /opt/elmfire/tutorials/01-constant_wind/01-run.sh
   Print all findings so we understand the exact file layout.

Build and test:
  docker build -t wildfire-09_elmfire pipelines/09_elmfire
  docker run --rm wildfire-09_elmfire
```

### Tests for E.2:
```bash
docker build -t wildfire-09_elmfire pipelines/09_elmfire && echo "PASS: Docker build" || echo "FAIL"
docker run --rm wildfire-09_elmfire 2>&1 | tee /tmp/elmfire_test.log
grep -q "TUTORIAL 01 PASSED" /tmp/elmfire_test.log && echo "PASS: Tutorial 01" || echo "FAIL: Tutorial 01"
grep -q "TUTORIAL 03 PASSED" /tmp/elmfire_test.log && echo "PASS: Tutorial 03" || echo "FAIL: Tutorial 03"
```

---

### Prompt E.3 — WindNinja Pipeline

```
Implement pipelines/04b_windninja. This takes raw wind speed/direction from the weather pipeline plus the DEM and produces spatially varying wind grids.

1. Create Dockerfile:
   WindNinja can be built from source on Linux.
   Clone: git clone https://github.com/firelab/windninja.git
   Build dependencies: cmake, gdal, boost, netcdf
   
   Alternatively, check if WindNinja has pre-built Linux binaries or a package.
   The CLI binary is called WindNinja_cli.
   
   IMPORTANT: WindNinja building can be complex. If the C++ build fails, a simpler approach for MVP:
   - Download a pre-built release if available
   - Or use WindNinja's API mode if they have one
   - Or as a last resort, generate simple terrain-adjusted wind using numpy:
     ridge_speed = base_speed * 1.3 (accelerate on ridges)
     valley_speed = base_speed * 0.6 (decelerate in valleys)
     Classify ridge/valley from the DEM curvature
     This is crude but better than uniform wind

2. Create src/run_windninja.py:
   
   Inputs:
   - data/topography/elevation.tif (DEM)
   - data/weather/weather_scenario.json (base wind speed and direction)
   - data/input/aoi_metadata.json
   
   Run WindNinja:
   WindNinja_cli \
     --elevation_file data/topography/elevation.tif \
     --initialization_method domainAverageInitialization \
     --input_speed <wind_speed_mph> \
     --input_speed_units mph \
     --input_direction <wind_direction> \
     --input_wind_height 20 \
     --units_input_wind_height ft \
     --output_wind_height 20 \
     --units_output_wind_height ft \
     --vegetation trees \
     --mesh_resolution 30 \
     --units_mesh_resolution m \
     --output_speed_units mph \
     --write_ascii_output true \
     --write_geoTIFF_output true
   
   WindNinja outputs *_vel.tif and *_ang.tif files (speed and direction grids).
   
   For time-varying wind (multi-hour simulation):
   - Run WindNinja for each hourly wind condition from weather data
   - Stack the hourly outputs into multiband GeoTIFFs
   
   Output:
   - data/weather/ws.tif (wind speed, single or multiband)
   - data/weather/wd.tif (wind direction, single or multiband)
   - data/weather/windninja_metadata.json
   
   If WindNinja is not available (build failed), fall back to:
   - Copy uniform wind values as single-band GeoTIFFs at 30m resolution
   - Document that WindNinja is not installed

3. Create README.md

Test:
  docker build -t wildfire-04b_windninja pipelines/04b_windninja
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-04b_windninja
```

### Tests for E.3:
```bash
docker build -t wildfire-04b_windninja pipelines/04b_windninja && echo "PASS: Build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-04b_windninja && echo "PASS: Ran" || echo "FAIL"

test -f data/weather/ws.tif && echo "PASS: Wind speed grid" || echo "FAIL"
test -f data/weather/wd.tif && echo "PASS: Wind direction grid" || echo "FAIL"

python3 -c "
import rasterio
with rasterio.open('data/weather/ws.tif') as src:
    print(f'Wind speed: {src.width}x{src.height}, {src.count} band(s)')
    data = src.read(1)
    print(f'  Range: {data.min():.1f} - {data.max():.1f} mph')
    assert data.max() > 0, 'All zeros — wind not generated'
    print('PASS: Wind speed grid has values')
"
```

---

### Prompt E.4 — Grid Assembly for ELMFIRE

```
Read the ELMFIRE input requirements section above carefully.

NOTE: The existing 07_grid_assembly reads data/fuel/fuel_clipped.tif. After E.1, that file no
longer exists — it is replaced by data/fuel/fbfm40.tif and the canopy TIFs. Remove all references
to fuel_clipped.tif in the rewrite.

Rewrite pipelines/07_grid_assembly to produce ELMFIRE-format inputs instead of C2FSB ASCII grids.

ELMFIRE needs ALL inputs as GeoTIFF rasters in a single directory. The src/assemble_grid.py should:

1. Load and validate alignment of ALL input rasters:
   From fuel pipeline: fbfm40.tif, cc.tif, ch.tif, cbh.tif, cbd.tif
   From topo pipeline: elevation.tif, slope.tif, aspect.tif
   Check: same CRS, dimensions, transform. Exit with error if misaligned.

2. Copy/rename fuel and topo rasters to ELMFIRE naming convention:
   data/fuel/fbfm40.tif → data/grid/fbfm40.tif
   data/fuel/cc.tif → data/grid/cc.tif
   data/fuel/ch.tif → data/grid/ch.tif
   data/fuel/cbh.tif → data/grid/cbh.tif
   data/fuel/cbd.tif → data/grid/cbd.tif
   data/topography/elevation.tif → data/grid/dem.tif
   data/topography/slope.tif → data/grid/slp.tif
   data/topography/aspect.tif → data/grid/asp.tif

3. Create the adjustment factor raster:
   data/grid/adj.tif — all values 1.0 (32-bit float, same dimensions)
   This is a spread rate multiplier. 1.0 = no adjustment.

4. Copy weather rasters:
   data/weather/ws.tif → data/grid/ws.tif (from WindNinja or uniform)
   data/weather/wd.tif → data/grid/wd.tif

5. Create fuel moisture rasters from data/moisture/fuel_moisture.json:
   data/grid/m1.tif — uniform 1-hr dead moisture (single band, same dimensions)
   data/grid/m10.tif — uniform 10-hr dead moisture
   data/grid/m100.tif — uniform 100-hr dead moisture
   All 32-bit float, values in percent (e.g., 4.0 for 4%).
   For multi-hour simulation, create multiband with same value repeated (ELMFIRE expects same band count as weather rasters).

6. Create the initial phi (level set) field:
   data/grid/phi.tif — 32-bit float, all values = 1.0 (unburned everywhere)
   Ignition is specified in elmfire.data via X_IGN/Y_IGN (see step 7), not encoded
   in phi.tif. This avoids a chicken-and-egg problem since 07 runs before 08.

7. Generate the ELMFIRE configuration file data/grid/elmfire.data:
   This is a Fortran namelist file. Generate it from a template:

   ```
   &INPUTS
   FUELS_AND_TOPOGRAPHY_DIRECTORY = './inputs'
   ASP_FILENAME = 'asp'
   CBD_FILENAME = 'cbd'
   CBH_FILENAME = 'cbh'
   CC_FILENAME  = 'cc'
   CH_FILENAME  = 'ch'
   DEM_FILENAME = 'dem'
   FBFM_FILENAME = 'fbfm40'
   SLP_FILENAME = 'slp'
   ADJ_FILENAME = 'adj'
   PHI_FILENAME = 'phi'
   DT_METEOROLOGY = 3600.0
   WEATHER_DIRECTORY = './inputs'
   WS_FILENAME  = 'ws'
   WD_FILENAME  = 'wd'
   M1_FILENAME  = 'm1'
   M10_FILENAME = 'm10'
   M100_FILENAME = 'm100'
   LH_MOISTURE_CONTENT = <from fuel_moisture.json>
   LW_MOISTURE_CONTENT = <from fuel_moisture.json>
   /

   &OUTPUTS
   OUTPUTS_DIRECTORY = './outputs'
   DTDUMP = 3600.0
   DUMP_TIMINGS = .TRUE.
   DUMP_INTERMEDIATE_TIMINGS = .TRUE.
   CALCULATE_BURN_PROBABILITY = .FALSE.
   /

   &SIMULATOR
   NUM_IGNITIONS = 1
   X_IGN(1) = <x coordinate>
   Y_IGN(1) = <y coordinate>
   T_IGN(1) = 0.0
   /

   &TIME_CONTROL
   SIMULATION_TSTOP = <hours * 3600>
   /

   &MONTE_CARLO
   NUM_ENSEMBLE_MEMBERS = 1
   NUM_METEOROLOGY_BANDS = <number of weather bands>
   /

   &CROWN_FIRE
   CROWN_FIRE_MODEL = 1
   /

   &SPOTTING
   ENABLE_SPOTTING = .TRUE.
   CROWN_FIRE_SPOTTING_PERCENT = 1.0
   ENABLE_SURFACE_FIRE_SPOTTING = .FALSE.
   /
   ```

   Populate values from aoi_metadata.json, ignition_metadata.json, fuel_moisture.json, and .env variables.

8. Write data/grid/grid_metadata.json with all assembled inputs documented.

IMPORTANT: ELMFIRE expects filenames WITHOUT the .tif extension in elmfire.data (it appends .tif automatically). So use 'dem' not 'dem.tif'.

IMPORTANT: All rasters must be 16-bit integer for fuel/topo layers and 32-bit float for weather/moisture/adj/phi layers. Convert dtype when copying if needed.

Test:
  docker build -t wildfire-07_grid_assembly pipelines/07_grid_assembly
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-07_grid_assembly
```

### Tests for E.4:
```bash
docker build -t wildfire-07_grid_assembly pipelines/07_grid_assembly && echo "PASS: Build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-07_grid_assembly && echo "PASS: Ran" || echo "FAIL"

# Check all required ELMFIRE input files
for f in asp.tif cbd.tif cbh.tif cc.tif ch.tif dem.tif fbfm40.tif slp.tif adj.tif phi.tif ws.tif wd.tif m1.tif m10.tif m100.tif; do
    test -f "data/grid/$f" && echo "PASS: $f" || echo "FAIL: $f missing"
done

test -f data/grid/elmfire.data && echo "PASS: elmfire.data config" || echo "FAIL"

# Validate all rasters are aligned
python3 -c "
import rasterio
ref = rasterio.open('data/grid/dem.tif')
for f in ['asp.tif','fbfm40.tif','slp.tif','cc.tif','ch.tif','cbh.tif','cbd.tif','ws.tif','wd.tif','m1.tif']:
    with rasterio.open(f'data/grid/{f}') as src:
        aligned = src.width == ref.width and src.height == ref.height
        print(f'  {f}: {\"PASS\" if aligned else \"FAIL\"}')
ref.close()
print('PASS: All rasters checked')
"

# Validate elmfire.data has required namelist groups
for group in INPUTS OUTPUTS SIMULATOR TIME_CONTROL; do
    grep -q "$group" data/grid/elmfire.data && echo "PASS: &$group present" || echo "FAIL: &$group missing"
done
```

---

### Prompt E.5 — Wire ELMFIRE to Real Data

```
The ELMFIRE Docker build from Prompt 6.2 should be working (tutorials pass).
The grid assembly from Prompt 7.0 should have produced all ELMFIRE inputs.

Update pipelines/09_elmfire/src/run_simulation.py to:

1. Keep the tutorial test as a function callable with --test flag

2. In normal mode:
   a) Verify all required input files exist in data/grid/
   b) Create the ELMFIRE run directory structure:
      /tmp/elmfire_run/inputs/ — symlink or copy all GeoTIFFs from data/grid/
      /tmp/elmfire_run/inputs/elmfire.data — copy from data/grid/
      /tmp/elmfire_run/outputs/ — empty directory for results
   
   c) Run ELMFIRE:
      cd /tmp/elmfire_run
      $ELMFIRE_BASE_DIR/build/elmfire elmfire.data
      (or however the binary is invoked — check from Tutorial 01's run script)
   
   d) Parse ELMFIRE outputs:
      - Time of arrival raster (toa directory): convert to GeoTIFF with proper CRS
      - Fire perimeter at each dump interval: extract from outputs
      - Final burn scar: create binary burned/unburned raster
      - Convert final burn scar to GeoJSON polygon (vectorize)
      - If crown fire enabled, extract fire type output (surface/passive/active crown)
   
   e) Save outputs in standard format for downstream pipelines:
      data/simulation/fire_perimeter_final.geojson
      data/simulation/burn_scar.tif
      data/simulation/time_of_arrival.tif
      data/simulation/fire_type.tif (if crown fire modeled)
      data/simulation/summary.json:
        {
          "engine": "elmfire",
          "total_cells_burned": ...,
          "total_area_burned_ha": ...,
          "simulation_hours": ...,
          "crown_fire_enabled": true,
          "spotting_enabled": true,
          "surface_fire_cells": ...,
          "passive_crown_fire_cells": ...,
          "active_crown_fire_cells": ...,
          "generated_at": "..."
        }
   
   f) For timestep animation, save hourly isochrone shapefiles or rasters to data/simulation/grids/

3. Handle errors: if ELMFIRE crashes, print the full elmfire.out log file contents for debugging.

Test:
  docker build -t wildfire-09_elmfire pipelines/09_elmfire
  
  # Tutorial test
  docker run --rm wildfire-09_elmfire python3 /app/src/run_simulation.py --test
  
  # Real data test (requires all previous pipelines)
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-09_elmfire
```

### Tests for E.5:
```bash
# Tutorial still works
docker run --rm wildfire-09_elmfire python3 /app/src/run_simulation.py --test 2>&1 | grep -q "TUTORIAL" && echo "PASS: Tutorial" || echo "FAIL"

# Real data
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-09_elmfire && echo "PASS: Simulation ran" || echo "FAIL"

test -f data/simulation/fire_perimeter_final.geojson && echo "PASS: Fire perimeter" || echo "FAIL"
test -f data/simulation/summary.json && echo "PASS: Summary" || echo "FAIL"

python3 -c "
import json
with open('data/simulation/summary.json') as f:
    s = json.load(f)
assert s['engine'] == 'elmfire', f'Wrong engine: {s[\"engine\"]}'
assert s['total_cells_burned'] > 0, 'Nothing burned'
print(f'PASS: ELMFIRE burned {s[\"total_cells_burned\"]} cells ({s[\"total_area_burned_ha\"]:.0f} ha)')
if s.get('crown_fire_enabled'):
    print(f'  Surface: {s.get(\"surface_fire_cells\",0)}, Passive crown: {s.get(\"passive_crown_fire_cells\",0)}, Active crown: {s.get(\"active_crown_fire_cells\",0)}')
"
```

---

### Prompt E.6 — End-to-End ELMFIRE Pipeline

```
Run the complete ELMFIRE pipeline end-to-end.

1. make clean
2. make all-elmfire (or run each step individually if the combined target isn't set up yet):
   make run-01
   make run-02  (now fetches all 8 LANDFIRE layers)
   make run-03
   make run-04
   make run-04b (WindNinja)
   make run-05
   make run-06
   make run-07  (ELMFIRE grid assembly)
   make run-08
   make run-sim ENGINE=elmfire
   make run-10

3. If any step fails, fix and re-run from that step.

4. After success, run make ui and verify:
   - Fire perimeter shows on the map
   - Summary shows ELMFIRE as the engine
   - Crown fire info appears if available

5. Update all README.md files for modified pipelines.

6. Update the top-level README.md:
   - Document that ELMFIRE is the primary engine
   - Document that C2FSB is available as secondary: make all ENGINE=c2fsb
   - Add section on WindNinja integration
   - List the LANDFIRE layers now being fetched

7. Commit everything. This is the new baseline before validation (Phase 8).
```

### Tests for E.6:
```bash
# Full pipeline
make clean

# Run each step and check
for step in run-01 run-02 run-03 run-04 run-04b run-05 run-06 run-07 run-08; do
    make $step && echo "PASS: $step" || echo "FAIL: $step"
done

make run-sim ENGINE=elmfire && echo "PASS: ELMFIRE simulation" || echo "FAIL"
make run-10 && echo "PASS: Consequence analysis" || echo "FAIL"

# Final validation
python3 -c "
import json
with open('data/simulation/summary.json') as f:
    s = json.load(f)
with open('data/consequence/consequence_summary.json') as f:
    c = json.load(f)
print('=== ELMFIRE PIPELINE RESULTS ===')
print(f'Engine: {s[\"engine\"]}')
print(f'Area burned: {c[\"total_area_burned_ha\"]:.0f} ha ({c[\"total_area_burned_acres\"]:.0f} acres)')
print(f'Structures exposed: {c[\"structures_exposed\"]}')
print(f'Population at risk: {c[\"estimated_population_at_risk\"]}')
if s.get('crown_fire_enabled'):
    total = s['total_cells_burned']
    crown = s.get('passive_crown_fire_cells',0) + s.get('active_crown_fire_cells',0)
    print(f'Crown fire: {crown} cells ({crown/total*100:.1f}% of burn area)')
print('================================')
"
```

---

## Troubleshooting

### ELMFIRE won't compile — Fortran compiler issues
```
ELMFIRE may require Intel Fortran (ifort/ifx). Try gfortran first.
If gfortran fails, install Intel oneAPI:
  apt-get install intel-oneapi-compiler-fortran
  source /opt/intel/oneapi/setvars.sh
Then rebuild.
Check the Makefile — it may have compiler-specific flags.
```

### ELMFIRE runs but produces no output
```
- Check elmfire.out log file for errors
- Verify SIMULATION_TSTOP is large enough (in seconds, not hours)
- Verify ignition coordinates are within the grid bounds
- Verify fuel model codes are valid Scott & Burgan (101-204)
- Verify weather rasters have the right number of bands (must match NUM_METEOROLOGY_BANDS)
```

### WindNinja won't build
```
WindNinja has many C++ dependencies (GDAL, Boost, NetCDF, etc.)
If the build fails, use the simplified terrain-adjustment fallback:
- Compute terrain curvature from DEM
- Ridge cells (positive curvature): multiply wind speed by 1.3
- Valley cells (negative curvature): multiply wind speed by 0.6
- Redirect wind direction to follow terrain channeling
This is crude but better than uniform wind.
```

### Raster band count mismatch
```
ELMFIRE requires weather rasters (ws, wd, m1, m10, m100) to all have
the same number of bands. If you have 24 bands for wind but 1 band for
moisture, expand the moisture rasters to 24 bands (repeat the same value).
```
