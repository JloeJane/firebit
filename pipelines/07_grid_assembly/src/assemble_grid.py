"""
Pipeline 07 — Grid Assembly (ELMFIRE format)

Assembles all upstream outputs into ELMFIRE-ready GeoTIFF rasters
and generates the elmfire.data Fortran namelist config.

Outputs in /data/grid/:
  Fuel/topo (int16):  fbfm40, asp, slp, dem, cc, ch, cbh, cbd
  Float rasters:      adj, phi, ws, wd, m1, m10, m100
  Config:             elmfire.data
  Metadata:           grid_metadata.json
"""

import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_bounds

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FUEL_DIR    = Path("/data/fuel")
TOPO_DIR    = Path("/data/topography")
WEATHER_DIR = Path("/data/weather")
MOISTURE_JSON = Path("/data/moisture/fuel_moisture.json")
AOI_META    = Path("/data/input/aoi_metadata.json")
OUT_DIR     = Path("/data/grid")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIM_HOURS = int(os.environ.get("ELMFIRE_SIMULATION_HOURS", 24))
CROWN_FIRE = os.environ.get("ELMFIRE_CROWN_FIRE", "1") == "1"
SPOTTING   = os.environ.get("ELMFIRE_ENABLE_SPOTTING", "true").lower() == "true"

DEFAULT_IGN_LAT = float(os.environ.get("IGNITION_LAT", 0))
DEFAULT_IGN_LON = float(os.environ.get("IGNITION_LON", 0))

# ---------------------------------------------------------------------------
# Required input rasters: (source_path, dest_name, dtype)
# ---------------------------------------------------------------------------
INT16_LAYERS = [
    (FUEL_DIR  / "fbfm40.tif", "fbfm40.tif"),
    (FUEL_DIR  / "cc.tif",     "cc.tif"),
    (FUEL_DIR  / "ch.tif",     "ch.tif"),
    (FUEL_DIR  / "cbh.tif",    "cbh.tif"),
    (FUEL_DIR  / "cbd.tif",    "cbd.tif"),
    (TOPO_DIR  / "elevation.tif", "dem.tif"),
    (TOPO_DIR  / "slope.tif",     "slp.tif"),
    (TOPO_DIR  / "aspect.tif",    "asp.tif"),
]

FLOAT32_WIND = [
    (WEATHER_DIR / "ws.tif", "ws.tif"),
    (WEATHER_DIR / "wd.tif", "wd.tif"),
]


def open_required(path):
    if not path.exists():
        sys.exit(f"ERROR: Required input missing: {path}")
    return rasterio.open(path)


def validate_alignment(rasters, ref_name="fbfm40.tif"):
    """Verify all rasters have matching CRS, dimensions, and origin."""
    ref = rasters[ref_name]
    errors = []
    for name, src in rasters.items():
        if name == ref_name:
            continue
        if src.crs != ref.crs:
            errors.append(f"  CRS mismatch: {name} {src.crs} vs ref {ref.crs}")
        if (src.height, src.width) != (ref.height, ref.width):
            errors.append(f"  Dimension mismatch: {name} {src.height}×{src.width} vs ref {ref.height}×{ref.width}")
        if not math.isclose(src.transform.c, ref.transform.c, abs_tol=1.0):
            errors.append(f"  X-origin mismatch: {name} {src.transform.c:.2f} vs ref {ref.transform.c:.2f}")
        if not math.isclose(src.transform.f, ref.transform.f, abs_tol=1.0):
            errors.append(f"  Y-origin mismatch: {name} {src.transform.f:.2f} vs ref {ref.transform.f:.2f}")
    if errors:
        print("ERROR: Raster alignment validation FAILED:")
        for e in errors:
            print(e)
        sys.exit(1)
    print(f"  Alignment OK — {len(rasters)} rasters, {ref.height}×{ref.width}, CRS={ref.crs}")


def copy_as_int16(src_path, dst_path):
    with rasterio.open(src_path) as src:
        data = src.read(1)
        nodata = src.nodata if src.nodata is not None else -9999
        data = np.where(data == nodata, -9999, data).astype(np.int16)
        meta = src.meta.copy()
        meta.update(dtype="int16", nodata=-9999, compress="lzw")
        with rasterio.open(dst_path, "w", **meta) as dst:
            dst.write(data, 1)
    valid = data[data != -9999]
    print(f"  {dst_path.name}  range: [{valid.min()}, {valid.max()}]")


def copy_as_float32(src_path, dst_path):
    with rasterio.open(src_path) as src:
        data = src.read(1).astype(np.float32)
        nodata = float(src.nodata) if src.nodata is not None else -9999.0
        data = np.where(data == nodata, -9999.0, data)
        meta = src.meta.copy()
        meta.update(dtype="float32", nodata=-9999.0, compress="lzw")
        with rasterio.open(dst_path, "w", **meta) as dst:
            dst.write(data, 1)
    valid = data[data != -9999.0]
    print(f"  {dst_path.name}  range: [{valid.min():.2f}, {valid.max():.2f}]")


def create_uniform_float32(value, ref_path, dst_path):
    with rasterio.open(ref_path) as ref:
        meta = ref.meta.copy()
        shape = (ref.height, ref.width)
    meta.update(dtype="float32", nodata=-9999.0, count=1, compress="lzw")
    data = np.full(shape, value, dtype=np.float32)
    with rasterio.open(dst_path, "w", **meta) as dst:
        dst.write(data, 1)
    print(f"  {dst_path.name}  uniform value: {value}")


def create_moisture_raster(value, ref_path, dst_path):
    create_uniform_float32(float(value), ref_path, dst_path)


def get_ignition_xy(aoi):
    """Return ignition point in EPSG:5070. Uses env vars or falls back to AOI center."""
    lat = DEFAULT_IGN_LAT
    lon = DEFAULT_IGN_LON

    if lat == 0 and lon == 0:
        # Fall back to AOI center
        b = aoi["bbox_4326"]
        lat = (b["north"] + b["south"]) / 2
        lon = (b["east"] + b["west"]) / 2
        print(f"  No IGNITION_LAT/LON set — using AOI center: {lat:.5f}, {lon:.5f}")
    else:
        print(f"  Ignition from env: {lat:.5f}, {lon:.5f}")

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    x, y = transformer.transform(lon, lat)
    print(f"  Ignition EPSG:5070: x={x:.2f}, y={y:.2f}")
    return x, y


def get_domain_corners(ref_path):
    """Return (xllcorner, yllcorner, cellsize) from a raster."""
    with rasterio.open(ref_path) as src:
        t = src.transform
        xll = t.c
        yll = t.f + src.height * t.e   # upper-left Y - nrows * cellsize
        cellsize = abs(t.a)
    return xll, yll, cellsize


def write_elmfire_data(out_path, xll, yll, cellsize, x_ign, y_ign, moisture, sim_hours,
                       n_met_bands, crown_fire, spotting):
    sim_tstop = sim_hours * 3600.0
    lh_mc = moisture.get("live_herb_pct", 30)
    lw_mc = moisture.get("live_woody_pct", 60)

    crown_block = ""
    if crown_fire:
        crown_block = """
&CROWN_FIRE
CROWN_FIRE_MODEL = 1
/
"""

    spotting_block = ""
    if spotting:
        spotting_block = """
&SPOTTING
ENABLE_SPOTTING = .TRUE.
CROWN_FIRE_SPOTTING_PERCENT = 1.0
ENABLE_SURFACE_FIRE_SPOTTING = .FALSE.
/
"""

    config = f"""&INPUTS
FUELS_AND_TOPOGRAPHY_DIRECTORY = './inputs'
ASP_FILENAME                   = 'asp'
CBD_FILENAME                   = 'cbd'
CBH_FILENAME                   = 'cbh'
CC_FILENAME                    = 'cc'
CH_FILENAME                    = 'ch'
DEM_FILENAME                   = 'dem'
FBFM_FILENAME                  = 'fbfm40'
SLP_FILENAME                   = 'slp'
ADJ_FILENAME                   = 'adj'
PHI_FILENAME                   = 'phi'
DT_METEOROLOGY                 = 3600.0
WEATHER_DIRECTORY              = './inputs'
WS_FILENAME                    = 'ws'
WD_FILENAME                    = 'wd'
M1_FILENAME                    = 'm1'
M10_FILENAME                   = 'm10'
M100_FILENAME                  = 'm100'
LH_MOISTURE_CONTENT            = {lh_mc:.1f}
LW_MOISTURE_CONTENT            = {lw_mc:.1f}
/

&OUTPUTS
OUTPUTS_DIRECTORY              = './outputs'
DTDUMP                         = 3600.0
DUMP_FLIN                      = .TRUE.
DUMP_SPREAD_RATE               = .TRUE.
DUMP_TIME_OF_ARRIVAL           = .TRUE.
CONVERT_TO_GEOTIFF             = .FALSE.
/

&COMPUTATIONAL_DOMAIN
A_SRS                          = 'EPSG:5070'
COMPUTATIONAL_DOMAIN_CELLSIZE  = {int(cellsize)}
COMPUTATIONAL_DOMAIN_XLLCORNER = {xll:.2f}
COMPUTATIONAL_DOMAIN_YLLCORNER = {yll:.2f}
/

&TIME_CONTROL
SIMULATION_DT                  = 30.0
SIMULATION_TSTOP               = {sim_tstop:.1f}
/

&SIMULATOR
NUM_IGNITIONS                  = 1
X_IGN(1)                       = {x_ign:.2f}
Y_IGN(1)                       = {y_ign:.2f}
T_IGN(1)                       = 0.0
WX_BILINEAR_INTERPOLATION      = .TRUE.
/

&MISCELLANEOUS
PATH_TO_GDAL                   = '/usr/bin'
SCRATCH                        = './scratch'
/

&MONTE_CARLO
NUM_ENSEMBLE_MEMBERS           = 1
NUM_METEOROLOGY_BANDS          = {n_met_bands}
/
{crown_block}{spotting_block}"""

    out_path.write_text(config.strip() + "\n")
    print(f"  elmfire.data written (tstop={sim_tstop:.0f}s, ign=({x_ign:.0f},{y_ign:.0f}), bands={n_met_bands})")


def main():
    print("=== Step 7: Grid Assembly (ELMFIRE) ===\n")

    # --- A: Load AOI and moisture ---
    with open(AOI_META) as f:
        aoi = json.load(f)
    with open(MOISTURE_JSON) as f:
        moisture = json.load(f)

    # --- B: Validate alignment of all int16 layers ---
    print("--- Validating raster alignment ---")
    rasters = {}
    for src_path, dst_name in INT16_LAYERS:
        r = open_required(src_path)
        rasters[dst_name] = r
    validate_alignment(rasters, ref_name="fbfm40.tif")
    for r in rasters.values():
        r.close()

    ref_path = FUEL_DIR / "fbfm40.tif"

    # --- C: Copy/convert int16 fuel and topo layers ---
    print("\n--- Copying fuel and topo layers (int16) ---")
    for src_path, dst_name in INT16_LAYERS:
        copy_as_int16(src_path, OUT_DIR / dst_name)

    # --- D: Copy wind rasters (float32) ---
    print("\n--- Copying wind rasters (float32) ---")
    n_met_bands = 1
    for src_path, dst_name in FLOAT32_WIND:
        if src_path.exists():
            copy_as_float32(src_path, OUT_DIR / dst_name)
            with rasterio.open(OUT_DIR / dst_name) as s:
                n_met_bands = s.count
        else:
            print(f"  WARNING: {src_path} missing — creating uniform fallback")
            val = 10.0 if "ws" in dst_name else 270.0
            create_uniform_float32(val, ref_path, OUT_DIR / dst_name)

    # --- E: Create adjustment and phi rasters ---
    print("\n--- Creating adj and phi rasters (float32, uniform 1.0) ---")
    create_uniform_float32(1.0, ref_path, OUT_DIR / "adj.tif")
    create_uniform_float32(1.0, ref_path, OUT_DIR / "phi.tif")

    # --- F: Create moisture rasters ---
    print("\n--- Creating moisture rasters (float32) ---")
    for key, fname in [("dead_1hr_pct", "m1.tif"), ("dead_10hr_pct", "m10.tif"), ("dead_100hr_pct", "m100.tif")]:
        create_moisture_raster(moisture[key], ref_path, OUT_DIR / fname)

    # --- G: Generate elmfire.data ---
    print("\n--- Generating elmfire.data ---")
    xll, yll, cellsize = get_domain_corners(ref_path)
    x_ign, y_ign = get_ignition_xy(aoi)
    write_elmfire_data(
        OUT_DIR / "elmfire.data",
        xll, yll, cellsize, x_ign, y_ign,
        moisture, SIM_HOURS, n_met_bands, CROWN_FIRE, SPOTTING,
    )

    # --- H: Write grid_metadata.json ---
    print("\n--- Writing grid_metadata.json ---")
    with rasterio.open(ref_path) as ref:
        nrows, ncols = ref.height, ref.width
        crs = str(ref.crs)

    outputs = [f.name for f in OUT_DIR.iterdir() if f.suffix in (".tif", ".data")]
    metadata = {
        "engine":       "elmfire",
        "ncols":        ncols,
        "nrows":        nrows,
        "cellsize":     int(cellsize),
        "xllcorner":    round(xll, 2),
        "yllcorner":    round(yll, 2),
        "crs":          crs,
        "sim_hours":    SIM_HOURS,
        "n_met_bands":  n_met_bands,
        "crown_fire":   CROWN_FIRE,
        "spotting":     SPOTTING,
        "outputs":      sorted(outputs),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(OUT_DIR / "grid_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print("\n" + "=" * 60)
    print("GRID ASSEMBLY COMPLETE (ELMFIRE)")
    print("=" * 60)
    print(f"  Grid: {nrows}×{ncols}, cellsize={int(cellsize)}m, CRS={crs}")
    print(f"  Domain LL: ({xll:.0f}, {yll:.0f})")
    print(f"  Ignition:  ({x_ign:.0f}, {y_ign:.0f})")
    print(f"  Outputs ({len(outputs)}): {', '.join(sorted(outputs))}")


if __name__ == "__main__":
    main()
