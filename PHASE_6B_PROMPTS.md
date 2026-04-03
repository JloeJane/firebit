# Claude Code Prompts — Phase 6B: Data Realism Bundle

## Goal

Eliminate all synthetic data from the platform. After this phase every pipeline
produces outputs derived from real observations or real geospatial products.
No hardcoded values, no fallback fabrications.

## Current synthetic data inventory

| Pipeline | What is synthetic | Fix |
|----------|-------------------|-----|
| 02_fuel | Elevation-band fuel codes when LFPS fails | Rewrite with `landfire` Python package (no auth needed); cache by AOI bbox |
| 04_weather | Hardcoded Nov 28 2016 Gatlinburg values | NOAA HRRR via herbie; IEM RAWS fallback |
| 05_fuel_moisture | Dead: Nelson EMC from fake weather; Live: hardcoded 30/60% | Dead auto-real once 04 is real; Live from WFAS NFMD RAWS |
| 06_assets | 300 random buildings when OSM < 10 results | Remove fallback; use whatever OSM returns |

## How to use this file

Run each prompt sequentially. Do not proceed to the next until all acceptance
tests pass. Prompts are ordered by dependency — 6B.1 and 6B.2 can be run in
either order; 6B.3 depends on 6B.2; 6B.4 is independent; 6B.5 depends on all.

**Prompt order:**
1. 6B.1 — Real fuel data (Pipeline 02)
2. 6B.2 — Real weather via HRRR (Pipeline 04)
3. 6B.3 — Real live fuel moisture (Pipeline 05)
4. 6B.4 — Remove synthetic building fallback (Pipeline 06)
5. 6B.5 — Multi-scenario comparison UI (Pipeline 11)

---

## Prompt 6B.1 — Real Fuel Data

```
Read these files in full before making any changes:
  - pipelines/02_fuel/src/fetch_fuel.py
  - pipelines/02_fuel/requirements.txt
  - pipelines/02_fuel/Dockerfile
  - data/input/aoi_metadata.json

Goal: replace the entire manual LFPS implementation in fetch_fuel.py with the
`landfire` Python package (pip name: landfire). No account registration is
required — the LFPS API is open. The package handles job submission, polling,
and download automatically. The pipeline must work for any AOI, not just
Townsend: derive the bbox from aoi_metadata.json.

### Background

The `landfire` package (landfire-python) is a maintained wrapper around the
LFPS REST API. It handles the async job lifecycle automatically.

  from landfire import Landfire
  from landfire.geospatial import get_bbox_from_file
  from landfire.product.search import ProductSearch

The pipeline currently has a manual LFPS implementation (approach_a_lfps) that
was failing with empty responses, plus a synthetic elevation-band fallback.
Both are to be deleted. The landfire package replaces both.

### Complete rewrite of fetch_fuel.py

Delete all existing code and write a clean implementation:

#### 1. Derive bbox from aoi_metadata.json

Read bbox_4326 from /data/input/aoi_metadata.json:
  bbox_4326 = {"west": ..., "south": ..., "east": ..., "north": ...}
  bbox_str = f"{bbox_4326['west']} {bbox_4326['south']} {bbox_4326['east']} {bbox_4326['north']}"

Do NOT use get_bbox_from_file() — the shapefile at /data/input/aoi_reprojected.shp
is in EPSG:5070, and the landfire package expects WGS84 (lon/lat). The bbox
from aoi_metadata.json is already in WGS84.

#### 2. Check cache before downloading

Cache path: /data/fuel/cache/landfire_fbfm40_<bbox_hash>.zip
bbox_hash: 8-char MD5 of the bbox string rounded to 4 decimal places per
coordinate (prevents re-download when floating-point noise changes last digits).

  import hashlib
  rounded = f"{round(w,4)} {round(s,4)} {round(e,4)} {round(n,4)}"
  bbox_hash = hashlib.md5(rounded.encode()).hexdigest()[:8]
  cache_zip = f"/data/fuel/cache/landfire_fbfm40_{bbox_hash}.zip"

If the cache zip exists, skip the download and go straight to unzip + reproject.

#### 3. Download via landfire package

  from landfire import Landfire

  os.makedirs("/data/fuel/cache", exist_ok=True)
  lf = Landfire(bbox=bbox_str, resample_res=30)
  lf.request_data(
      layers=["240FBFM40"],
      output_path=cache_zip,
  )

Layer code "240FBFM40" is FBFM40 from the LF2024 (version 240) product.
If this code raises a product-not-found error, use ProductSearch to find
the current FBFM40 code and use that instead:
  from landfire.product.search import ProductSearch
  ps = ProductSearch()
  results = ps.search(names=["FBFM40"])
  # Use the code from the most recent available product version

Print progress: "Downloading LANDFIRE FBFM40 via landfire package..."
The request_data() call is synchronous — it blocks until the job completes
and the zip is downloaded. It may take 2–5 minutes.

#### 4. Unzip and locate the GeoTIFF

  import zipfile
  extract_dir = "/data/fuel/cache/extracted"
  with zipfile.ZipFile(cache_zip) as zf:
      zf.extractall(extract_dir)
  tif_files = list(Path(extract_dir).rglob("*.tif"))
  assert tif_files, f"No .tif found in zip: {list(Path(extract_dir).rglob('*'))}"
  raw_tif = str(tif_files[0])

#### 5. Reproject to AOI grid

Use the existing reproject_fuel_raw() function — it is correct and should be
kept unchanged. It reprojects from the raw LANDFIRE CRS to EPSG:5070, snapped
to the exact grid dimensions from aoi_metadata.json.

#### 6. Save outputs

Use the existing save_fuel_tif() and write_csv_and_metadata() functions —
they are correct, keep them unchanged.

Source label: "LANDFIRE FBFM40 2024 (LF240) via landfire package"

#### 7. Remove all synthetic code

Delete:
  - approach_a_lfps(), lfps_submit_job(), lfps_poll_job(), lfps_download()
  - approach_synthetic()
  - ELEV_FUEL_BANDS constant
  - All LFPS_SUBMIT / LFPS_BASE URL constants
  - All code that writes or deletes SYNTHETIC_DATA_WARNING.txt

If the landfire download fails (network error, package error), let the
exception propagate — do not catch and fall back. The Docker container will
exit non-zero and the error message will be visible in the terminal.

### Changes to requirements.txt

Replace the existing contents with:
  landfire
  rasterio
  geopandas
  numpy
  requests

Remove any LFPS-related packages that were added before.

### Changes to Dockerfile

Keep the existing libexpat1 install. No additional system packages needed.
The landfire package is pure Python.

  FROM python:3.12-slim

  RUN apt-get update && apt-get install -y --no-install-recommends \
      libexpat1 \
      && rm -rf /var/lib/apt/lists/*

  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY src/ src/
  CMD ["python", "src/fetch_fuel.py"]

### Cache directory

The Makefile mounts $(PWD)/data:/data. Create data/fuel/cache/ in the repo
(add a .gitkeep so the directory is tracked, and add data/fuel/cache/*.zip
and data/fuel/cache/extracted/ to .gitignore).

### Acceptance tests

Run these after `make run-02` (first run will take several minutes to download):

  # 1. No synthetic warning file
  test ! -f data/fuel/SYNTHETIC_DATA_WARNING.txt && echo "PASS: no synthetic warning" || echo "FAIL: synthetic warning still present"

  # 2. fuel_clipped.tif exists with correct shape and real fuel codes
  python3 -c "
  import rasterio, numpy as np
  with rasterio.open('data/fuel/fuel_clipped.tif') as ds:
      d = ds.read(1)
      valid = d[d > 0]
      assert len(valid) > 10000, f'Too few valid cells: {len(valid)}'
      assert d.shape == (421, 434), f'Wrong shape: {d.shape}'
      codes = set(int(x) for x in np.unique(valid))
      print(f'PASS: {len(valid):,} valid cells, shape {d.shape}, fuel codes: {sorted(codes)}')
  "

  # 3. Source label is landfire package, not SYNTHETIC
  python3 -c "
  import json
  m = json.load(open('data/fuel/fuel_metadata.json'))
  src = m['source']
  assert 'SYNTHETIC' not in src, f'Still synthetic: {src}'
  assert 'LANDFIRE' in src, f'Not LANDFIRE: {src}'
  print(f'PASS: source = {src}')
  "

  # 4. Cache zip exists for this AOI
  python3 -c "
  import glob
  files = glob.glob('data/fuel/cache/landfire_fbfm40_*.zip')
  assert files, 'No cache zip found'
  print(f'PASS: cache: {files[0]}')
  "

  # 5. Second run uses cache (completes in <10 seconds, no download)
  time make run-02
  # Should print 'Using cached LANDFIRE tile' and finish quickly

  # 6. Full pipeline still passes
  make test

### Known landmines

- The landfire package's request_data() writes a progress log to stdout.
  If it raises an exception about an invalid layer code, use ProductSearch
  to find the correct code for the current LANDFIRE version. Layer codes
  change between product versions (e.g. 200FBFM40 for LF2020, 220FBFM40
  for LF2022, 240FBFM40 for LF2024).

- The downloaded zip contains a multi-band GeoTIFF in LANDFIRE's native
  Albers projection (similar to EPSG:5070 but not identical). The existing
  reproject_fuel_raw() handles this correctly via rasterio.warp.reproject.

- The landfire package may write temp files to the current working directory.
  Inside Docker, /app is the working directory. This is fine — they are
  discarded when the container exits.

- If the download takes longer than Docker's default timeout, increase the
  timeout in the Makefile DOCKER_RUN variable or add --timeout to request_data.
  The landfire package's default poll interval is 5s with no cap on wait time.

- After caching, the extracted/ subdirectory can be large (several hundred MB
  for a full state tile). Add it to .gitignore. The pipeline only needs the
  zip on disk; delete extracted/ after reprojecting if disk space is a concern.
```

---

## Prompt 6B.2 — Real Weather via HRRR

```
Read these files in full before making any changes:
  - pipelines/04_weather/src/fetch_weather.py
  - pipelines/04_weather/requirements.txt
  - pipelines/04_weather/Dockerfile
  - pipelines/05_fuel_moisture/src/calc_moisture.py
  - data/input/aoi_metadata.json

Goal: replace the hardcoded synthetic weather scenario with real NOAA HRRR
analysis data fetched via the herbie Python package. The pipeline must read
the target date from an environment variable so it works for any fire scenario,
not just Gatlinburg 2016.

### Background

HRRR (High-Resolution Rapid Refresh) is NOAA's 3km hourly surface model.
Historical HRRR archives are available on AWS (s3://noaa-hrrr-bdp-pds/) and
GCS, accessible via the herbie package without credentials.

The herbie package:
  from herbie import Herbie
  H = Herbie("2016-11-28 18:00", model="hrrr", product="sfc", fxx=0)

fxx=0 is the analysis hour (no forecast offset). herbie automatically selects
the best available archive (AWS or GCS).

### Environment variable

Read WEATHER_DATE from os.environ. Default: "2016-11-28 18:00" (peak of the
Gatlinburg fire). Format: "YYYY-MM-DD HH:MM" UTC. Add WEATHER_DATE= to
.env if it doesn't already exist there (leave the value blank so the default
is used unless overridden).

### HRRR variables to extract

For each analysis hour, extract at the AOI centroid (lat/lon from
aoi_metadata.json → centroid_lat_4326, centroid_lon_4326):

  - TMP:2 m above ground       → temperature (°C, convert from K)
  - RH:2 m above ground        → relative humidity (%)
  - UGRD:10 m above ground     → U-component wind (m/s)
  - VGRD:10 m above ground     → V-component wind (m/s)

Convert U/V to wind speed and direction:
  ws_ms  = sqrt(U² + V²)
  ws_kmh = ws_ms * 3.6
  wd_deg = (270 - degrees(atan2(V, U))) % 360   # meteorological convention

### Fetching 24 hourly rows

Fetch HRRR analyses for hours 0–23 of WEATHER_DATE (24 separate Herbie
objects, fxx=0 for each). If a specific hour fails to download, interpolate
from the nearest available hours rather than failing. If fewer than 6 hours
are available, fall through to the RAWS fallback.

Use herbie's ds = H.xarray("TMP:2 m") to get an xarray Dataset, then
interpolate to the AOI centroid using ds.interp(latitude=lat, longitude=lon).
Repeat for each variable.

### RAWS fallback

If HRRR fetch fails entirely (network error, date out of archive range, etc.):
use the Iowa Environmental Mesonet (IEM) ASOS/RAWS API to fetch hourly
observations from the nearest station within 150km of the AOI centroid.

IEM endpoint:
  https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
  ?station=<STATION_ID>&data=tmpf,relh,sknt,drct
  &year1=YYYY&month1=MM&day1=DD
  &year2=YYYY&month2=MM&day2=DD
  &tz=UTC&format=onlycomma&latlon=yes&elev=yes

To find the nearest station: query
  https://mesonet.agron.iastate.edu/geojson/network.geojson?network=TN_ASOS
to get station list, then pick the nearest by haversine distance to AOI
centroid. Temperature is in °F — convert to °C. Wind speed is in knots —
convert to km/h (× 1.852). If the IEM station has no data for the date,
sys.exit(1) with a clear message.

### Output format (unchanged)

The output file format consumed by downstream pipelines must not change:

data/weather/Weather.csv columns: Instance,datetime,WS,WD,TMP,RH
  - WS in km/h
  - WD in degrees (meteorological: 0=N, 90=E, 180=S, 270=W)
  - TMP in °C
  - RH in percent
  - 24 hourly rows, Instance=1 for all

data/weather/weather_scenario.json must retain these keys (pipeline 05
reads them):
  - wind_speed_kmh       (representative value — use hour 18 or daily mean)
  - wind_direction_deg   (same)
  - temperature_c
  - relative_humidity_pct
  - source               (e.g. "NOAA HRRR analysis 2016-11-28 via herbie")

data/weather/weather_metadata.json:
  - Remove "data_type": "SYNTHETIC" and "warning" keys
  - Add "source": "HRRR" or "RAWS_IEM" depending on which path was used
  - Add "weather_date": the WEATHER_DATE value used
  - Add "station_id" if RAWS path was taken

### Changes to requirements.txt

Replace: numpy==2.2.4
Add:
  herbie-data
  cfgrib
  eccodes
  xarray
  scipy
  requests
  numpy

(herbie-data is the pip package name; it installs as `herbie`)

### Changes to Dockerfile

herbie requires eccodes system library for GRIB2 decoding:
  RUN apt-get update && apt-get install -y --no-install-recommends libeccodes-dev && rm -rf /var/lib/apt/lists/*

### Acceptance tests

Run these after `make run-04`:

  # 1. Weather.csv has 24 rows with non-constant, non-zero WS
  python3 -c "
  import csv
  rows = list(csv.DictReader(open('data/weather/Weather.csv')))
  assert len(rows) == 24, f'Expected 24 rows, got {len(rows)}'
  ws_vals = [float(r['WS']) for r in rows]
  assert max(ws_vals) > 0, 'All wind speeds are zero'
  print(f'PASS: 24 rows, WS range {min(ws_vals):.1f}–{max(ws_vals):.1f} km/h')
  "

  # 2. No SYNTHETIC in source
  python3 -c "
  import json
  m = json.load(open('data/weather/weather_metadata.json'))
  assert m.get('source','') not in ('', 'SYNTHETIC'), f'Bad source: {m.get(\"source\")}'
  assert 'SYNTHETIC' not in str(m), f'SYNTHETIC still in metadata: {m}'
  print(f'PASS: source={m[\"source\"]}')
  "

  # 3. weather_scenario.json has all keys pipeline 05 needs
  python3 -c "
  import json
  s = json.load(open('data/weather/weather_scenario.json'))
  for k in ['temperature_c','relative_humidity_pct','wind_speed_kmh','wind_direction_deg']:
      assert k in s, f'Missing key: {k}'
      assert isinstance(s[k], (int,float)), f'Non-numeric: {k}={s[k]}'
  print('PASS: all required keys present and numeric')
  "

  # 4. Temperatures are in Celsius range (not Kelvin, not Fahrenheit)
  python3 -c "
  import json
  s = json.load(open('data/weather/weather_scenario.json'))
  t = s['temperature_c']
  assert -40 < t < 60, f'Temperature out of Celsius range: {t}'
  print(f'PASS: temperature_c = {t}°C')
  "

  # 5. Pipelines 05 and 07 still pass after the weather change
  make run-05 && make run-07

### Known landmines

- herbie downloads GRIB2 files to a local cache (~/.herbie/ by default).
  Inside Docker this cache lives inside the container and is discarded on
  exit. That is fine — the pipeline only needs to run once per Weather.csv.
  Set HERBIE_SAVE_DIR to /data/weather/hrrr_cache/ so the GRIB files
  persist on the host mount in case you need to debug.

- HRRR xarray output uses EPSG:4326 coordinates named "latitude" and
  "longitude". The centroid from aoi_metadata.json is in 4326. Use
  ds.sel(latitude=lat, longitude=lon, method="nearest") instead of
  interp if the coordinate spacing is coarse.

- HRRR archives on AWS go back to 2014-07-30. The Gatlinburg date
  (2016-11-28) is within range.

- herbie may return wind components as UGRD/VGRD in a single Dataset or
  as separate xarray calls. Check the typeOfLevel="heightAboveGround" and
  level=10 filters.

- The IEM RAWS fallback returns temperatures in °F by default in the
  "tmpf" field. Conversion: C = (F - 32) × 5/9. Wind speed "sknt" is knots.
```

---

## Prompt 6B.3 — Real Live Fuel Moisture

```
Read these files in full before making any changes:
  - pipelines/05_fuel_moisture/src/calc_moisture.py
  - pipelines/05_fuel_moisture/requirements.txt
  - pipelines/05_fuel_moisture/Dockerfile
  - data/weather/weather_scenario.json   (output from 6B.2)

Goal: replace the hardcoded live fuel moisture values (30% herb / 60% woody)
with real observations from RAWS stations via the WFAS National Fuel Moisture
Database (NFMD) API. Dead fuel moisture derived from real weather is already
scientifically valid — keep the Nelson EMC calculation, it just needs real
T/RH input which it now gets from 6B.2.

### Background

Dead fuel moisture (1hr, 10hr, 100hr) is calculated from equilibrium moisture
content (EMC) using the Nelson (1984) formula. This is standard fire weather
methodology. With real T and RH from HRRR (or RAWS) the dead fuel moisture
is real — no change needed to the formula, only remove the "SYNTHETIC" labels.

Live fuel moisture is different: it reflects vegetation water content and is
measured directly at RAWS stations or derived from satellite NDVI. The WFAS
National Fuel Moisture Database (NFMD) collects live FM observations from
RAWS stations across the US.

### NFMD API

The NFMD REST endpoint for site observations:
  https://www.wfas.net/nfmd/public/index.php?state=TN&nfmd_action=showSiteList

However, NFMD's API is not formally documented. Use the Wildland Fire
Assessment System (WFAS) gacc-level data instead, which is JSON-accessible:

  https://www.wfas.net/nfmd/public/index.php?reg=0&state=TN&nfmd_action=showSiteData&siteId=<site_id>&year=<YYYY>

Finding nearby sites: query the site list, parse HTML with BeautifulSoup,
find sites within 200km of AOI centroid using haversine distance, sort by
proximity, try the nearest 5 until one returns data for the target year.

If NFMD is unreachable or no sites found within 200km:
Use the IEM RAWS network (same API as 6B.2) for "1hr_fuel_moisture" and
"10hr_fuel_moisture" observations where available:
  https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?data=fm1,fm10
  (network=TN_RAWS)

### What to compute

1. Dead moisture (unchanged formula, new label):
   - Read temperature_c and relative_humidity_pct from weather_scenario.json
   - Apply Nelson (1984) EMC as currently coded
   - dead_1hr  = emc
   - dead_10hr = emc × 1.5
   - dead_100hr = emc × 2.5

2. Live herb moisture (new — from NFMD or IEM):
   - Query nearest RAWS station with live herb FM observations
   - Use the monthly mean for the target date's month if hourly/daily data
     is unavailable (NFMD stores monthly averages per site per year)
   - live_herb_pct = observed value

3. Live woody moisture (new — from NFMD or IEM):
   - Same approach as herb
   - live_woody_pct = observed value

4. If no real data can be retrieved after all attempts:
   sys.exit(1) with a message listing the sites queried and the error.
   Do not fall back to hardcoded 30/60.

### Target date

Read WEATHER_DATE from os.environ (same variable as pipeline 04).
Default: "2016-11-28". Use only the date portion for NFMD monthly lookups.

### Changes to fuel_moisture.json

Remove "data_type": "DERIVED_FROM_SYNTHETIC" and "warning" fields.
Add:
  "source_dead": "Nelson (1984) EMC from HRRR weather"
  "source_live": "WFAS NFMD station <site_id>" or "IEM RAWS station <id>"
  "station_id": <id>
  "station_distance_km": <distance>
  "weather_date": <date used>

### Changes to requirements.txt

Add:
  beautifulsoup4
  requests
  (numpy and json are already present)

### Acceptance tests

Run these after `make run-05`:

  # 1. No SYNTHETIC or DERIVED_FROM_SYNTHETIC labels
  python3 -c "
  import json
  m = json.load(open('data/moisture/fuel_moisture.json'))
  assert 'SYNTHETIC' not in str(m), f'SYNTHETIC still present: {m}'
  assert 'DERIVED' not in str(m), f'DERIVED still present: {m}'
  print('PASS: no synthetic labels')
  "

  # 2. All 5 moisture values are present and in realistic ranges
  python3 -c "
  import json
  m = json.load(open('data/moisture/fuel_moisture.json'))
  assert 1 <= m['dead_1hr_pct'] <= 40,   f'1hr out of range: {m[\"dead_1hr_pct\"]}'
  assert 2 <= m['dead_10hr_pct'] <= 50,  f'10hr out of range: {m[\"dead_10hr_pct\"]}'
  assert 4 <= m['dead_100hr_pct'] <= 60, f'100hr out of range: {m[\"dead_100hr_pct\"]}'
  assert 30 <= m['live_herb_pct'] <= 300, f'herb out of range: {m[\"live_herb_pct\"]}'
  assert 60 <= m['live_woody_pct'] <= 300, f'woody out of range: {m[\"live_woody_pct\"]}'
  print('PASS: all moisture values in realistic ranges')
  print(f'  dead: {m[\"dead_1hr_pct\"]}% / {m[\"dead_10hr_pct\"]}% / {m[\"dead_100hr_pct\"]}%')
  print(f'  live: herb={m[\"live_herb_pct\"]}%  woody={m[\"live_woody_pct\"]}%')
  "

  # 3. Source fields present and non-empty
  python3 -c "
  import json
  m = json.load(open('data/moisture/fuel_moisture.json'))
  assert m.get('source_live'), 'source_live missing or empty'
  assert m.get('station_id'), 'station_id missing'
  print(f'PASS: live source = {m[\"source_live\"]}')
  "

  # 4. Grid assembly still passes with new moisture values
  make run-07

### Known landmines

- NFMD stores live herb and live woody moisture as separate fields. Some sites
  only report one of the two. If a site has herb but not woody, use the herb
  value × 2 as a woody proxy rather than failing.

- NFMD site pages are HTML, not JSON. BeautifulSoup parsing is fragile — write
  a targeted parser that looks for the data table by its id or a unique heading,
  not by position, so it survives minor page layout changes.

- Live herb moisture in November is typically 40–80% for cured grass in the
  southern Appalachians, 60–120% for mixed shrub. If the fetched value is
  outside 30–300%, log a warning and query the next nearest station.

- IEM RAWS fm1/fm10 fields are dead fuel moisture (1hr/10hr straw tubes),
  not live fuel moisture. If falling back to IEM, use those for dead fuel
  correction (override Nelson EMC if the direct measurements are available)
  and note that live moisture is estimated from the closest NFMD monthly mean.
```

---

## Prompt 6B.4 — Remove Synthetic Building Fallback

```
Read this file in full before making any changes:
  - pipelines/06_assets/src/fetch_assets.py

Goal: remove the synthetic building fallback. If OSM Overpass returns 0
buildings for the AOI, that is the correct answer — it means there are no
mapped buildings. The consequence pipeline will then report 0 structures
exposed. Do not fabricate buildings.

### Changes to fetch_assets.py

1. Delete the `synthetic_buildings()` function (lines ~107–143).

2. Delete the `TOWNSEND_LAT`, `TOWNSEND_LON`, and `MIN_BUILDINGS` constants.

3. In `main()`, replace the buildings fallback block:

   OLD:
     if polys is None or len(polys) < MIN_BUILDINGS:
         if polys is not None:
             print(f"  Only {len(polys)} buildings from Overpass (< {MIN_BUILDINGS}), using synthetic fallback")
         polys = synthetic_buildings(bbox)
         source_label = "synthetic_mvp"

   NEW:
     if polys is None:
         print("  WARNING: Overpass buildings query failed — writing empty buildings layer")
         polys = []
     source_label = "OpenStreetMap"

4. Remove `import random` (no longer used).

5. In the assets_metadata.json write block, ensure `source_label` is always
   set to "OpenStreetMap" (already done by change 3).

### No changes needed to consequence pipeline

Pipeline 10 already handles 0 exposed buildings correctly (it just reports
0 in consequence_summary.json). No changes needed downstream.

### Acceptance tests

Run these after `make run-06`:

  # 1. buildings.geojson exists (may be empty FeatureCollection)
  python3 -c "
  import json
  fc = json.load(open('data/assets/buildings.geojson'))
  assert fc['type'] == 'FeatureCollection', 'Not a FeatureCollection'
  n = len(fc['features'])
  print(f'PASS: {n} buildings (from OSM)')
  "

  # 2. Source is OpenStreetMap, not synthetic
  python3 -c "
  import json
  m = json.load(open('data/assets/assets_metadata.json'))
  assert m['buildings_source'] == 'OpenStreetMap', f'Wrong source: {m[\"buildings_source\"]}'
  assert 'synthetic' not in m['buildings_source'].lower(), 'Still synthetic'
  print(f'PASS: source = {m[\"buildings_source\"]}')
  "

  # 3. No synthetic_buildings function present in source
  import subprocess, sys
  result = subprocess.run(['grep', '-n', 'synthetic_buildings', 'pipelines/06_assets/src/fetch_assets.py'], capture_output=True, text=True)
  if result.stdout:
      print(f'FAIL: synthetic_buildings still in code:\\n{result.stdout}')
      sys.exit(1)
  print('PASS: synthetic_buildings removed')

  # Shell version of test 3:
  ! grep -n "synthetic_buildings" pipelines/06_assets/src/fetch_assets.py && echo "FAIL: still present" || echo "PASS: removed"

  # 4. Full pipeline test still passes
  make test

### Known landmines

- For the Townsend AOI, Overpass reliably returns real OSM buildings (there are
  structures there). The synthetic fallback was a defensive measure for empty
  areas. After removal, if Overpass is down, you get an empty layer — that is
  the correct behavior.

- The `random` import must be removed. Leave the `import time` if it is used
  for the Overpass retry delay (check before deleting).
```

---

## Prompt 6B.5 — Multi-Scenario Comparison UI

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/src/app.py
  - pipelines/11_web_ui/templates/index.html
  - data/weather/weather_scenario.json
  - data/input/aoi_metadata.json

Goal: add a side-by-side Leaflet map comparison UI that lets users select two
different simulation scenarios (varying wind speed, wind direction, or ignition
point) and compare fire spread and damage side by side.

### Scenario data model

A scenario is a pre-computed simulation run with different input parameters.
Scenarios are stored as subdirectories under data/scenarios/:

  data/scenarios/
    scenarios.json            ← catalog (list of scenario objects)
    baseline/
      weather.json            ← {wind_speed_kmh, wind_direction_deg, temp_c, rh_pct}
      fire_perimeter.geojson
      burn_scar.tif
      grids/                  ← grid_t000.tif … grid_tNNN.tif
      consequence.json        ← {structures_exposed, area_burned_ha, total_loss_usd}
    high_wind/
      ...same structure...
    wind_shift/
      ...same structure...

The baseline scenario is the current simulation output from pipelines 09+10.
The other scenarios are generated by a new make target.

### Step 1 — Scenario generation script

Create scripts/generate_scenarios.py that:

1. Reads data/simulation/ and data/consequence/ outputs (the baseline run).

2. Creates data/scenarios/baseline/ by symlinking or copying:
   - fire_perimeter.geojson ← data/simulation/fire_perimeter_final.geojson
   - burn_scar.tif          ← data/simulation/burn_scar.tif
   - grids/                 ← data/simulation/grids/
   - consequence.json       ← subset of data/consequence/consequence_summary.json
   - weather.json           ← from data/weather/weather_scenario.json

3. Defines two additional scenarios as parameter dicts:

   SCENARIOS = [
     {
       "id": "high_wind",
       "label": "High Wind (55 km/h)",
       "wind_speed_kmh": 55,
       "wind_direction_deg": 200,   # same direction as baseline
       "ignition_lat": None,        # use same as baseline
       "ignition_lon": None,
     },
     {
       "id": "wind_shift",
       "label": "Wind Shift (NW → SE)",
       "wind_speed_kmh": 35,
       "wind_direction_deg": 315,   # northwest
       "ignition_lat": None,
       "ignition_lon": None,
     },
   ]

4. For each additional scenario, runs a stripped-down simulation:
   a. Write a Weather.csv to a temp dir with 24 rows using the scenario wind
      speed and direction, same T and RH as baseline.
   b. Copy fuels.asc, elevation.asc, FuelMoistureContent.csv, Ignitions.csv,
      spain_lookup_table.csv from data/grid/ to the temp dir.
   c. Run Cell2Fire binary directly (do not re-run all pipelines):
        /opt/C2F-W/Cell2Fire/Cell2Fire \
          --input-instance-folder <tmp_dir>/ \
          --output-folder <tmp_output>/ \
          --sim-years 1 --nsim 1 --final-grid --grids --Fire-Period-Length 1.0 \
          --weather rows --nweathers 1 --ROS-CV 0 --HFI-opt
   d. Process outputs using the same logic as pipeline 09: sort ForestGrid*.csv
      numerically, produce per-timestep GeoTIFFs, produce fire_perimeter.geojson.
   e. Run consequence analysis using the same logic as pipeline 10: overlay
      perimeter with data/assets/buildings.geojson (or data/consequence/ exposed
      buildings geojson).
   f. Save outputs to data/scenarios/<scenario_id>/.

5. Writes data/scenarios/scenarios.json:
   [
     {"id": "baseline", "label": "Baseline (real weather)", "wind_speed_kmh": ..., "wind_direction_deg": ..., "structures_exposed": ..., "area_burned_ha": ...},
     {"id": "high_wind", "label": "High Wind (55 km/h)", ...},
     {"id": "wind_shift", "label": "Wind Shift (NW → SE)", ...}
   ]

Add Makefile target:
  scenarios: build-09_cell2fire
      @echo "=== Generating comparison scenarios ==="
      docker run --rm -v $(PWD)/data:/data -v $(PWD)/scripts:/scripts \
        --entrypoint python3 wildfire-09_cell2fire /scripts/generate_scenarios.py

### Step 2 — FastAPI backend changes

Add to app.py:

  SCENARIOS_DIR = Path("/data/scenarios")
  SCENARIOS_JSON = SCENARIOS_DIR / "scenarios.json"

  @app.get("/api/scenarios")
  def list_scenarios():
      if not SCENARIOS_JSON.exists():
          return []
      return json.loads(SCENARIOS_JSON.read_text())

  @app.get("/api/scenarios/{scenario_id}/perimeter")
  def scenario_perimeter(scenario_id: str):
      p = SCENARIOS_DIR / scenario_id / "fire_perimeter.geojson"
      if not p.exists():
          raise HTTPException(404, f"Scenario {scenario_id} not found")
      return Response(p.read_text(), media_type="application/json")

  @app.get("/api/scenarios/{scenario_id}/grids")
  def scenario_grids(scenario_id: str):
      d = SCENARIOS_DIR / scenario_id / "grids"
      if not d.exists():
          return {"timesteps": 0, "files": []}
      files = sorted(d.glob("grid_t*.tif"), key=lambda f: int(f.stem.split("t")[1]))
      return {"timesteps": len(files), "files": [f.name for f in files]}

  @app.get("/api/scenarios/{scenario_id}/grids/{filename}")
  def scenario_grid_tile(scenario_id: str, filename: str):
      p = SCENARIOS_DIR / scenario_id / "grids" / filename
      if not p.exists():
          raise HTTPException(404)
      return serve_geotiff_as_png(p)   # reuse existing GeoTIFF→PNG logic

  @app.get("/api/scenarios/{scenario_id}/consequence")
  def scenario_consequence(scenario_id: str):
      p = SCENARIOS_DIR / scenario_id / "consequence.json"
      if not p.exists():
          raise HTTPException(404)
      return json.loads(p.read_text())

### Step 3 — Frontend changes

Add a "Compare Scenarios" toggle button to the top-right of the existing UI.
When activated:

1. The map container splits into two equal-width panels side by side.
   Each panel is an independent Leaflet map instance sharing the same
   satellite base layer tileset but with independent overlays.

2. Above each map, a dropdown shows available scenarios from /api/scenarios.
   Default: left map = "baseline", right map = "high_wind".

3. Each map has its own fire perimeter layer and time-slider animation using
   the selected scenario's /api/scenarios/{id}/grids endpoint.

4. Below each map, a small stats bar shows: area burned, structures exposed,
   estimated loss — from /api/scenarios/{id}/consequence.

5. The two maps are synchronized: panning/zooming one map moves the other.
   Use Leaflet's sync plugin (cdn: leaflet.sync.js) or implement manual
   moveend event forwarding.

6. When "Compare Scenarios" is deactivated, the UI returns to single-map mode
   showing the baseline scenario.

### CSS/layout

The split-map container should be:
  display: flex;
  flex-direction: row;
  Each child: width: 50%; height: 100vh;

The stats bar below each map should use the existing dark theme colors.
Keep the existing sidebar (consequence summary) visible only in single-map mode.

### Acceptance tests

  # 1. Scenario catalog exists after make scenarios
  make scenarios
  python3 -c "
  import json
  s = json.load(open('data/scenarios/scenarios.json'))
  assert len(s) >= 3, f'Expected >= 3 scenarios, got {len(s)}'
  ids = [x['id'] for x in s]
  assert 'baseline' in ids
  assert 'high_wind' in ids
  print(f'PASS: {len(s)} scenarios: {ids}')
  "

  # 2. Each scenario has required files
  python3 -c "
  import os, json
  scenarios = json.load(open('data/scenarios/scenarios.json'))
  for sc in scenarios:
      sid = sc['id']
      for f in ['fire_perimeter.geojson', 'consequence.json']:
          p = f'data/scenarios/{sid}/{f}'
          assert os.path.exists(p), f'Missing: {p}'
  print('PASS: all scenario files present')
  "

  # 3. API endpoints respond
  # (start UI first: make ui-dev)
  curl -s http://localhost:8001/api/scenarios | python3 -c "
  import json, sys
  data = json.load(sys.stdin)
  assert len(data) >= 3
  print(f'PASS: /api/scenarios returned {len(data)} scenarios')
  "

  curl -s http://localhost:8001/api/scenarios/high_wind/consequence | python3 -c "
  import json, sys
  d = json.load(sys.stdin)
  assert 'area_burned_ha' in d
  print(f'PASS: high_wind area burned = {d[\"area_burned_ha\"]} ha')
  "

  # 4. Baseline and high_wind produce different burn areas
  python3 -c "
  import json
  b = json.load(open('data/scenarios/baseline/consequence.json'))
  h = json.load(open('data/scenarios/high_wind/consequence.json'))
  assert b['area_burned_ha'] != h['area_burned_ha'], 'Scenarios produced identical results'
  print(f'PASS: baseline={b[\"area_burned_ha\"]:.0f} ha  high_wind={h[\"area_burned_ha\"]:.0f} ha')
  "

  # 5. Full make test still passes
  make test

### Known landmines

- generate_scenarios.py runs inside the 09_cell2fire Docker image (which has
  the C2F-W binary). It must not import any module not in that image's
  requirements.txt. Keep it to stdlib + rasterio + geopandas + numpy.

- Cell2Fire output folder must be writable and must not already contain
  Grids/ or Messages/ from a previous run. Create a fresh temp dir per
  scenario using tempfile.mkdtemp() inside /tmp/scenarios/.

- The Fire-Period-Length and other C2F-W flags must match exactly what
  pipeline 09 uses. Read them from run_simulation.py before hardcoding them
  in the scenario generator.

- Leaflet map sync: when initializing two maps on the same page, each must
  have a unique DOM id and be sized explicitly. If one map renders as 0px
  height, call map.invalidateSize() after the container is visible.

- The compare toggle should be a CSS class swap on the root container, not
  a page reload. The second map instance should be initialized lazily (on
  first toggle) not at page load, to avoid double-loading tile layers.
```
