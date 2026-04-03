import io
import json
import os
from pathlib import Path

import geopandas as gpd
import matplotlib.cm as cm
import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from pyproj import Transformer
from PIL import Image
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response

app = FastAPI(title="Wildfire Platform")

BASE_DIR = Path(__file__).parent.parent
HTML_PATH = BASE_DIR / "templates" / "index.html"

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
AOI_SHP          = "/data/input/aoi_reprojected.shp"
FIRE_PERIMETER   = "/data/output/fire_perimeter.geojson"
EXPOSED_BLDGS    = "/data/output/exposed_buildings.geojson"
ALL_BLDGS        = "/data/assets/buildings.geojson"
SUMMARY_JSON     = "/data/output/consequence_summary.json"
IGNITION_JSON    = "/data/grid/ignition_metadata.json"
GRIDS_DIR        = Path("/data/simulation/grids")
FUEL_TIF         = Path("/data/fuel/fuel_clipped.tif")
ELEVATION_TIF    = Path("/data/topography/elevation.tif")
AOI_METADATA     = "/data/input/aoi_metadata.json"

# ---------------------------------------------------------------------------
# Timestep cache — built once at startup
# ---------------------------------------------------------------------------
TIMESTEP_CACHE: dict[int, dict] = {}

def _build_timestep_cache() -> None:
    if not GRIDS_DIR.exists():
        print("WARNING: data/simulation/grids/ does not exist — animation unavailable")
        return
    tifs = sorted(GRIDS_DIR.glob("grid_t*.tif"))
    if not tifs:
        print("WARNING: no grid_t*.tif files found in data/simulation/grids/ — animation unavailable")
        return
    transformer = Transformer.from_crs(5070, 4326, always_xy=True)
    for idx, tif_path in enumerate(tifs):
        try:
            with rasterio.open(tif_path) as src:
                band = src.read(1).astype(np.uint8)
                mask = (band == 1).astype(np.uint8)
                features = []
                for geom_dict, val in rasterio_shapes(mask, transform=src.transform):
                    if val != 1:
                        continue
                    # Reproject coordinates from EPSG:5070 to EPSG:4326
                    coords = geom_dict["coordinates"]
                    reprojected = []
                    for ring in coords:
                        new_ring = [list(transformer.transform(x, y)) for x, y in ring]
                        reprojected.append(new_ring)
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": geom_dict["type"], "coordinates": reprojected},
                        "properties": {},
                    })
            TIMESTEP_CACHE[idx] = {"type": "FeatureCollection", "features": features}
            print(f"INFO: loaded timestep {idx} from {tif_path.name} ({len(features)} features)")
        except Exception as e:
            print(f"WARNING: failed to load {tif_path}: {e}")

_build_timestep_cache()


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


def _generate_fuel_overlay() -> bytes | None:
    if not FUEL_TIF.exists():
        print("WARNING: fuel_clipped.tif not found — fuel overlay unavailable")
        return None
    try:
        with rasterio.open(FUEL_TIF) as src:
            band = src.read(1)
            nodata = src.nodata
        if nodata is not None:
            band = np.where(band == int(nodata), 0, band)
        band = band.astype(np.uint8)
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
        with rasterio.open(ELEVATION_TIF) as src:
            band = src.read(1).astype(np.float32)
            nodata = src.nodata
        mask = (band == nodata) if nodata is not None else ~np.isfinite(band)
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
    return JSONResponse(safe_read_geojson(FIRE_PERIMETER))


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


@app.get("/api/grids/")
async def get_grids_list():
    keys = sorted(TIMESTEP_CACHE.keys())
    return JSONResponse({"timesteps": keys, "count": len(keys)})


@app.get("/api/grids/{timestep}")
async def get_grid_timestep(timestep: int):
    if timestep not in TIMESTEP_CACHE:
        return JSONResponse({"detail": "timestep not found"}, status_code=404)
    return JSONResponse(TIMESTEP_CACHE[timestep])
