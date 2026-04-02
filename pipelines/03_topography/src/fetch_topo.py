import os
import json
import numpy as np
import requests
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from datetime import datetime, timezone

# --- Paths ---
META_JSON = "/data/input/aoi_metadata.json"
TOPO_DIR  = "/data/topography"
ELEV_RAW  = os.path.join(TOPO_DIR, "elevation_raw.tif")
ELEV_TIF  = os.path.join(TOPO_DIR, "elevation.tif")
SLOPE_TIF = os.path.join(TOPO_DIR, "slope.tif")
ASPECT_TIF = os.path.join(TOPO_DIR, "aspect.tif")
TOPO_META = os.path.join(TOPO_DIR, "topo_metadata.json")

USGS_API = (
    "https://elevation.nationalmap.gov/arcgis/rest/services"
    "/3DEPElevation/ImageServer/exportImage"
)

# Approximate degrees per 30m at mid-latitudes
DEGREES_PER_30M = 30.0 / 111_320.0


def load_aoi_metadata():
    with open(META_JSON) as f:
        return json.load(f)


def fetch_elevation_raw(bbox_4326, width_px, height_px):
    """Download raw elevation GeoTIFF from USGS 3DEP ImageServer."""
    west, south, east, north = (
        bbox_4326["west"], bbox_4326["south"],
        bbox_4326["east"], bbox_4326["north"],
    )

    params = {
        "bbox":                   f"{west},{south},{east},{north}",
        "bboxSR":                 4326,
        "imageSR":                4326,
        "size":                   f"{width_px},{height_px}",
        "format":                 "tiff",
        "pixelType":              "F32",
        "noData":                 -9999,
        "noDataInterpretation":   "esriNoDataMatchAny",
        "f":                      "image",
    }

    print(f"Fetching USGS 3DEP elevation...")
    print(f"  bbox (4326): {west},{south},{east},{north}")
    print(f"  size: {width_px} x {height_px} px")
    print(f"  URL: {USGS_API}")

    resp = requests.get(USGS_API, params=params, timeout=180)

    if resp.status_code != 200:
        raise RuntimeError(
            f"USGS API returned HTTP {resp.status_code}\n"
            f"Request URL: {resp.url}\n"
            f"Response: {resp.text[:500]}"
        )

    content_type = resp.headers.get("Content-Type", "")
    if b"TIFF" not in resp.content[:8] and b"II" not in resp.content[:2]:
        raise RuntimeError(
            f"Response does not appear to be a GeoTIFF.\n"
            f"Content-Type: {content_type}\n"
            f"Request URL: {resp.url}\n"
            f"First 200 bytes: {resp.content[:200]}"
        )

    os.makedirs(TOPO_DIR, exist_ok=True)
    with open(ELEV_RAW, "wb") as f:
        f.write(resp.content)
    print(f"  Saved raw elevation: {ELEV_RAW}  ({len(resp.content) / 1024:.0f} KB)")
    return ELEV_RAW, west, south, east, north


def reproject_to_5070(raw_tif, src_bbox, bbox_5070, grid_rows, grid_cols):
    """Reproject raw elevation to EPSG:5070 at exact AOI grid alignment."""
    west, south, east, north = src_bbox

    xmin = bbox_5070["xmin"]
    ymin = bbox_5070["ymin"]
    xmax = bbox_5070["xmax"]
    ymax = bbox_5070["ymax"]

    dst_transform = from_bounds(xmin, ymin, xmax, ymax, grid_cols, grid_rows)
    dst_crs = CRS.from_epsg(5070)

    with rasterio.open(raw_tif) as src:
        # Use embedded CRS if present, else assume EPSG:4326 (we requested imageSR=4326)
        src_crs = src.crs if src.crs else CRS.from_epsg(4326)

        # Use embedded transform if georeferenced, else compute from request bbox
        if src.transform and src.transform != rasterio.transform.IDENTITY:
            src_transform = src.transform
        else:
            src_transform = from_bounds(west, south, east, north, src.width, src.height)

        print(f"  Source CRS:  {src_crs}")
        print(f"  Source size: {src.width} x {src.height}")

        dst_array = np.zeros((grid_rows, grid_cols), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst_array,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            src_nodata=-9999.0,
            dst_nodata=-9999.0,
        )

    # Fill any remaining nodata / zero edge pixels using nearest-neighbor fallback
    nodata_mask = (dst_array <= -9000) | (dst_array == 0)
    if nodata_mask.any():
        n_bad = int(nodata_mask.sum())
        print(f"  Warning: {n_bad} nodata/zero pixels after reproject — filling with nearest valid value.")
        valid_mask = ~nodata_mask
        if valid_mask.any():
            from scipy.ndimage import distance_transform_edt
            _, idx = distance_transform_edt(nodata_mask, return_indices=True)
            dst_array[nodata_mask] = dst_array[idx[0][nodata_mask], idx[1][nodata_mask]]

    profile = {
        "driver":    "GTiff",
        "dtype":     "float32",
        "width":     grid_cols,
        "height":    grid_rows,
        "count":     1,
        "crs":       dst_crs,
        "transform": dst_transform,
        "nodata":    -9999.0,
        "compress":  "lzw",
    }
    with rasterio.open(ELEV_TIF, "w", **profile) as dst:
        dst.write(dst_array, 1)

    print(f"  Saved elevation.tif: {grid_rows} rows × {grid_cols} cols, EPSG:5070, 30m")
    return dst_array, dst_transform, dst_crs, profile


def derive_slope_aspect(elevation, profile):
    """Compute slope (degrees) and aspect (degrees from north, 0-360)."""
    # Work on valid data
    valid = elevation > -9000
    elev = np.where(valid, elevation, np.nan)

    # np.gradient returns [dy, dx] for a 2D array; cell size = 30m
    dy, dx = np.gradient(elev, 30.0)

    slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
    aspect = np.degrees(np.arctan2(-dx, dy))
    aspect = (aspect + 360.0) % 360.0

    # Replace nan with nodata
    nodata = -9999.0
    slope  = np.where(np.isnan(slope),  nodata, slope).astype(np.float32)
    aspect = np.where(np.isnan(aspect), nodata, aspect).astype(np.float32)

    with rasterio.open(SLOPE_TIF, "w", **profile) as dst:
        dst.write(slope, 1)
    print(f"  Saved slope.tif")

    with rasterio.open(ASPECT_TIF, "w", **profile) as dst:
        dst.write(aspect, 1)
    print(f"  Saved aspect.tif")

    return slope, aspect


def write_metadata(elevation, slope):
    valid_e = elevation[elevation > -9000]
    valid_s = slope[slope > -9000]

    metadata = {
        "elevation_min_m":  round(float(valid_e.min()), 1),
        "elevation_max_m":  round(float(valid_e.max()), 1),
        "elevation_mean_m": round(float(valid_e.mean()), 1),
        "slope_mean_deg":   round(float(valid_s.mean()), 2),
        "slope_max_deg":    round(float(valid_s.max()), 2),
        "rows":             int(elevation.shape[0]),
        "cols":             int(elevation.shape[1]),
        "resolution_m":     30,
        "crs":              "EPSG:5070",
        "source":           "USGS 3DEP",
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }

    with open(TOPO_META, "w") as f:
        json.dump(metadata, f, indent=2)

    print()
    print("=== Topography Summary ===")
    print(f"  Elevation: {metadata['elevation_min_m']:.0f} – {metadata['elevation_max_m']:.0f} m"
          f"  (mean {metadata['elevation_mean_m']:.0f} m)")
    print(f"  Slope:     0 – {metadata['slope_max_deg']:.1f}°  (mean {metadata['slope_mean_deg']:.1f}°)")
    print(f"  Grid:      {metadata['rows']} rows × {metadata['cols']} cols at {metadata['resolution_m']}m")
    print(f"  CRS:       {metadata['crs']}")
    print("==========================")


def main():
    print("=== Step 3: Topography Pipeline ===")

    aoi = load_aoi_metadata()
    bbox_4326 = aoi["bbox_4326"]
    bbox_5070 = aoi["bbox_5070"]
    grid_rows = aoi["grid_rows"]
    grid_cols = aoi["grid_cols"]

    # Pixel count for download request (slightly oversample, let warp handle resampling)
    width_px  = max(int((bbox_4326["east"] - bbox_4326["west"]) / DEGREES_PER_30M) + 10, 50)
    height_px = max(int((bbox_4326["north"] - bbox_4326["south"]) / DEGREES_PER_30M) + 10, 50)

    # 1. Fetch raw elevation
    raw_tif, west, south, east, north = fetch_elevation_raw(bbox_4326, width_px, height_px)
    src_bbox = (west, south, east, north)

    # 2. Reproject to EPSG:5070 at exact grid alignment
    print("\nReprojecting to EPSG:5070...")
    elevation, transform, crs, profile = reproject_to_5070(
        raw_tif, src_bbox, bbox_5070, grid_rows, grid_cols
    )

    # 3. Derive slope and aspect
    print("\nDeriving slope and aspect...")
    slope, aspect = derive_slope_aspect(elevation, profile)

    # 4. Write metadata
    write_metadata(elevation, slope)


if __name__ == "__main__":
    main()
