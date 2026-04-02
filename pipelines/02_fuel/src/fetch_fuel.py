"""
Fuel Pipeline — fetches LANDFIRE FBFM40 fuel model data for the AOI.

Approach order:
  A) LANDFIRE Product Service (LFPS) async REST API
  B) Synthetic elevation-based fallback (if A fails or times out)
"""

import csv
import json
import os
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO

import numpy as np
import rasterio
import requests
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
META_JSON  = "/data/input/aoi_metadata.json"
FUEL_DIR   = "/data/fuel"
FUEL_RAW   = os.path.join(FUEL_DIR, "fuel_raw.tif")
FUEL_TIF   = os.path.join(FUEL_DIR, "fuel_clipped.tif")
FUEL_CSV   = os.path.join(FUEL_DIR, "fuel_model_grid.csv")
FUEL_META  = os.path.join(FUEL_DIR, "fuel_metadata.json")
ELEV_TIF   = "/data/topography/elevation.tif"

# LANDFIRE Product Service endpoints
LFPS_SUBMIT = (
    "https://lfps.usgs.gov/arcgis/rest/services"
    "/LandfireProductService/GPServer/LandfireProductService/submitJob"
)
LFPS_BASE = (
    "https://lfps.usgs.gov/arcgis/rest/services"
    "/LandfireProductService/GPServer/LandfireProductService"
)

# Elevation-band → FBFM40 code mapping (Smoky Mountains approximation)
ELEV_FUEL_BANDS = [
    (0,    400,  102),   # GR2  — grass / low-elevation open
    (400,  800,  165),   # TU5  — timber understory
    (800,  1200, 183),   # TL3  — timber litter
    (1200, 9999, 188),   # TL8  — timber litter, higher elevation
]

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
    # CSV
    print("  Writing fuel_model_grid.csv...")
    with open(FUEL_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row", "col", "fuel_code"])
        for r in range(rows):
            for c in range(cols):
                code = int(data[r, c])
                if code > 0:
                    writer.writerow([r, c, code])

    # Metadata
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


# ---------------------------------------------------------------------------
# Approach A: LANDFIRE Product Service (LFPS) async API
# ---------------------------------------------------------------------------

def lfps_submit_job(bbox_4326):
    """Submit LFPS job and return jobId, or raise on failure."""
    west  = bbox_4326["west"]
    south = bbox_4326["south"]
    east  = bbox_4326["east"]
    north = bbox_4326["north"]

    aoi_json = json.dumps({
        "geometryType": "esriGeometryEnvelope",
        "geometry": {
            "xmin": west, "ymin": south,
            "xmax": east, "ymax": north,
            "spatialReference": {"wkid": 4326},
        },
    })

    payload = {
        "Layer_list":          "200FBFM40",
        "Area_of_Interest":    aoi_json,
        "Output_Projection":   "102039",   # USGS Albers (close to EPSG:5070)
        "Resample_Resolution": "30",
        "f":                   "json",
    }

    print(f"  Submitting LFPS job...")
    resp = requests.post(LFPS_SUBMIT, data=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()

    if "jobId" not in body:
        raise RuntimeError(f"LFPS submit — no jobId in response: {body}")

    job_id = body["jobId"]
    print(f"  Job ID: {job_id}")
    return job_id


def lfps_poll_job(job_id, max_wait=300, interval=10):
    """Poll until the job succeeds or timeout. Returns final status dict."""
    status_url = f"{LFPS_BASE}/jobs/{job_id}"
    elapsed = 0
    while elapsed < max_wait:
        resp = requests.get(status_url, params={"f": "json"}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        status = body.get("jobStatus", "")
        print(f"  LFPS status: {status}  ({elapsed}s elapsed)")
        if status == "esriJobSucceeded":
            return body
        if status in ("esriJobFailed", "esriJobCancelled", "esriJobTimedOut"):
            raise RuntimeError(f"LFPS job {status}: {body}")
        time.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"LFPS job did not complete within {max_wait}s")


def lfps_download(job_id):
    """Download job output and save as fuel_raw.tif. Returns path."""
    results_url = f"{LFPS_BASE}/jobs/{job_id}/results/Output_File"
    resp = requests.get(results_url, params={"f": "json"}, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    download_url = (
        result.get("value", {}).get("url")
        or result.get("value")
    )
    if not download_url:
        raise RuntimeError(f"Could not extract download URL from: {result}")

    print(f"  Downloading: {download_url}")
    dl = requests.get(download_url, timeout=300, stream=True)
    dl.raise_for_status()

    os.makedirs(FUEL_DIR, exist_ok=True)
    raw_bytes = dl.content

    # LFPS usually returns a ZIP containing a GeoTIFF
    if raw_bytes[:2] == b"PK":
        print("  Response is a ZIP — extracting GeoTIFF...")
        with zipfile.ZipFile(BytesIO(raw_bytes)) as zf:
            tif_names = [n for n in zf.namelist() if n.lower().endswith(".tif")]
            if not tif_names:
                raise RuntimeError(f"No .tif in ZIP: {zf.namelist()}")
            with zf.open(tif_names[0]) as src, open(FUEL_RAW, "wb") as dst:
                dst.write(src.read())
    else:
        with open(FUEL_RAW, "wb") as f:
            f.write(raw_bytes)

    print(f"  Saved fuel_raw.tif  ({os.path.getsize(FUEL_RAW) / 1024:.0f} KB)")
    return FUEL_RAW


def approach_a_lfps(bbox_4326):
    """Full LFPS workflow. Returns path to fuel_raw.tif or raises."""
    job_id = lfps_submit_job(bbox_4326)
    lfps_poll_job(job_id)
    return lfps_download(job_id)


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
# Synthetic fallback: elevation-band fuel assignment
# ---------------------------------------------------------------------------

def approach_synthetic(transform, crs, rows, cols):
    """
    Assign FBFM40 fuel codes from elevation bands using data/topography/elevation.tif.
    Elevation bands approximate Smoky Mountains vegetation zonation.
    """
    print("  Building synthetic fuel grid from elevation bands...")

    if not os.path.exists(ELEV_TIF):
        raise FileNotFoundError(
            f"Elevation raster not found: {ELEV_TIF}\n"
            "Run pipeline 03 (topography) before pipeline 02."
        )

    with rasterio.open(ELEV_TIF) as src:
        elev = src.read(1).astype(np.float32)

    fuel = np.full((rows, cols), -9999, dtype=np.int16)
    for lo, hi, code in ELEV_FUEL_BANDS:
        mask = (elev >= lo) & (elev < hi)
        fuel[mask] = code

    # Write a copy as fuel_raw.tif so downstream checks pass
    profile = {
        "driver": "GTiff", "dtype": "int16",
        "width": cols, "height": rows, "count": 1,
        "crs": crs, "transform": transform,
        "nodata": -9999, "compress": "lzw",
    }
    os.makedirs(FUEL_DIR, exist_ok=True)
    with rasterio.open(FUEL_RAW, "w", **profile) as dst:
        dst.write(fuel, 1)

    print(f"  Synthetic fuel grid complete — {(fuel > 0).sum()} valid cells")
    return fuel, "SYNTHETIC (elevation-band proxy — not real LANDFIRE data)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Step 2: Fuel Pipeline ===")
    os.makedirs(FUEL_DIR, exist_ok=True)

    aoi = load_aoi()
    bbox_4326 = aoi["bbox_4326"]
    rows      = aoi["grid_rows"]
    cols      = aoi["grid_cols"]
    transform, crs = dst_transform_and_crs(aoi)

    source_label = None
    fuel_data    = None

    # --- Approach A: LFPS ---
    print("\nApproach A: LANDFIRE Product Service API...")
    try:
        raw_tif = approach_a_lfps(bbox_4326)
        fuel_data = reproject_fuel_raw(raw_tif, transform, crs, rows, cols)
        source_label = "LANDFIRE FBFM40 2022 via LFPS API"
        print("  Approach A succeeded.")
    except Exception as exc:
        print(f"  Approach A failed: {exc}")
        fuel_data = None

    # --- Synthetic fallback ---
    if fuel_data is None:
        print("\nSynthetic fallback: elevation-band fuel assignment...")
        fuel_data, source_label = approach_synthetic(transform, crs, rows, cols)

    # --- Save outputs ---
    print("\nSaving outputs...")
    save_fuel_tif(fuel_data, transform, crs, rows, cols, source_label)
    write_csv_and_metadata(fuel_data, rows, cols, source_label)

    # Drop a hard-to-miss warning file if real LANDFIRE data was not used
    warning_file = os.path.join(FUEL_DIR, "SYNTHETIC_DATA_WARNING.txt")
    if "SYNTHETIC" in source_label:
        with open(warning_file, "w") as f:
            f.write(
                "WARNING: fuel_clipped.tif contains SYNTHETIC data.\n"
                "Real LANDFIRE FBFM40 data was not fetched.\n\n"
                "To get real data:\n"
                "  1. Register for a LANDFIRE account at https://landfire.gov/\n"
                "  2. Verify the LFPS API endpoint is accessible:\n"
                "       curl 'https://lfps.usgs.gov/arcgis/rest/services/LandfireProductService/GPServer/LandfireProductService?f=json'\n"
                "  3. Re-run: make run-02\n\n"
                "This file is deleted automatically when real data is fetched successfully.\n"
            )
        print(
            "\n⚠  SYNTHETIC FUEL DATA — see data/fuel/SYNTHETIC_DATA_WARNING.txt"
        )
    else:
        # Clean up stale warning if real data now present
        if os.path.exists(warning_file):
            os.remove(warning_file)


if __name__ == "__main__":
    main()
