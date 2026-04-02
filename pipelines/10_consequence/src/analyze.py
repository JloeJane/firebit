import json
import os
import shutil
import glob
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
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
        pop_at_risk = round(float(pop_gdf[exposed_pop_mask]["estimated_pop"].sum()), 1)
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
