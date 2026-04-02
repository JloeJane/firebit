import os
import json
import math
from datetime import datetime, timezone

import geopandas as gpd
from shapely.geometry import box

# --- Config from environment ---
AOI_SHAPEFILE = os.environ.get("AOI_SHAPEFILE", "data/input/townsend_aoi.shp")
TARGET_CRS = os.environ.get("TARGET_CRS", "EPSG:5070")
RESOLUTION_M = int(os.environ.get("GRID_RESOLUTION", "30"))

BBOX_NORTH = float(os.environ.get("BBOX_NORTH", "35.65"))
BBOX_SOUTH = float(os.environ.get("BBOX_SOUTH", "35.55"))
BBOX_EAST  = float(os.environ.get("BBOX_EAST",  "-83.70"))
BBOX_WEST  = float(os.environ.get("BBOX_WEST",  "-83.83"))

INPUT_DIR = "/data/input"
RAW_SHP   = os.path.join(INPUT_DIR, "townsend_aoi.shp")
REPR_SHP  = os.path.join(INPUT_DIR, "aoi_reprojected.shp")
META_JSON = os.path.join(INPUT_DIR, "aoi_metadata.json")


def generate_townsend_aoi() -> gpd.GeoDataFrame:
    """Create the rectangular Townsend AOI polygon in EPSG:4326."""
    polygon = box(BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH)
    gdf = gpd.GeoDataFrame({"name": ["townsend_aoi"]}, geometry=[polygon], crs="EPSG:4326")
    return gdf


def load_or_generate_aoi() -> gpd.GeoDataFrame:
    """Load user-provided shapefile if it exists, otherwise generate test AOI."""
    user_shp = os.path.join(INPUT_DIR, os.path.basename(AOI_SHAPEFILE))
    if os.path.exists(user_shp) and user_shp != RAW_SHP:
        print(f"Loading user-provided shapefile: {user_shp}")
        gdf = gpd.read_file(user_shp)
        if gdf.crs is None:
            raise ValueError("User shapefile has no CRS defined.")
        if gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")
    else:
        print("No user shapefile found — generating Townsend test AOI.")
        gdf = generate_townsend_aoi()

    # Validate geometry
    if not gdf.geometry.iloc[0].is_valid:
        print("Geometry invalid — attempting repair with buffer(0).")
        gdf["geometry"] = gdf.geometry.buffer(0)

    return gdf


def main():
    os.makedirs(INPUT_DIR, exist_ok=True)

    # 1. Load or generate AOI in EPSG:4326
    gdf_4326 = load_or_generate_aoi()

    # Save raw AOI
    gdf_4326.to_file(RAW_SHP)
    print(f"Saved raw AOI: {RAW_SHP}")

    # 2. Reproject to EPSG:5070
    gdf_5070 = gdf_4326.to_crs(TARGET_CRS)
    gdf_5070.to_file(REPR_SHP)
    print(f"Saved reprojected AOI ({TARGET_CRS}): {REPR_SHP}")

    # 3. Bounding boxes
    b4326 = gdf_4326.total_bounds   # (xmin, ymin, xmax, ymax) = (W, S, E, N)
    b5070 = gdf_5070.total_bounds

    bbox_4326 = {
        "north": round(float(b4326[3]), 6),
        "south": round(float(b4326[1]), 6),
        "east":  round(float(b4326[2]), 6),
        "west":  round(float(b4326[0]), 6),
    }
    bbox_5070 = {
        "xmin": round(float(b5070[0]), 2),
        "ymin": round(float(b5070[1]), 2),
        "xmax": round(float(b5070[2]), 2),
        "ymax": round(float(b5070[3]), 2),
    }

    # 4. Area
    area_m2 = float(gdf_5070.geometry.iloc[0].area)
    area_ha = area_m2 / 10_000
    area_sq_mi = area_m2 / 2_589_988.11

    # 5. Grid dimensions
    width_m  = bbox_5070["xmax"] - bbox_5070["xmin"]
    height_m = bbox_5070["ymax"] - bbox_5070["ymin"]
    grid_cols = math.ceil(width_m  / RESOLUTION_M)
    grid_rows = math.ceil(height_m / RESOLUTION_M)

    # 6. Metadata
    metadata = {
        "bbox_4326":        bbox_4326,
        "bbox_5070":        bbox_5070,
        "area_sq_mi":       round(area_sq_mi, 2),
        "area_ha":          round(area_ha, 1),
        "grid_rows":        grid_rows,
        "grid_cols":        grid_cols,
        "resolution_m":     RESOLUTION_M,
        "crs_projected":    TARGET_CRS,
        "crs_geographic":   "EPSG:4326",
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }

    with open(META_JSON, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved metadata: {META_JSON}")

    # 7. Summary
    print()
    print("=== AOI Summary ===")
    print(f"  Bounding box (lat/lon): N={bbox_4326['north']}  S={bbox_4326['south']}  "
          f"E={bbox_4326['east']}  W={bbox_4326['west']}")
    print(f"  Area:    {area_sq_mi:.1f} sq mi  /  {area_ha:.0f} ha")
    print(f"  Grid:    {grid_rows} rows × {grid_cols} cols  "
          f"(~{grid_rows * grid_cols / 1_000_000:.1f}M cells at {RESOLUTION_M}m)")
    print(f"  CRS:     {TARGET_CRS}")
    print("===================")


if __name__ == "__main__":
    main()
