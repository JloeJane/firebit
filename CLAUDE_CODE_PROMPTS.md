# Claude Code Prompts — Wildfire Modeling Platform

## How to Use This File

Run each prompt sequentially in Claude Code. **Do not proceed to the next prompt until all tests pass for the current one.** If a prompt fails partway through, fix the issue before moving on — don't skip ahead.

Each prompt includes:
- **What to build**
- **Acceptance tests** (how you know it worked)
- **Known landmines** (things Claude Code will struggle with)

Copy-paste each prompt into Claude Code exactly as written. The `---` separators are just for this document.

---

## Phase 0: Repo Scaffolding

### Prompt 0.1 — Create the skeleton

```
Read the file IMPLEMENTATION_PLAN.md thoroughly before doing anything.

Create the full repository directory structure described in the plan. Specifically:

1. Create all directories under pipelines/ (01_shapefile_ingestion through 11_web_ui), each with src/ subdirectory
2. Create the data/ directory with all subdirectories: input/, fuel/, topography/, weather/, moisture/, assets/, grid/, simulation/, consequence/, output/
3. Create the .env file with the exact contents from the plan
4. Create the Makefile with the exact contents from the plan
5. Create a .gitignore that ignores: data/fuel/*, data/topography/*, data/weather/*, data/moisture/*, data/assets/*, data/grid/*, data/simulation/*, data/consequence/*, data/output/*, but keeps data/input/. Also ignore __pycache__/, *.pyc, .env.local
6. Add a .gitkeep file in every empty data/ subdirectory so git tracks them
7. Copy IMPLEMENTATION_PLAN.md to the repo root if it isn't there already

Do NOT create any Dockerfiles or Python files yet — just the directory structure, Makefile, .env, and .gitignore.
```

### Tests for 0.1:
```bash
# Verify structure exists
test -f Makefile && echo "PASS: Makefile exists" || echo "FAIL"
test -f .env && echo "PASS: .env exists" || echo "FAIL"
test -f .gitignore && echo "PASS: .gitignore exists" || echo "FAIL"
test -d pipelines/01_shapefile_ingestion/src && echo "PASS: pipeline 01 structure" || echo "FAIL"
test -d pipelines/09_cell2fire/src && echo "PASS: pipeline 09 structure" || echo "FAIL"
test -d pipelines/11_web_ui/templates && echo "PASS: web ui templates dir" || echo "FAIL"
test -d data/input && echo "PASS: data/input exists" || echo "FAIL"
test -d data/simulation && echo "PASS: data/simulation exists" || echo "FAIL"
ls pipelines/ | wc -l  # Should be 11
ls data/ | wc -l  # Should be 10 (input, fuel, topography, weather, moisture, assets, grid, simulation, consequence, output)
```

---

## Phase 1: Shapefile Ingestion + Topography

### Prompt 1.1 — Shapefile Ingestion Pipeline

```
Read IMPLEMENTATION_PLAN.md, specifically the section for Step 1: Shapefile Ingestion (01_shapefile_ingestion).

Implement this pipeline completely:

1. Create pipelines/01_shapefile_ingestion/Dockerfile:
   - Base image: python:3.12-slim
   - Install system deps: libgdal-dev, gdal-bin, libgeos-dev, libproj-dev, g++ (needed to compile GDAL Python bindings)
   - Install Python deps from requirements.txt
   - Set WORKDIR and CMD to run src/ingest.py

2. Create pipelines/01_shapefile_ingestion/requirements.txt:
   - geopandas, shapely, pyproj, fiona

3. Create pipelines/01_shapefile_ingestion/src/ingest.py:
   - Read .env variables from environment (os.environ)
   - Since no user shapefile exists yet, GENERATE the Townsend test AOI:
     - Create a polygon covering the Tuckaleechee Cove to GSMNP boundary area
     - Use these approximate vertices (in EPSG:4326 lat/lon):
       (35.52, -83.86), (35.52, -83.65), (35.65, -83.65), (35.65, -83.86)
     - This is a simple rectangular bounding box — fine for MVP
   - Save the raw AOI as data/input/townsend_aoi.shp (EPSG:4326)
   - Reproject to EPSG:5070 (Conus Albers Equal Area)
   - Save as data/input/aoi_reprojected.shp
   - Compute bounding box in BOTH EPSG:5070 and EPSG:4326
   - Compute area in square miles and hectares
   - Estimate grid dimensions at 30m resolution
   - Write data/input/aoi_metadata.json with:
     {
       "bbox_4326": {"north": ..., "south": ..., "east": ..., "west": ...},
       "bbox_5070": {"xmin": ..., "ymin": ..., "xmax": ..., "ymax": ...},
       "area_sq_mi": ...,
       "area_ha": ...,
       "grid_rows": ...,
       "grid_cols": ...,
       "resolution_m": 30,
       "crs_projected": "EPSG:5070",
       "crs_geographic": "EPSG:4326",
       "generated_at": "<ISO timestamp>"
     }
   - Print a summary to stdout showing all key values

4. Create pipelines/01_shapefile_ingestion/README.md — write it as a template that documents:
   - Pipeline purpose
   - Inputs and outputs with file paths
   - How to run: `make run-01`
   - Note that the README will be updated by the pipeline at runtime (future enhancement)

Test it by running:
  docker build -t wildfire-01_shapefile_ingestion pipelines/01_shapefile_ingestion
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-01_shapefile_ingestion

The pipeline must complete without errors. Verify data/input/aoi_metadata.json exists and contains valid values. Verify data/input/aoi_reprojected.shp exists.

IMPORTANT: The Dockerfile must handle GDAL installation carefully. On Debian slim, you need: apt-get update && apt-get install -y libgdal-dev gdal-bin python3-gdal. Then pip install with the GDAL version matching the system GDAL: pip install GDAL==$(gdal-config --version). If this causes issues, try using the osgeo/gdal:ubuntu-small-3.6.4 base image instead of python:3.12-slim.
```

### Tests for 1.1:
```bash
# Build test
docker build -t wildfire-01_shapefile_ingestion pipelines/01_shapefile_ingestion && echo "PASS: Docker build" || echo "FAIL: Docker build"

# Run test
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-01_shapefile_ingestion && echo "PASS: Pipeline ran" || echo "FAIL: Pipeline crashed"

# Output file tests
test -f data/input/aoi_reprojected.shp && echo "PASS: Reprojected shapefile exists" || echo "FAIL"
test -f data/input/aoi_metadata.json && echo "PASS: Metadata JSON exists" || echo "FAIL"
test -f data/input/townsend_aoi.shp && echo "PASS: Raw AOI shapefile exists" || echo "FAIL"

# Content validation
python3 -c "
import json
with open('data/input/aoi_metadata.json') as f:
    meta = json.load(f)
assert 'bbox_4326' in meta, 'Missing bbox_4326'
assert 'bbox_5070' in meta, 'Missing bbox_5070'
assert meta['resolution_m'] == 30, 'Wrong resolution'
assert meta['grid_rows'] > 100, f'Grid too small: {meta[\"grid_rows\"]} rows'
assert meta['grid_cols'] > 100, f'Grid too small: {meta[\"grid_cols\"]} cols'
assert meta['area_sq_mi'] > 30, f'Area too small: {meta[\"area_sq_mi\"]}'
assert meta['area_sq_mi'] < 80, f'Area too large: {meta[\"area_sq_mi\"]}'
print(f'PASS: Metadata valid — {meta[\"grid_rows\"]}x{meta[\"grid_cols\"]} grid, {meta[\"area_sq_mi\"]:.1f} sq mi')
"

# CRS validation
python3 -c "
import geopandas as gpd
gdf = gpd.read_file('data/input/aoi_reprojected.shp')
assert gdf.crs.to_epsg() == 5070, f'Wrong CRS: {gdf.crs}'
assert len(gdf) == 1, f'Expected 1 polygon, got {len(gdf)}'
assert gdf.geometry.iloc[0].is_valid, 'Invalid geometry'
print(f'PASS: Shapefile CRS is EPSG:5070, geometry valid')
"
```

---

### Prompt 1.2 — Topography Pipeline

```
Read IMPLEMENTATION_PLAN.md, specifically Step 3: Topography Pipeline (03_topography).

Implement this pipeline completely:

1. Create pipelines/03_topography/Dockerfile:
   - Use the same base image approach that worked for 01_shapefile_ingestion (whatever resolved the GDAL issue)
   - Install: rasterio, numpy, geopandas, requests, pyproj
   - If using py3dep for USGS data fetching, include it. Otherwise use direct requests to the USGS 3DEP National Map API.

2. Create pipelines/03_topography/requirements.txt

3. Create pipelines/03_topography/src/fetch_topo.py:
   - Read data/input/aoi_metadata.json to get the bbox in EPSG:4326
   - Fetch elevation data from USGS 3DEP. Use the National Map API:
     URL: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage
     Parameters:
       bbox=<west>,<south>,<east>,<north> (in EPSG:4326)
       bboxSR=4326
       imageSR=4326
       size=<width>,<height> (calculate from bbox at ~30m resolution in degrees: ~0.00027 degrees per pixel)
       format=tiff
       f=image
     Save the response as data/topography/elevation_raw.tif
   - If the API call fails or returns an error, print a clear error message with the URL attempted and the response status. Do NOT silently continue.
   - Reproject to EPSG:5070 at exactly 30m resolution using rasterio.warp.reproject.
     CRITICAL: Use the grid dimensions from aoi_metadata.json (grid_rows, grid_cols) and compute the transform from bbox_5070 to ensure pixel-perfect alignment with the fuel grid later.
     The transform should be:
       from rasterio.transform import from_bounds
       transform = from_bounds(xmin, ymin, xmax, ymax, grid_cols, grid_rows)
   - Save as data/topography/elevation.tif
   - Derive slope (degrees) using numpy gradient:
       dy, dx = np.gradient(elevation, 30)  # 30m cell size
       slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
   - Derive aspect (degrees from north, 0-360):
       aspect = np.degrees(np.arctan2(-dx, dy))
       aspect = (aspect + 360) % 360
   - Save slope.tif and aspect.tif with the same transform and CRS
   - Write data/topography/topo_metadata.json:
     {
       "elevation_min_m": ...,
       "elevation_max_m": ...,
       "elevation_mean_m": ...,
       "slope_mean_deg": ...,
       "slope_max_deg": ...,
       "rows": ...,
       "cols": ...,
       "resolution_m": 30,
       "crs": "EPSG:5070",
       "source": "USGS 3DEP",
       "generated_at": "<ISO timestamp>"
     }
   - Print a summary to stdout

4. Create pipelines/03_topography/README.md documenting the pipeline.

CRITICAL: The output rasters (elevation.tif, slope.tif, aspect.tif) must have EXACTLY the same dimensions (rows, cols), resolution (30m), CRS (EPSG:5070), and origin as what the fuel pipeline will produce. Use aoi_metadata.json bbox_5070 and grid_rows/grid_cols to compute the rasterio transform. This is the #1 source of bugs in the entire platform.

Test by running:
  docker build -t wildfire-03_topography pipelines/03_topography
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-03_topography
```

### Tests for 1.2:
```bash
# Build and run
docker build -t wildfire-03_topography pipelines/03_topography && echo "PASS: Docker build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-03_topography && echo "PASS: Pipeline ran" || echo "FAIL"

# File existence
test -f data/topography/elevation.tif && echo "PASS: elevation.tif exists" || echo "FAIL"
test -f data/topography/slope.tif && echo "PASS: slope.tif exists" || echo "FAIL"
test -f data/topography/aspect.tif && echo "PASS: aspect.tif exists" || echo "FAIL"
test -f data/topography/topo_metadata.json && echo "PASS: metadata exists" || echo "FAIL"

# Raster validation
python3 -c "
import rasterio
import json
import numpy as np

with open('data/input/aoi_metadata.json') as f:
    aoi = json.load(f)

with rasterio.open('data/topography/elevation.tif') as src:
    assert src.crs.to_epsg() == 5070, f'Wrong CRS: {src.crs}'
    assert src.width == aoi['grid_cols'], f'Width mismatch: {src.width} vs {aoi[\"grid_cols\"]}'
    assert src.height == aoi['grid_rows'], f'Height mismatch: {src.height} vs {aoi[\"grid_rows\"]}'
    assert abs(src.res[0] - 30) < 1, f'Wrong X resolution: {src.res[0]}'
    assert abs(src.res[1] - 30) < 1, f'Wrong Y resolution: {src.res[1]}'
    data = src.read(1)
    assert data.min() > 0, f'Elevation min suspiciously low: {data.min()}'
    assert data.max() < 3000, f'Elevation max suspiciously high: {data.max()}'
    print(f'PASS: elevation.tif — {src.width}x{src.height}, elev range {data.min():.0f}-{data.max():.0f}m')

with rasterio.open('data/topography/slope.tif') as src:
    data = src.read(1)
    assert data.min() >= 0, 'Negative slope'
    assert data.max() < 90, f'Slope > 90 degrees: {data.max()}'
    print(f'PASS: slope.tif — range {data.min():.1f}-{data.max():.1f} degrees')

with rasterio.open('data/topography/aspect.tif') as src:
    data = src.read(1)
    assert data.min() >= 0, 'Negative aspect'
    assert data.max() <= 360, f'Aspect > 360: {data.max()}'
    print(f'PASS: aspect.tif — range {data.min():.1f}-{data.max():.1f} degrees')
"

# Cross-validate with metadata
python3 -c "
import json
with open('data/topography/topo_metadata.json') as f:
    meta = json.load(f)
assert meta['elevation_min_m'] > 0, 'Bad min elevation'
assert meta['elevation_max_m'] > meta['elevation_min_m'], 'Max <= min elevation'
assert meta['crs'] == 'EPSG:5070', 'Wrong CRS in metadata'
print(f'PASS: Metadata consistent — elevation {meta[\"elevation_min_m\"]:.0f}-{meta[\"elevation_max_m\"]:.0f}m, mean slope {meta[\"slope_mean_deg\"]:.1f}°')
"
```

---

## Phase 2: Fuel, Weather, Moisture, Grid Assembly

### Prompt 2.1 — Fuel Pipeline

```
Read IMPLEMENTATION_PLAN.md, specifically Step 2: Fuel Pipeline (02_fuel).

Implement this pipeline. This is the trickiest data fetch because LANDFIRE's API can be unreliable.

1. Create pipelines/02_fuel/Dockerfile (same GDAL approach that worked before)

2. Create pipelines/02_fuel/requirements.txt:
   - rasterio, geopandas, numpy, requests

3. Create pipelines/02_fuel/src/fetch_fuel.py:
   - Read data/input/aoi_metadata.json
   - Fetch LANDFIRE FBFM40 data. Try these approaches in order:
   
     APPROACH A (preferred): LANDFIRE Product Service REST API
       URL: https://lfps.usgs.gov/arcgis/rest/services/LandfireProductService/GPServer/LandfireProductService/submitJob
       This is an async job-based API. You submit a job, poll for completion, then download.
       Parameters: Layer list should include "200FBFM40" (the 40 Scott & Burgan fuel models)
       Area of interest from bbox_4326
       
     APPROACH B (fallback): Direct LANDFIRE download
       Go to https://landfire.gov/viewer/ programmatically or use their bulk download.
       For the Smoky Mountains area, the data falls in LANDFIRE zone 28 or 54.
       
     APPROACH C (last resort — use this if A and B fail): 
       Download the LANDFIRE FBFM40 GeoTIFF for the entire southeastern US from the LANDFIRE bulk download page, cache it in data/fuel/cache/, and clip locally. The file URL pattern is:
       https://landfire.gov/bulk/downloadfile.php?ESSION=&TYPE=landfire&FNAME=LF2022_FBFM40_220_CONUS.zip
       This is a large file (~2GB) but only needs to download once.
       If this URL doesn't work, print a message telling the dev to manually download from landfire.gov and place the FBFM40 GeoTIFF in data/fuel/cache/
   
   - Whatever approach works, save the raw data as data/fuel/fuel_raw.tif
   - Reproject to EPSG:5070, clip to AOI, resample to 30m using NEAREST neighbor (fuel codes are categorical — never interpolate)
   - CRITICAL: Use the same transform computation as topography pipeline:
       from rasterio.transform import from_bounds
       transform = from_bounds(xmin, ymin, xmax, ymax, grid_cols, grid_rows)
     Where xmin/ymin/xmax/ymax come from aoi_metadata.json bbox_5070 and grid_cols/grid_rows match exactly
   - Save as data/fuel/fuel_clipped.tif
   - Generate data/fuel/fuel_model_grid.csv with columns: row, col, fuel_code
   - Generate data/fuel/fuel_metadata.json:
     {
       "unique_fuel_codes": [list of unique FBFM40 codes present],
       "fuel_distribution": {code: percentage, ...},
       "nodata_percentage": ...,
       "rows": ...,
       "cols": ...,
       "source": "LANDFIRE FBFM40 2022",
       "generated_at": "..."
     }
   - Print summary showing fuel types found and their distribution

4. Create README.md

IMPORTANT: If LANDFIRE APIs are down or too slow during development, create a SYNTHETIC fuel grid as a fallback:
  - Use the elevation data from data/topography/elevation.tif as a proxy
  - Assign fuel models based on elevation bands:
    < 400m: GR2 (grass, code 102)
    400-800m: TU5 (timber understory, code 165)
    800-1200m: TL3 (timber litter, code 183)
    > 1200m: TL8 (timber litter, code 188)
  - Mark this clearly as synthetic in the metadata
  - This is a reasonable approximation of Smoky Mountains vegetation zonation
  Document the fallback in the README.

Test by running:
  docker build -t wildfire-02_fuel pipelines/02_fuel
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-02_fuel
```

### Tests for 2.1:
```bash
# Build and run
docker build -t wildfire-02_fuel pipelines/02_fuel && echo "PASS: Docker build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-02_fuel && echo "PASS: Pipeline ran" || echo "FAIL"

# File existence
test -f data/fuel/fuel_clipped.tif && echo "PASS: fuel_clipped.tif" || echo "FAIL"
test -f data/fuel/fuel_metadata.json && echo "PASS: metadata" || echo "FAIL"

# Raster alignment test — THIS IS THE CRITICAL TEST
python3 -c "
import rasterio

with rasterio.open('data/fuel/fuel_clipped.tif') as fuel:
    with rasterio.open('data/topography/elevation.tif') as topo:
        assert fuel.width == topo.width, f'Width mismatch: fuel={fuel.width} topo={topo.width}'
        assert fuel.height == topo.height, f'Height mismatch: fuel={fuel.height} topo={topo.height}'
        assert fuel.crs == topo.crs, f'CRS mismatch: fuel={fuel.crs} topo={topo.crs}'
        assert fuel.transform == topo.transform, f'Transform mismatch:\n  fuel={fuel.transform}\n  topo={topo.transform}'
        print(f'PASS: Fuel and topography grids are pixel-aligned ({fuel.width}x{fuel.height})')
"

# Fuel code validation
python3 -c "
import rasterio
import numpy as np

with rasterio.open('data/fuel/fuel_clipped.tif') as src:
    data = src.read(1)
    unique = np.unique(data[data > 0])
    print(f'Fuel codes present: {unique}')
    assert len(unique) > 1, 'Only one fuel code — suspicious'
    assert len(unique) < 100, f'Too many fuel codes ({len(unique)}) — probably not FBFM40'
    nodata_pct = (data <= 0).sum() / data.size * 100
    assert nodata_pct < 50, f'Too much nodata: {nodata_pct:.1f}%'
    print(f'PASS: {len(unique)} unique fuel codes, {nodata_pct:.1f}% nodata')
"
```

---

### Prompt 2.2 — Weather + Fuel Moisture Pipelines

```
Read IMPLEMENTATION_PLAN.md, specifically Step 4 (Weather) and Step 5 (Fuel Moisture).

These are the two simplest pipelines for MVP since we're using synthetic/derived data. Implement both:

PIPELINE 04_weather:

1. Create Dockerfile (python:3.12-slim is fine — no GDAL needed)
2. Create requirements.txt (just json and csv from stdlib, maybe add numpy)
3. Create src/fetch_weather.py:
   - Generate a synthetic fire weather scenario representing hot/dry/windy conditions similar to November 28, 2016 (the day the Gatlinburg fire blew up):
     {
       "wind_speed_kmh": 30,
       "wind_direction_deg": 200,
       "temperature_c": 21,
       "relative_humidity_pct": 18,
       "scenario_name": "hot_dry_southwest_wind",
       "source": "SYNTHETIC — based on Nov 28 2016 Gatlinburg conditions",
       "notes": "REPLACE WITH REAL WEATHER DATA POST-MVP. See IMPLEMENTATION_PLAN.md Step 4 dev notes for RAWS/HRRR integration guidance."
     }
   - Save as data/weather/weather_scenario.json
   - ALSO generate Cell2Fire-compatible Weather.csv:
     Instance,datetime,WS,WD,TMP,RH
     1,2026-01-01 00:00:00,30,200,21,18
     1,2026-01-01 01:00:00,30,200,21,18
     ... (repeat for 24 hours — constant conditions for MVP)
   - Save as data/weather/Weather.csv
   - Write data/weather/weather_metadata.json
4. Create README.md — PROMINENTLY note this is synthetic data

PIPELINE 05_fuel_moisture:

1. Create Dockerfile (python:3.12-slim)
2. Create requirements.txt (numpy)
3. Create src/calc_moisture.py:
   - Read data/weather/weather_scenario.json
   - Calculate equilibrium moisture content (EMC) from temperature and RH:
     EMC is approximated by:
       if RH < 10: EMC = 0.03229 + 0.281073*RH - 0.000578*T*RH
       elif RH < 50: EMC = 2.22749 + 0.160107*RH - 0.01478*T
       else: EMC = 21.0606 + 0.005565*RH^2 - 0.00035*T*RH - 0.483199*RH
     (where T is temp in Celsius, RH is percent)
   - From EMC, derive:
     1hr dead fuel moisture ≈ EMC (fast equilibration)
     10hr dead fuel moisture ≈ EMC * 1.5
     100hr dead fuel moisture ≈ EMC * 2.5
   - Hardcode live fuel moisture for late fall in Smokies:
     live_herb = 30 (cured)
     live_woody = 60
   - Save data/moisture/fuel_moisture.json:
     {
       "dead_1hr_pct": ...,
       "dead_10hr_pct": ...,
       "dead_100hr_pct": ...,
       "live_herb_pct": 30,
       "live_woody_pct": 60,
       "emc_pct": ...,
       "source": "derived_from_synthetic_weather",
       "generated_at": "..."
     }
   - Write metadata and print summary
4. Create README.md

Test both:
  docker build -t wildfire-04_weather pipelines/04_weather
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-04_weather
  docker build -t wildfire-05_fuel_moisture pipelines/05_fuel_moisture
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-05_fuel_moisture
```

### Tests for 2.2:
```bash
# Weather
docker build -t wildfire-04_weather pipelines/04_weather && echo "PASS: Weather build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-04_weather && echo "PASS: Weather ran" || echo "FAIL"

python3 -c "
import json, csv
with open('data/weather/weather_scenario.json') as f:
    w = json.load(f)
assert w['wind_speed_kmh'] > 0, 'No wind'
assert 0 <= w['wind_direction_deg'] <= 360, 'Bad wind dir'
assert 0 < w['relative_humidity_pct'] < 100, 'Bad RH'
print(f'PASS: Weather — {w[\"wind_speed_kmh\"]}km/h from {w[\"wind_direction_deg\"]}°, {w[\"temperature_c\"]}°C, {w[\"relative_humidity_pct\"]}% RH')

with open('data/weather/Weather.csv') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    assert len(rows) >= 12, f'Too few weather rows: {len(rows)}'
    assert 'WS' in rows[0], 'Missing WS column'
    assert 'WD' in rows[0], 'Missing WD column'
    print(f'PASS: Weather.csv — {len(rows)} hourly rows')
"

# Fuel Moisture
docker build -t wildfire-05_fuel_moisture pipelines/05_fuel_moisture && echo "PASS: Moisture build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-05_fuel_moisture && echo "PASS: Moisture ran" || echo "FAIL"

python3 -c "
import json
with open('data/moisture/fuel_moisture.json') as f:
    m = json.load(f)
assert 0 < m['dead_1hr_pct'] < 30, f'Bad 1hr moisture: {m[\"dead_1hr_pct\"]}'
assert m['dead_1hr_pct'] < m['dead_10hr_pct'] < m['dead_100hr_pct'], 'Moisture should increase 1hr < 10hr < 100hr'
assert m['live_herb_pct'] == 30, 'Live herb should be 30'
assert m['live_woody_pct'] == 60, 'Live woody should be 60'
print(f'PASS: Moisture — 1hr={m[\"dead_1hr_pct\"]:.1f}%, 10hr={m[\"dead_10hr_pct\"]:.1f}%, 100hr={m[\"dead_100hr_pct\"]:.1f}%')
"
```

---

### Prompt 2.3 — Grid Assembly Pipeline

```
Read IMPLEMENTATION_PLAN.md, specifically Step 7: Grid Assembly (07_grid_assembly).

This is the most critical integration pipeline. It merges all upstream outputs into Cell2Fire-compatible input files.

1. Create pipelines/07_grid_assembly/Dockerfile (needs GDAL)
2. Create requirements.txt: rasterio, numpy, pandas, geopandas

3. Create pipelines/07_grid_assembly/src/assemble_grid.py:
   
   This script must:
   
   a) Load and VALIDATE alignment of all input rasters:
      - data/fuel/fuel_clipped.tif
      - data/topography/elevation.tif
      - data/topography/slope.tif
      - data/topography/aspect.tif
      Check: same CRS, same dimensions, same transform. If ANY mismatch, print an error with details of the mismatch and exit with code 1. Do not silently continue.
   
   b) Convert fuel raster to Cell2Fire ASCII grid format:
      Save as data/grid/fuels.asc with header:
        ncols <cols>
        nrows <rows>
        xllcorner <x coordinate of lower-left corner>
        yllcorner <y coordinate of lower-left corner>
        cellsize 30
        NODATA_value -9999
      Then the data rows (space-separated values, top row first).
      
      IMPORTANT: Cell2Fire expects fuel codes as integers. LANDFIRE FBFM40 codes like 102 (GR2), 165 (TU5) need to be mapped to Cell2Fire's expected format. For the Rothermel/US fuel model mode, Cell2Fire may expect codes 1-40 corresponding to the Scott & Burgan standard models, or it may accept the raw FBFM codes directly depending on the fork. 
      
      Create a fuel lookup CSV at data/grid/fuel_lookup.csv:
        fbfm_code,fuel_name,cell2fire_code
        91,Urban/Developed,0
        92,Snow/Ice,0
        93,Agriculture,0
        98,Water,0
        99,Barren,0
        101,GR1,1
        102,GR2,2
        ... (map all 40 Scott & Burgan models to sequential 1-40 codes)
        ... (non-burnable codes map to 0)
      
      Apply this mapping when writing fuels.asc. Cells with code 0 are non-burnable.
   
   c) Convert elevation to ASCII grid: data/grid/elevation.asc
   
   d) Copy Weather.csv: cp data/weather/Weather.csv to data/grid/Weather.csv
   
   e) Create fuel moisture content file for Cell2Fire. 
      The format depends on the Cell2Fire version but typically:
      data/grid/FBP_FuelMoistureContent.csv or similar.
      Read data/moisture/fuel_moisture.json and format accordingly.
   
   f) Write data/grid/grid_metadata.json:
      {
        "ncols": ...,
        "nrows": ...,
        "cellsize": 30,
        "xllcorner": ...,
        "yllcorner": ...,
        "crs": "EPSG:5070",
        "total_cells": ...,
        "burnable_cells": ...,
        "non_burnable_cells": ...,
        "fuel_codes_mapped": true,
        "alignment_validated": true,
        "generated_at": "..."
      }
   
   g) Print a comprehensive summary: grid dimensions, fuel distribution after mapping, burnable vs non-burnable percentages.

4. Create README.md

Test:
  docker build -t wildfire-07_grid_assembly pipelines/07_grid_assembly
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-07_grid_assembly
```

### Tests for 2.3:
```bash
docker build -t wildfire-07_grid_assembly pipelines/07_grid_assembly && echo "PASS: Build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-07_grid_assembly && echo "PASS: Ran" || echo "FAIL"

# File existence
for f in fuels.asc elevation.asc Weather.csv grid_metadata.json fuel_lookup.csv; do
    test -f "data/grid/$f" && echo "PASS: $f exists" || echo "FAIL: $f missing"
done

# ASC format validation
python3 -c "
import json

with open('data/grid/grid_metadata.json') as f:
    meta = json.load(f)

# Validate ASC header
with open('data/grid/fuels.asc') as f:
    lines = f.readlines()
    assert lines[0].startswith('ncols'), 'Bad ASC header line 1'
    assert lines[1].startswith('nrows'), 'Bad ASC header line 2'
    ncols = int(lines[0].split()[1])
    nrows = int(lines[1].split()[1])
    assert ncols == meta['ncols'], f'ncols mismatch: ASC={ncols} meta={meta[\"ncols\"]}'
    assert nrows == meta['nrows'], f'nrows mismatch: ASC={nrows} meta={meta[\"nrows\"]}'
    
    # Check first data row
    data_row = lines[6].strip().split()
    assert len(data_row) == ncols, f'Data row has {len(data_row)} values, expected {ncols}'
    print(f'PASS: fuels.asc — {nrows}x{ncols} grid, header valid')

# Same check for elevation
with open('data/grid/elevation.asc') as f:
    lines = f.readlines()
    ncols_elev = int(lines[0].split()[1])
    nrows_elev = int(lines[1].split()[1])
    assert ncols_elev == ncols, 'Elevation/fuel ncols mismatch'
    assert nrows_elev == nrows, 'Elevation/fuel nrows mismatch'
    print(f'PASS: elevation.asc matches fuel grid dimensions')

print(f'PASS: Grid assembled — {meta[\"burnable_cells\"]} burnable of {meta[\"total_cells\"]} total cells')
"
```

---

## Phase 3: Cell2Fire Simulation

### Prompt 3.1 — Cell2Fire Docker Build + Synthetic Test

```
Read IMPLEMENTATION_PLAN.md, specifically Step 9: Cell2Fire Simulation (09_cell2fire).

IMPORTANT: Do this in TWO stages. First build Cell2Fire and test on a tiny synthetic grid. Only after that works, wire it to the real data.

STAGE A — Build Cell2Fire in Docker:

1. Create pipelines/09_cell2fire/Dockerfile:
   
   FROM ubuntu:22.04
   
   Install: g++, make, python3, python3-pip, git, libboost-all-dev
   
   Clone Cell2Fire: git clone https://github.com/cell2fire/Cell2Fire.git /opt/cell2fire
   
   Build the C++ binary:
     cd /opt/cell2fire/cell2fire/Cell2FireC
     make
   
   The binary should be at /opt/cell2fire/cell2fire/Cell2FireC/Cell2Fire
   
   Also pip install: numpy, rasterio, geopandas, shapely
   
   IMPORTANT: If the main Cell2Fire repo doesn't compile or doesn't support US fuel models, try these alternatives in order:
   - https://github.com/fire2a/C2F-W (fire2a fork with broader fuel model support)
   - https://github.com/fire2a/fire2a-lib
   
   The Dockerfile CMD should run src/run_simulation.py

2. Create pipelines/09_cell2fire/src/run_simulation.py — BUT FIRST just make it a test script that:
   a) Generates a tiny 50x50 synthetic grid:
      - fuels.asc: all cells = fuel model 1 (short grass)
      - elevation.asc: flat (all 300m)
      - Weather.csv: constant wind 20 km/h from south
      - Ignitions.csv: center cell ignited
   b) Runs Cell2Fire on this synthetic grid:
      /opt/cell2fire/cell2fire/Cell2FireC/Cell2Fire \
        --input-instance-folder /tmp/test_grid/ \
        --output-folder /tmp/test_output/ \
        --ignitions \
        --sim-years 1 \
        --nsims 1 \
        --grids \
        --final-grid \
        --Fire-Period-Length 1.0 \
        --output-messages \
        --ROS-CV 0.0 \
        --seed 123
   c) Checks that output was generated (fire spread grids exist)
   d) Prints "SYNTHETIC TEST PASSED" if it worked
   e) If Cell2Fire exits with an error, print the full stderr and stdout so we can debug

   IMPORTANT: Cell2Fire's command-line interface varies between versions. If the flags above don't work, run:
     /opt/cell2fire/cell2fire/Cell2FireC/Cell2Fire --help
   And print the help output so we know what flags are available.

   ALSO IMPORTANT: Cell2Fire may expect a specific directory structure for its input:
     instance_folder/
       fuels.asc (or Fuel.asc)
       elevation.asc (or Elevation.asc) 
       Weather.csv
       Ignitions.csv
   The exact expected filenames may vary. Check the Cell2Fire source or documentation.

Build and test:
  docker build -t wildfire-09_cell2fire pipelines/09_cell2fire
  docker run --rm wildfire-09_cell2fire
  
Note: This first test does NOT mount the data volume. It uses internal synthetic data only. We're just proving the C++ binary works.
```

### Tests for 3.1:
```bash
# Build (this will take a while — C++ compilation)
docker build -t wildfire-09_cell2fire pipelines/09_cell2fire && echo "PASS: Docker build with C++ compilation" || echo "FAIL: Build failed"

# Run synthetic test (no data volume needed)
docker run --rm wildfire-09_cell2fire 2>&1 | tee /tmp/cell2fire_test.log
grep -q "SYNTHETIC TEST PASSED" /tmp/cell2fire_test.log && echo "PASS: Cell2Fire runs on synthetic grid" || echo "FAIL: Cell2Fire synthetic test failed — check log"

# If it failed, check for common issues:
grep -i "error" /tmp/cell2fire_test.log && echo "WARN: Errors detected in log"
grep -i "fuel" /tmp/cell2fire_test.log | head -5
```

---

### Prompt 3.2 — Ignition Service

```
Read IMPLEMENTATION_PLAN.md Step 8: Ignition Service.

Implement pipelines/08_ignition:

1. Dockerfile (python:3.12-slim + pyproj, rasterio, numpy)
2. requirements.txt
3. src/set_ignition.py:
   - Check for environment variables IGNITION_LAT and IGNITION_LON
   - If not set, use default: 35.56, -83.75 (ridge south of Townsend — fire would spread north toward town)
   - Read data/grid/grid_metadata.json for grid origin, cellsize, dimensions
   - Convert lat/lon to EPSG:5070
   - Map to grid cell: 
     col = int((x_5070 - xllcorner) / cellsize)
     row = int((yllcorner + nrows*cellsize - y_5070) / cellsize)  # rows count from top
     cell_id = row * ncols + col + 1  # Cell2Fire uses 1-based indexing
   - Validate that the cell falls within the grid and is a burnable fuel type (read fuels.asc and check)
   - If the cell is non-burnable, search nearby cells for a burnable one
   - Write data/grid/Ignitions.csv:
     Year,Ncell
     1,<cell_id>
   - Write data/grid/ignition_metadata.json with lat, lon, projected coords, cell row/col/id, fuel type at ignition point
   - Print summary

4. README.md

Test:
  docker build -t wildfire-08_ignition pipelines/08_ignition
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-08_ignition
```

### Tests for 3.2:
```bash
docker build -t wildfire-08_ignition pipelines/08_ignition && echo "PASS: Build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-08_ignition && echo "PASS: Ran" || echo "FAIL"

test -f data/grid/Ignitions.csv && echo "PASS: Ignitions.csv exists" || echo "FAIL"

python3 -c "
import csv, json
with open('data/grid/Ignitions.csv') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    assert len(rows) == 1, f'Expected 1 ignition, got {len(rows)}'
    cell_id = int(rows[0]['Ncell'])
    assert cell_id > 0, f'Invalid cell ID: {cell_id}'

with open('data/grid/grid_metadata.json') as f:
    meta = json.load(f)
    max_cell = meta['ncols'] * meta['nrows']
    assert cell_id <= max_cell, f'Cell ID {cell_id} exceeds grid size {max_cell}'

with open('data/grid/ignition_metadata.json') as f:
    ig = json.load(f)
    assert 35.0 < ig['lat'] < 36.0, f'Ignition lat out of range: {ig[\"lat\"]}'
    print(f'PASS: Ignition at ({ig[\"lat\"]:.4f}, {ig[\"lon\"]:.4f}), cell {cell_id}')
"

---

### Prompt 3.3 — Wire Cell2Fire to Real Data

```
Read IMPLEMENTATION_PLAN.md Step 9 again. The synthetic test from Prompt 3.1 should be passing and
pipeline 08 (Ignitions.csv) should already exist from Prompt 3.2.

Now update pipelines/09_cell2fire/src/run_simulation.py to:

1. Keep the synthetic test as a function that can be called with a --test flag
2. In normal mode (no --test flag), run on real data:
   a) Read data/grid/grid_metadata.json for grid dimensions and parameters
   b) Verify required input files exist:
      - data/grid/fuels.asc
      - data/grid/elevation.asc
      - data/grid/Weather.csv
      - data/grid/Ignitions.csv  ← written by pipeline 08
      If any are missing, print which files are missing and exit with code 1.
   c) Prepare the Cell2Fire input directory (/tmp/c2f_real_input/):
      - Copy fuels.asc, elevation.asc, Ignitions.csv
      - Copy spain_lookup_table.csv from /opt/C2F-W/spain_lookup_table.csv
      - IMPORTANT: Translate Weather.csv format before copying.
        data/grid/Weather.csv has columns Instance,datetime,WS,WD,TMP,RH (pipeline 04 format).
        C2F-W S&B mode needs Instance,datetime,WS,WD,FireScenario.
        Write a translated copy: keep Instance/datetime/WS/WD, drop TMP and RH,
        add FireScenario=2 (matches official C2F-W S&B examples).
   d) Run Cell2Fire on the real grid with appropriate flags
   e) Parse outputs:
      - Read the fire spread grids from the output (Grids/Grids1/ForestGrid*.csv)
      - Each ForestGrid is a flat array of nrows*ncols values (0=unburned, 1=burned)
      - Convert the final burn scar grid to a GeoTIFF using grid_metadata.json
        (use xllcorner, yllcorner, cellsize, nrows, ncols, crs to build the rasterio transform)
      - Convert the final burn scar to a GeoJSON polygon (vectorize the burned cells using
        rasterio.features.shapes)
      - Save as:
        data/simulation/burn_scar.tif
        data/simulation/fire_perimeter_final.geojson
      - Compute summary stats from Cell2Fire stdout (or from the grids directly):
        total_cells_burned, total_area_burned_ha, simulation_hours, max_ros (set to null if unavailable)
      - Save as data/simulation/summary.json
   f) Convert each per-timestep ForestGrid*.csv to a GeoTIFF in data/simulation/grids/
      Name them grid_t000.tif, grid_t001.tif, etc.
      These will be used for the fire animation in the web UI.

Test:
  docker build -t wildfire-09_cell2fire pipelines/09_cell2fire

  # Synthetic test still works
  docker run --rm wildfire-09_cell2fire python3 src/run_simulation.py --test

  # Real data mode (requires pipelines 02-08 to have run)
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-09_cell2fire
```

### Tests for 3.3:
```bash
# Synthetic test still works
docker run --rm wildfire-09_cell2fire python3 /app/src/run_simulation.py --test 2>&1 | grep -q "SYNTHETIC TEST PASSED" && echo "PASS: Synthetic test" || echo "FAIL"

# Real data test (requires phases 1-2 complete)
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-09_cell2fire && echo "PASS: Real simulation ran" || echo "FAIL"

# Output validation
test -f data/simulation/fire_perimeter_final.geojson && echo "PASS: Fire perimeter GeoJSON" || echo "FAIL"
test -f data/simulation/summary.json && echo "PASS: Summary JSON" || echo "FAIL"

python3 -c "
import json
with open('data/simulation/summary.json') as f:
    s = json.load(f)
assert s['total_cells_burned'] > 0, 'No cells burned — simulation may have failed silently'
assert s['total_area_burned_ha'] > 0, 'No area burned'
print(f'PASS: Simulation burned {s[\"total_cells_burned\"]} cells ({s[\"total_area_burned_ha\"]:.0f} ha)')
"

python3 -c "
import json
with open('data/simulation/fire_perimeter_final.geojson') as f:
    gj = json.load(f)
assert gj['type'] in ('FeatureCollection', 'Feature'), f'Bad GeoJSON type: {gj[\"type\"]}'
if gj['type'] == 'FeatureCollection':
    assert len(gj['features']) > 0, 'Empty FeatureCollection'
print('PASS: Fire perimeter is valid GeoJSON')
"
```

---

## Phase 4: Assets, Consequence, Web UI

### Prompt 4.1 — Assets Pipeline

```
Read IMPLEMENTATION_PLAN.md Step 6: Assets & Exposure Pipeline.

Implement pipelines/06_assets:

1. Dockerfile (needs GDAL + network access for downloading building data)
2. requirements.txt: geopandas, requests, rasterio, shapely, numpy

3. src/fetch_assets.py:
   - Read data/input/aoi_metadata.json and data/input/aoi_reprojected.shp
   
   BUILDINGS:
   - Use the OpenStreetMap Overpass API to fetch buildings within the AOI bbox:
     URL: https://overpass-api.de/api/interpreter
     Query: 
       [out:json][timeout:120];
       (way["building"](south,west,north,east);
        relation["building"](south,west,north,east););
       out body; >; out skel qt;
     Where south/west/north/east come from bbox_4326
   - Parse the response into GeoDataFrame with building polygons
   - If Overpass API fails or returns too few buildings (<10), fall back to generating SYNTHETIC buildings:
     Place 200-400 random building points concentrated in the Townsend valley (lower elevations, near roads)
     This is acceptable for MVP — note it clearly in metadata
   - Reproject to EPSG:5070
   - Save as data/assets/buildings.geojson
   
   POPULATION:
   - For MVP, estimate population from building count: assume 2.3 people per residential building
   - Create a simple population point layer from building centroids with estimated_pop attribute
   - Save as data/assets/population.geojson
   - Future: use Census block-level data
   
   INFRASTRUCTURE:
   - Use Overpass API to fetch major roads (highway=primary,secondary,tertiary) and power lines (power=line) in AOI
   - Save as data/assets/infrastructure.geojson
   - If API fails, this is optional for MVP — create empty GeoJSON
   
   Write data/assets/assets_metadata.json:
   {
     "total_buildings": ...,
     "estimated_population": ...,
     "road_segments": ...,
     "power_line_segments": ...,
     "source": "OpenStreetMap Overpass API",
     "generated_at": "..."
   }

4. README.md

Test:
  docker build -t wildfire-06_assets pipelines/06_assets
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-06_assets
```

### Tests for 4.1:
```bash
docker build -t wildfire-06_assets pipelines/06_assets && echo "PASS: Build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-06_assets && echo "PASS: Ran" || echo "FAIL"

test -f data/assets/buildings.geojson && echo "PASS: buildings.geojson" || echo "FAIL"
test -f data/assets/assets_metadata.json && echo "PASS: metadata" || echo "FAIL"

python3 -c "
import json
with open('data/assets/buildings.geojson') as f:
    gj = json.load(f)
if gj['type'] == 'FeatureCollection':
    n = len(gj['features'])
else:
    n = 1
assert n > 0, 'No buildings found'
print(f'PASS: {n} buildings loaded')

with open('data/assets/assets_metadata.json') as f:
    meta = json.load(f)
print(f'PASS: {meta[\"total_buildings\"]} buildings, est. pop {meta[\"estimated_population\"]}')
"
```

---

### Prompt 4.2 — Consequence Analysis

```
Read IMPLEMENTATION_PLAN.md Step 10: Consequence Analysis.

Implement pipelines/10_consequence:

1. Dockerfile (needs GDAL)
2. requirements.txt: geopandas, rasterio, shapely, numpy

3. src/analyze.py:
   - Load data/simulation/fire_perimeter_final.geojson
   - Load data/assets/buildings.geojson
   - Load data/assets/infrastructure.geojson (if exists)
   - Load data/assets/assets_metadata.json
   
   BUILDING EXPOSURE:
   - Spatial join: find all buildings within or intersecting the fire perimeter
   - Save exposed buildings as data/consequence/exposed_buildings.geojson
   
   POPULATION AT RISK:
   - Sum estimated_pop for all exposed buildings (or use population.geojson)
   
   INFRASTRUCTURE:
   - If infrastructure.geojson exists, intersect with fire perimeter
   - Count road segments and power line segments exposed
   
   FIRE ARRIVAL TIME (if per-timestep grids exist):
   - For each exposed building, find the simulation timestep when fire reached that cell
   - Calculate "time to first structure" = minimum fire arrival time across all exposed buildings
   
   Write data/consequence/consequence_summary.json:
   {
     "total_area_burned_ha": ...,
     "total_area_burned_acres": ...,
     "structures_exposed": ...,
     "estimated_population_at_risk": ...,
     "infrastructure_exposed": {
       "road_segments": ...,
       "power_line_segments": ...
     },
     "fire_arrival_to_first_structure_hrs": ...,
     "generated_at": "..."
   }
   
   Also copy key outputs to data/output/:
   - data/output/consequence_summary.json
   - data/output/exposed_buildings.geojson
   - data/output/fire_perimeter.geojson (copy from simulation)
   
   Print full summary to stdout.

4. README.md

Test:
  docker build -t wildfire-10_consequence pipelines/10_consequence
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-10_consequence
```

### Tests for 4.2:
```bash
docker build -t wildfire-10_consequence pipelines/10_consequence && echo "PASS: Build" || echo "FAIL"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-10_consequence && echo "PASS: Ran" || echo "FAIL"

test -f data/consequence/consequence_summary.json && echo "PASS: summary" || echo "FAIL"
test -f data/consequence/exposed_buildings.geojson && echo "PASS: exposed buildings" || echo "FAIL"
test -f data/output/consequence_summary.json && echo "PASS: output copy" || echo "FAIL"

python3 -c "
import json
with open('data/consequence/consequence_summary.json') as f:
    s = json.load(f)
assert 'structures_exposed' in s, 'Missing structures_exposed'
assert 'estimated_population_at_risk' in s, 'Missing population'
assert s['total_area_burned_ha'] > 0, 'No area burned'
print(f'PASS: {s[\"structures_exposed\"]} structures exposed, {s[\"estimated_population_at_risk\"]} people at risk, {s[\"total_area_burned_ha\"]:.0f} ha burned')
"
```

---

### Prompt 4.3 — Web UI

```
Read IMPLEMENTATION_PLAN.md Step 11: Web UI.

Implement pipelines/11_web_ui:

1. Dockerfile:
   - python:3.12-slim
   - Install: fastapi, uvicorn, geopandas, shapely
   - Expose port 8000
   - CMD: uvicorn src.app:app --host 0.0.0.0 --port 8000

2. requirements.txt

3. src/app.py — FastAPI application:
   
   Endpoints:
   - GET / — serve the Leaflet HTML page
   - GET /api/aoi — return AOI boundary as GeoJSON (read from data/input/aoi_reprojected.shp, convert to EPSG:4326 for Leaflet)
   - GET /api/fire-perimeter — return fire perimeter as GeoJSON in EPSG:4326
   - GET /api/buildings/exposed — return exposed buildings as GeoJSON in EPSG:4326
   - GET /api/buildings/all — return all buildings as GeoJSON in EPSG:4326
   - GET /api/summary — return consequence_summary.json
   - GET /api/ignition — return ignition point as GeoJSON in EPSG:4326
   
   IMPORTANT: All GeoJSON served to Leaflet MUST be in EPSG:4326 (lat/lon). The data files are in EPSG:5070. Convert on the fly using geopandas .to_crs(epsg=4326) before serializing.
   
   Handle missing files gracefully — if a pipeline hasn't been run yet, return an empty FeatureCollection instead of crashing.

4. templates/index.html — Leaflet map:
   
   - Use Leaflet 1.9.x from CDN
   - Basemap: OpenStreetMap tiles (or USGS topo: https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x})
   - On page load, fetch all API endpoints and add as layers:
     - AOI boundary: blue dashed outline, no fill
     - Fire perimeter: red fill, 40% opacity
     - All buildings: small gray circles
     - Exposed buildings: orange/red circles, larger
     - Ignition point: red marker with label "Ignition"
   - Layer control (toggle layers on/off)
   - Sidebar or overlay panel showing consequence summary:
     - Area burned (ha and acres)
     - Structures exposed
     - Population at risk
     - Time to first structure (if available)
   - Auto-zoom to fit the AOI boundary
   - Style should be clean and functional, dark theme preferred
   
   Keep it simple — no React, no build step. Plain HTML + JS + Leaflet CDN.

5. README.md

Test:
  docker build -t wildfire-11_web_ui pipelines/11_web_ui
  docker run --rm --env-file .env -v $(pwd)/data:/data -p 8000:8000 wildfire-11_web_ui
  
  Then open http://localhost:8000 in a browser.
```

### Tests for 4.3:
```bash
docker build -t wildfire-11_web_ui pipelines/11_web_ui && echo "PASS: Build" || echo "FAIL"

# Start in background
docker run -d --name wildfire-ui --env-file .env -v $(pwd)/data:/data -p 8000:8000 wildfire-11_web_ui
sleep 3

# API tests
curl -s http://localhost:8000/ | grep -q "Leaflet" && echo "PASS: HTML page serves" || echo "FAIL"
curl -s http://localhost:8000/api/summary | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'PASS: Summary API — {d[\"structures_exposed\"]} structures')" 2>/dev/null || echo "FAIL: Summary API"
curl -s http://localhost:8000/api/aoi | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['type']=='FeatureCollection'; print('PASS: AOI API')" 2>/dev/null || echo "FAIL: AOI API"
curl -s http://localhost:8000/api/fire-perimeter | python3 -c "import sys,json; d=json.load(sys.stdin); print('PASS: Fire perimeter API')" 2>/dev/null || echo "FAIL: Fire perimeter API"
curl -s http://localhost:8000/api/buildings/exposed | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'PASS: Exposed buildings API — {len(d.get(\"features\",[]))} features')" 2>/dev/null || echo "FAIL: Exposed buildings API"

# Cleanup
docker stop wildfire-ui && docker rm wildfire-ui
```

---

## Phase 5: End-to-End Integration + Polish

### Prompt 5.1 — Full Pipeline Run

```
All individual pipelines should now be implemented. Let's test the complete end-to-end flow.

1. First, update the Makefile if any target names or Docker image names changed during implementation. Make sure `make all` runs steps 01 through 10 in order and `make ui` launches the web UI.

2. Run `make clean` to clear all intermediate data.

3. Run `make all` and capture the full output. If any step fails:
   - Read the error message
   - Fix the issue in the failing pipeline
   - Re-run from that step (e.g., `make run-07` if grid assembly failed)
   - Do NOT skip steps

4. After `make all` completes successfully, run `make ui` and verify the web UI shows:
   - The AOI boundary around Townsend
   - A fire perimeter polygon
   - Building points (exposed ones highlighted)
   - Summary statistics in the sidebar

5. Add a `make test` target to the Makefile that runs all the validation tests from this prompt file in sequence. It should print PASS/FAIL for each and a final summary.

6. Update every pipeline's README.md to reflect what was actually built (not what was planned). Each README should document:
   - What the pipeline does (1-2 sentences)
   - Input files it reads (with paths)
   - Output files it produces (with paths)
   - Docker image name
   - How to run standalone: the exact docker run command
   - Any known limitations or synthetic data warnings
   - Dependencies (Python packages and system libs)

7. Create a top-level README.md for the repo that explains:
   - What this project is
   - Prerequisites (Docker, WSL, make)
   - Quick start: `make all && make ui` then open http://localhost:8000
   - Architecture overview (reference the diagrams)
   - Pipeline descriptions (brief, link to each pipeline's README)
   - Known limitations
   - Future roadmap (reference IMPLEMENTATION_PLAN.md)
```

### Tests for 5.1:
```bash
# Clean slate test
make clean
make all 2>&1 | tee /tmp/full_pipeline.log
echo "Exit code: $?"

# Check all critical output files exist
for f in \
    data/input/aoi_metadata.json \
    data/fuel/fuel_clipped.tif \
    data/topography/elevation.tif \
    data/topography/slope.tif \
    data/weather/Weather.csv \
    data/moisture/fuel_moisture.json \
    data/grid/fuels.asc \
    data/grid/Ignitions.csv \
    data/simulation/fire_perimeter_final.geojson \
    data/simulation/summary.json \
    data/consequence/consequence_summary.json \
    data/output/consequence_summary.json; do
    test -f "$f" && echo "PASS: $f" || echo "FAIL: $f MISSING"
done

# Final integration validation
python3 -c "
import json

with open('data/simulation/summary.json') as f:
    sim = json.load(f)
with open('data/consequence/consequence_summary.json') as f:
    con = json.load(f)

print('=== FINAL RESULTS ===')
print(f'Area burned: {con[\"total_area_burned_ha\"]:.0f} ha ({con[\"total_area_burned_acres\"]:.0f} acres)')
print(f'Structures exposed: {con[\"structures_exposed\"]}')
print(f'Population at risk: {con[\"estimated_population_at_risk\"]}')
print(f'Cells burned: {sim[\"total_cells_burned\"]}')
print()

# Sanity checks
assert con['total_area_burned_ha'] > 10, 'Suspiciously small burn area'
assert con['total_area_burned_ha'] < 15000, 'Suspiciously large burn area (entire AOI burned?)'
assert con['structures_exposed'] >= 0, 'Negative structures?'
print('ALL SANITY CHECKS PASSED')
"

# Web UI smoke test
docker run -d --name wildfire-ui-final --env-file .env -v $(pwd)/data:/data -p 8000:8000 wildfire-11_web_ui
sleep 3
curl -sf http://localhost:8000/ > /dev/null && echo "PASS: Web UI is serving" || echo "FAIL: Web UI not responding"
curl -sf http://localhost:8000/api/summary | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'PASS: Web UI API working — reporting {d[\"structures_exposed\"]} exposed structures')
"
docker stop wildfire-ui-final && docker rm wildfire-ui-final

echo ""
echo "=== END-TO-END TEST COMPLETE ==="
```

---

## Troubleshooting Reference

Include this section in your repo. When Claude Code hits a wall on a specific prompt, paste the relevant section below into the follow-up prompt.

### GDAL won't install in Docker
```
Try these base images in order:
1. ghcr.io/osgeo/gdal:ubuntu-small-3.9.3 (has GDAL pre-installed, add python3-pip)
2. python:3.12-slim with: apt-get install -y libgdal-dev gdal-bin && pip install GDAL==$(gdal-config --version)
3. ubuntu:22.04 with: apt-get install -y python3-pip gdal-bin libgdal-dev python3-gdal
```

### Cell2Fire won't compile
```
Common issues:
- Missing Boost: apt-get install -y libboost-all-dev
- Missing make: apt-get install -y build-essential
- Wrong directory: the Makefile is in cell2fire/Cell2FireC/, not the repo root
- Try the fire2a fork: https://github.com/fire2a/C2F-W
```

### Cell2Fire runs but nothing burns
```
Common causes:
- Ignition cell is on a non-burnable fuel type (water, urban, barren)
- Fuel model codes don't match what Cell2Fire expects
- Weather CSV format is wrong (check column names exactly)
- Fuel moisture is too high (fire won't spread in wet fuel)
- Fire-Period-Length is too short (try 1.0 = 1 hour steps)
```

### Grid alignment errors
```
Always compute transforms from the same source:
  from rasterio.transform import from_bounds
  transform = from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)
Where xmin/ymin/xmax/ymax come from aoi_metadata.json bbox_5070
and ncols/nrows come from aoi_metadata.json grid_cols/grid_rows

NEVER let individual pipelines compute their own bounds — always reference the canonical aoi_metadata.json.
```

### Overpass API timeout or rate limit
```
- Add a 2-second delay between requests
- Reduce bbox size (fetch a slightly smaller area)
- Use a mirror: https://overpass.kumi.systems/api/interpreter
- Fall back to synthetic building data (documented in the prompt)
```
