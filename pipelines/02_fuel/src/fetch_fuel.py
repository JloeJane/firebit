"""
Fuel Pipeline — fetches LANDFIRE FBFM40 fuel model data for the AOI
via the LANDFIRE Product Service v2 REST API.
"""

import csv
import hashlib
import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
META_JSON  = "/data/input/aoi_metadata.json"
FUEL_DIR   = "/data/fuel"
CACHE_DIR  = "/data/fuel/cache"
FUEL_TIF   = os.path.join(FUEL_DIR, "fuel_clipped.tif")
FUEL_CSV   = os.path.join(FUEL_DIR, "fuel_model_grid.csv")
FUEL_META  = os.path.join(FUEL_DIR, "fuel_metadata.json")

# LANDFIRE Product Service v2
LFPS_SUBMIT = "https://lfps.usgs.gov/api/job/submit"
LFPS_STATUS = "https://lfps.usgs.gov/api/job/status"
LFPS_LAYER  = "LF2022_FBFM40"
LFPS_EMAIL  = os.environ.get("LANDFIRE_EMAIL", "pipeline@noreply.invalid")

SOURCE_LABEL = "LANDFIRE FBFM40 2022 (LF2022) via LFPS v2 API"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_aoi():
    with open(META_JSON) as f:
        return json.load(f)


def dst_transform_and_crs(aoi):
    b = aoi["bbox_5070"]
    transform = from_bounds(
        b["xmin"], b["ymin"], b["xmax"], b["ymax"],
        aoi["grid_cols"], aoi["grid_rows"],
    )
    return transform, CRS.from_epsg(5070)


def save_fuel_tif(data, transform, crs, rows, cols, source_label):
    """Write fuel_clipped.tif with exact grid alignment."""
    profile = {
        "driver":    "GTiff",
        "dtype":     "int16",
        "width":     cols,
        "height":    rows,
        "count":     1,
        "crs":       crs,
        "transform": transform,
        "nodata":    -9999,
        "compress":  "lzw",
    }
    os.makedirs(FUEL_DIR, exist_ok=True)
    with rasterio.open(FUEL_TIF, "w", **profile) as dst:
        dst.write(data.astype(np.int16), 1)
    print(f"  Saved fuel_clipped.tif  ({rows}×{cols}, {source_label})")


def write_csv_and_metadata(data, rows, cols, source_label):
    """Write fuel_model_grid.csv and fuel_metadata.json."""
    print("  Writing fuel_model_grid.csv...")
    with open(FUEL_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row", "col", "fuel_code"])
        for r in range(rows):
            for c in range(cols):
                code = int(data[r, c])
                if code > 0:
                    writer.writerow([r, c, code])

    valid = data[data > 0]
    total = data.size
    nodata_pct = round((data <= 0).sum() / total * 100, 2)
    unique_codes = sorted(int(x) for x in np.unique(valid))
    distribution = {
        str(code): round(float((valid == code).sum() / total * 100), 3)
        for code in unique_codes
    }

    metadata = {
        "unique_fuel_codes":  unique_codes,
        "fuel_distribution":  distribution,
        "nodata_percentage":  nodata_pct,
        "rows":               rows,
        "cols":               cols,
        "source":             source_label,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
    }
    with open(FUEL_META, "w") as f:
        json.dump(metadata, f, indent=2)

    print()
    print("=== Fuel Model Summary ===")
    print(f"  Source:       {source_label}")
    print(f"  Grid:         {rows} rows × {cols} cols")
    print(f"  Nodata:       {nodata_pct:.1f}%")
    print(f"  Fuel codes ({len(unique_codes)}):  {unique_codes}")
    for code, pct in distribution.items():
        print(f"    code {code:>4}: {pct:.1f}%")
    print("==========================")


def reproject_fuel_raw(raw_tif, transform, crs, rows, cols):
    """Reproject raw fuel raster to exact AOI grid using nearest-neighbor."""
    with rasterio.open(raw_tif) as src:
        src_crs = src.crs or CRS.from_epsg(5070)
        print(f"  Raw fuel CRS: {src_crs}  size: {src.width}×{src.height}")

        dst_array = np.full((rows, cols), -9999, dtype=np.int16)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src_crs,
            dst_transform=transform,
            dst_crs=crs,
            resampling=Resampling.nearest,
            src_nodata=src.nodata,
            dst_nodata=-9999,
        )
    return dst_array


# ---------------------------------------------------------------------------
# LFPS v2 API
# ---------------------------------------------------------------------------

def lfps_submit(bbox_str):
    """Submit LFPS v2 job. Returns jobId string."""
    params = {
        "Layer_List":        LFPS_LAYER,
        "Area_of_Interest":  bbox_str,
        "Email":             LFPS_EMAIL,
    }
    print(f"  Submitting LFPS v2 job (layer={LFPS_LAYER})...")
    resp = requests.get(LFPS_SUBMIT, params=params, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if "jobId" not in body:
        raise RuntimeError(f"LFPS submit: no jobId in response: {body}")
    job_id = body["jobId"]
    print(f"  Job ID: {job_id}")
    return job_id


def lfps_poll(job_id, max_wait=600, interval=10):
    """Poll until job succeeds. Returns outputFile URL."""
    elapsed = 0
    while elapsed < max_wait:
        resp = requests.get(
            LFPS_STATUS,
            params={"JobId": job_id},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        status = body.get("status", "")
        print(f"  LFPS status: {status}  ({elapsed}s elapsed)")

        if "Succeeded" in status:
            url = body.get("outputFile")
            if not url:
                raise RuntimeError(f"Job succeeded but outputFile is missing: {body}")
            return url

        if "Failed" in status:
            messages = body.get("messages", [])
            raise RuntimeError(f"LFPS job failed: {messages}")

        time.sleep(interval)
        elapsed += interval

    raise TimeoutError(f"LFPS job did not complete within {max_wait}s")


def lfps_download(download_url, cache_zip):
    """Download the output zip to cache_zip."""
    print(f"  Downloading: {download_url}")
    resp = requests.get(download_url, timeout=300, stream=True)
    resp.raise_for_status()
    with open(cache_zip, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
    print(f"  Cached: {cache_zip}  ({os.path.getsize(cache_zip) / 1024:.0f} KB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Step 2: Fuel Pipeline ===")
    os.makedirs(FUEL_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    aoi = load_aoi()
    bbox_4326 = aoi["bbox_4326"]
    rows      = aoi["grid_rows"]
    cols      = aoi["grid_cols"]
    transform, crs = dst_transform_and_crs(aoi)

    w = bbox_4326["west"]
    s = bbox_4326["south"]
    e = bbox_4326["east"]
    n = bbox_4326["north"]

    bbox_str  = f"{w} {s} {e} {n}"
    rounded   = f"{round(w,4)} {round(s,4)} {round(e,4)} {round(n,4)}"
    bbox_hash = hashlib.md5(rounded.encode()).hexdigest()[:8]
    cache_zip = os.path.join(CACHE_DIR, f"landfire_lf2022fbfm40_{bbox_hash}.zip")

    # --- Check cache ---
    if os.path.exists(cache_zip):
        print(f"Using cached LANDFIRE tile: {cache_zip}")
    else:
        print("Downloading LANDFIRE FBFM40 via LFPS v2 API...")
        job_id = lfps_submit(bbox_str)
        download_url = lfps_poll(job_id)
        lfps_download(download_url, cache_zip)

    # --- Unzip and locate GeoTIFF ---
    extract_dir = os.path.join(CACHE_DIR, f"extracted_{bbox_hash}")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(cache_zip) as zf:
        zf.extractall(extract_dir)

    tif_files = list(Path(extract_dir).rglob("*.tif"))
    assert tif_files, f"No .tif found in zip: {list(Path(extract_dir).rglob('*'))}"
    raw_tif = str(tif_files[0])
    print(f"  Raw GeoTIFF: {raw_tif}")

    # --- Reproject to AOI grid ---
    print("  Reprojecting to AOI grid (EPSG:5070)...")
    fuel_data = reproject_fuel_raw(raw_tif, transform, crs, rows, cols)

    # --- Save outputs ---
    print("\nSaving outputs...")
    save_fuel_tif(fuel_data, transform, crs, rows, cols, SOURCE_LABEL)
    write_csv_and_metadata(fuel_data, rows, cols, SOURCE_LABEL)


if __name__ == "__main__":
    main()
