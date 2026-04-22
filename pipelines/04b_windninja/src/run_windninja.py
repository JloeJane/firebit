"""
WindNinja pipeline — generates terrain-adjusted wind grids.

Reads:  data/topography/elevation.tif
        data/weather/weather_scenario.json  (base wind speed/direction)
        data/input/aoi_metadata.json

Writes: data/weather/ws.tif  (wind speed, mph, 32-bit float)
        data/weather/wd.tif  (wind direction, degrees, 32-bit float)
        data/weather/windninja_metadata.json
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

TOPO_DIR    = Path(os.environ.get("TOPO_DIR",    "/data/topography"))
WEATHER_DIR = Path(os.environ.get("WEATHER_DIR", "/data/weather"))
DATA_DIR    = Path(os.environ.get("DATA_DIR",    "/data"))

DEM_TIF          = TOPO_DIR / "elevation.tif"
WEATHER_JSON     = WEATHER_DIR / "weather_scenario.json"
AOI_META         = DATA_DIR / "input" / "aoi_metadata.json"
WS_OUT           = WEATHER_DIR / "ws.tif"
WD_OUT           = WEATHER_DIR / "wd.tif"
WINDNINJA_META   = WEATHER_DIR / "windninja_metadata.json"


def load_weather():
    if not WEATHER_JSON.exists():
        print(f"WARNING: {WEATHER_JSON} not found — using defaults (10 mph, 270°)")
        return {"wind_speed_mph": 10.0, "wind_direction_deg": 270.0}
    with open(WEATHER_JSON) as f:
        data = json.load(f)
    speed = data.get("wind_speed_mph") or data.get("wind_speed") or 10.0
    direction = data.get("wind_direction_deg") or data.get("wind_direction") or 270.0
    return {"wind_speed_mph": float(speed), "wind_direction_deg": float(direction)}


def run_windninja(dem_path, speed_mph, direction_deg, out_dir):
    """Run WindNinja_cli with domainAverageInitialization. Returns output dir."""
    cmd = [
        "WindNinja_cli",
        f"--elevation_file={dem_path}",
        "--initialization_method=domainAverageInitialization",
        f"--input_speed={speed_mph}",
        "--input_speed_units=mph",
        f"--input_direction={direction_deg}",
        "--input_wind_height=20",
        "--units_input_wind_height=ft",
        "--output_wind_height=20",
        "--units_output_wind_height=ft",
        "--vegetation=trees",
        "--mesh_resolution=30",
        "--units_mesh_resolution=m",
        "--output_speed_units=mph",
        "--write_goog_output=false",
        "--write_shapefile_output=false",
        "--write_ascii_output=false",
        "--write_farsite_atm=false",
        "--write_wx_model_goog_output=false",
        "--write_wx_model_shapefile_output=false",
        "--write_wx_model_ascii_output=false",
        f"--output_path={out_dir}",
        "--num_threads=2",
    ]

    print(f"  Running WindNinja_cli (speed={speed_mph} mph, dir={direction_deg}°)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.stdout:
        print(result.stdout[-2000:])
    if result.stderr:
        print("STDERR:", result.stderr[-1000:])

    if result.returncode != 0:
        raise RuntimeError(f"WindNinja_cli failed (exit {result.returncode})")

    return out_dir


def find_windninja_outputs(out_dir):
    """Find WindNinja velocity and angle output rasters."""
    out_path = Path(out_dir)
    vel_files = sorted(out_path.glob("*_vel.tif"))
    ang_files = sorted(out_path.glob("*_ang.tif"))

    if not vel_files or not ang_files:
        all_files = list(out_path.iterdir())
        raise FileNotFoundError(
            f"WindNinja outputs not found in {out_dir}. Files: {[f.name for f in all_files]}"
        )

    return vel_files[-1], ang_files[-1]


def save_wind_raster(src_path, out_path, ref_meta):
    """Copy a WindNinja output raster, ensuring float32 and matching CRS."""
    with rasterio.open(src_path) as src:
        data = src.read(1).astype(np.float32)
        meta = ref_meta.copy()
        meta.update(dtype="float32", count=1, nodata=-9999.0)
        with rasterio.open(out_path, "w", **meta) as dst:
            dst.write(data, 1)
    print(f"  Saved {out_path.name}  range: [{data.min():.1f}, {data.max():.1f}]")


def terrain_fallback(speed_mph, direction_deg):
    """
    Fallback when WindNinja is unavailable: terrain-adjusted wind using DEM curvature.
    Ridge cells get 1.3× speed, valley cells get 0.6× speed.
    """
    print("  Using terrain-adjustment fallback (WindNinja not available)...")

    with rasterio.open(DEM_TIF) as src:
        dem = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        nodata = src.nodata or -9999

    dem = np.where(dem == nodata, np.nan, dem)

    # Simple Laplacian curvature: positive = ridge, negative = valley
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.pad(dem, 1, mode="edge")
    laplacian = (
        pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:]
        - 4 * pad[1:-1, 1:-1]
    )

    speed_grid = np.full_like(dem, speed_mph)
    speed_grid = np.where(laplacian > 5,  speed_mph * 1.3, speed_grid)   # ridges
    speed_grid = np.where(laplacian < -5, speed_mph * 0.6, speed_grid)   # valleys
    speed_grid = np.where(np.isnan(dem), -9999.0, speed_grid)

    dir_grid = np.full_like(dem, direction_deg)
    dir_grid = np.where(np.isnan(dem), -9999.0, dir_grid)

    out_meta = meta.copy()
    out_meta.update(dtype="float32", count=1, nodata=-9999.0)

    with rasterio.open(WS_OUT, "w", **out_meta) as dst:
        dst.write(speed_grid.astype(np.float32), 1)
    with rasterio.open(WD_OUT, "w", **out_meta) as dst:
        dst.write(dir_grid.astype(np.float32), 1)

    print(f"  Fallback ws.tif: range [{speed_grid[speed_grid != -9999].min():.1f}, {speed_grid[speed_grid != -9999].max():.1f}] mph")
    return "terrain_fallback"


def main():
    print("=== Step 4b: WindNinja Wind Field Generation ===")

    if not DEM_TIF.exists():
        sys.exit(f"ERROR: DEM not found at {DEM_TIF} — run pipeline 03 first")

    weather = load_weather()
    speed_mph = weather["wind_speed_mph"]
    direction_deg = weather["wind_direction_deg"]
    print(f"Base wind: {speed_mph} mph @ {direction_deg}°")

    # Check WindNinja is available
    wn_path = shutil.which("WindNinja_cli")
    if not wn_path:
        print("WARNING: WindNinja_cli not found in PATH — using fallback")
        method = terrain_fallback(speed_mph, direction_deg)
    else:
        print(f"  WindNinja_cli found: {wn_path}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                run_windninja(str(DEM_TIF), speed_mph, direction_deg, tmp_dir)
                vel_tif, ang_tif = find_windninja_outputs(tmp_dir)

                with rasterio.open(DEM_TIF) as ref:
                    ref_meta = ref.meta.copy()

                save_wind_raster(vel_tif, WS_OUT, ref_meta)
                save_wind_raster(ang_tif, WD_OUT, ref_meta)
                method = "windninja_domain_average"
                print("  WindNinja completed successfully.")

            except Exception as e:
                print(f"WARNING: WindNinja failed ({e}) — using terrain fallback")
                method = terrain_fallback(speed_mph, direction_deg)

    meta = {
        "method": method,
        "input_speed_mph": speed_mph,
        "input_direction_deg": direction_deg,
        "outputs": ["ws.tif", "wd.tif"],
    }
    with open(WINDNINJA_META, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n=== WindNinja Pipeline Complete (method: {method}) ===")


if __name__ == "__main__":
    main()
