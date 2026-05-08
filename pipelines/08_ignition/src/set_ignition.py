import json
import os
import csv
import re
from datetime import datetime, timezone

import numpy as np
from pyproj import Transformer

DEFAULT_LAT = 35.56
DEFAULT_LON = -83.75

GRID_METADATA     = "/data/grid/grid_metadata.json"
FUELS_ASC         = "/data/grid/fuels.asc"
FBFM40_TIF        = "/data/grid/fbfm40.tif"
IGNITIONS_CSV     = "/data/grid/Ignitions.csv"
IGNITION_METADATA = "/data/grid/ignition_metadata.json"
ELMFIRE_DATA      = "/data/grid/elmfire.data"

NON_BURNABLE_CODES = {91, 92, 93, 98, 99, -9999}


def load_grid_metadata():
    with open(GRID_METADATA) as f:
        return json.load(f)


def load_fuels(meta):
    import rasterio
    nrows = meta["nrows"]
    ncols = meta["ncols"]
    # Prefer GeoTIFF (ELMFIRE pipeline); fall back to ASC (C2FSB pipeline)
    if os.path.exists(FBFM40_TIF):
        with rasterio.open(FBFM40_TIF) as src:
            return src.read(1).astype(np.int32)
    fuels = np.zeros((nrows, ncols), dtype=np.int32)
    with open(FUELS_ASC) as f:
        for _ in range(6):
            f.readline()
        for r in range(nrows):
            line = f.readline().split()
            fuels[r, :] = [int(v) for v in line]
    return fuels


def latlon_to_grid_cell(lat, lon, meta):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    x, y = transformer.transform(lon, lat)

    xll = meta["xllcorner"]
    yll = meta["yllcorner"]
    nrows = meta["nrows"]
    ncols = meta["ncols"]
    cellsize = meta["cellsize"]

    col = int((x - xll) / cellsize)
    row = int((yll + nrows * cellsize - y) / cellsize)

    return row, col, x, y


def find_burnable_cell(row, col, fuels, meta):
    nrows = meta["nrows"]
    ncols = meta["ncols"]

    if 0 <= row < nrows and 0 <= col < ncols:
        fuel = fuels[row, col]
        if fuel not in NON_BURNABLE_CODES and fuel != 0:
            return row, col, fuel

    print(f"  Cell ({row}, {col}) fuel={fuels[row, col] if 0 <= row < nrows and 0 <= col < ncols else 'OOB'} is non-burnable. Searching nearby cells...")

    for radius in range(1, 50):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if abs(dr) != radius and abs(dc) != radius:
                    continue
                r2, c2 = row + dr, col + dc
                if 0 <= r2 < nrows and 0 <= c2 < ncols:
                    fuel = fuels[r2, c2]
                    if fuel not in NON_BURNABLE_CODES and fuel != 0:
                        print(f"  Found burnable cell at ({r2}, {c2}), offset ({dr}, {dc}), fuel={fuel}")
                        return r2, c2, fuel

    raise ValueError("No burnable cell found near ignition point")


def patch_elmfire_data(x_5070, y_5070):
    """Update X_IGN/Y_IGN in elmfire.data with the resolved burnable-cell coordinates."""
    text = open(ELMFIRE_DATA).read()
    text = re.sub(r"X_IGN\(1\)\s*=\s*[\d\.\-]+", f"X_IGN(1)                       = {x_5070:.2f}", text)
    text = re.sub(r"Y_IGN\(1\)\s*=\s*[\d\.\-]+", f"Y_IGN(1)                       = {y_5070:.2f}", text)
    open(ELMFIRE_DATA, "w").write(text)
    print(f"  Patched elmfire.data: X_IGN={x_5070:.2f}, Y_IGN={y_5070:.2f}")


def main():
    lat = float(os.environ.get("IGNITION_LAT", DEFAULT_LAT))
    lon = float(os.environ.get("IGNITION_LON", DEFAULT_LON))

    source = "environment variable" if "IGNITION_LAT" in os.environ else "default"
    print(f"Ignition point ({source}): lat={lat}, lon={lon}")

    meta = load_grid_metadata()
    print(f"Grid: {meta['ncols']} cols x {meta['nrows']} rows, cellsize={meta['cellsize']}m, CRS=EPSG:5070")

    print("Loading fuels raster...")
    fuels = load_fuels(meta)

    row, col, x_5070, y_5070 = latlon_to_grid_cell(lat, lon, meta)
    print(f"Projected to EPSG:5070: x={x_5070:.2f}, y={y_5070:.2f}")
    print(f"Initial grid cell: row={row}, col={col}")

    nrows, ncols = meta["nrows"], meta["ncols"]
    if not (0 <= row < nrows and 0 <= col < ncols):
        print(f"  WARNING: Ignition ({lat}, {lon}) is outside grid bounds — falling back to grid center")
        row, col = nrows // 2, ncols // 2
        # Recompute x_5070/y_5070 from the clamped cell
        xll, yll, cellsize = meta["xllcorner"], meta["yllcorner"], meta["cellsize"]
        x_5070 = xll + (col + 0.5) * cellsize
        y_5070 = yll + (nrows - row - 0.5) * cellsize

    row, col, fuel_code = find_burnable_cell(row, col, fuels, meta)

    # Cell2Fire uses 1-based indexing, rows count from top
    cell_id = row * meta["ncols"] + col + 1

    print(f"Ignition cell: row={row}, col={col}, cell_id={cell_id}, fuel_code={fuel_code}")

    os.makedirs("/data/grid", exist_ok=True)

    with open(IGNITIONS_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Year", "Ncell"])
        writer.writerow([1, cell_id])

    ignition_meta = {
        "lat": lat,
        "lon": lon,
        "x_5070": round(x_5070, 2),
        "y_5070": round(y_5070, 2),
        "row": row,
        "col": col,
        "cell_id": cell_id,
        "fuel_code": int(fuel_code),
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(IGNITION_METADATA, "w") as f:
        json.dump(ignition_meta, f, indent=2)

    print(f"Wrote {IGNITIONS_CSV}")
    print(f"Wrote {IGNITION_METADATA}")

    # Patch elmfire.data with the resolved burnable-cell coordinates
    if os.path.exists(ELMFIRE_DATA):
        patch_elmfire_data(x_5070, y_5070)

    print(f"\nSummary: ignition at ({lat:.4f}, {lon:.4f}) → cell {cell_id} (row={row}, col={col}), fuel={fuel_code}")


if __name__ == "__main__":
    main()
