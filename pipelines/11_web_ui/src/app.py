import csv
import io
import json
import os
import queue
import shutil
import threading
import time
from pathlib import Path

import docker as docker_sdk
import geopandas as gpd
import matplotlib.cm as cm
import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from rasterio.warp import reproject, Resampling, calculate_default_transform
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import unary_union
from PIL import Image
from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Wildfire Platform")

BASE_DIR = Path(__file__).parent.parent
HTML_PATH = BASE_DIR / "templates" / "index.html"

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
AOI_SHP          = "/data/input/aoi_reprojected.shp"
EXPOSED_BLDGS    = "/data/output/exposed_buildings.geojson"
ALL_BLDGS        = "/data/assets/buildings.geojson"
SUMMARY_JSON     = "/data/output/consequence_summary.json"
IGNITION_JSON    = "/data/grid/ignition_metadata.json"
GRIDS_DIR        = Path("/data/simulation/grids")
FUEL_TIF         = Path("/data/fuel/fuel_clipped.tif")
ELEVATION_TIF    = Path("/data/topography/elevation.tif")
AOI_METADATA     = "/data/input/aoi_metadata.json"

HOST_DATA_DIR = os.environ.get("HOST_DATA_DIR", "/data")

# Run state — written by background thread, read by SSE endpoint
_run_lock   = threading.Lock()
_run_events: queue.Queue = queue.Queue()
_run_cancel = threading.Event()

# ---------------------------------------------------------------------------
# Timestep helpers — lazy-loaded on first request
# ---------------------------------------------------------------------------
TIMESTEP_CACHE: dict[int, dict] = {}
_TRANSFORMER = Transformer.from_crs(5070, 4326, always_xy=True)


def _tif_list() -> list[Path]:
    return sorted(GRIDS_DIR.glob("grid_t*.tif"))


def _vectorize_tif(tif_path: Path) -> list[dict]:
    """Read a burned-cell GeoTIFF, dissolve into one multipolygon, reproject to WGS84."""
    with rasterio.open(tif_path) as src:
        band = src.read(1).astype(np.uint8)
        mask = (band == 1).astype(np.uint8)
        if not mask.any():
            return []
        raw_shapes = [
            shape(geom) for geom, val in rasterio_shapes(mask, transform=src.transform)
            if val == 1
        ]
        if not raw_shapes:
            return []
        dissolved = unary_union(raw_shapes)
    # reproject the dissolved geometry to WGS84
    dissolved_wgs84 = _reproject_shape(dissolved)
    geom_json = dissolved_wgs84.__geo_interface__
    return [{"type": "Feature", "geometry": geom_json, "properties": {}}]


def _reproject_shape(geom):
    """Reproject a shapely geometry from EPSG:5070 to WGS84 in one pass."""
    import shapely.ops
    return shapely.ops.transform(
        lambda x, y: _TRANSFORMER.transform(x, y),
        geom,
    )


def _load_timestep(idx: int) -> dict:
    if idx not in TIMESTEP_CACHE:
        tifs = _tif_list()
        if idx >= len(tifs):
            return {"type": "FeatureCollection", "features": []}
        try:
            features = _vectorize_tif(tifs[idx])
            TIMESTEP_CACHE[idx] = {"type": "FeatureCollection", "features": features}
        except Exception as e:
            print(f"WARNING: failed to load timestep {idx}: {e}")
            TIMESTEP_CACHE[idx] = {"type": "FeatureCollection", "features": []}
    return TIMESTEP_CACHE[idx]


def _perimeter_from_final_frame() -> dict:
    """Derive fire perimeter by dissolving burned cells in the final grid_t*.tif."""
    tifs = _tif_list()
    if not tifs:
        return EMPTY_FC
    try:
        with rasterio.open(tifs[-1]) as src:
            band = src.read(1).astype(np.uint8)
            mask = (band == 1).astype(np.uint8)
            polygons = [
                shape(geom)
                for geom, val in rasterio_shapes(mask, transform=src.transform)
                if val == 1
            ]
        if not polygons:
            return EMPTY_FC
        merged = unary_union(polygons)
        # Reproject from EPSG:5070 to EPSG:4326 via geopandas
        gdf = gpd.GeoDataFrame(geometry=[merged], crs="EPSG:5070").to_crs(epsg=4326)
        return json.loads(gdf.to_json())
    except Exception as e:
        print(f"WARNING: failed to derive perimeter from final frame: {e}")
        return EMPTY_FC


# ---------------------------------------------------------------------------
# Raster overlay PNGs — built once at startup
# ---------------------------------------------------------------------------

def _tab10_rgb(idx: int) -> tuple:
    r, g, b, _ = cm.tab10(idx / 10.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def _build_fuel_lut() -> np.ndarray:
    """256-row RGBA lookup table for FBFM40 codes (Anderson 13 and S&B 40).

    Palette is ecologically intuitive:
      GR  (grass)            — tan/yellow:    fast spread, low intensity
      GS  (grass-shrub)      — yellow-green:  transitional
      SH  (shrub)            — olive green:   moderate load
      TU  (timber understory)— forest green:  high intensity when ignited
      TL  (timber litter)    — brown:         deep litter, sustained burn
      SB  (slash-blowdown)   — dark brown:    heavy load, extreme behavior
    """
    lut = np.zeros((256, 4), dtype=np.uint8)  # default: transparent

    GR = (210, 180, 100, 180)   # tan
    GS = (180, 200,  80, 180)   # yellow-green
    SH = (100, 150,  60, 180)   # olive green
    TU = ( 40, 110,  50, 180)   # forest green
    TL = (139, 100,  55, 180)   # brown
    SB = ( 90,  60,  30, 180)   # dark brown

    # Anderson 13 codes
    for code in range(1, 10):    lut[code] = GR
    for code in range(10, 20):   lut[code] = SH
    for code in range(20, 30):   lut[code] = TL
    for code in range(30, 41):   lut[code] = SB

    # S&B FBFM40 codes
    for code in range(101, 110): lut[code] = GR   # GR grass
    for code in range(121, 125): lut[code] = GS   # GS grass-shrub
    for code in range(141, 150): lut[code] = SH   # SH shrub
    for code in range(161, 166): lut[code] = TU   # TU timber understory
    for code in range(181, 190): lut[code] = TL   # TL timber litter
    for code in range(201, 205): lut[code] = SB   # SB slash-blowdown

    # Non-burnable codes stay transparent (already 0)
    return lut


def _warp_to_4326(src_path: Path) -> np.ndarray:
    """Reproject a single-band raster to EPSG:4326 aligned to the AOI bbox_4326 extent."""
    with open(AOI_METADATA) as f:
        bbox = json.load(f).get("bbox_4326", {})
    west  = bbox["west"]
    south = bbox["south"]
    east  = bbox["east"]
    north = bbox["north"]

    with rasterio.open(src_path) as src:
        # Compute output dimensions that preserve approx the same pixel density
        _, native_w, native_h = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds
        )
        dst_transform = rasterio.transform.from_bounds(west, south, east, north, native_w, native_h)
        destination = np.zeros((native_h, native_w), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
            src_nodata=src.nodata,
            dst_nodata=0,
        )
    return destination


def _generate_fuel_overlay() -> bytes | None:
    if not FUEL_TIF.exists():
        print("WARNING: fuel_clipped.tif not found — fuel overlay unavailable")
        return None
    try:
        band = _warp_to_4326(FUEL_TIF).astype(np.uint8)
        lut = _build_fuel_lut()
        rgba = lut[band]
        buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
        print("INFO: fuel overlay generated")
        return buf.getvalue()
    except Exception as e:
        print(f"WARNING: failed to generate fuel overlay: {e}")
        return None


def _generate_elevation_overlay() -> bytes | None:
    if not ELEVATION_TIF.exists():
        print("WARNING: elevation.tif not found — elevation overlay unavailable")
        return None
    try:
        band = _warp_to_4326(ELEVATION_TIF)
        mask = (band == 0)
        band[mask] = np.nan
        valid = band[~mask]
        elev_min, elev_max = float(np.nanmin(valid)), float(np.nanmax(valid))
        norm = np.zeros_like(band)
        norm[~mask] = (band[~mask] - elev_min) / (elev_max - elev_min)
        rgba = (cm.terrain(norm) * 255).astype(np.uint8)
        rgba[mask, 3] = 0
        rgba[~mask, 3] = 160
        buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
        print("INFO: elevation overlay generated")
        return buf.getvalue()
    except Exception as e:
        print(f"WARNING: failed to generate elevation overlay: {e}")
        return None


FUEL_OVERLAY_PNG: bytes | None = None
ELEVATION_OVERLAY_PNG: bytes | None = None


def generate_overlays() -> None:
    global FUEL_OVERLAY_PNG, ELEVATION_OVERLAY_PNG
    FUEL_OVERLAY_PNG = _generate_fuel_overlay()
    ELEVATION_OVERLAY_PNG = _generate_elevation_overlay()


generate_overlays()


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

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


class ScenarioRequest(BaseModel):
    bbox_north:    float
    bbox_south:    float
    bbox_east:     float
    bbox_west:     float
    weather_date:  str    # "YYYY-MM-DD"
    ignition_lat:  float
    ignition_lon:  float


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMPTY_FC = {"type": "FeatureCollection", "features": []}


def safe_read_geojson(path: str) -> dict:
    """Read a GeoJSON file and reproject to EPSG:4326. Returns empty FC on failure."""
    if not os.path.exists(path):
        return EMPTY_FC
    try:
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:5070")
        gdf = gdf.to_crs(epsg=4326)
        return json.loads(gdf.to_json())
    except Exception as e:
        print(f"WARNING: failed to load {path}: {e}")
        return EMPTY_FC


def safe_read_shp(path: str) -> dict:
    """Read a shapefile and reproject to EPSG:4326. Returns empty FC on failure."""
    if not os.path.exists(path):
        return EMPTY_FC
    try:
        gdf = gpd.read_file(path)
        gdf = gdf.to_crs(epsg=4326)
        return json.loads(gdf.to_json())
    except Exception as e:
        print(f"WARNING: failed to load {path}: {e}")
        return EMPTY_FC


def safe_read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML_PATH.read_text())


@app.get("/api/aoi")
async def get_aoi():
    return JSONResponse(safe_read_shp(AOI_SHP))


@app.get("/api/fire-perimeter")
async def get_fire_perimeter():
    return JSONResponse(_perimeter_from_final_frame())


@app.get("/api/buildings/exposed")
async def get_exposed_buildings():
    return JSONResponse(safe_read_geojson(EXPOSED_BLDGS))


@app.get("/api/buildings/all")
async def get_all_buildings():
    return JSONResponse(safe_read_geojson(ALL_BLDGS))


@app.get("/api/summary")
async def get_summary():
    return JSONResponse(safe_read_json(SUMMARY_JSON))


@app.get("/api/ignition")
async def get_ignition():
    meta = safe_read_json(IGNITION_JSON)
    if not meta:
        return JSONResponse(EMPTY_FC)
    return JSONResponse({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [meta["lon"], meta["lat"]],
            },
            "properties": {
                "cell_id": meta.get("cell_id"),
                "fuel_code": meta.get("fuel_code"),
            },
        }],
    })


@app.get("/api/overlay/fuel.png")
async def get_fuel_overlay():
    if FUEL_OVERLAY_PNG is None:
        return JSONResponse({"detail": "fuel overlay not available"}, status_code=404)
    return Response(content=FUEL_OVERLAY_PNG, media_type="image/png")


@app.get("/api/overlay/elevation.png")
async def get_elevation_overlay():
    if ELEVATION_OVERLAY_PNG is None:
        return JSONResponse({"detail": "elevation overlay not available"}, status_code=404)
    return Response(content=ELEVATION_OVERLAY_PNG, media_type="image/png")


@app.get("/api/overlay/bounds")
async def get_overlay_bounds():
    meta = safe_read_json(AOI_METADATA)
    bbox = meta.get("bbox_4326", {})
    return JSONResponse({
        "south": bbox.get("south"),
        "west":  bbox.get("west"),
        "north": bbox.get("north"),
        "east":  bbox.get("east"),
    })


@app.get("/api/weather")
async def get_weather():
    path = "/data/grid/Weather.csv"
    if not os.path.exists(path):
        return JSONResponse([])
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({"ws": float(r["WS"]), "wd": float(r["WD"])})
            except (KeyError, ValueError):
                pass
    return JSONResponse(rows)


@app.get("/api/grids/")
async def get_grids_list():
    tifs = _tif_list()
    return JSONResponse({"timesteps": list(range(len(tifs))), "count": len(tifs)})


@app.get("/api/grids/{timestep}")
async def get_grid_timestep(timestep: int):
    tifs = _tif_list()
    if timestep < 0 or timestep >= len(tifs):
        return JSONResponse({"detail": "timestep not found"}, status_code=404)
    return JSONResponse(_load_timestep(timestep))


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


@app.get("/api/run/cancel")
async def cancel_run():
    _run_cancel.set()
    return {"status": "cancelling"}
