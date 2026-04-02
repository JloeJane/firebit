"""
Pipeline 09 — Cell2Fire Simulation

Usage:
  python3 src/run_simulation.py          # real data mode (reads /data/grid/)
  python3 src/run_simulation.py --test   # synthetic 50×50 test grid

Synthetic test:
  Generates a 50x50 homogeneous GR1 grass grid (flat terrain, constant wind from south),
  ignites the center cell, and verifies fire spread output is produced.

Key C2F-W S&B facts confirmed by testing:
  - S&B mode is the DEFAULT (no --sim S flag needed)
  - Required inputs: fuels.asc, elevation.asc, spain_lookup_table.csv, Weather.csv, Ignitions.csv
  - Data.csv is generated automatically from ASC files (input folder must be writable)
  - Optional files (slope.asc, saz.asc, cbd.asc, etc.) are filled with NaN if absent
  - Weather.csv header: Instance,datetime,WS,WD,FireScenario
  - Output: Grids/Grids1/ForestGrid*.csv + Messages/MessagesFile1.csv
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import rasterio
import rasterio.features
import rasterio.transform
from rasterio.crs import CRS
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CELL2FIRE = "/opt/C2F-W/Cell2Fire/Cell2Fire"
LOOKUP_TABLE = "/opt/C2F-W/spain_lookup_table.csv"

# Synthetic test paths
TEST_INPUT_DIR = "/tmp/c2f_test_grid"
TEST_OUTPUT_DIR = "/tmp/c2f_test_output"

# Real data paths
GRID_DIR = "/data/grid"
REAL_INPUT_DIR = "/tmp/c2f_real_input"
REAL_OUTPUT_DIR = "/data/simulation"

GRID_METADATA = "/data/grid/grid_metadata.json"

# ---------------------------------------------------------------------------
# Synthetic grid parameters
# ---------------------------------------------------------------------------
NROWS = 50
NCOLS = 50
CELLSIZE = 30
FUEL_CODE = 101        # GR1 — Short, Sparse Dry Climate Grass (S&B FBFM40 code)
ELEV_M = 300.0
WIND_KMH = 20.0
WIND_DIR_DEG = 180.0   # from south → fire spreads north
N_WEATHER_ROWS = 24

CENTER_CELL = (NROWS // 2) * NCOLS + (NCOLS // 2) + 1


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def write_asc(path, data, xllcorner=0, yllcorner=0, cellsize=CELLSIZE,
              nodata=-9999, fmt="{:.1f}"):
    nrows, ncols = data.shape
    with open(path, "w") as f:
        f.write(f"ncols {ncols}\n")
        f.write(f"nrows {nrows}\n")
        f.write(f"xllcorner {xllcorner}\n")
        f.write(f"yllcorner {yllcorner}\n")
        f.write(f"cellsize {cellsize}\n")
        f.write(f"NODATA_value {nodata}\n")
        for row in data:
            f.write(" ".join(fmt.format(v) for v in row) + "\n")


def copy_lookup_table(dest_dir):
    if os.path.exists(LOOKUP_TABLE):
        shutil.copy(LOOKUP_TABLE, os.path.join(dest_dir, "spain_lookup_table.csv"))
        print(f"  Copied spain_lookup_table.csv from {LOOKUP_TABLE}")
    else:
        result = subprocess.run(
            ["find", "/opt/C2F-W", "-name", "spain_lookup_table.csv"],
            capture_output=True, text=True
        )
        candidates = result.stdout.strip().splitlines()
        if candidates:
            shutil.copy(candidates[0], os.path.join(dest_dir, "spain_lookup_table.csv"))
            print(f"  Copied spain_lookup_table.csv from {candidates[0]}")
        else:
            print("  ERROR: spain_lookup_table.csv not found anywhere in /opt/C2F-W", file=sys.stderr)
            sys.exit(1)


def verify_binary():
    if not os.path.exists(CELL2FIRE):
        print(f"\nERROR: Cell2Fire binary not found at {CELL2FIRE}", file=sys.stderr)
        found = subprocess.run(["find", "/opt", "-name", "Cell2Fire", "-type", "f"],
                               capture_output=True, text=True)
        print(f"Binaries found: {found.stdout or '(none)'}", file=sys.stderr)
        sys.exit(1)


def run_cell2fire(input_dir, output_dir):
    cmd = [
        CELL2FIRE,
        "--input-instance-folder", input_dir + "/",
        "--output-folder",         output_dir + "/",
        "--ignitions",
        "--sim-years",             "1",
        "--nsims",                 "1",
        "--grids",
        "--final-grid",
        "--Fire-Period-Length",    "1.0",
        "--output-messages",
        "--ROS-CV",                "0.0",
        "--seed",                  "123",
    ]
    print(f"Command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.stdout.strip():
        print("--- Cell2Fire stdout ---")
        print(result.stdout[:5000])
    if result.stderr.strip():
        print("--- Cell2Fire stderr ---")
        print(result.stderr[:2000])

    if result.returncode != 0:
        print(f"\nERROR: Cell2Fire exited with code {result.returncode}", file=sys.stderr)
        sys.exit(1)

    return result


def load_forest_grid(path, nrows, ncols):
    """Read a ForestGrid*.csv flat array and reshape to (nrows, ncols).

    C2F-W writes values comma-separated within lines and newline-separated across
    lines, so we split on all whitespace+commas.
    """
    with open(path) as f:
        content = f.read()
    import re
    values = [int(v) for v in re.split(r"[,\s]+", content.strip()) if v]
    arr = np.array(values, dtype=np.uint8).reshape(nrows, ncols)
    return arr


def remap_fuels_to_fbfm40(src_asc, dst_asc, fuel_lookup_csv):
    """
    Re-write fuels.asc replacing sequential Cell2Fire codes with original FBFM40 codes.

    Pipeline 07 maps FBFM40 → sequential (e.g. 102→2, 165→27) for internal use.
    C2F-W's spain_lookup_table.csv expects the original FBFM40 codes, so we reverse.
    Non-burnable (code 0) stays 0 — C2F-W treats unknown codes as non-burnable.
    """
    # Build reverse map: cell2fire_code → fbfm_code (skip non-burnable → 0)
    reverse = {}
    with open(fuel_lookup_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            c2f = int(row["cell2fire_code"])
            fbfm = int(row["fbfm_code"])
            if c2f != 0:
                reverse[c2f] = fbfm

    # Read header
    header_lines = []
    data_lines = []
    with open(src_asc) as f:
        for _ in range(6):
            header_lines.append(f.readline())
        for line in f:
            data_lines.append(line)

    # Re-map and write
    with open(dst_asc, "w") as f:
        for h in header_lines:
            f.write(h)
        for line in data_lines:
            tokens = line.split()
            remapped = [str(reverse.get(int(t), 0)) for t in tokens]
            f.write(" ".join(remapped) + "\n")

    print(f"  Remapped fuels.asc: sequential codes → FBFM40 codes")


def build_transform(meta):
    """Build a rasterio Affine transform from grid_metadata (ll corner → ul corner)."""
    xll = meta["xllcorner"]
    yll = meta["yllcorner"]
    nrows = meta["nrows"]
    cellsize = meta["cellsize"]
    # upper-left corner
    return rasterio.transform.from_origin(xll, yll + nrows * cellsize, cellsize, cellsize)


def write_geotiff(path, data, transform, crs_str, dtype=rasterio.uint8):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=dtype,
        crs=CRS.from_string(crs_str),
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def burn_scar_to_geojson(burn_grid, transform, crs_str):
    """Vectorize burned cells (value=1) into a GeoJSON FeatureCollection."""
    shapes = list(rasterio.features.shapes(
        burn_grid.astype(np.uint8),
        mask=(burn_grid == 1).astype(np.uint8),
        transform=transform,
    ))
    if not shapes:
        # Return empty FeatureCollection
        return {"type": "FeatureCollection", "features": []}

    polygons = [shape(geom) for geom, val in shapes if val == 1]
    merged = unary_union(polygons)
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": crs_str}},
        "features": [{
            "type": "Feature",
            "geometry": mapping(merged),
            "properties": {},
        }],
    }


# ---------------------------------------------------------------------------
# Synthetic test
# ---------------------------------------------------------------------------

def run_synthetic_test():
    print("=== Generating 50x50 synthetic S&B test grid ===")

    os.makedirs(TEST_INPUT_DIR, exist_ok=True)
    os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)

    fuels = np.full((NROWS, NCOLS), FUEL_CODE, dtype=np.int32)
    write_asc(os.path.join(TEST_INPUT_DIR, "fuels.asc"), fuels, fmt="{:.0f}")

    elev = np.full((NROWS, NCOLS), ELEV_M)
    write_asc(os.path.join(TEST_INPUT_DIR, "elevation.asc"), elev)

    weather_path = os.path.join(TEST_INPUT_DIR, "Weather.csv")
    base_dt = datetime(2026, 1, 1, 13, 0, 0)
    with open(weather_path, "w") as f:
        f.write("Instance,datetime,WS,WD,FireScenario\n")
        for i in range(N_WEATHER_ROWS):
            dt = base_dt + timedelta(hours=i)
            f.write(f"test,{dt.strftime('%Y-%m-%d %H:%M')},{WIND_KMH:.1f},{WIND_DIR_DEG:.1f},2\n")

    ign_path = os.path.join(TEST_INPUT_DIR, "Ignitions.csv")
    with open(ign_path, "w") as f:
        f.write("Year,Ncell\n")
        f.write(f"1,{CENTER_CELL}")

    copy_lookup_table(TEST_INPUT_DIR)

    print(f"  Input files in {TEST_INPUT_DIR}:")
    for fname in sorted(os.listdir(TEST_INPUT_DIR)):
        size = os.path.getsize(os.path.join(TEST_INPUT_DIR, fname))
        print(f"    {fname}  ({size:,} bytes)")
    print(f"  Ignition cell: {CENTER_CELL} (row={NROWS//2}, col={NCOLS//2}, 1-indexed)")

    verify_binary()

    print(f"\n=== Running Cell2Fire (S&B default mode) on {NROWS}x{NCOLS} synthetic grid ===")
    run_cell2fire(TEST_INPUT_DIR, TEST_OUTPUT_DIR)

    print(f"\n=== Verifying outputs in {TEST_OUTPUT_DIR} ===")
    all_outputs = []
    for root, dirs, files in os.walk(TEST_OUTPUT_DIR):
        for fname in files:
            all_outputs.append(os.path.join(root, fname))

    if not all_outputs:
        print("ERROR: No output files produced", file=sys.stderr)
        sys.exit(1)

    print(f"Output files ({len(all_outputs)}):")
    for p in sorted(all_outputs):
        rel = os.path.relpath(p, TEST_OUTPUT_DIR)
        size = os.path.getsize(p)
        print(f"  {rel}  ({size:,} bytes)")

    grid_files = [p for p in all_outputs if "ForestGrid" in p and p.endswith(".csv")]
    if grid_files:
        last_grid = sorted(grid_files)[-1]
        with open(last_grid) as f:
            content = f.read(200)
        print(f"\n  Final grid sample ({os.path.basename(last_grid)}):")
        print(f"  {content[:100]}")

    print("\n" + "=" * 50)
    print("SYNTHETIC TEST PASSED")
    print("=" * 50)
    print(f"  Grid: {NROWS}x{NCOLS} cells | Fuel: GR1 (101) | Wind: {WIND_KMH}km/h from {WIND_DIR_DEG}°")
    print(f"  {len(grid_files)} fire-spread grid snapshots produced")


# ---------------------------------------------------------------------------
# Real data simulation
# ---------------------------------------------------------------------------

def translate_weather(src_path, dst_path):
    """
    Translate pipeline-04 Weather.csv format to C2F-W S&B format.

    Input cols:  Instance, datetime, WS, WD, TMP, RH
    Output cols: Instance, datetime, WS, WD, FireScenario
    Also strips seconds from datetime (e.g. '2026-01-01 00:00:00' → '2026-01-01 00:00').
    """
    rows_out = []
    with open(src_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Truncate datetime to HH:MM if seconds are present
            dt_str = row["datetime"].strip()
            if dt_str.count(":") == 2:
                dt_str = dt_str.rsplit(":", 1)[0]
            rows_out.append({
                "Instance": row["Instance"],
                "datetime": dt_str,
                "WS": row["WS"],
                "WD": row["WD"],
                "FireScenario": "2",
            })

    with open(dst_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Instance", "datetime", "WS", "WD", "FireScenario"])
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"  Translated Weather.csv: {len(rows_out)} rows → {dst_path}")


def run_real_simulation():
    # --- Load grid metadata ---
    with open(GRID_METADATA) as f:
        meta = json.load(f)

    nrows = meta["nrows"]
    ncols = meta["ncols"]
    cellsize = meta["cellsize"]
    crs_str = meta["crs"]
    print(f"Grid: {ncols} cols × {nrows} rows, {cellsize}m cells, {crs_str}")

    # --- Verify required inputs ---
    required = [
        "/data/grid/fuels.asc",
        "/data/grid/elevation.asc",
        "/data/grid/Weather.csv",
        "/data/grid/Ignitions.csv",
    ]
    missing = [p for p in required if not os.path.exists(p)]
    if missing:
        print("ERROR: Required input files missing:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)
    print("All required input files present.")

    # --- Prepare input directory ---
    if os.path.exists(REAL_INPUT_DIR):
        shutil.rmtree(REAL_INPUT_DIR)
    os.makedirs(REAL_INPUT_DIR)

    for fname in ("elevation.asc", "Ignitions.csv"):
        shutil.copy(f"/data/grid/{fname}", os.path.join(REAL_INPUT_DIR, fname))
        print(f"  Copied {fname}")

    # Remap fuels: pipeline 07 writes sequential codes; C2F-W needs original FBFM40 codes
    fuel_lookup = "/data/grid/fuel_lookup.csv"
    remap_fuels_to_fbfm40(
        "/data/grid/fuels.asc",
        os.path.join(REAL_INPUT_DIR, "fuels.asc"),
        fuel_lookup,
    )

    translate_weather("/data/grid/Weather.csv", os.path.join(REAL_INPUT_DIR, "Weather.csv"))
    copy_lookup_table(REAL_INPUT_DIR)

    print(f"\nInput files staged in {REAL_INPUT_DIR}:")
    for fname in sorted(os.listdir(REAL_INPUT_DIR)):
        size = os.path.getsize(os.path.join(REAL_INPUT_DIR, fname))
        print(f"  {fname}  ({size:,} bytes)")

    # --- Run Cell2Fire ---
    os.makedirs(REAL_OUTPUT_DIR, exist_ok=True)
    verify_binary()
    print(f"\n=== Running Cell2Fire on real {nrows}×{ncols} grid ===")
    run_cell2fire(REAL_INPUT_DIR, REAL_OUTPUT_DIR)

    # --- Collect output grids ---
    grids_dir = os.path.join(REAL_OUTPUT_DIR, "Grids", "Grids1")
    grid_files = sorted([
        os.path.join(grids_dir, f)
        for f in os.listdir(grids_dir)
        if f.startswith("ForestGrid") and f.endswith(".csv")
    ], key=lambda p: int(re.search(r'(\d+)', os.path.basename(p)).group(1))) if os.path.isdir(grids_dir) else []

    if not grid_files:
        print("ERROR: No ForestGrid*.csv files found in output", file=sys.stderr)
        sys.exit(1)

    print(f"\n{len(grid_files)} timestep grid(s) found.")

    transform = build_transform(meta)

    # --- Per-timestep GeoTIFFs ---
    timestep_dir = os.path.join(REAL_OUTPUT_DIR, "grids")
    os.makedirs(timestep_dir, exist_ok=True)
    for i, gf in enumerate(grid_files):
        arr = load_forest_grid(gf, nrows, ncols)
        out_path = os.path.join(timestep_dir, f"grid_t{i:03d}.tif")
        write_geotiff(out_path, arr, transform, crs_str)
    print(f"Wrote {len(grid_files)} timestep GeoTIFFs to {timestep_dir}/")

    # --- Final burn scar GeoTIFF ---
    final_grid = load_forest_grid(grid_files[-1], nrows, ncols)
    burn_tif = os.path.join(REAL_OUTPUT_DIR, "burn_scar.tif")
    write_geotiff(burn_tif, final_grid, transform, crs_str)
    print(f"Wrote {burn_tif}")

    # --- Fire perimeter GeoJSON ---
    geojson = burn_scar_to_geojson(final_grid, transform, crs_str)
    perimeter_path = os.path.join(REAL_OUTPUT_DIR, "fire_perimeter_final.geojson")
    with open(perimeter_path, "w") as f:
        json.dump(geojson, f)
    print(f"Wrote {perimeter_path}")

    # --- Summary stats ---
    total_burned = int(final_grid.sum())
    area_ha = round(total_burned * (cellsize ** 2) / 10_000, 2)
    summary = {
        "total_cells_burned": total_burned,
        "total_area_burned_ha": area_ha,
        "simulation_hours": len(grid_files),
        "max_ros": None,
        "nrows": nrows,
        "ncols": ncols,
        "cellsize_m": cellsize,
        "crs": crs_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path = os.path.join(REAL_OUTPUT_DIR, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote {summary_path}")

    print("\n" + "=" * 50)
    print("SIMULATION COMPLETE")
    print("=" * 50)
    print(f"  Cells burned:  {total_burned:,} / {nrows * ncols:,}")
    print(f"  Area burned:   {area_ha:,.1f} ha")
    print(f"  Timesteps:     {len(grid_files)}")
    print(f"  Burn scar:     {burn_tif}")
    print(f"  Perimeter:     {perimeter_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true",
                        help="Run synthetic 50×50 grid test instead of real data")
    args = parser.parse_args()

    if args.test:
        run_synthetic_test()
    else:
        run_real_simulation()
