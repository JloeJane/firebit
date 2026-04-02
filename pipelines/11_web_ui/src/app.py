import json
import os
from pathlib import Path

import geopandas as gpd
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
