#!/usr/bin/env python3
"""ELMFIRE fire spread simulation pipeline."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
import geopandas as gpd

ELMFIRE_VER = os.environ.get("ELMFIRE_VER", "2025.0212")
ELMFIRE_BASE = os.environ.get("ELMFIRE_BASE_DIR", "/elmfire/elmfire")
TUTORIAL_DIR = Path(ELMFIRE_BASE) / "tutorials" / "01-constant-wind"

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
GRID_DIR = Path(os.environ.get("GRID_DIR", "/data/grid"))
SIM_DIR = Path(os.environ.get("SIM_DIR", "/data/simulation"))

REQUIRED_INPUTS = [
    "asp.tif", "cbd.tif", "cbh.tif", "cc.tif", "ch.tif",
    "dem.tif", "fbfm40.tif", "slp.tif", "adj.tif", "phi.tif",
    "ws.tif", "wd.tif", "m1.tif", "m10.tif", "m100.tif",
    "elmfire.data",
]


def run_tutorial_test():
    """Run ELMFIRE tutorial 01 to verify the binary works."""
    print("=== Running ELMFIRE Tutorial 01 (constant wind) ===")

    run_dir = Path("/tmp/elmfire_tutorial_01")
    if run_dir.exists():
        shutil.rmtree(run_dir)
    shutil.copytree(TUTORIAL_DIR, run_dir)

    for d in ["inputs", "outputs", "scratch"]:
        (run_dir / d).mkdir(exist_ok=True)

    result = subprocess.run(
        ["bash", "01-run.sh"],
        cwd=run_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print("STDOUT:", result.stdout[-3000:])
        print("STDERR:", result.stderr[-3000:])
        print("FAIL: Tutorial 01 returned non-zero exit code")
        return False

    tif_outputs = list((run_dir / "outputs").glob("*.tif"))
    if not tif_outputs:
        print("FAIL: Tutorial 01 produced no .tif outputs")
        print("Outputs dir contents:", list((run_dir / "outputs").iterdir()))
        return False

    print(f"Tutorial outputs: {[f.name for f in tif_outputs]}")
    print("ELMFIRE TUTORIAL 01 PASSED")
    return True


def verify_inputs():
    """Check all required ELMFIRE input files exist."""
    missing = [f for f in REQUIRED_INPUTS if not (GRID_DIR / f).exists()]
    if missing:
        print(f"ERROR: Missing input files in {GRID_DIR}: {missing}")
        sys.exit(1)
    print(f"All {len(REQUIRED_INPUTS)} required inputs present.")


def run_simulation():
    """Run ELMFIRE with real pipeline inputs and save outputs."""
    verify_inputs()

    run_dir = Path("/tmp/elmfire_run")
    if run_dir.exists():
        shutil.rmtree(run_dir)

    inputs_dir = run_dir / "inputs"
    outputs_dir = run_dir / "outputs"
    scratch_dir = run_dir / "scratch"
    for d in [inputs_dir, outputs_dir, scratch_dir]:
        d.mkdir(parents=True)

    for f in REQUIRED_INPUTS:
        shutil.copy2(GRID_DIR / f, inputs_dir / f)

    # elmfire.data expects paths relative to run dir
    config_path = inputs_dir / "elmfire.data"
    config_text = config_path.read_text()
    config_text = config_text.replace("SCRATCH.*=.*", "")
    # Ensure scratch and outputs dirs are set correctly
    for old, new in [
        ("'./scratch'", f"'{scratch_dir}'"),
        ("'./outputs'", f"'{outputs_dir}'"),
        ("'./inputs'", f"'{inputs_dir}'"),
    ]:
        config_text = config_text.replace(old, new)
    config_path.write_text(config_text)

    print(f"=== Running ELMFIRE {ELMFIRE_VER} ===")
    binary = f"elmfire_{ELMFIRE_VER}"
    result = subprocess.run(
        [binary, str(config_path)],
        cwd=str(run_dir),
        capture_output=True,
        text=True,
        timeout=3600,
    )

    log_file = outputs_dir / "elmfire.out"
    if log_file.exists():
        print("--- elmfire.out (last 50 lines) ---")
        lines = log_file.read_text().splitlines()
        print("\n".join(lines[-50:]))

    if result.returncode != 0:
        print("STDOUT:", result.stdout[-3000:])
        print("STDERR:", result.stderr[-3000:])
        sys.exit(f"ELMFIRE exited with code {result.returncode}")

    return outputs_dir


def convert_outputs(outputs_dir: Path):
    """Convert ELMFIRE binary outputs to GeoTIFFs and standardized formats."""
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    grids_dir = SIM_DIR / "grids"
    grids_dir.mkdir(exist_ok=True)

    # Convert .bil outputs to GeoTIFF using the CRS from dem.tif
    with rasterio.open(GRID_DIR / "dem.tif") as ref:
        crs = ref.crs
        transform = ref.transform

    bil_files = list(outputs_dir.glob("*.bil"))
    print(f"Converting {len(bil_files)} .bil files to GeoTIFF...")
    for bil in bil_files:
        out_tif = grids_dir / (bil.stem + ".tif")
        subprocess.run(
            ["gdal_translate", "-a_srs", crs.to_string(),
             "-co", "COMPRESS=DEFLATE", str(bil), str(out_tif)],
            check=True, capture_output=True,
        )

    toa_files = sorted(grids_dir.glob("time_of_arrival*.tif"))
    if not toa_files:
        sys.exit("ERROR: No time_of_arrival output found — simulation may not have burned anything.")

    toa_path = toa_files[-1]
    shutil.copy2(toa_path, SIM_DIR / "time_of_arrival.tif")

    # Build burn scar from time of arrival (burned = toa > 0)
    with rasterio.open(toa_path) as src:
        toa = src.read(1)
        meta = src.meta.copy()
        nodata = src.nodata or -9999.0

    burned = ((toa > 0) & (toa != nodata)).astype(np.uint8)
    total_burned = int(burned.sum())
    resolution_m = abs(meta["transform"].a)
    area_ha = total_burned * resolution_m ** 2 / 10_000

    burn_meta = meta.copy()
    burn_meta.update(dtype="uint8", nodata=0, count=1)
    burn_path = SIM_DIR / "burn_scar.tif"
    with rasterio.open(burn_path, "w", **burn_meta) as dst:
        dst.write(burned, 1)

    # Vectorize burn scar to GeoJSON perimeter
    with rasterio.open(burn_path) as src:
        data = src.read(1)
        polys = [
            shape(geom) for geom, val in shapes(data, transform=src.transform) if val == 1
        ]

    if polys:
        merged = unary_union(polys)
        gdf = gpd.GeoDataFrame(geometry=[merged], crs=meta["crs"])
        gdf = gdf.to_crs("EPSG:4326")
        gdf.to_file(SIM_DIR / "fire_perimeter_final.geojson", driver="GeoJSON")
        print(f"Fire perimeter saved: {len(polys)} polygons merged.")
    else:
        print("WARNING: No burned polygons — writing empty perimeter.")
        gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_file(
            SIM_DIR / "fire_perimeter_final.geojson", driver="GeoJSON"
        )

    # Copy fire type raster if present (crown fire output)
    fire_type_files = sorted(grids_dir.glob("fire_type*.tif"))
    if fire_type_files:
        shutil.copy2(fire_type_files[-1], SIM_DIR / "fire_type.tif")

    # Build summary
    sim_hours = int(os.environ.get("ELMFIRE_SIMULATION_HOURS", 24))
    summary = {
        "engine": "elmfire",
        "elmfire_version": ELMFIRE_VER,
        "total_cells_burned": total_burned,
        "total_area_burned_ha": round(area_ha, 2),
        "total_area_burned_acres": round(area_ha * 2.471, 2),
        "simulation_hours": sim_hours,
        "crown_fire_enabled": os.environ.get("ELMFIRE_CROWN_FIRE", "1") == "1",
        "spotting_enabled": os.environ.get("ELMFIRE_ENABLE_SPOTTING", "true").lower() == "true",
        "generated_at": datetime.utcnow().isoformat() + "+00:00",
    }

    if fire_type_files:
        with rasterio.open(SIM_DIR / "fire_type.tif") as src:
            ft = src.read(1)
        summary["surface_fire_cells"] = int((ft == 1).sum())
        summary["passive_crown_fire_cells"] = int((ft == 2).sum())
        summary["active_crown_fire_cells"] = int((ft == 3).sum())

    (SIM_DIR / "summary.json").write_text(json.dumps(summary, indent=2))

    print("=== Simulation complete ===")
    print(f"  Area burned:  {area_ha:.1f} ha ({area_ha * 2.471:.1f} acres)")
    print(f"  Cells burned: {total_burned}")
    print(f"  Outputs in:   {SIM_DIR}")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run tutorial verification only")
    args = parser.parse_args()

    if args.test:
        ok = run_tutorial_test()
        sys.exit(0 if ok else 1)

    outputs_dir = run_simulation()
    convert_outputs(outputs_dir)


if __name__ == "__main__":
    main()
