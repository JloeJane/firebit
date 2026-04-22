"""
Fuel Pipeline — fetches LANDFIRE fuel and canopy layers for the AOI
via the LANDFIRE Product Service v2 REST API (one job per layer).

Outputs (all EPSG:5070, 30m, aligned to AOI grid):
  fuel/fbfm40.tif  — Scott & Burgan 40 fuel model codes (int16)
  fuel/cc.tif      — canopy cover, percent (int16)
  fuel/ch.tif      — canopy height, 10×meters (int16)
  fuel/cbh.tif     — canopy base height, 10×meters (int16)
  fuel/cbd.tif     — canopy bulk density, 100×kg/m³ (int16)
"""

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

META_JSON = "/data/input/aoi_metadata.json"
FUEL_DIR  = "/data/fuel"
CACHE_DIR = "/data/fuel/cache"
FUEL_META = os.path.join(FUEL_DIR, "fuel_metadata.json")

LFPS_SUBMIT = "https://lfps.usgs.gov/api/job/submit"
LFPS_STATUS = "https://lfps.usgs.gov/api/job/status"
LFPS_EMAIL  = os.environ.get("LANDFIRE_EMAIL", "pipeline@noreply.invalid")

# One LFPS job per layer (API does not support multi-layer requests)
LAYERS = {
    "LF2022_FBFM40": "fbfm40.tif",
    "LF2022_CC":     "cc.tif",
    "LF2022_CH":     "ch.tif",
    "LF2022_CBH":    "cbh.tif",
    "LF2022_CBD":    "cbd.tif",
}


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


def reproject_layer(raw_tif, transform, crs, rows, cols):
    with rasterio.open(raw_tif) as src:
        src_crs = src.crs or CRS.from_epsg(5070)
        print(f"    Source CRS: {src_crs}  size: {src.width}×{src.height}")
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


def save_layer(data, out_path, transform, crs):
    profile = {
        "driver":    "GTiff",
        "dtype":     "int16",
        "width":     data.shape[1],
        "height":    data.shape[0],
        "count":     1,
        "crs":       crs,
        "transform": transform,
        "nodata":    -9999,
        "compress":  "lzw",
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)


def lfps_submit(layer_code, bbox_str):
    resp = requests.get(
        LFPS_SUBMIT,
        params={"Layer_List": layer_code, "Area_of_Interest": bbox_str, "Email": LFPS_EMAIL},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if "jobId" not in body:
        raise RuntimeError(f"LFPS submit ({layer_code}): no jobId: {body}")
    return body["jobId"]


def lfps_poll(job_id, layer_code, max_wait=900, interval=15):
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
        print(f"  [{layer_code}] status: {status}  ({elapsed}s)")
        if "Succeeded" in status:
            url = body.get("outputFile")
            if not url:
                raise RuntimeError(f"Job succeeded but outputFile missing: {body}")
            return url
        if "Failed" in status:
            raise RuntimeError(f"LFPS job failed ({layer_code}): {body.get('messages', [])}")
        time.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"LFPS job timed out after {max_wait}s ({layer_code})")


def lfps_download(url, cache_zip):
    resp = requests.get(url, timeout=600, stream=True)
    resp.raise_for_status()
    with open(cache_zip, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
    print(f"    Cached: {cache_zip}  ({os.path.getsize(cache_zip) / 1024:.0f} KB)")


def find_layer_tif(extract_dir):
    """Return the first .tif found in extract_dir (one layer per zip)."""
    tifs = list(Path(extract_dir).rglob("*.tif"))
    if not tifs:
        raise FileNotFoundError(f"No .tif in {extract_dir}: {list(Path(extract_dir).rglob('*'))}")
    return str(tifs[0])


def fetch_layer(layer_code, bbox_str, bbox_hash):
    """Download one LANDFIRE layer, using cache if available. Returns path to raw .tif."""
    cache_zip = os.path.join(CACHE_DIR, f"landfire_{layer_code.lower()}_{bbox_hash}.zip")
    extract_dir = os.path.join(CACHE_DIR, f"extracted_{layer_code.lower()}_{bbox_hash}")

    if os.path.exists(cache_zip):
        print(f"  [{layer_code}] Using cache: {cache_zip}")
    else:
        print(f"  [{layer_code}] Submitting LFPS job...")
        job_id = lfps_submit(layer_code, bbox_str)
        print(f"  [{layer_code}] Job ID: {job_id}")
        url = lfps_poll(job_id, layer_code)
        print(f"  [{layer_code}] Downloading...")
        lfps_download(url, cache_zip)

    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(cache_zip) as zf:
        zf.extractall(extract_dir)

    return find_layer_tif(extract_dir)


def main():
    print("=== Step 2: Fuel Pipeline ===")
    os.makedirs(FUEL_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    aoi = load_aoi()
    rows, cols = aoi["grid_rows"], aoi["grid_cols"]
    transform, crs = dst_transform_and_crs(aoi)

    b = aoi["bbox_4326"]
    w, s, e, n = b["west"], b["south"], b["east"], b["north"]
    bbox_str  = f"{w} {s} {e} {n}"
    bbox_hash = hashlib.md5(f"{round(w,4)} {round(s,4)} {round(e,4)} {round(n,4)}".encode()).hexdigest()[:8]

    print(f"AOI: {bbox_str}")
    print(f"Grid: {rows}×{cols} at 30m  |  Fetching {len(LAYERS)} LANDFIRE layers\n")

    layer_stats = {}
    for layer_code, out_name in LAYERS.items():
        print(f"\n--- {layer_code} → {out_name} ---")
        raw_tif = fetch_layer(layer_code, bbox_str, bbox_hash)
        print(f"    Raw TIF: {Path(raw_tif).name}")
        data = reproject_layer(raw_tif, transform, crs, rows, cols)
        out_path = os.path.join(FUEL_DIR, out_name)
        save_layer(data, out_path, transform, crs)
        valid = data[data != -9999]
        vmin = int(valid.min()) if len(valid) else None
        vmax = int(valid.max()) if len(valid) else None
        nodata = int((data == -9999).sum())
        print(f"    Saved {out_name}  range: [{vmin}, {vmax}]  nodata: {nodata} cells")
        layer_stats[out_name] = {"min": vmin, "max": vmax, "nodata_cells": nodata}

    metadata = {
        "layers": layer_stats,
        "grid_rows": rows,
        "grid_cols": cols,
        "crs": "EPSG:5070",
        "resolution_m": 30,
        "source": "LANDFIRE 2022 via LFPS v2 API",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(FUEL_META, "w") as f:
        json.dump(metadata, f, indent=2)

    print("\n=== Fuel Pipeline Complete ===")
    for name, stats in layer_stats.items():
        print(f"  {name}: [{stats['min']}, {stats['max']}]")


if __name__ == "__main__":
    main()
