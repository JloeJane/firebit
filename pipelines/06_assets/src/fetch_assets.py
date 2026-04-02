import json
import os
import random
import time
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import requests
from shapely.geometry import Point, Polygon, mapping

AOI_METADATA = "/data/input/aoi_metadata.json"
OUT_DIR = "/data/assets"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT = 120
MIN_BUILDINGS = 10

# Townsend valley approximate center — used to bias synthetic building placement
TOWNSEND_LAT = 35.594
TOWNSEND_LON = -83.773


def load_aoi():
    with open(AOI_METADATA) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Overpass helpers
# ---------------------------------------------------------------------------

def overpass_query(query, label):
    print(f"  Querying Overpass API: {label}...")
    try:
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=OVERPASS_TIMEOUT + 30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  WARNING: Overpass request failed ({label}): {e}")
        return None


def osm_ways_to_polygons(elements):
    """Convert Overpass way+node elements to Shapely Polygons."""
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in elements if e["type"] == "node"}
    polys = []
    for e in elements:
        if e["type"] != "way":
            continue
        refs = e.get("nodes", [])
        coords = [nodes[r] for r in refs if r in nodes]
        if len(coords) >= 4:
            try:
                polys.append(Polygon(coords))
            except Exception:
                pass
    return polys


def osm_ways_to_linestrings(elements):
    """Convert Overpass way+node elements to coordinate lists (line segments)."""
    from shapely.geometry import LineString
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in elements if e["type"] == "node"}
    lines = []
    for e in elements:
        if e["type"] != "way":
            continue
        refs = e.get("nodes", [])
        coords = [nodes[r] for r in refs if r in nodes]
        if len(coords) >= 2:
            try:
                lines.append(LineString(coords))
            except Exception:
                pass
    return lines


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------

def fetch_buildings(bbox):
    s, w, n, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]
    query = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  way["building"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
);
out body; >; out skel qt;
"""
    data = overpass_query(query, "buildings")
    if data is None:
        return None

    elements = data.get("elements", [])
    polys = osm_ways_to_polygons(elements)
    print(f"  Parsed {len(polys)} building polygons from Overpass")
    return polys


def synthetic_buildings(bbox, n=300, seed=42):
    """
    Generate synthetic building footprints concentrated around Townsend valley.
    Used when Overpass API is unavailable or returns too few results.
    """
    print(f"  Generating {n} synthetic buildings (MVP fallback)...")
    rng = random.Random(seed)

    s, w, n_lat, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]

    # Cluster 70% near Townsend center, spread 30% across the AOI
    buildings = []
    for i in range(n):
        if rng.random() < 0.70:
            # Valley cluster: tight spread around Townsend
            lat = rng.gauss(TOWNSEND_LAT, 0.015)
            lon = rng.gauss(TOWNSEND_LON, 0.020)
        else:
            lat = rng.uniform(s, n_lat)
            lon = rng.uniform(w, e)

        # Clamp to bbox
        lat = max(s, min(n_lat, lat))
        lon = max(w, min(e, lon))

        # Small rectangular footprint (~10×12m)
        dx = 0.00009  # ~10m in degrees lon
        dy = 0.00011  # ~12m in degrees lat
        buildings.append(Polygon([
            (lon - dx, lat - dy),
            (lon + dx, lat - dy),
            (lon + dx, lat + dy),
            (lon - dx, lat + dy),
            (lon - dx, lat - dy),
        ]))

    return buildings


def build_buildings_gdf(polys, source_label):
    gdf = gpd.GeoDataFrame(
        {"source": [source_label] * len(polys)},
        geometry=polys,
        crs="EPSG:4326",
    )
    gdf = gdf.to_crs("EPSG:5070")
    return gdf


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

def fetch_infrastructure(bbox):
    s, w, n, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]
    query = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  way["highway"~"^(primary|secondary|tertiary)$"]({s},{w},{n},{e});
  way["power"="line"]({s},{w},{n},{e});
);
out body; >; out skel qt;
"""
    data = overpass_query(query, "infrastructure")
    if data is None:
        return None, None

    elements = data.get("elements", [])
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in elements if e["type"] == "node"}

    roads = []
    power_lines = []
    for e in elements:
        if e["type"] != "way":
            continue
        tags = e.get("tags", {})
        refs = e.get("nodes", [])
        coords = [nodes[r] for r in refs if r in nodes]
        if len(coords) < 2:
            continue
        from shapely.geometry import LineString
        try:
            line = LineString(coords)
        except Exception:
            continue
        if "highway" in tags:
            roads.append({"geometry": line, "highway": tags.get("highway", "")})
        elif tags.get("power") == "line":
            power_lines.append({"geometry": line, "power": "line"})

    return roads, power_lines


def build_infra_gdf(features, crs_from="EPSG:4326"):
    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:5070")
    gdf = gpd.GeoDataFrame(features, crs=crs_from)
    return gdf.to_crs("EPSG:5070")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    meta = load_aoi()
    bbox = meta["bbox_4326"]
    print(f"AOI bbox (WGS84): N={bbox['north']} S={bbox['south']} E={bbox['east']} W={bbox['west']}")

    # --- Buildings ---
    print("\n=== Fetching buildings ===")
    polys = fetch_buildings(bbox)
    source_label = "OpenStreetMap"

    if polys is None or len(polys) < MIN_BUILDINGS:
        if polys is not None:
            print(f"  Only {len(polys)} buildings from Overpass (< {MIN_BUILDINGS}), using synthetic fallback")
        polys = synthetic_buildings(bbox)
        source_label = "synthetic_mvp"

    buildings_gdf = build_buildings_gdf(polys, source_label)
    buildings_path = os.path.join(OUT_DIR, "buildings.geojson")
    buildings_gdf.to_file(buildings_path, driver="GeoJSON")
    print(f"  Saved {len(buildings_gdf)} buildings → {buildings_path} (source: {source_label})")

    # --- Population ---
    print("\n=== Estimating population ===")
    PEOPLE_PER_BUILDING = 2.3
    pop_gdf = buildings_gdf.copy()
    pop_gdf["geometry"] = pop_gdf.geometry.centroid
    pop_gdf["estimated_pop"] = PEOPLE_PER_BUILDING
    pop_path = os.path.join(OUT_DIR, "population.geojson")
    pop_gdf[["geometry", "estimated_pop"]].to_file(pop_path, driver="GeoJSON")
    total_pop = round(len(buildings_gdf) * PEOPLE_PER_BUILDING, 1)
    print(f"  Estimated population: {total_pop} ({len(buildings_gdf)} buildings × {PEOPLE_PER_BUILDING})")

    # --- Infrastructure ---
    print("\n=== Fetching infrastructure ===")
    roads_raw, power_raw = fetch_infrastructure(bbox)

    if roads_raw is None:
        print("  Infrastructure fetch failed — writing empty layer")
        roads_raw, power_raw = [], []

    roads_gdf = build_infra_gdf(roads_raw)
    power_gdf = build_infra_gdf(power_raw)

    infra_features = []
    for _, row in roads_gdf.iterrows():
        infra_features.append({
            "type": "Feature",
            "geometry": mapping(row.geometry),
            "properties": {"type": "road", "highway": row.get("highway", "")},
        })
    for _, row in power_gdf.iterrows():
        infra_features.append({
            "type": "Feature",
            "geometry": mapping(row.geometry),
            "properties": {"type": "power_line"},
        })

    infra_geojson = {"type": "FeatureCollection", "features": infra_features}
    infra_path = os.path.join(OUT_DIR, "infrastructure.geojson")
    with open(infra_path, "w") as f:
        json.dump(infra_geojson, f)
    print(f"  Road segments: {len(roads_gdf)}, Power line segments: {len(power_gdf)}")
    print(f"  Saved infrastructure → {infra_path}")

    # --- Metadata ---
    assets_meta = {
        "total_buildings": len(buildings_gdf),
        "estimated_population": total_pop,
        "road_segments": len(roads_gdf),
        "power_line_segments": len(power_gdf),
        "source": source_label,
        "buildings_source": source_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = os.path.join(OUT_DIR, "assets_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(assets_meta, f, indent=2)
    print(f"\nWrote {meta_path}")
    print(f"\nSummary: {len(buildings_gdf)} buildings, est. pop {total_pop}, "
          f"{len(roads_gdf)} road segments, {len(power_gdf)} power lines")


if __name__ == "__main__":
    main()
