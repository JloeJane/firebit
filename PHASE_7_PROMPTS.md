# Claude Code Prompts — Phase 7: Interactive Scenario Builder

## Goal

Make the platform interactive. A user draws a bounding box on the map, drops an ignition point,
picks a weather date, clicks Run, and watches the 10-pipeline sequence execute live — then the
map reloads automatically with the new results. No new infrastructure required: the web UI
container gains Docker socket access and uses the Docker Python SDK to sequence the existing
pipeline containers.

## What changes

| Area | What changes |
|------|-------------|
| `Makefile` | Mount Docker socket + pass `HOST_DATA_DIR` to `ui` and `ui-dev` targets |
| `requirements.txt` (pipeline 11) | Add `docker` Python SDK |
| `app.py` (pipeline 11) | Add `POST /api/run`, `GET /api/run/status` (SSE), `GET /api/run/cancel` |
| `index.html` (pipeline 11) | Leaflet.Draw bbox + ignition tools, scenario builder sidebar section, SSE progress panel, map reload |

No changes to pipelines 01–10. All pipeline containers run unchanged.

## How to Use This File

Run each prompt sequentially in Claude Code. **Do not proceed to the next prompt until all tests
pass for the current one.** Prompts build on each other — run them in order.

Each prompt includes:
- **What to build** (the instruction block to paste into Claude Code)
- **Tests for X.X** (bash commands that must all print PASS before moving on)
- **Known landmines** (common failure points)

**Prompt order:**
1. 7.1 — Backend orchestration (Docker SDK, pipeline runner, SSE endpoints) ✅ DONE
2. 7.2 — Scenario builder UI (Leaflet.Draw, sidebar form, Run/Clear buttons) ✅ DONE
3. 7.3 — reloadAllLayers() soft reload (replaces location.reload()) ← NEXT
4. 7.4 — Validation + UX polish

---

## Prompt 7.1 — Backend Orchestration

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/src/app.py
  - pipelines/11_web_ui/requirements.txt
  - Makefile

Context: the web UI is a read-only FastAPI app. It currently has no ability to trigger pipeline
runs. The goal is to add a POST /api/run endpoint that accepts scenario parameters, starts a
background thread that sequences the 10 pipeline containers via the Docker Python SDK, and streams
progress back to the browser via Server-Sent Events at GET /api/run/status.

The Docker socket approach means the web UI container spawns sibling containers on the host —
the same containers the Makefile runs. No changes to any pipeline image are needed.

### 1. Makefile changes

In both the `ui` and `ui-dev` targets, add two lines after the `-v $(PWD)/data:/data \` line:

  -v /var/run/docker.sock:/var/run/docker.sock \
  -e HOST_DATA_DIR=$(PWD)/data \

The HOST_DATA_DIR env var gives the container the absolute host-side path for the data volume
mount. The Docker SDK needs this to pass the correct host path when starting sibling containers.

### 2. requirements.txt

Add `docker` on a new line. This is the official Docker Python SDK (pip package name: docker).

### 3. app.py — imports

Add at the top alongside the existing imports:

  import threading
  import time
  import queue
  import shutil
  import docker as docker_sdk
  from fastapi import Body
  from fastapi.responses import StreamingResponse
  from pydantic import BaseModel

### 4. app.py — new module-level state

Add after the existing path constants:

  HOST_DATA_DIR = os.environ.get("HOST_DATA_DIR", "/data")

  # Run state — written by background thread, read by SSE endpoint
  _run_lock   = threading.Lock()
  _run_events: queue.Queue = queue.Queue()
  _run_cancel = threading.Event()

### 5. app.py — _clear_data_dirs()

Add this helper function:

  def _clear_data_dirs() -> None:
      """Delete pipeline outputs before a fresh run. Preserve data/fuel/cache/."""
      dirs_to_clear = [
          "/data/input", "/data/topography", "/data/weather", "/data/moisture",
          "/data/assets", "/data/grid", "/data/simulation", "/data/consequence", "/data/output",
      ]
      for d in dirs_to_clear:
          p = Path(d)
          if p.exists():
              shutil.rmtree(p)
          p.mkdir(parents=True, exist_ok=True)
      # Clear fuel except cache/
      fuel = Path("/data/fuel")
      if fuel.exists():
          for item in fuel.iterdir():
              if item.name != "cache":
                  if item.is_dir():
                      shutil.rmtree(item)
                  else:
                      item.unlink()

### 6. app.py — _run_pipeline()

  def _run_pipeline(client, image_tag: str, env_vars: dict) -> None:
      """Build and run one pipeline container. Raises on non-zero exit."""
      pipeline_name = image_tag.replace("wildfire-", "")
      build_path = str(Path(__file__).parent.parent.parent / "pipelines" / pipeline_name)
      print(f"DEBUG: build_path = {build_path}")   # verify on first run
      if Path(build_path).exists():
          client.images.build(path=build_path, tag=image_tag, rm=True)
      client.containers.run(
          image_tag,
          remove=True,
          volumes={HOST_DATA_DIR: {"bind": "/data", "mode": "rw"}},
          environment=env_vars,
      )

### 7. app.py — Pydantic request model

  class ScenarioRequest(BaseModel):
      bbox_north:    float
      bbox_south:    float
      bbox_east:     float
      bbox_west:     float
      weather_date:  str    # "YYYY-MM-DD"
      ignition_lat:  float
      ignition_lon:  float

### 8. app.py — pipeline sequence and background runner

  PIPELINE_SEQUENCE = [
      ("01_shapefile_ingestion", "AOI boundary"),
      ("03_topography",          "Topography (3DEP)"),
      ("02_fuel",                "Fuel data (LANDFIRE)"),
      ("04_weather",             "Weather (HRRR)"),
      ("05_fuel_moisture",       "Fuel moisture"),
      ("06_assets",              "Assets (OSM)"),
      ("07_grid_assembly",       "Grid assembly"),
      ("08_ignition",            "Ignition point"),
      ("09_cell2fire",           "Fire simulation (C2F-W)"),
      ("10_consequence",         "Consequence analysis"),
  ]

  def _pipeline_runner(req: ScenarioRequest) -> None:
      global TIMESTEP_CACHE, FUEL_OVERLAY_PNG, ELEVATION_OVERLAY_PNG
      env_vars = {
          "BBOX_NORTH":   str(req.bbox_north),
          "BBOX_SOUTH":   str(req.bbox_south),
          "BBOX_EAST":    str(req.bbox_east),
          "BBOX_WEST":    str(req.bbox_west),
          "WEATHER_DATE": req.weather_date,
          "IGNITION_LAT": str(req.ignition_lat),
          "IGNITION_LON": str(req.ignition_lon),
      }
      try:
          client = docker_sdk.from_env()
          _clear_data_dirs()
          for pipeline_id, display_name in PIPELINE_SEQUENCE:
              if _run_cancel.is_set():
                  _run_events.put({"type": "cancelled", "step": display_name})
                  return
              _run_events.put({"type": "step_start", "step": display_name})
              try:
                  _run_pipeline(client, f"wildfire-{pipeline_id}", env_vars)
                  _run_events.put({"type": "step_done", "step": display_name})
              except Exception as e:
                  _run_events.put({"type": "error", "step": display_name, "message": str(e)})
                  return
          # Invalidate caches so the reloaded map gets fresh data
          TIMESTEP_CACHE.clear()
          FUEL_OVERLAY_PNG = None
          ELEVATION_OVERLAY_PNG = None
          generate_overlays()
          _run_events.put({"type": "complete"})
      finally:
          _run_lock.release()

### 9. app.py — POST /api/run

  @app.post("/api/run", status_code=202)
  async def run_scenario(req: ScenarioRequest):
      width  = abs(req.bbox_east  - req.bbox_west)
      height = abs(req.bbox_north - req.bbox_south)
      if not (0.05 <= width  <= 2.0):
          return JSONResponse({"detail": f"bbox width {width:.3f}° must be 0.05–2.0°"}, status_code=422)
      if not (0.05 <= height <= 2.0):
          return JSONResponse({"detail": f"bbox height {height:.3f}° must be 0.05–2.0°"}, status_code=422)
      if not _run_lock.acquire(blocking=False):
          return JSONResponse({"detail": "run already in progress"}, status_code=409)
      _run_cancel.clear()
      while not _run_events.empty():
          _run_events.get_nowait()
      threading.Thread(target=_pipeline_runner, args=(req,), daemon=True).start()
      return {"status": "started"}

### 10. app.py — GET /api/run/status (SSE)

  @app.get("/api/run/status")
  async def run_status():
      def event_stream():
          while True:
              try:
                  event = _run_events.get(timeout=30)
                  yield f"data: {json.dumps(event)}\n\n"
                  if event["type"] in ("complete", "error", "cancelled"):
                      break
              except queue.Empty:
                  yield 'data: {"type": "ping"}\n\n'
      return StreamingResponse(event_stream(), media_type="text/event-stream")

### 11. app.py — GET /api/run/cancel

  @app.get("/api/run/cancel")
  async def cancel_run():
      _run_cancel.set()
      return {"status": "cancelling"}

Rebuild the pipeline 11 image via `make ui-dev` and verify the UI starts before moving on.
```

### Tests for 7.1:
```bash
# Start the UI container via make ui-dev (mounts docker.sock)
make ui-dev &
sleep 5

# 1. Docker socket is mounted in the running container
docker inspect ui-dev 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
mounts = d[0].get('Mounts', [])
sock = [m for m in mounts if 'docker.sock' in m.get('Source','')]
assert sock, 'docker.sock not mounted — check Makefile ui-dev target'
print('PASS: docker.sock mounted')
"

# 2. POST /api/run rejects oversized bbox (returns 422)
# Note: use -s without -f so curl prints the body even on 4xx responses
curl -s -X POST http://localhost:8001/api/run \
  -H "Content-Type: application/json" \
  -d '{"bbox_north":40,"bbox_south":35,"bbox_east":-80,"bbox_west":-90,
       "weather_date":"2016-11-28","ignition_lat":35.56,"ignition_lon":-83.75}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'width' in d.get('detail','') or 'height' in d.get('detail',''), f'Unexpected: {d}'
print('PASS: oversized bbox rejected with 422')
"

# 3. POST /api/run accepts valid bbox → returns 202
STATUS=$(curl -sf -o /dev/null -w "%{http_code}" -X POST http://localhost:8001/api/run \
  -H "Content-Type: application/json" \
  -d '{"bbox_north":35.65,"bbox_south":35.55,"bbox_east":-83.7,"bbox_west":-83.83,
       "weather_date":"2016-11-28","ignition_lat":35.56,"ignition_lon":-83.75}')
[ "$STATUS" = "202" ] && echo "PASS: valid run returns 202" || echo "FAIL: expected 202, got $STATUS"

# 4. Second POST while running → 409
sleep 1
curl -s -X POST http://localhost:8001/api/run \
  -H "Content-Type: application/json" \
  -d '{"bbox_north":35.65,"bbox_south":35.55,"bbox_east":-83.7,"bbox_west":-83.83,
       "weather_date":"2016-11-28","ignition_lat":35.56,"ignition_lon":-83.75}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'in progress' in d.get('detail',''), f'Unexpected: {d}'
print('PASS: concurrent run rejected with 409')
"

# 5. SSE endpoint responds with text/event-stream content-type
# Note: use -N (no-buffer) with --max-time to GET the stream without hanging
curl -s -N --max-time 2 -v http://localhost:8001/api/run/status 2>&1 \
  | grep -i "text/event-stream" && echo "PASS: SSE content-type" || echo "FAIL: wrong content-type"

# 6. Cancel endpoint returns JSON
curl -sf http://localhost:8001/api/run/cancel \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('status') == 'cancelling', f'Unexpected: {d}'
print('PASS: cancel endpoint returns cancelling status')
"
```

**Known landmines:**
- `HOST_DATA_DIR` must be the absolute path on the **host** (e.g. `/home/user/projects/firebit/data`),
  not the in-container `/data`. The Docker SDK passes this to the host Docker daemon when creating
  sibling containers. Print it at startup to verify — if it's wrong, pipeline containers will
  start but read/write to an empty volume and produce no outputs.
- `_run_lock.release()` must be in a `finally` block inside `_pipeline_runner`. If it's only
  called on success, the lock stays held forever after any error and no further runs are possible.
- `Path(__file__).parent.parent.parent` resolves relative to `src/app.py` inside the container.
  With the live-mount (`-v pipelines/11_web_ui/src:/app/src`), this path may not reach the repo root.
  Print the resolved `build_path` on first run. If it's wrong, pass `REPO_ROOT` as an env var in
  the Makefile and read it in `_run_pipeline`.
- `StreamingResponse` with a synchronous generator runs in the main thread and blocks the event loop
  during the `queue.get(timeout=30)` wait. Wrap the generator in `asyncio.to_thread` or use an
  `asyncio.Queue` if the server becomes unresponsive while waiting for events.

---

## Prompt 7.2 — Scenario Builder UI

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/templates/index.html

Context: the backend from 7.1 is complete. POST /api/run accepts scenario parameters and
GET /api/run/status streams SSE events. Now we add the UI: a new "Scenario Builder" section
in the sidebar with a Leaflet.Draw rectangle tool for the bbox, a click-to-place ignition point,
a date picker for weather, and Run/Clear buttons.

### 1. Add Leaflet.Draw to <head>

After the existing Leaflet 1.9.4 <script> tag, add:

  <link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" />
  <script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>

### 2. Dark theme overrides for Leaflet.Draw toolbar

Add to the <style> block:

  .leaflet-draw-toolbar a {
    background-color: #16213e !important;
    border-color: #0f3460 !important;
    color: #ccc !important;
  }
  .leaflet-draw-toolbar a:hover { background-color: #0f3460 !important; }
  .leaflet-draw-section { border-color: #0f3460 !important; }

### 3. Scenario Builder sidebar section

Add the following HTML block inside #sidebar, immediately above
<div class="section" id="animation-panel">:

  <div class="section" id="scenario-panel">
    <h2>Scenario Builder</h2>

    <div style="margin-bottom:10px;">
      <div style="font-size:0.78rem;color:#888;margin-bottom:4px;">1. Draw AOI bounding box</div>
      <button id="btn-draw-bbox"
              style="background:#0f3460;color:#ccc;border:1px solid #0f3460;border-radius:4px;
                     padding:4px 10px;cursor:pointer;font-size:0.80rem;width:100%;">
        ⬜ Draw Bbox
      </button>
      <div id="bbox-display"
           style="font-size:0.72rem;color:#aaa;margin-top:4px;display:none;white-space:pre;"></div>
    </div>

    <div style="margin-bottom:10px;">
      <div style="font-size:0.78rem;color:#888;margin-bottom:4px;">2. Weather date</div>
      <input type="date" id="weather-date" value="2016-11-28"
             style="background:#1a1a2e;color:#e0e0e0;border:1px solid #0f3460;
                    border-radius:4px;padding:4px 8px;font-size:0.82rem;width:100%;
                    box-sizing:border-box;" />
    </div>

    <div style="margin-bottom:10px;">
      <div style="font-size:0.78rem;color:#888;margin-bottom:4px;">3. Drop ignition point</div>
      <button id="btn-drop-ignition"
              style="background:#0f3460;color:#ccc;border:1px solid #0f3460;border-radius:4px;
                     padding:4px 10px;cursor:pointer;font-size:0.80rem;width:100%;">
        📍 Drop Point
      </button>
      <div id="ignition-display"
           style="font-size:0.72rem;color:#aaa;margin-top:4px;display:none;white-space:pre;"></div>
    </div>

    <button id="btn-run-scenario" disabled
            style="width:100%;background:#e94560;color:white;border:none;border-radius:4px;
                   padding:7px;font-size:0.85rem;font-weight:600;opacity:0.4;
                   cursor:not-allowed;margin-bottom:4px;">
      ▶ Run Scenario
    </button>
    <button id="btn-clear-scenario"
            style="width:100%;background:transparent;color:#666;border:1px solid #333;
                   border-radius:4px;padding:4px;cursor:pointer;font-size:0.75rem;">
      ✕ Clear
    </button>
    <div id="run-progress-panel" style="display:none;margin-top:10px;">
      <div id="progress-steps"></div>
      <button id="btn-cancel-run"
              style="margin-top:8px;width:100%;background:transparent;color:#888;
                     border:1px solid #444;border-radius:4px;padding:4px;
                     cursor:pointer;font-size:0.75rem;">
        ✕ Cancel run
      </button>
    </div>
    <div id="scenario-error"
         style="font-size:0.75rem;color:#e94560;margin-top:6px;display:none;line-height:1.4;"></div>
  </div>

### 4. JavaScript — scenario state variables

Add near the top of the <script> block, after the existing layer group declarations:

  let scenarioBbox         = null;   // {north, south, east, west}
  let scenarioIgnition     = null;   // {lat, lon}
  let drawnBboxLayer       = null;
  let placedIgnitionMarker = null;
  let scenarioMode         = null;   // 'ignition' | null

  const PIPELINE_STEPS = [
    "AOI boundary", "Topography (3DEP)", "Fuel data (LANDFIRE)", "Weather (HRRR)",
    "Fuel moisture", "Assets (OSM)", "Grid assembly", "Ignition point",
    "Fire simulation (C2F-W)", "Consequence analysis"
  ];

### 5. JavaScript — Leaflet.Draw setup

Add after Object.values(layers).forEach(lg => lg.addTo(map)):

  const drawnItems = new L.FeatureGroup();
  map.addLayer(drawnItems);

  const drawRect = new L.Draw.Rectangle(map, {
    shapeOptions: { color: '#4fc3f7', weight: 2, fillOpacity: 0.05, dashArray: '6 4' }
  });

  map.on(L.Draw.Event.CREATED, function(e) {
    if (drawnBboxLayer) map.removeLayer(drawnBboxLayer);
    drawnBboxLayer = e.layer;
    map.addLayer(drawnBboxLayer);
    const b = e.layer.getBounds();
    scenarioBbox = {
      north: b.getNorth(), south: b.getSouth(),
      east:  b.getEast(),  west:  b.getWest()
    };
    document.getElementById('bbox-display').style.display = '';
    document.getElementById('bbox-display').textContent =
      `N ${b.getNorth().toFixed(4)}  S ${b.getSouth().toFixed(4)}\n` +
      `E ${b.getEast().toFixed(4)}   W ${b.getWest().toFixed(4)}`;
    _checkRunReady();
  });

### 6. JavaScript — ignition point placement

Add a map click handler after the draw setup:

  map.on('click', function(e) {
    if (scenarioMode !== 'ignition') return;
    if (placedIgnitionMarker) map.removeLayer(placedIgnitionMarker);
    placedIgnitionMarker = L.circleMarker(e.latlng, {
      radius: 9, color: '#fff', weight: 2, fillColor: '#e94560', fillOpacity: 1
    }).addTo(map);
    scenarioIgnition = { lat: e.latlng.lat, lon: e.latlng.lng };
    document.getElementById('ignition-display').style.display = '';
    document.getElementById('ignition-display').textContent =
      `${e.latlng.lat.toFixed(5)}°N  ${e.latlng.lng.toFixed(5)}°E`;
    scenarioMode = null;
    map.getContainer().style.cursor = '';
    document.getElementById('btn-drop-ignition').textContent = '📍 Drop Point';
    _checkRunReady();
  });

### 7. JavaScript — button handlers and helpers

  function _checkRunReady() {
    const ready = scenarioBbox !== null && scenarioIgnition !== null;
    const btn = document.getElementById('btn-run-scenario');
    btn.disabled = !ready;
    btn.style.opacity = ready ? '1' : '0.4';
    btn.style.cursor  = ready ? 'pointer' : 'not-allowed';
  }

  document.getElementById('btn-draw-bbox').addEventListener('click', () => drawRect.enable());

  document.getElementById('btn-drop-ignition').addEventListener('click', () => {
    scenarioMode = 'ignition';
    map.getContainer().style.cursor = 'crosshair';
    document.getElementById('btn-drop-ignition').textContent = '🎯 Click map…';
  });

  document.getElementById('btn-run-scenario').addEventListener('click', async () => {
    document.getElementById('scenario-error').style.display = 'none';
    document.getElementById('btn-run-scenario').disabled = true;
    document.getElementById('btn-run-scenario').textContent = '⏳ Starting…';
    const body = {
      bbox_north:   scenarioBbox.north,
      bbox_south:   scenarioBbox.south,
      bbox_east:    scenarioBbox.east,
      bbox_west:    scenarioBbox.west,
      weather_date: document.getElementById('weather-date').value,
      ignition_lat: scenarioIgnition.lat,
      ignition_lon: scenarioIgnition.lon,
    };
    const resp = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (resp.status === 202) {
      startProgressStream();
    } else {
      const d = await resp.json();
      document.getElementById('scenario-error').textContent = d.detail || 'Unknown error';
      document.getElementById('scenario-error').style.display = '';
      document.getElementById('btn-run-scenario').disabled = false;
      document.getElementById('btn-run-scenario').textContent = '▶ Run Scenario';
      _checkRunReady();
    }
  });

  document.getElementById('btn-clear-scenario').addEventListener('click', () => {
    scenarioBbox = null;
    scenarioIgnition = null;
    scenarioMode = null;
    if (drawnBboxLayer)       { map.removeLayer(drawnBboxLayer);       drawnBboxLayer = null; }
    if (placedIgnitionMarker) { map.removeLayer(placedIgnitionMarker); placedIgnitionMarker = null; }
    map.getContainer().style.cursor = '';
    ['bbox-display','ignition-display','scenario-error'].forEach(id => {
      document.getElementById(id).style.display = 'none';
    });
    document.getElementById('btn-drop-ignition').textContent = '📍 Drop Point';
    document.getElementById('btn-run-scenario').textContent  = '▶ Run Scenario';
    _checkRunReady();
  });

Rebuild the pipeline 11 image and verify with `make ui-dev`. The UI must load without JS errors.
```

### Tests for 7.2:
```bash
# UI must be running via `make ui-dev` before these tests

# All required DOM element IDs exist in the rendered HTML
for ID in scenario-panel btn-draw-bbox btn-drop-ignition btn-run-scenario \
           btn-clear-scenario weather-date run-progress-panel btn-cancel-run; do
  curl -sf http://localhost:8001/ | grep -q "$ID" \
    && echo "PASS: $ID found" || echo "FAIL: $ID missing"
done

# Leaflet.Draw stylesheet is linked
curl -sf http://localhost:8001/ | grep -q 'leaflet-draw' \
  && echo "PASS: leaflet-draw CSS loaded" || echo "FAIL: leaflet-draw CSS missing"

# Leaflet.Draw script tag is present
curl -sf http://localhost:8001/ | grep -q 'leaflet.draw.js' \
  && echo "PASS: leaflet-draw JS loaded" || echo "FAIL: leaflet-draw JS missing"

# Scenario panel appears before animation panel in DOM order
python3 -c "
import urllib.request
html = urllib.request.urlopen('http://localhost:8001/').read().decode()
sp = html.find('scenario-panel')
ap = html.find('animation-panel')
assert sp != -1 and ap != -1, 'One or both panels missing'
assert sp < ap, f'scenario-panel ({sp}) must appear before animation-panel ({ap})'
print('PASS: scenario-panel is above animation-panel in DOM')
"

# Manual browser checks (cannot be automated):
# - Click "Draw Bbox" → cursor changes, rectangle draws on map, bbox coords appear in sidebar
# - Click "Drop Point" → button text changes to "Click map…", cursor becomes crosshair
# - Click on map → red marker placed, lat/lon shown in sidebar
# - Run button enabled only after both bbox and ignition are set
# - Clear resets all state and removes drawn layers
```

**Known landmines:**
- `L.Draw.Event.CREATED` fires for all draw tools. Since only `drawRect` is enabled here it is
  safe, but add a `if (e.layerType !== 'rectangle') return` guard if other tools are added later.
- The map `click` handler fires for Leaflet control clicks too. The `scenarioMode !== 'ignition'`
  guard prevents accidental ignition placement on any click.
- `input[type="date"]` always returns `YYYY-MM-DD` regardless of browser locale — safe to pass
  directly to the backend without reformatting.
- `drawRect.enable()` activates drawing mode. If the user hits Escape, Leaflet.Draw exits drawing
  mode but the button text stays "⬜ Draw Bbox" — no state desync, just a cosmetic issue.

---

## Prompt 7.3 — reloadAllLayers() soft reload

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/templates/index.html

Context: prompts 7.1 and 7.2 are complete and working end-to-end. The current code has a
working startProgressStream() that handles all SSE event types correctly. The one gap is the
completion handler: it currently does `setTimeout(() => location.reload(), 1500)` which is a
hard page reload — the user loses their zoom level, base layer choice, and drawn bbox. This
prompt replaces that with a soft reloadAllLayers() that re-fetches only the map data in-place.

## What is ALREADY in index.html (do not duplicate or overwrite):
- startProgressStream() — fully working; handles step_start/step_done/error/cancelled/complete;
  uses CSS classes step-pending/step-active/step-done/step-error with @keyframes stepPulse
- _checkRunReady() — enables/disables Run button based on bbox + ignition state
- All scenario panel HTML: #scenario-panel, #run-progress-panel, #progress-steps, #btn-cancel-run,
  #scenario-error, #btn-draw-bbox, #btn-drop-ignition, #btn-run-scenario, #btn-clear-scenario
- Wind indicator: #wind-indicator, updateWindIndicator(idx), GET /api/weather endpoint
- resetMapLayers() + #btn-reset-map button in Data Status section
- weatherData[], PIPELINE_STEPS[], stepIndex map (name→index for SSE dispatch)

## Changes needed

### 1. HTML — scenario label div

Add immediately after <h1>🔥 Wildfire Platform</h1>:

  <div id="scenario-label"
       style="font-size:0.72rem;color:#888;padding:2px 16px 6px;display:none;"></div>

### 2. JavaScript — module-level overlay vars

Add near the top of the <script> block alongside the other `let` declarations:

  let layerControl     = null;
  let fuelOverlayLayer = null;
  let elevOverlayLayer = null;

### 3. JavaScript — change const layerControl to assignment

In the existing Promise.all `.then()` callback, find:

  const layerControl = L.control.layers(

Change to:

  layerControl = L.control.layers(

(Remove the `const` — the variable is now declared at module scope in step 2.)

### 4. JavaScript — add reloadAllLayers()

Add this function to the <script> block:

  async function reloadAllLayers() {
    animCache = {};

    // AOI
    layers.aoi.clearLayers();
    const aoi = await fetchJSON('/api/aoi');
    if (hasFeatures(aoi)) {
      L.geoJSON(aoi, {
        style: { color: '#4fc3f7', weight: 2, dashArray: '6 4', fillOpacity: 0, opacity: 0.9 }
      }).addTo(layers.aoi);
      map.fitBounds(layers.aoi.getBounds(), { padding: [20, 20] });
      setDot('dot-aoi', true);
    }

    // Fire perimeter
    layers.perimeter.clearLayers();
    const perimeter = await fetchJSON('/api/fire-perimeter');
    if (hasFeatures(perimeter)) {
      L.geoJSON(perimeter, {
        style: { color: '#e94560', weight: 2, fillColor: '#e94560', fillOpacity: 0.4 }
      }).addTo(layers.perimeter);
      setDot('dot-perimeter', true);
    }

    // All buildings
    layers.buildings.clearLayers();
    const allBldgs = await fetchJSON('/api/buildings/all');
    if (hasFeatures(allBldgs)) {
      L.geoJSON(allBldgs, {
        pointToLayer: (f, latlng) => L.circleMarker(latlng, {
          radius: 4, color: '#aaa', weight: 1, fillColor: '#888', fillOpacity: 0.7,
        }),
        style: { color: '#aaa', weight: 1, fillColor: '#888', fillOpacity: 0.5 },
      }).addTo(layers.buildings);
      setDot('dot-buildings', true);
    }

    // Exposed buildings
    layers.exposed.clearLayers();
    const exposedBldgs = await fetchJSON('/api/buildings/exposed');
    if (hasFeatures(exposedBldgs)) {
      L.geoJSON(exposedBldgs, {
        pointToLayer: (f, latlng) => L.circleMarker(latlng, {
          radius: 7, color: '#ff6b35', weight: 2, fillColor: '#ff6b35', fillOpacity: 0.9,
        }),
        style: { color: '#ff6b35', weight: 2, fillColor: '#ff6b35', fillOpacity: 0.8 },
        onEachFeature: (f, layer) => { layer.bindPopup('<b>Exposed Building</b>'); },
      }).addTo(layers.exposed);
      setDot('dot-exposed', true);
    }

    // Ignition
    layers.ignition.clearLayers();
    const ignition = await fetchJSON('/api/ignition');
    if (hasFeatures(ignition)) {
      ignition.features.forEach(f => {
        const [lon, lat] = f.geometry.coordinates;
        L.circleMarker([lat, lon], {
          radius: 9, color: '#fff', weight: 2, fillColor: '#e94560', fillOpacity: 1,
        })
          .bindPopup('<b>Ignition Point</b><br>Cell ID: ' + (f.properties.cell_id || '—'))
          .addTo(layers.ignition);
      });
      setDot('dot-ignition', true);
    }

    // Summary stats
    const summary = await fetchJSON('/api/summary');
    if (summary && summary.total_area_burned_ha !== undefined) {
      document.getElementById('s-area').textContent =
        summary.total_area_burned_ha.toFixed(1) + ' ha';
      document.getElementById('s-acres').textContent =
        (summary.total_area_burned_acres || (summary.total_area_burned_ha * 2.47).toFixed(1)) + ' ac';
      document.getElementById('s-structures').textContent = summary.structures_exposed ?? '—';
      document.getElementById('s-population').textContent = summary.estimated_population_at_risk ?? '—';
      document.getElementById('s-roads').textContent =
        summary.infrastructure_exposed?.road_segments ?? '—';
      const arr = summary.fire_arrival_to_first_structure_hrs;
      document.getElementById('s-arrival').textContent = arr != null ? arr + ' hrs' : 'N/A';
    }

    // Weather data for wind indicator
    weatherData = await fetchJSON('/api/weather').catch(() => []);

    // Animation grids
    const info = await fetchJSON('/api/grids/');
    animTotal = info.count;
    if (animTotal > 0) {
      animSlider.max   = animTotal - 1;
      animSlider.value = 0;
      updateAnimLabel(0);
      document.getElementById('animation-panel').style.display = '';
      loadFrame(0);
    }

    // Raster overlays — cache-bust with timestamp so browser doesn't serve stale PNG
    const bounds = await fetchJSON('/api/overlay/bounds').catch(() => ({}));
    if (bounds.south) {
      const t  = Date.now();
      const c1 = [bounds.south, bounds.west];
      const c2 = [bounds.north, bounds.east];
      if (fuelOverlayLayer) { map.removeLayer(fuelOverlayLayer); layerControl && layerControl.removeLayer(fuelOverlayLayer); }
      if (elevOverlayLayer) { map.removeLayer(elevOverlayLayer); layerControl && layerControl.removeLayer(elevOverlayLayer); }
      fuelOverlayLayer = L.imageOverlay(`/api/overlay/fuel.png?t=${t}`,      [c1, c2], { opacity: 0.75, interactive: false });
      elevOverlayLayer = L.imageOverlay(`/api/overlay/elevation.png?t=${t}`, [c1, c2], { opacity: 0.65, interactive: false });
      if (layerControl) {
        layerControl.addOverlay(fuelOverlayLayer, 'Fuel types');
        layerControl.addOverlay(elevOverlayLayer, 'Elevation');
      }
    }
  }

### 5. JavaScript — replace location.reload() with soft reload in startProgressStream()

In the existing startProgressStream() function, find the complete handler:

  } else if (data.type === 'complete') {
    _runEventSource.close();
    document.getElementById('btn-run-scenario').textContent = '✅ Done — reloading…';
    setTimeout(() => location.reload(), 1500);

Replace with:

  } else if (data.type === 'complete') {
    _runEventSource.close();
    document.getElementById('progress-steps').insertAdjacentHTML('beforeend',
      '<div style="font-size:0.78rem;color:#4caf50;margin-top:6px;">✅ Complete — reloading map…</div>');
    await new Promise(r => setTimeout(r, 1200));
    await reloadAllLayers();
    document.getElementById('run-progress-panel').style.display = 'none';
    document.getElementById('btn-run-scenario').textContent     = '▶ Run Scenario';
    _checkRunReady();
    const d   = document.getElementById('weather-date').value;
    const lat = scenarioIgnition ? scenarioIgnition.lat.toFixed(4) : '—';
    const lon = scenarioIgnition ? scenarioIgnition.lon.toFixed(4) : '—';
    const lbl = document.getElementById('scenario-label');
    if (lbl) { lbl.textContent = `Custom: ${d} · ${lat}°N ${lon}°E`; lbl.style.display = ''; }

Note: the onmessage handler must be declared `async` for the await calls to work:
  _runEventSource.onmessage = async function(e) {

Rebuild the pipeline 11 image and verify with `make ui-dev`. The UI must load without JS errors.
No page reload should occur after a completed run — the map layers should update in-place.
```

### Tests for 7.3:
```bash
# UI must be running via `make ui-dev` before these tests

# scenario-label div present
curl -sf http://localhost:8001/ | grep -q 'scenario-label' \
  && echo "PASS: scenario-label div in HTML" || echo "FAIL: scenario-label missing"

# reloadAllLayers function is defined in the JS
curl -sf http://localhost:8001/ | grep -q 'reloadAllLayers' \
  && echo "PASS: reloadAllLayers defined" || echo "FAIL: reloadAllLayers missing"

# layerControl declared at module scope (let, not const)
curl -sf http://localhost:8001/ | grep -q 'let layerControl' \
  && echo "PASS: layerControl declared as let" || echo "FAIL: layerControl is const — reloadAllLayers will not work"

# location.reload() should be gone from the complete handler
curl -sf http://localhost:8001/ | grep -q 'location.reload' \
  && echo "FAIL: location.reload() still present — should be replaced by reloadAllLayers()" \
  || echo "PASS: location.reload() removed"

# fuelOverlayLayer and elevOverlayLayer declared at module scope
curl -sf http://localhost:8001/ | grep -q 'fuelOverlayLayer' \
  && echo "PASS: fuelOverlayLayer declared" || echo "FAIL: fuelOverlayLayer missing"

# Full end-to-end run — Townsend default scenario (takes 5–15 min depending on cache):
curl -sf -X POST http://localhost:8001/api/run \
  -H "Content-Type: application/json" \
  -d '{"bbox_north":35.65,"bbox_south":35.55,"bbox_east":-83.7,"bbox_west":-83.83,
       "weather_date":"2016-11-28","ignition_lat":35.56,"ignition_lon":-83.75}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('status')=='started', d; print('PASS: run accepted')"

# Stream progress events to terminal (Ctrl-C when done or after seeing 'complete')
curl -sN http://localhost:8001/api/run/status | head -60

# After run completes — verify fire perimeter and animation frames are available
curl -sf http://localhost:8001/api/fire-perimeter | python3 -c "
import json, sys
fc = json.load(sys.stdin)
assert len(fc.get('features',[])) > 0, 'No perimeter features — simulation may have failed'
print('PASS: fire perimeter populated after run')
"
curl -sf http://localhost:8001/api/grids/ | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['count'] > 0, 'No animation frames — simulation may have failed'
print(f'PASS: {d[\"count\"]} animation frames available after run')
"
```

**Known landmines:**
- `onmessage` must be `async function` for the `await reloadAllLayers()` call inside the complete
  handler to work. Without `async`, the await is silently ignored and the function returns before
  the reload finishes.
- `layerControl` must be declared `let` at module scope and the `const` removed from the inner
  assignment. If both exist (`let layerControl` at top and `const layerControl` inside the then
  block), the inner one shadows the outer one and reloadAllLayers() sees `null`.
- `fuelOverlayLayer` and `elevOverlayLayer` must be module-level so reloadAllLayers() can call
  `map.removeLayer()` on the previous overlays before adding fresh ones. Without this, each
  run stacks a new overlay on top of the old one.
- Cache-bust the overlay PNG URLs with `?t=Date.now()`. The browser caches image URLs aggressively
  and will serve the old fuel/elevation PNG without the query string parameter.
- `animCache` is reset to `{}` at the start of reloadAllLayers — this is correct and necessary.
  If not reset, the animation panel will display stale frames from the previous run.
- `generate_overlays()` is synchronous in the FastAPI main thread. For large AOIs it may block
  for a few seconds after the run completes before the `complete` SSE event is emitted. This is
  acceptable for now.

---

## Prompt 7.4 — Validation + UX Polish

```
Read these files in full before making any changes:
  - pipelines/11_web_ui/src/app.py
  - pipelines/11_web_ui/templates/index.html

Context: prompts 7.1–7.3 are complete and the scenario builder runs end-to-end. This prompt
adds server-side date and ignition validation, client-side bbox size feedback, and an ignition
placement warning when the ignition point is outside the drawn bbox.

### 1. app.py — weather date validation

In the run_scenario endpoint, after the bbox dimension checks, add:

  from datetime import date as _date
  try:
      _date.fromisoformat(req.weather_date)
  except ValueError:
      return JSONResponse(
          {"detail": f"Invalid weather_date '{req.weather_date}' — use YYYY-MM-DD"},
          status_code=422)

### 2. app.py — ignition within bbox validation

After the date check, add:

  if not (req.bbox_south <= req.ignition_lat <= req.bbox_north and
          req.bbox_west  <= req.ignition_lon <= req.bbox_east):
      return JSONResponse(
          {"detail": "Ignition point is outside the bounding box"},
          status_code=422)

### 3. index.html — client-side bbox size feedback

Inside the map.on(L.Draw.Event.CREATED, ...) handler, after storing scenarioBbox and displaying
the bbox coords, add:

  const width  = Math.abs(scenarioBbox.east  - scenarioBbox.west);
  const height = Math.abs(scenarioBbox.north - scenarioBbox.south);
  const errEl  = document.getElementById('scenario-error');
  if (width > 2.0 || height > 2.0) {
    errEl.textContent =
      `AOI too large (${width.toFixed(2)}° × ${height.toFixed(2)}°) — max 2° × 2°. ` +
      `Large areas take 10+ min and require a new LANDFIRE download.`;
    errEl.style.display = '';
    if (drawnBboxLayer) drawnBboxLayer.setStyle({ color: '#e94560' });
    scenarioBbox = null;
    _checkRunReady();
    return;
  }
  if (width < 0.05 || height < 0.05) {
    errEl.textContent =
      `AOI too small (${width.toFixed(3)}° × ${height.toFixed(3)}°) — minimum 0.05°`;
    errEl.style.display = '';
    if (drawnBboxLayer) drawnBboxLayer.setStyle({ color: '#e94560' });
    scenarioBbox = null;
    _checkRunReady();
    return;
  }
  errEl.style.display = 'none';

### 4. index.html — ignition outside bbox warning

In the map click handler, after storing scenarioIgnition, add:

  if (scenarioBbox) {
    const inside = scenarioIgnition.lat >= scenarioBbox.south &&
                   scenarioIgnition.lat <= scenarioBbox.north &&
                   scenarioIgnition.lon >= scenarioBbox.west  &&
                   scenarioIgnition.lon <= scenarioBbox.east;
    if (!inside) {
      document.getElementById('ignition-display').textContent +=
        '\n⚠ Outside AOI bbox';
    }
  }

Do not block the run for this — the server validation in step 2 will reject it with a clear
message if the user tries to run anyway.

Rebuild the pipeline 11 image and verify with `make ui-dev`.
```

### Tests for 7.4:
```bash
# UI must be running via `make ui-dev` before these tests

# 1. Bad weather date rejected with 422
curl -sf -X POST http://localhost:8001/api/run \
  -H "Content-Type: application/json" \
  -d '{"bbox_north":35.65,"bbox_south":35.55,"bbox_east":-83.7,"bbox_west":-83.83,
       "weather_date":"not-a-date","ignition_lat":35.56,"ignition_lon":-83.75}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'weather_date' in d.get('detail',''), f'Expected weather_date in detail, got: {d}'
print('PASS: bad weather date rejected')
"

# 2. Ignition outside bbox rejected with 422
curl -sf -X POST http://localhost:8001/api/run \
  -H "Content-Type: application/json" \
  -d '{"bbox_north":35.65,"bbox_south":35.55,"bbox_east":-83.7,"bbox_west":-83.83,
       "weather_date":"2016-11-28","ignition_lat":40.0,"ignition_lon":-83.75}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'outside' in d.get('detail','').lower(), f'Expected \"outside\" in detail, got: {d}'
print('PASS: out-of-bbox ignition rejected')
"

# 3. Valid request still accepted (ignition inside bbox)
STATUS=$(curl -sf -o /dev/null -w "%{http_code}" -X POST http://localhost:8001/api/run \
  -H "Content-Type: application/json" \
  -d '{"bbox_north":35.65,"bbox_south":35.55,"bbox_east":-83.7,"bbox_west":-83.83,
       "weather_date":"2016-11-28","ignition_lat":35.56,"ignition_lon":-83.75}')
[ "$STATUS" = "202" ] \
  && echo "PASS: valid request still returns 202 after validation added" \
  || echo "FAIL: expected 202, got $STATUS"

# Cancel the run so the lock is released for subsequent tests
sleep 1
curl -sf http://localhost:8001/api/run/cancel > /dev/null

# 4. bbox size validation code is in the HTML JS
curl -sf http://localhost:8001/ | grep -q 'AOI too large\|max 2' \
  && echo "PASS: bbox too-large error message in JS" || echo "FAIL: bbox size check missing"
curl -sf http://localhost:8001/ | grep -q 'AOI too small\|minimum 0.05\|0\.05' \
  && echo "PASS: bbox too-small error message in JS" || echo "FAIL: bbox min-size check missing"

# 5. Outside bbox warning text is in the HTML JS
curl -sf http://localhost:8001/ | grep -q 'Outside AOI bbox' \
  && echo "PASS: ignition outside-bbox warning in JS" || echo "FAIL: ignition warning missing"

# Manual browser checks (cannot be automated):
# - Draw bbox > 2° in either dimension → outline turns red, error shown, Run stays disabled
# - Draw bbox < 0.05° → same red outline + error
# - Valid bbox → outline stays cyan, no error shown
# - Place ignition outside drawn bbox → "⚠ Outside AOI bbox" appears under lat/lon display
# - Clicking Run with out-of-bbox ignition → server returns error message shown in sidebar
```

**Known landmines:**
- `_date.fromisoformat()` in Python 3.10 and earlier accepts only strict `YYYY-MM-DD`. In 3.11+
  it also accepts datetime strings — fine for our purposes either way.
- The server rejects ignitions outside the bbox with 422. This means a user who draws a bbox
  and places the ignition just outside will get a hard error on Run. If this causes friction during
  testing, relax the server check to a warning (log but proceed) — pipeline 08 already handles
  non-burnable cells gracefully with a 50-cell search radius.
- The `errEl.style.display = 'none'` line that clears the error on a valid bbox must appear at
  the end of the CREATED handler, after the size checks. If it runs before the checks, valid
  draws will briefly flash a cleared error state on re-draw.
- The `return` inside the size-check blocks exits the CREATED handler early, so `_checkRunReady()`
  is called inside the block before returning. If you forget this call, the Run button will stay
  enabled with a null `scenarioBbox` and the POST will fail silently.
