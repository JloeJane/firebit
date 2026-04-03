import json
import os
import shutil
import glob
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import requests
import rasterio
import rasterio.transform
from shapely.geometry import shape

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIRE_PERIMETER   = "/data/simulation/fire_perimeter_final.geojson"
BURN_SCAR_TIF    = "/data/simulation/burn_scar.tif"
SIMULATION_JSON  = "/data/simulation/summary.json"
TIMESTEP_GRIDS   = "/data/simulation/grids"
GRID_METADATA    = "/data/grid/grid_metadata.json"

BUILDINGS_GJ     = "/data/assets/buildings.geojson"
POPULATION_GJ    = "/data/assets/population.geojson"
INFRA_GJ         = "/data/assets/infrastructure.geojson"
ASSETS_META      = "/data/assets/assets_metadata.json"

CONSEQUENCE_DIR  = "/data/consequence"
OUTPUT_DIR       = "/data/output"
AOI_METADATA     = "/data/input/aoi_metadata.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path) as f:
        return json.load(f)


def fire_arrival_grid(grid_dir, nrows, ncols):
    """
    Build an (nrows, ncols) array where each cell value is the first timestep
    index (0-based) at which that cell burned, or -1 if never burned.
    """
    tif_paths = sorted(glob.glob(os.path.join(grid_dir, "grid_t*.tif")))
    if not tif_paths:
        return None

    arrival = np.full((nrows, ncols), -1, dtype=np.int16)
    for t, path in enumerate(tif_paths):
        with rasterio.open(path) as src:
            band = src.read(1)
        # Mark cells that burned this timestep and haven't been marked yet
        newly_burned = (band == 1) & (arrival == -1)
        arrival[newly_burned] = t

    return arrival


def xy_to_rowcol(x, y, meta):
    """Convert projected x/y (EPSG:5070) to grid row/col using grid_metadata."""
    col = int((x - meta["xllcorner"]) / meta["cellsize"])
    row = int((meta["yllcorner"] + meta["nrows"] * meta["cellsize"] - y) / meta["cellsize"])
    return row, col


# ---------------------------------------------------------------------------
# NSI valuation
# ---------------------------------------------------------------------------

def fetch_nsi_values(bbox_4326: dict) -> gpd.GeoDataFrame:
    """Fetch structure values from the FEMA National Structure Inventory API."""
    url = "https://nsi.sec.usace.army.mil/nsiapi/structures"
    params = {
        "bbox": f"{bbox_4326['west']},{bbox_4326['south']},{bbox_4326['east']},{bbox_4326['north']}",
        "fmt": "fc",
    }
    empty = gpd.GeoDataFrame()
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        fc = resp.json()
        gdf = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
        gdf = gdf.to_crs("EPSG:5070")
        keep = ["geometry"] + [c for c in ["val_struct", "val_cont", "occtype", "sqft"]
                               if c in gdf.columns]
        gdf = gdf[keep]
        print(f"NSI: fetched {len(gdf)} structures")
        return gdf
    except requests.exceptions.Timeout:
        print("WARNING: NSI API timed out — using fallback values")
        return empty
    except Exception as e:
        print(f"WARNING: NSI API failed ({e}) — using fallback values")
        return empty


def assign_building_values(buildings_gdf: gpd.GeoDataFrame,
                           nsi_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Enrich buildings with estimated replacement values from NSI or sqft fallback."""
    gdf = buildings_gdf.copy().reset_index(drop=True)

    def _fallback_sqft(geom):
        area = geom.area  # m² in EPSG:5070
        return area * 10.764 if area > 0 else 1200.0

    if len(nsi_gdf) == 0:
        sqfts = np.array([_fallback_sqft(g) for g in gdf.geometry])
        gdf["structure_sqft"]      = sqfts
        gdf["estimated_value_usd"] = (sqfts * 175).astype(int)
        gdf["occupancy_type"]      = "RES1-ESTIMATED"
        return gdf

    assert gdf.crs.to_epsg() == nsi_gdf.crs.to_epsg(), \
        f"CRS mismatch: {gdf.crs} vs {nsi_gdf.crs}"

    nsi_join_cols = ["geometry"] + [c for c in ["val_struct", "occtype", "sqft"]
                                    if c in nsi_gdf.columns]
    merged = gpd.sjoin_nearest(gdf, nsi_gdf[nsi_join_cols], max_distance=50, how="left")
    merged = merged[~merged.index.duplicated(keep="first")].reset_index(drop=True)

    matched = merged["val_struct"].notna() if "val_struct" in merged.columns \
              else np.zeros(len(merged), dtype=bool)

    # Default all to fallback, then override where NSI matched
    fallback_sqfts = np.array([_fallback_sqft(g) for g in merged.geometry])
    merged["structure_sqft"]      = fallback_sqfts
    merged["estimated_value_usd"] = (fallback_sqfts * 175).astype(int)
    merged["occupancy_type"]      = "RES1-ESTIMATED"

    if "sqft" in merged.columns:
        valid = matched & merged["sqft"].notna()
        merged.loc[valid, "structure_sqft"] = merged.loc[valid, "sqft"]
        # Recalculate value for those rows using updated sqft (will be overwritten by val_struct below)
        merged.loc[valid, "estimated_value_usd"] = (merged.loc[valid, "structure_sqft"] * 175).astype(int)

    if "val_struct" in merged.columns:
        valid = matched & merged["val_struct"].notna()
        merged.loc[valid, "estimated_value_usd"] = merged.loc[valid, "val_struct"].astype(int)

    if "occtype" in merged.columns:
        valid = matched & merged["occtype"].notna()
        merged.loc[valid, "occupancy_type"] = merged.loc[valid, "occtype"]

    drop_cols = [c for c in ["index_right", "val_struct", "val_cont", "occtype", "sqft"]
                 if c in merged.columns]
    return merged.drop(columns=drop_cols)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(CONSEQUENCE_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # --- Load simulation outputs ---
    sim_meta = load_json(SIMULATION_JSON)
    total_area_ha  = sim_meta["total_area_burned_ha"]
    total_area_acres = round(total_area_ha * 2.47105, 1)
    print(f"Simulation: {total_area_ha:.1f} ha ({total_area_acres:.1f} acres) burned")

    # --- Load fire perimeter ---
    perimeter_gdf = gpd.read_file(FIRE_PERIMETER)
    if perimeter_gdf.crs is None:
        perimeter_gdf = perimeter_gdf.set_crs("EPSG:5070")
    elif perimeter_gdf.crs.to_string() != "EPSG:5070":
        perimeter_gdf = perimeter_gdf.to_crs("EPSG:5070")

    fire_union = perimeter_gdf.geometry.union_all()
    print(f"Fire perimeter loaded: {fire_union.geom_type}, "
          f"area={fire_union.area / 10_000:.1f} ha")

    # --- Load buildings ---
    buildings_gdf = gpd.read_file(BUILDINGS_GJ)
    if buildings_gdf.crs is None:
        buildings_gdf = buildings_gdf.set_crs("EPSG:5070")
    elif buildings_gdf.crs.to_string() != "EPSG:5070":
        buildings_gdf = buildings_gdf.to_crs("EPSG:5070")
    print(f"Buildings loaded: {len(buildings_gdf)}")

    # --- Fetch NSI values and enrich all buildings ---
    bbox_4326 = load_json(AOI_METADATA).get("bbox_4326", {})
    nsi_gdf = fetch_nsi_values(bbox_4326)
    buildings_gdf = assign_building_values(buildings_gdf, nsi_gdf)
    buildings_gdf.to_file(BUILDINGS_GJ, driver="GeoJSON")
    print(f"Enriched {len(buildings_gdf)} buildings with value estimates")

    # --- Building exposure: intersects or within fire perimeter ---
    exposed_mask = buildings_gdf.geometry.intersects(fire_union)
    exposed_gdf  = buildings_gdf[exposed_mask].copy()
    print(f"Exposed buildings: {len(exposed_gdf)} / {len(buildings_gdf)}")

    # --- Population at risk ---
    pop_at_risk = 0.0
    if os.path.exists(POPULATION_GJ):
        pop_gdf = gpd.read_file(POPULATION_GJ)
        if pop_gdf.crs is None:
            pop_gdf = pop_gdf.set_crs("EPSG:5070")
        elif pop_gdf.crs.to_string() != "EPSG:5070":
            pop_gdf = pop_gdf.to_crs("EPSG:5070")
        exposed_pop_mask = pop_gdf.geometry.intersects(fire_union)
        if "estimated_pop" in pop_gdf.columns:
            pop_at_risk = round(float(pop_gdf[exposed_pop_mask]["estimated_pop"].sum()), 1)
        else:
            pop_at_risk = round(int(exposed_pop_mask.sum()) * 2.3, 1)
    else:
        # Fall back to 2.3 per exposed building
        pop_at_risk = round(len(exposed_gdf) * 2.3, 1)
    print(f"Estimated population at risk: {pop_at_risk}")

    # --- Infrastructure exposure ---
    road_count  = 0
    power_count = 0
    if os.path.exists(INFRA_GJ):
        infra_gdf = gpd.read_file(INFRA_GJ)
        if len(infra_gdf) > 0:
            if infra_gdf.crs is None:
                infra_gdf = infra_gdf.set_crs("EPSG:5070")
            elif infra_gdf.crs.to_string() != "EPSG:5070":
                infra_gdf = infra_gdf.to_crs("EPSG:5070")
            exposed_infra = infra_gdf[infra_gdf.geometry.intersects(fire_union)]
            if "type" in exposed_infra.columns:
                road_count  = int((exposed_infra["type"] == "road").sum())
                power_count = int((exposed_infra["type"] == "power_line").sum())
            else:
                road_count = len(exposed_infra)
    print(f"Infrastructure exposed: {road_count} road segments, {power_count} power lines")

    # --- Fire arrival time to first structure ---
    fire_arrival_hrs = None
    grid_meta = None
    if os.path.exists(GRID_METADATA):
        grid_meta = load_json(GRID_METADATA)

    if grid_meta and os.path.isdir(TIMESTEP_GRIDS) and len(exposed_gdf) > 0:
        arrival = fire_arrival_grid(
            TIMESTEP_GRIDS, grid_meta["nrows"], grid_meta["ncols"]
        )
        if arrival is not None:
            earliest = None
            for geom in exposed_gdf.geometry:
                cx, cy = geom.centroid.x, geom.centroid.y
                r, c = xy_to_rowcol(cx, cy, grid_meta)
                if 0 <= r < grid_meta["nrows"] and 0 <= c < grid_meta["ncols"]:
                    t = int(arrival[r, c])
                    if t >= 0:
                        if earliest is None or t < earliest:
                            earliest = t
            if earliest is not None:
                # Each timestep = Fire-Period-Length hours (1.0 h)
                fire_arrival_hrs = round(float(earliest), 1)
    print(f"Fire arrival to first structure: {fire_arrival_hrs} hrs")

    # --- Save exposed buildings ---
    exposed_path = os.path.join(CONSEQUENCE_DIR, "exposed_buildings.geojson")
    exposed_gdf.to_file(exposed_path, driver="GeoJSON")
    print(f"Saved exposed buildings → {exposed_path}")

    # --- NSI loss stats ---
    nsi_match_count = int((exposed_gdf["occupancy_type"] != "RES1-ESTIMATED").sum()) \
                      if "occupancy_type" in exposed_gdf.columns else 0
    total_loss_usd  = int(exposed_gdf["estimated_value_usd"].sum()) \
                      if "estimated_value_usd" in exposed_gdf.columns else 0
    _avg = buildings_gdf["estimated_value_usd"].mean() \
           if "estimated_value_usd" in buildings_gdf.columns else 0
    avg_value_usd = int(round(_avg)) if _avg == _avg else 0  # guard NaN
    nsi_source      = "FEMA NSI" if nsi_match_count > 0 else "estimated"
    print(f"Total estimated loss: ${total_loss_usd:,}  (NSI matches: {nsi_match_count}, source: {nsi_source})")

    # --- Write consequence summary ---
    summary = {
        "total_area_burned_ha":              total_area_ha,
        "total_area_burned_acres":           total_area_acres,
        "structures_exposed":                len(exposed_gdf),
        "estimated_population_at_risk":      pop_at_risk,
        "infrastructure_exposed": {
            "road_segments":       road_count,
            "power_line_segments": power_count,
        },
        "fire_arrival_to_first_structure_hrs": fire_arrival_hrs,
        "total_estimated_loss_usd":          total_loss_usd,
        "avg_structure_value_usd":           avg_value_usd,
        "nsi_match_count":                   nsi_match_count,
        "nsi_source":                        nsi_source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path = os.path.join(CONSEQUENCE_DIR, "consequence_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Saved consequence summary → {summary_path}")

    # --- Copy key outputs to data/output/ ---
    shutil.copy(summary_path, os.path.join(OUTPUT_DIR, "consequence_summary.json"))
    shutil.copy(exposed_path, os.path.join(OUTPUT_DIR, "exposed_buildings.geojson"))
    shutil.copy(FIRE_PERIMETER, os.path.join(OUTPUT_DIR, "fire_perimeter.geojson"))
    print(f"Copied outputs to {OUTPUT_DIR}/")

    # --- Print summary ---
    print("\n" + "=" * 50)
    print("CONSEQUENCE ANALYSIS COMPLETE")
    print("=" * 50)
    print(f"  Area burned:          {total_area_ha:.1f} ha ({total_area_acres:.1f} acres)")
    print(f"  Structures exposed:   {len(exposed_gdf)}")
    print(f"  Population at risk:   {pop_at_risk}")
    print(f"  Road segments:        {road_count}")
    print(f"  Power lines:          {power_count}")
    print(f"  Time to 1st struct:   {fire_arrival_hrs} hrs")


if __name__ == "__main__":
    main()
