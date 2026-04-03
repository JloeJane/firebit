# Claude Code Prompts — Phase 6A: UI & Output Enhancements

## How to Use This File

Run each prompt sequentially in Claude Code. **Do not proceed to the next prompt until all tests pass for the current one.** Prompts build on each other — run them in order.

Each prompt includes:
- **What to build**
- **Acceptance tests** (bash commands that must pass)
- **Known landmines** (common failure points)

> **Already done:**
> - 6A.0 — Satellite base layer (Esri World Imagery default, + CartoDB Dark, OpenStreetMap Street)
> - 6A.1 — Fire spread animation (time-slider + play/pause over 25 timestep GeoTIFFs)
> - 6A.2 — Raster overlays (fuel type + elevation as toggleable PNG image layers)

**Prompt order (logical dependency):**
1. ~~6A.1 — Fire spread animation~~ ✓
2. ~~6A.2 — Raster overlays~~ ✓
3. ~~6A.3 — Dollar-value damage estimates~~ ✓
4. 6A.4 — Click-to-inspect building popups (depends on 6A.3 data)
5. 6A.5 — CWPP report generation

---

## Prompt 6A.1 — Fire Spread Animation

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/src/app.py
  - pipelines/11_web_ui/templates/index.html
  - pipelines/09_cell2fire/README.md

Context: per-timestep burn state GeoTIFFs already exist in data/simulation/grids/ as
grid_t000.tif, grid_t001.tif ... grid_t024.tif (or however many timesteps the simulation
produced). Each GeoTIFF is in EPSG:5070. Pixel value 1 = burned, 0 = unburned or NoData.
The goal is to add a time-slider to the Leaflet UI that animates fire spread across timesteps.

### Backend changes — app.py

1. At startup (module level, not inside a route), scan data/simulation/grids/ for files
   matching the pattern grid_t*.tif. Sort them lexicographically. For each file:
   - Open with rasterio
   - Read band 1 as a uint8 array
   - Use rasterio.features.shapes() to vectorize all pixels where value == 1 into polygons
   - Reproject the geometries from EPSG:5070 to EPSG:4326 using pyproj.Transformer
     (transform each polygon's coordinates using Transformer.from_crs(5070, 4326, always_xy=True))
   - Build a GeoJSON FeatureCollection
   - Store in a module-level dict: TIMESTEP_CACHE[timestep_index] = geojson_dict
   If data/simulation/grids/ does not exist or is empty, log a warning and leave the cache empty.
   This preprocessing runs once at container startup — it's acceptable to take a few seconds.

2. Add two new routes:

   GET /api/grids/
   Returns JSON: {"timesteps": [0, 1, 2, ...], "count": N}
   Derived from the keys of TIMESTEP_CACHE. Returns {"timesteps": [], "count": 0} if empty.

   GET /api/grids/{timestep}
   timestep is an integer (0-based index).
   Returns the cached GeoJSON FeatureCollection for that timestep.
   Returns 404 JSON {"detail": "timestep not found"} if out of range.

### Frontend changes — index.html

3. Add an animation panel to the sidebar, below the Legend section:

   <div class="section" id="animation-panel">
     <h2>Fire Animation</h2>
     <div id="anim-controls"> ... </div>
   </div>

   The panel should be hidden (display:none) on page load and shown only after the grids
   endpoint confirms at least 1 timestep is available.

4. After fetching /api/grids/ at page load:
   - If count == 0: leave the panel hidden, add a status dot showing animation unavailable.
   - If count > 0: show the panel with:
     - A range input slider: min=0, max=count-1, step=1, value=0, id="anim-slider"
     - A label showing "T+Xhr" (simulation hour) updated as the slider moves, id="anim-label"
     - A Play/Pause toggle button, id="anim-play"
     - A frame counter "Frame N / Total" id="anim-counter"

5. Add a new layer group: layers.animFrame = L.featureGroup() — add it to the map.
   Add it to the layer control overlays as 'Fire animation frame'.

6. When the slider changes value (input event):
   - Fetch /api/grids/{value} (use a cache: store fetched GeoJSON in a JS object keyed by timestep index to avoid re-fetching)
   - Clear layers.animFrame
   - Render the fetched GeoJSON with style: color '#ff4500', weight 0, fillColor '#ff4500', fillOpacity 0.55
   - Update the label and counter

7. Play/Pause button logic:
   - When playing: advance the slider by 1 every 750ms using setInterval, wrapping back to 0 after the last frame
   - When paused: clearInterval
   - Toggle button text between "▶ Play" and "⏸ Pause"
   - Stop playback if the user manually moves the slider

8. On initial load after confirming timesteps exist, automatically load frame 0 so the first
   fire state is visible without user interaction.

### Style requirements
- Animation panel uses the same .section / h2 styling as the rest of the sidebar
- Slider: width 100%, accent-color #e94560
- Play button: background #e94560, color white, border none, border-radius 4px, padding 5px 12px, cursor pointer, font-size 0.82rem
- Label and counter: font-size 0.82rem, color #aaa

Do not change any other routes or styling. Keep all existing layers and behavior intact.
Rebuild the pipeline 11 Docker image and verify the UI loads without errors.
```

### Tests for 6A.1:
```bash
# Start the UI container in the background for testing
docker build -t wildfire-11_web_ui pipelines/11_web_ui && echo "PASS: build" || echo "FAIL: build"
docker run -d --name ui-test --env-file .env -v $(pwd)/data:/data -p 8001:8000 wildfire-11_web_ui
sleep 3

# API: grids list endpoint
curl -sf http://localhost:8001/api/grids/ | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'timesteps' in d, 'Missing timesteps key'
assert 'count' in d, 'Missing count key'
assert isinstance(d['timesteps'], list), 'timesteps must be list'
print(f'PASS: /api/grids/ — {d[\"count\"]} timesteps available')
"

# API: first timestep (only if grids exist)
python3 -c "
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://localhost:8001/api/grids/').read())
if d['count'] == 0:
    print('SKIP: no simulation grids in data/simulation/grids/ — run make all first')
else:
    fc = json.loads(urllib.request.urlopen('http://localhost:8001/api/grids/0').read())
    assert fc['type'] == 'FeatureCollection', f'Expected FeatureCollection, got {fc[\"type\"]}'
    print(f'PASS: /api/grids/0 — {len(fc[\"features\"])} features')
"

# API: 404 on out-of-range timestep
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/grids/9999)
[ "$STATUS" = "404" ] && echo "PASS: out-of-range timestep returns 404" || echo "FAIL: expected 404, got $STATUS"

# HTML contains animation slider
curl -sf http://localhost:8001/ | grep -q 'anim-slider' && echo "PASS: slider in HTML" || echo "FAIL: slider missing"
curl -sf http://localhost:8001/ | grep -q 'anim-play' && echo "PASS: play button in HTML" || echo "FAIL: play button missing"

# Cleanup
docker stop ui-test && docker rm ui-test
```

**Known landmines:**
- `rasterio.features.shapes()` requires the array to be `float32` or `uint8` — cast explicitly with `.astype(np.uint8)` before calling.
- The GeoTIFF transform gives coordinates in EPSG:5070 (meters). `pyproj.Transformer.from_crs(5070, 4326, always_xy=True)` — the `always_xy=True` is critical or lat/lon will be swapped.
- If `data/simulation/grids/` is empty (simulation hasn't run yet), the cache is empty and the animation panel stays hidden — this is expected behavior, not a bug.
- The `rasterio.features.shapes()` function returns `(geometry_dict, value)` tuples — only keep tuples where `value == 1`.
- setInterval in JS keeps running across slider drags if you forget to clearInterval on manual input events.

---

## Prompt 6A.2 — Raster Layer Overlays (Fuel Type + Elevation)

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/src/app.py
  - pipelines/11_web_ui/templates/index.html
  - pipelines/02_fuel/README.md
  - pipelines/03_topography/README.md

Context: fuel_clipped.tif lives in data/fuel/fuel_clipped.tif (EPSG:5070, FBFM40 codes).
elevation.tif lives in data/topography/elevation.tif (EPSG:5070, meters). Both cover the
same bounding box as the AOI. The goal is to add these as optional visual overlays in the
Leaflet layer control — users toggle them on/off to understand fuel distribution and terrain.

### Backend changes — app.py

At startup, generate two PNG overlay images and store them in memory as bytes.
Add a helper function generate_overlays() called at module load:

1. FUEL OVERLAY — data/fuel/fuel_clipped.tif:
   - Open with rasterio, read band 1 (uint8 FBFM40 codes)
   - Replace NoData values with 0
   - Assign a fixed color per fuel code using this mapping (FBFM40 → RGB):
       0: (0,0,0,0)          # transparent (NoData / non-burnable)
       1-9: orange tones     # grass fuels  — use matplotlib tab10 colors c0-c2
       10-19: yellow tones   # shrub fuels  — use tab10 c3-c5
       20-29: red tones      # timber fuels — use tab10 c6-c8
       30-40: brown tones    # slash fuels  — use tab10 c9, grays
       Non-burnable (91, 92, 93, 98, 99): transparent
     Implementation: create an RGBA numpy array (rows, cols, 4), use np.where for each range,
     set alpha=180 for all burnable cells (for semi-transparency).
   - Use PIL.Image.fromarray() to create an RGBA image, then save to a BytesIO buffer as PNG.
   - Store as module-level FUEL_OVERLAY_PNG (bytes or None if file missing).

2. ELEVATION OVERLAY — data/topography/elevation.tif:
   - Open with rasterio, read band 1 as float32
   - Replace NoData with np.nan
   - Normalize to 0-255 range: ((elev - elev_min) / (elev_max - elev_min) * 255).astype(uint8)
   - Apply matplotlib's 'terrain' colormap: use matplotlib.cm.terrain on the normalized array
     to produce an RGBA array (values 0.0-1.0 input, RGBA float output → convert to uint8)
   - Set alpha channel to 160 for all non-NaN cells, 0 for NaN cells
   - Save to BytesIO buffer as PNG.
   - Store as module-level ELEVATION_OVERLAY_PNG (bytes or None if file missing).

3. Add two new routes:

   GET /api/overlay/fuel.png
   Content-Type: image/png
   Returns FUEL_OVERLAY_PNG using FastAPI Response(content=..., media_type="image/png")
   Returns 404 if FUEL_OVERLAY_PNG is None.

   GET /api/overlay/elevation.png
   Content-Type: image/png
   Returns ELEVATION_OVERLAY_PNG.
   Returns 404 if ELEVATION_OVERLAY_PNG is None.

4. Add a new route to expose the overlay bounds:

   GET /api/overlay/bounds
   Returns JSON with the AOI bounding box in EPSG:4326 for use by Leaflet:
   {"south": ..., "west": ..., "north": ..., "east": ...}
   Read these from data/input/aoi_metadata.json (bbox_4326 field).
   Returns null values if metadata file missing.

### Frontend changes — index.html

5. After loading summary data, fetch /api/overlay/bounds. If bounds are available:

   - Create two L.imageOverlay instances:
       const fuelOverlay = L.imageOverlay('/api/overlay/fuel.png',
         [[bounds.south, bounds.west], [bounds.north, bounds.east]],
         { opacity: 0.75, interactive: false }
       );
       const elevOverlay = L.imageOverlay('/api/overlay/elevation.png',
         [[bounds.south, bounds.west], [bounds.north, bounds.east]],
         { opacity: 0.65, interactive: false }
       );

   - Add both to the layer control overlays (do NOT add to map by default — user toggles on):
       'Fuel types':  fuelOverlay,
       'Elevation':   elevOverlay,

6. Add two new legend entries to the sidebar Legend section:
   - Fuel types: a small multi-color gradient swatch indicating "grass → shrub → timber"
   - Elevation: a terrain-gradient swatch indicating "low → high"

   Use this pattern for the gradient swatches:
   <div class="swatch" style="background: linear-gradient(to right, #f4a460, #228b22, #8b4513); width:40px;"></div>

Do not modify any existing routes or layer groups. Rebuild and verify.
```

### Tests for 6A.2:
```bash
docker build -t wildfire-11_web_ui pipelines/11_web_ui && echo "PASS: build" || echo "FAIL: build"
docker run -d --name ui-test --env-file .env -v $(pwd)/data:/data -p 8001:8000 wildfire-11_web_ui
sleep 3

# Bounds endpoint
curl -sf http://localhost:8001/api/overlay/bounds | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'south' in d and 'north' in d and 'east' in d and 'west' in d, 'Missing bound keys'
assert d['south'] is not None, 'south is null'
assert d['north'] > d['south'], 'north must be > south'
assert d['east'] > d['west'], 'east must be > west'
print(f'PASS: bounds — S:{d[\"south\"]} N:{d[\"north\"]} W:{d[\"west\"]} E:{d[\"east\"]}')
"

# Fuel overlay PNG (only if fuel data exists)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/overlay/fuel.png)
if [ "$STATUS" = "200" ]; then
  CTYPE=$(curl -sI http://localhost:8001/api/overlay/fuel.png | grep -i content-type)
  echo "$CTYPE" | grep -q "image/png" && echo "PASS: fuel overlay is PNG" || echo "FAIL: wrong content-type: $CTYPE"
  SIZE=$(curl -s http://localhost:8001/api/overlay/fuel.png | wc -c)
  [ "$SIZE" -gt 1000 ] && echo "PASS: fuel PNG has content ($SIZE bytes)" || echo "FAIL: fuel PNG too small"
elif [ "$STATUS" = "404" ]; then
  echo "SKIP: fuel overlay 404 — run make run-02 first to generate fuel_clipped.tif"
else
  echo "FAIL: fuel overlay returned $STATUS"
fi

# Elevation overlay PNG (only if topo data exists)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/overlay/elevation.png)
if [ "$STATUS" = "200" ]; then
  CTYPE=$(curl -sI http://localhost:8001/api/overlay/elevation.png | grep -i content-type)
  echo "$CTYPE" | grep -q "image/png" && echo "PASS: elevation overlay is PNG" || echo "FAIL: wrong content-type"
elif [ "$STATUS" = "404" ]; then
  echo "SKIP: elevation overlay 404 — run make run-03 first to generate elevation.tif"
else
  echo "FAIL: elevation overlay returned $STATUS"
fi

# HTML contains overlay layer references
curl -sf http://localhost:8001/ | grep -q 'fuelOverlay\|fuel\.png' && echo "PASS: fuel overlay wired in HTML" || echo "FAIL: fuel overlay missing from HTML"
curl -sf http://localhost:8001/ | grep -q 'elevOverlay\|elevation\.png' && echo "PASS: elevation overlay wired in HTML" || echo "FAIL: elevation overlay missing from HTML"

docker stop ui-test && docker rm ui-test
```

**Known landmines:**
- `matplotlib.cm.terrain` returns RGBA floats in [0,1]. Multiply by 255 and cast to `uint8` before passing to `PIL.Image.fromarray()`.
- PIL must be installed in requirements.txt as `Pillow` (not `PIL`). Add `Pillow` and `matplotlib` to `pipelines/11_web_ui/requirements.txt`.
- `L.imageOverlay` bounds format is `[[south, west], [north, east]]` — not `[west, south, east, north]`. Getting this wrong misaligns the overlay by the full AOI width/height.
- For the elevation colormap, `np.nan` cells must get alpha=0. Compute a `valid_mask = ~np.isnan(elev)` and set `rgba[:,:,3] = np.where(valid_mask, 160, 0)`.
- Do not add overlays to the map by default — users should toggle them. Adding them at startup obscures the satellite basemap.

---

## Prompt 6A.3 — Dollar-Value Damage Estimates

```
Read these files in full before making any changes:
  - pipelines/10_consequence/src/analyze.py
  - pipelines/10_consequence/README.md
  - pipelines/06_assets/src/fetch_assets.py

Context: pipeline 10 currently produces exposed_buildings.geojson with basic properties
(geometry + whatever OSM provided). The goal is to enrich each building with an estimated
replacement value in USD. We will use the FEMA National Structure Inventory (NSI) as the
primary source, with a square-footage fallback when NSI is unavailable or has no nearby match.

### Changes to pipelines/10_consequence/src/analyze.py

1. Add a new function fetch_nsi_values(bbox_4326: dict) -> gpd.GeoDataFrame:
   - Call the FEMA NSI API:
       url = "https://nsi.sec.usace.army.mil/nsiapi/structures"
       params = {
           "bbox": f"{bbox_4326['west']},{bbox_4326['south']},{bbox_4326['east']},{bbox_4326['north']}",
           "fmt": "fc"
       }
   - Set a 30-second timeout on the request. On timeout or any HTTP error, log a warning and
     return an empty GeoDataFrame.
   - Parse the GeoJSON FeatureCollection response into a GeoDataFrame with CRS EPSG:4326.
   - Reproject to EPSG:5070.
   - Keep only these columns: geometry, val_struct, val_cont, occtype, sqft
     (val_struct = structure replacement value in USD, val_cont = contents value,
      occtype = occupancy type string e.g. "RES1-1SNB", sqft = floor area)
   - Return the GeoDataFrame. Return empty GDF on any exception.

2. Add a new function assign_building_values(buildings_gdf, nsi_gdf) -> gpd.GeoDataFrame:
   - If nsi_gdf is empty, assign fallback values to all buildings and return.
   - Spatial join: for each building in buildings_gdf, find the nearest NSI structure within
     50 metres using geopandas.sjoin_nearest(buildings_gdf, nsi_gdf, max_distance=50, how='left').
   - For buildings that matched NSI: use val_struct as estimated_value_usd, sqft as structure_sqft,
     occtype as occupancy_type.
   - For buildings that did NOT match NSI (NaN val_struct after join):
       - Estimate sqft from the building's own geometry area if it's a polygon: sqft = geometry.area * 10.764 (m² to sqft)
       - If the building is a point (no area), use default 1200 sqft
       - Apply $175/sqft replacement cost: estimated_value_usd = sqft * 175
       - Set occupancy_type = "RES1-ESTIMATED"
   - Ensure estimated_value_usd is always set (no NaN) and is an integer.
   - Return the GeoDataFrame with these new columns added: estimated_value_usd, structure_sqft, occupancy_type.

3. In the main pipeline execution:
   - Load bbox_4326 from data/input/aoi_metadata.json
   - Call fetch_nsi_values(bbox_4326)
   - Call assign_building_values() on both buildings.geojson and exposed_buildings.geojson
   - Save the enriched versions back to the same output paths
   - Add to consequence_summary.json:
       "total_estimated_loss_usd": sum of estimated_value_usd for exposed buildings (int)
       "avg_structure_value_usd": mean estimated_value_usd across ALL buildings (int, rounded)
       "nsi_match_count": how many exposed buildings matched NSI vs used fallback
       "nsi_source": "FEMA NSI" if any matches, "estimated" if all fallback

4. Update data/output/consequence_summary.json and data/output/exposed_buildings.geojson
   (already happens via the existing copy step at the end of analyze.py — verify those copies
   still occur after your changes).

5. Update pipelines/10_consequence/requirements.txt:
   Add requests if not already present.

Rebuild pipeline 10 and re-run it:
  docker build -t wildfire-10_consequence pipelines/10_consequence
  docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-10_consequence

Verify outputs before moving on.
```

### Tests for 6A.3:
```bash
docker build -t wildfire-10_consequence pipelines/10_consequence && echo "PASS: build" || echo "FAIL: build"
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-10_consequence && echo "PASS: pipeline ran" || echo "FAIL: pipeline crashed"

# exposed_buildings.geojson has value fields
python3 -c "
import json
with open('data/output/exposed_buildings.geojson') as f:
    fc = json.load(f)
if not fc['features']:
    print('SKIP: no exposed buildings (fire did not reach structures)')
else:
    f0 = fc['features'][0]['properties']
    assert 'estimated_value_usd' in f0, f'Missing estimated_value_usd. Keys: {list(f0.keys())}'
    assert 'occupancy_type' in f0, 'Missing occupancy_type'
    assert isinstance(f0['estimated_value_usd'], (int, float)), 'estimated_value_usd must be numeric'
    assert f0['estimated_value_usd'] > 0, 'estimated_value_usd must be > 0'
    print(f'PASS: exposed buildings have value data — sample value \${f0[\"estimated_value_usd\"]:,}')
"

# buildings.geojson (all) has value fields
python3 -c "
import json
with open('data/assets/buildings.geojson') as f:
    fc = json.load(f)
assert len(fc['features']) > 0, 'No buildings'
f0 = fc['features'][0]['properties']
assert 'estimated_value_usd' in f0, f'Missing estimated_value_usd. Keys: {list(f0.keys())}'
assert f0['estimated_value_usd'] > 0, 'Value must be positive'
print(f'PASS: all buildings have value — {len(fc[\"features\"])} buildings, sample \${f0[\"estimated_value_usd\"]:,}')
"

# consequence_summary has loss total
python3 -c "
import json
with open('data/output/consequence_summary.json') as f:
    s = json.load(f)
assert 'total_estimated_loss_usd' in s, f'Missing total_estimated_loss_usd. Keys: {list(s.keys())}'
assert 'avg_structure_value_usd' in s, 'Missing avg_structure_value_usd'
assert 'nsi_source' in s, 'Missing nsi_source'
assert isinstance(s['total_estimated_loss_usd'], (int, float)), 'Must be numeric'
print(f'PASS: summary has loss data — total loss \${s[\"total_estimated_loss_usd\"]:,}, source: {s[\"nsi_source\"]}')
"

# output copies exist
test -f data/output/exposed_buildings.geojson && echo "PASS: output exposed_buildings copy exists" || echo "FAIL"
test -f data/output/consequence_summary.json && echo "PASS: output summary copy exists" || echo "FAIL"
```

**Known landmines:**
- The NSI API returns structures in EPSG:4326 (WGS84). Our buildings are in EPSG:5070. Reproject NSI to 5070 BEFORE the spatial join — do NOT try to join across CRS.
- `geopandas.sjoin_nearest` requires both GDFs to have the same CRS. Assert this before calling.
- `max_distance=50` is in the CRS units — for EPSG:5070 that's metres, which is correct.
- After the left join, column names from the right GDF get suffixed if they conflict. Check the actual column names with `print(merged.columns.tolist())` and adjust accordingly.
- The NSI API can be slow (5-20 seconds) or return 500 errors. Always wrap in try/except with a clear fallback log message — the pipeline must not fail just because NSI is down.
- If buildings.geojson contains polygon geometries (not just points), `geometry.area` gives m² in EPSG:5070. For point geometries, `.area` is 0 — use the default 1200 sqft fallback.

---

## Prompt 6A.4 — Click-to-Inspect Building Popups

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/templates/index.html
  - pipelines/11_web_ui/src/app.py

Context: buildings now have estimated_value_usd, occupancy_type, and structure_sqft properties
(added in 6A.3). Exposed buildings also have fire_arrival_time_hrs from pipeline 10.
The goal is to replace the generic "Exposed Building" popup with a rich dark-themed popup
for all buildings.

### Frontend changes only — index.html

1. Replace the existing exposed buildings onEachFeature with a proper popup builder function.
   Add this function near the top of the <script> block:

   function buildingPopup(props, isExposed) {
     const value = props.estimated_value_usd
       ? '$' + Number(props.estimated_value_usd).toLocaleString()
       : 'Unknown';
     const sqft = props.structure_sqft
       ? Number(props.structure_sqft).toFixed(0) + ' sqft'
       : '—';
     const occ = props.occupancy_type || '—';
     const name = props.name || props['addr:street'] || null;

     let html = '<div class="bldg-popup">';
     if (name) html += `<div class="popup-title">${name}</div>`;
     html += `<div class="popup-row"><span>Type</span><span>${occ}</span></div>`;
     html += `<div class="popup-row"><span>Est. size</span><span>${sqft}</span></div>`;
     html += `<div class="popup-row"><span>Est. value</span><span class="popup-value">${value}</span></div>`;

     if (isExposed) {
       const arrival = props.fire_arrival_time_hrs != null
         ? props.fire_arrival_time_hrs + ' hrs'
         : 'Within perimeter';
       const risk = props.fire_arrival_time_hrs != null
         ? (props.fire_arrival_time_hrs < 2 ? 'CRITICAL' :
            props.fire_arrival_time_hrs < 6 ? 'HIGH' :
            props.fire_arrival_time_hrs < 12 ? 'MEDIUM' : 'LOW')
         : 'HIGH';
       const riskColor = { CRITICAL: '#e94560', HIGH: '#ff6b35', MEDIUM: '#ffc107', LOW: '#4caf50' }[risk];
       html += `<div class="popup-row"><span>Fire arrival</span><span>${arrival}</span></div>`;
       html += `<div class="popup-risk" style="color:${riskColor}">⚠ ${risk} RISK</div>`;
     }

     html += '</div>';
     return html;
   }

2. Update the "All buildings" GeoJSON layer to bind popups:
   Add onEachFeature to the allBldgs L.geoJSON call:
     onEachFeature: (f, layer) => {
       layer.bindPopup(buildingPopup(f.properties, false), { maxWidth: 220 });
     },

3. Update the "Exposed buildings" GeoJSON layer to use the new popup:
   Replace the existing onEachFeature binding with:
     onEachFeature: (f, layer) => {
       layer.bindPopup(buildingPopup(f.properties, true), { maxWidth: 220 });
     },

4. Add popup CSS to the <style> block:

   .bldg-popup {
     font-family: 'Segoe UI', system-ui, sans-serif;
     font-size: 0.82rem;
     color: #e0e0e0;
     min-width: 180px;
   }
   .popup-title {
     font-weight: 600;
     font-size: 0.88rem;
     margin-bottom: 6px;
     color: #fff;
     border-bottom: 1px solid #333;
     padding-bottom: 4px;
   }
   .popup-row {
     display: flex;
     justify-content: space-between;
     gap: 12px;
     margin-bottom: 4px;
   }
   .popup-row span:first-child { color: #888; }
   .popup-value { color: #4fc3f7; font-weight: 600; }
   .popup-risk {
     margin-top: 6px;
     font-weight: 700;
     font-size: 0.8rem;
     text-align: center;
   }

5. Override Leaflet's default popup background for dark theme. Add to the <style> block:

   .leaflet-popup-content-wrapper {
     background: #1e2a3a !important;
     color: #e0e0e0 !important;
     border: 1px solid #0f3460 !important;
     border-radius: 6px !important;
     box-shadow: 0 4px 16px rgba(0,0,0,0.6) !important;
   }
   .leaflet-popup-tip {
     background: #1e2a3a !important;
   }
   .leaflet-popup-close-button {
     color: #aaa !important;
   }

6. Update the sidebar summary section to display the total estimated loss if available.
   Add this stat row after the "Structures exposed" row:
   <div class="stat-row">
     <span class="stat-label">Est. total loss</span>
     <span class="stat-value highlight" id="s-loss">—</span>
   </div>

   In the summary JS block, populate it:
   const loss = summary.total_estimated_loss_usd;
   document.getElementById('s-loss').textContent = loss
     ? '$' + Number(loss).toLocaleString()
     : 'N/A';

No backend changes needed. Rebuild pipeline 11 and verify popups work.
```

### Tests for 6A.4:
```bash
docker build -t wildfire-11_web_ui pipelines/11_web_ui && echo "PASS: build" || echo "FAIL: build"
docker run -d --name ui-test --env-file .env -v $(pwd)/data:/data -p 8001:8000 wildfire-11_web_ui
sleep 3

# HTML structure checks
curl -sf http://localhost:8001/ | grep -q 'bldg-popup' && echo "PASS: popup CSS class present" || echo "FAIL: popup CSS missing"
curl -sf http://localhost:8001/ | grep -q 'buildingPopup' && echo "PASS: buildingPopup function present" || echo "FAIL: function missing"
curl -sf http://localhost:8001/ | grep -q 's-loss' && echo "PASS: total loss stat row present" || echo "FAIL: loss stat missing"
curl -sf http://localhost:8001/ | grep -q 'leaflet-popup-content-wrapper' && echo "PASS: popup dark theme CSS present" || echo "FAIL: dark popup CSS missing"
curl -sf http://localhost:8001/ | grep -q 'CRITICAL\|HIGH.*RISK\|fire_arrival_time_hrs\|arrival' && echo "PASS: risk tier logic present" || echo "FAIL: risk logic missing"

# Summary API still works
curl -sf http://localhost:8001/api/summary | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'PASS: summary loads — keys: {list(d.keys())}')
"

# All existing layers still work
curl -sf http://localhost:8001/api/aoi | python3 -c "import sys,json; d=json.load(sys.stdin); print('PASS: AOI loads')"
curl -sf http://localhost:8001/api/fire-perimeter | python3 -c "import sys,json; d=json.load(sys.stdin); print('PASS: perimeter loads')"
curl -sf http://localhost:8001/api/buildings/all | python3 -c "import sys,json; d=json.load(sys.stdin); print('PASS: all buildings load')"

docker stop ui-test && docker rm ui-test
```

**Known landmines:**
- `props.fire_arrival_time_hrs` may be named differently in your pipeline 10 output (e.g. `arrival_time_hrs` or `arrival_hrs`). Check the actual property name in `data/output/exposed_buildings.geojson` before hardcoding it in the popup function.
- Leaflet popup CSS overrides require `!important` — Leaflet loads its own stylesheet after the page CSS and will win without it.
- `Number(props.estimated_value_usd).toLocaleString()` formats with commas on most browsers but can behave differently in some locales. It's fine for MVP.
- The OSM `name` and `addr:street` properties may both be absent for most buildings in Townsend — the popup gracefully omits the title row when both are null.

---

## Prompt 6A.5 — CWPP Report Generation

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/src/app.py
  - pipelines/11_web_ui/templates/index.html
  - pipelines/11_web_ui/requirements.txt
  - pipelines/11_web_ui/Dockerfile
  - pipelines/10_consequence/README.md

Context: all consequence data is available in data/output/. The goal is to generate a
Community Wildfire Protection Plan-style HTML report served at /report, with a print-to-PDF
stylesheet so users can print it from the browser (no server-side PDF rendering needed).

### Backend changes — app.py

1. Add Jinja2 template rendering. Add to imports:
     from fastapi.templating import Jinja2Templates
     from fastapi import Request
   Initialize: templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

2. Add a new route:

   GET /report
   Renders templates/report.html with the following context dict:
   {
     "aoi_name": "Townsend, TN / Tuckaleechee Cove",
     "simulation_date": <ISO date from consequence_summary.json "generated_at" field, or today>,
     "scenario": "Synthetic fire weather — Nov 2016 Gatlinburg-analog conditions",
     "summary": <dict from consequence_summary.json>,
     "exposed_buildings": <list of feature properties dicts from exposed_buildings.geojson, sorted by fire_arrival_time_hrs ascending>,
     "total_buildings": <count of features in data/assets/buildings.geojson>,
     "recommendations": <see step 3>,
   }
   Use Request as the first parameter (required by Jinja2Templates.TemplateResponse).

3. Generate a recommendations list in the route handler based on summary data:
   recommendations = []
   - If structures_exposed > 0:
       "Establish defensible space (minimum 30 ft) around all {structures_exposed} structures
        within the modeled fire perimeter."
   - If fire_arrival_to_first_structure_hrs is not None and < 3:
       "Immediate evacuation planning required: fire arrival time to first structure is
        {arrival:.1f} hours under modeled conditions."
   - If fire_arrival_to_first_structure_hrs is None or fire_arrival_to_first_structure_hrs >= 3:
       "Develop pre-evacuation trigger points based on fire weather watch/warning issuance."
   - Always append:
       "Conduct annual vegetation management along SR-73 (Wears Valley Road) and
        Laurel Creek Road — primary evacuation routes cross the modeled burn area."
       "Coordinate with Great Smoky Mountains National Park on cross-boundary fuel treatment
        projects in the WUI zone along the park boundary."
       "Install community notification systems (Wireless Emergency Alerts) for zones
        adjacent to the GSMNP boundary."

### New template — templates/report.html

4. Create pipelines/11_web_ui/templates/report.html.
   This is a standalone HTML page (not the map). It should look like a professional report.
   Use this structure:

   - <head>: include Google Fonts (Merriweather for headings, Source Sans Pro for body).
     Include a <style> block with print-friendly CSS (see below).
   - Header: agency logo placeholder (grey box), report title "Community Wildfire
     Protection Plan — Consequence Assessment", AOI name, simulation date.
   - Section 1 "Executive Summary": 3-4 bullet points pulling from summary data — area burned,
     structures exposed, estimated loss, fire arrival time.
   - Section 2 "Simulation Parameters": table with rows for Scenario, Weather, Fuel data source,
     Simulator, Grid resolution, Duration.
   - Section 3 "Fire Behavior": table with area burned (ha + acres), total cells burned,
     simulation duration.
   - Section 4 "Community Exposure": table listing each exposed building — columns: #, Occupancy
     Type, Est. Value, Fire Arrival Time. Show "No structures exposed" if list is empty.
     Show only the first 50 rows if more (note count).
   - Section 5 "Recommendations": numbered list from the recommendations context variable.
   - Section 6 "Limitations": fixed text describing the known limitations (synthetic fuel,
     synthetic weather, single scenario).
   - Footer: "Generated by Wildfire Platform | {simulation_date} | This is a modeling output
     for planning purposes only — not for emergency response."
   - Print button at top right (screen only, hidden on print):
     <button onclick="window.print()" class="print-btn">Print / Save PDF</button>

5. Print CSS requirements (inside the <style> block using @media print):
   - Hide the print button
   - Set page size to letter, margins 1in
   - Force all sections to have break-inside: avoid
   - Use black text on white background

6. Screen CSS requirements:
   - max-width: 900px, margin: auto, padding: 2rem
   - Headers in a dark navy (#1a2744), body text #333
   - Tables: full width, collapsed borders, alternating row shading (#f5f7fa / white)
   - Section headers: border-bottom 2px solid #e94560, padding-bottom 4px

7. Add a link to the report in the sidebar of index.html. Add to the bottom of the sidebar,
   above the footer info section:
   <div class="section">
     <a href="/report" target="_blank"
        style="display:block;text-align:center;padding:8px;background:#e94560;
               color:white;border-radius:4px;font-size:0.82rem;text-decoration:none;
               font-weight:600;">
       📄 View CWPP Report
     </a>
   </div>

8. Add jinja2 to pipelines/11_web_ui/requirements.txt if not already present.

Rebuild pipeline 11 and verify both the map and report load.
```

### Tests for 6A.5:
```bash
docker build -t wildfire-11_web_ui pipelines/11_web_ui && echo "PASS: build" || echo "FAIL: build"
docker run -d --name ui-test --env-file .env -v $(pwd)/data:/data -p 8001:8000 wildfire-11_web_ui
sleep 3

# Report page loads
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/report)
[ "$STATUS" = "200" ] && echo "PASS: /report returns 200" || echo "FAIL: /report returned $STATUS"

# Report contains key sections
curl -sf http://localhost:8001/report | grep -qi "Executive Summary" && echo "PASS: Executive Summary section" || echo "FAIL: missing Executive Summary"
curl -sf http://localhost:8001/report | grep -qi "Simulation Parameters" && echo "PASS: Simulation Parameters section" || echo "FAIL: missing Simulation Parameters"
curl -sf http://localhost:8001/report | grep -qi "Community Exposure" && echo "PASS: Community Exposure section" || echo "FAIL: missing Community Exposure"
curl -sf http://localhost:8001/report | grep -qi "Recommendations" && echo "PASS: Recommendations section" || echo "FAIL: missing Recommendations"
curl -sf http://localhost:8001/report | grep -qi "Limitations" && echo "PASS: Limitations section" || echo "FAIL: missing Limitations"

# Report contains actual data (not all dashes)
curl -sf http://localhost:8001/report | grep -qi "Townsend\|Tuckaleechee" && echo "PASS: AOI name in report" || echo "FAIL: AOI name missing"
curl -sf http://localhost:8001/report | grep -qi "Cell2Fire\|C2F-W\|simulator" && echo "PASS: simulator info in report" || echo "FAIL: simulator info missing"

# Print button present
curl -sf http://localhost:8001/report | grep -q 'window.print\|print-btn' && echo "PASS: print button in report" || echo "FAIL: print button missing"

# CWPP report link in main map UI
curl -sf http://localhost:8001/ | grep -q '/report' && echo "PASS: report link in sidebar" || echo "FAIL: report link missing from sidebar"

# Map UI still loads correctly after Jinja2 addition
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/)
[ "$STATUS" = "200" ] && echo "PASS: main map still loads" || echo "FAIL: main map broken ($STATUS)"

# All API routes still functional
for route in /api/aoi /api/fire-perimeter /api/buildings/all /api/summary /api/grids/; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001$route)
  [ "$STATUS" = "200" ] && echo "PASS: $route" || echo "FAIL: $route returned $STATUS"
done

docker stop ui-test && docker rm ui-test
```

**Known landmines:**
- FastAPI's `HTMLResponse` (used for `/`) and Jinja2's `TemplateResponse` (used for `/report`) coexist without conflict, but you must import `Request` from `fastapi` and pass it as the first arg to `TemplateResponse` — Jinja2Templates will throw a KeyError without it.
- `Jinja2Templates` requires `jinja2` in requirements.txt AND installed in the Dockerfile. It's usually pulled in as a FastAPI optional dep — add `jinja2` explicitly to be safe.
- The `exposed_buildings` list passed to the template is a list of `properties` dicts, not GeoJSON features. Extract with `[f["properties"] for f in fc["features"]]` in the route handler.
- Sorting by `fire_arrival_time_hrs` will crash if any building has `None` for that value. Use `key=lambda x: x.get("fire_arrival_time_hrs") or float('inf')` to sort None values last.
- Google Fonts loads from an external CDN — this requires internet access inside the Docker container at runtime. If the container has no outbound internet, use a system font stack fallback in CSS: `font-family: 'Merriweather', Georgia, serif`.
- The `/` route currently uses `HTMLResponse(HTML_PATH.read_text())` directly, not Jinja2. Do NOT convert it to a TemplateResponse — it will break the existing map since index.html is not a Jinja2 template.
```
