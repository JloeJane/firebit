import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from pyproj import Transformer
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

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


@app.get("/api/grids/")
async def get_grids_list():
    keys = sorted(TIMESTEP_CACHE.keys())
    return JSONResponse({"timesteps": keys, "count": len(keys)})


@app.get("/api/grids/{timestep}")
async def get_grid_timestep(timestep: int):
    if timestep not in TIMESTEP_CACHE:
        return JSONResponse({"detail": "timestep not found"}, status_code=404)
    return JSONResponse(TIMESTEP_CACHE[timestep])
