"""
Pipeline 07 — Grid Assembly
Merges all upstream pipeline outputs into Cell2Fire-compatible input files.

Validates raster alignment, maps FBFM40 fuel codes to Cell2Fire sequential codes,
writes ASC grids, copies weather, and formats fuel moisture content.
"""

import csv
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone

import numpy as np
import rasterio

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FUEL_TIF = "/data/fuel/fuel_clipped.tif"
ELEV_TIF = "/data/topography/elevation.tif"
SLOPE_TIF = "/data/topography/slope.tif"
ASPECT_TIF = "/data/topography/aspect.tif"
WEATHER_CSV_SRC = "/data/weather/Weather.csv"
MOISTURE_JSON = "/data/moisture/fuel_moisture.json"

OUT_DIR = "/data/grid"
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Scott & Burgan 40 fuel model lookup: FBFM40 code → (name, Cell2Fire code)
# Non-burnable codes map to Cell2Fire code 0.
# Burnable codes map to sequential 1-40 following Scott & Burgan ordering.
# ---------------------------------------------------------------------------
FUEL_LOOKUP = {
    # Non-burnable
    91:  ("NB1_Urban_Developed",  0),
    92:  ("NB2_Snow_Ice",         0),
    93:  ("NB3_Agriculture",      0),
    98:  ("NB8_Water",            0),
    99:  ("NB9_Barren_Sparse",    0),
    # GR — Grass models (9)
    101: ("GR1", 1),
    102: ("GR2", 2),
    103: ("GR3", 3),
    104: ("GR4", 4),
    105: ("GR5", 5),
    106: ("GR6", 6),
    107: ("GR7", 7),
    108: ("GR8", 8),
    109: ("GR9", 9),
    # GS — Grass-Shrub models (4)
    121: ("GS1", 10),
    122: ("GS2", 11),
    123: ("GS3", 12),
    124: ("GS4", 13),
    # SH — Shrub models (9)
    141: ("SH1", 14),
    142: ("SH2", 15),
    143: ("SH3", 16),
    144: ("SH4", 17),
    145: ("SH5", 18),
    146: ("SH6", 19),
    147: ("SH7", 20),
    148: ("SH8", 21),
    149: ("SH9", 22),
    # TU — Timber Understory models (5)
    161: ("TU1", 23),
    162: ("TU2", 24),
    163: ("TU3", 25),
    164: ("TU4", 26),
    165: ("TU5", 27),
    # TL — Timber Litter models (9)
    181: ("TL1", 28),
    182: ("TL2", 29),
    183: ("TL3", 30),
    184: ("TL4", 31),
    185: ("TL5", 32),
    186: ("TL6", 33),
    187: ("TL7", 34),
    188: ("TL8", 35),
    189: ("TL9", 36),
    # SB — Slash-Blowdown models (4)
    201: ("SB1", 37),
    202: ("SB2", 38),
    203: ("SB3", 39),
    204: ("SB4", 40),
}


def open_raster(path):
    if not os.path.exists(path):
        print(f"ERROR: Missing required input file: {path}", file=sys.stderr)
        sys.exit(1)
    return rasterio.open(path)


# ---------------------------------------------------------------------------
# Step A — Load and validate alignment
# ---------------------------------------------------------------------------
print("=== Step A: Validating raster alignment ===")

layers = {
    "fuel":    FUEL_TIF,
    "elevation": ELEV_TIF,
    "slope":   SLOPE_TIF,
    "aspect":  ASPECT_TIF,
}

rasters = {}
for name, path in layers.items():
    rasters[name] = open_raster(path)

ref_name = "fuel"
ref = rasters[ref_name]
ref_crs = ref.crs
ref_shape = (ref.height, ref.width)
ref_transform = ref.transform

errors = []
for name, src in rasters.items():
    if name == ref_name:
        continue
    if src.crs != ref_crs:
        errors.append(
            f"  CRS mismatch — {name}: {src.crs} vs {ref_name}: {ref_crs}"
        )
    if (src.height, src.width) != ref_shape:
        errors.append(
            f"  Dimension mismatch — {name}: {src.height}x{src.width} "
            f"vs {ref_name}: {ref_shape[0]}x{ref_shape[1]}"
        )
    if not math.isclose(src.transform.c, ref_transform.c, abs_tol=0.01):
        errors.append(
            f"  X-origin mismatch — {name}: {src.transform.c:.4f} "
            f"vs {ref_name}: {ref_transform.c:.4f}"
        )
    if not math.isclose(src.transform.f, ref_transform.f, abs_tol=0.01):
        errors.append(
            f"  Y-origin mismatch — {name}: {src.transform.f:.4f} "
            f"vs {ref_name}: {ref_transform.f:.4f}"
        )

if errors:
    print("ERROR: Raster alignment validation FAILED:", file=sys.stderr)
    for e in errors:
        print(e, file=sys.stderr)
    for src in rasters.values():
        src.close()
    sys.exit(1)

nrows = ref.height
ncols = ref.width
# cellsize: use abs of x pixel size (should be 30m)
cellsize = abs(ref_transform.a)
# ASC lower-left corner: xllcorner = upper-left x, yllcorner = upper-left y + nrows * (negative y pixel)
xllcorner = ref_transform.c
yllcorner = ref_transform.f + nrows * ref_transform.e  # e is negative

print(f"  OK — all rasters aligned: {nrows} rows × {ncols} cols, "
      f"cellsize={cellsize:.1f}m, CRS={ref_crs}")
print(f"  Origin (upper-left): ({ref_transform.c:.2f}, {ref_transform.f:.2f})")
print(f"  Lower-left corner: ({xllcorner:.2f}, {yllcorner:.2f})")


# ---------------------------------------------------------------------------
# Step B — Write fuel_lookup.csv and convert fuel raster
# ---------------------------------------------------------------------------
print("\n=== Step B: Writing fuel lookup and fuels.asc ===")

lookup_path = os.path.join(OUT_DIR, "fuel_lookup.csv")
with open(lookup_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["fbfm_code", "fuel_name", "cell2fire_code"])
    for fbfm_code, (fuel_name, c2f_code) in sorted(FUEL_LOOKUP.items()):
        writer.writerow([fbfm_code, fuel_name, c2f_code])
print(f"  Wrote {lookup_path} ({len(FUEL_LOOKUP)} entries)")

fuel_data = rasters["fuel"].read(1).astype(np.int32)
nodata_val = rasters["fuel"].nodata

# Build vectorized mapping: unknown codes → 0 (treat as non-burnable)
mapped = np.zeros_like(fuel_data, dtype=np.int32)
unique_codes = np.unique(fuel_data)
unmapped_codes = []
for code in unique_codes:
    if nodata_val is not None and code == int(nodata_val):
        mapped[fuel_data == code] = -9999
    elif code in FUEL_LOOKUP:
        mapped[fuel_data == code] = FUEL_LOOKUP[code][1]
    else:
        unmapped_codes.append(int(code))
        mapped[fuel_data == code] = 0  # unknown → non-burnable

if unmapped_codes:
    print(f"  WARNING: {len(unmapped_codes)} fuel codes not in lookup, treated as non-burnable: {unmapped_codes}")

total_cells = nrows * ncols
nodata_cells = int(np.sum(mapped == -9999))
non_burnable_cells = int(np.sum((mapped == 0) & (fuel_data != (int(nodata_val) if nodata_val is not None else -1))))
burnable_cells = total_cells - nodata_cells - non_burnable_cells

# Write fuels.asc
fuels_asc_path = os.path.join(OUT_DIR, "fuels.asc")
with open(fuels_asc_path, "w") as f:
    f.write(f"ncols {ncols}\n")
    f.write(f"nrows {nrows}\n")
    f.write(f"xllcorner {xllcorner:.6f}\n")
    f.write(f"yllcorner {yllcorner:.6f}\n")
    f.write(f"cellsize {int(cellsize)}\n")
    f.write(f"NODATA_value -9999\n")
    for row in mapped:
        f.write(" ".join(str(v) for v in row) + "\n")
print(f"  Wrote {fuels_asc_path}")

# Fuel distribution after mapping
mapped_codes, mapped_counts = np.unique(mapped[mapped >= 0], return_counts=True)
print(f"  Fuel distribution (Cell2Fire codes):")
for code, count in zip(mapped_codes, mapped_counts):
    pct = 100.0 * count / total_cells
    label = "non-burnable" if code == 0 else f"burnable (C2F code {code})"
    print(f"    Code {code:3d}: {count:7d} cells ({pct:.1f}%) — {label}")


# ---------------------------------------------------------------------------
# Step C — Write elevation.asc
# ---------------------------------------------------------------------------
print("\n=== Step C: Writing elevation.asc ===")

elev_data = rasters["elevation"].read(1)
elev_nodata = rasters["elevation"].nodata
elev_out = np.where(
    (elev_nodata is not None) & (elev_data == elev_nodata),
    -9999,
    np.round(elev_data, 1)
)

elev_asc_path = os.path.join(OUT_DIR, "elevation.asc")
with open(elev_asc_path, "w") as f:
    f.write(f"ncols {ncols}\n")
    f.write(f"nrows {nrows}\n")
    f.write(f"xllcorner {xllcorner:.6f}\n")
    f.write(f"yllcorner {yllcorner:.6f}\n")
    f.write(f"cellsize {int(cellsize)}\n")
    f.write(f"NODATA_value -9999\n")
    for row in elev_out:
        f.write(" ".join(f"{v:.1f}" for v in row) + "\n")
print(f"  Wrote {elev_asc_path}")


# ---------------------------------------------------------------------------
# Step D — Copy Weather.csv
# ---------------------------------------------------------------------------
print("\n=== Step D: Copying Weather.csv ===")

if not os.path.exists(WEATHER_CSV_SRC):
    print(f"ERROR: Missing weather file: {WEATHER_CSV_SRC}", file=sys.stderr)
    sys.exit(1)

weather_dst = os.path.join(OUT_DIR, "Weather.csv")
shutil.copy2(WEATHER_CSV_SRC, weather_dst)
with open(weather_dst) as f:
    weather_rows = sum(1 for _ in f) - 1  # subtract header
print(f"  Copied {weather_dst} ({weather_rows} hourly rows)")


# ---------------------------------------------------------------------------
# Step E — Write fuel moisture CSV for Cell2Fire
# ---------------------------------------------------------------------------
print("\n=== Step E: Writing FuelMoistureContent.csv ===")

if not os.path.exists(MOISTURE_JSON):
    print(f"ERROR: Missing moisture file: {MOISTURE_JSON}", file=sys.stderr)
    sys.exit(1)

with open(MOISTURE_JSON) as f:
    moisture = json.load(f)

m1   = moisture["dead_1hr_pct"]
m10  = moisture["dead_10hr_pct"]
m100 = moisture["dead_100hr_pct"]
mherb = moisture["live_herb_pct"]
mwood = moisture["live_woody_pct"]

# Cell2Fire US fuel model FuelMoistureContent.csv: one row per fuel type (1-40)
# Columns: ID, m1, m10, m100, mherb, mwood (values in percent)
fmc_path = os.path.join(OUT_DIR, "FuelMoistureContent.csv")
with open(fmc_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "m1", "m10", "m100", "mherb", "mwood"])
    for fuel_id in range(1, 41):
        writer.writerow([fuel_id, m1, m10, m100, mherb, mwood])
print(f"  Wrote {fmc_path} (40 fuel types, uniform moisture)")
print(f"  Moisture: 1hr={m1}%  10hr={m10}%  100hr={m100}%  herb={mherb}%  woody={mwood}%")


# ---------------------------------------------------------------------------
# Step F — Write grid_metadata.json
# ---------------------------------------------------------------------------
print("\n=== Step F: Writing grid_metadata.json ===")

metadata = {
    "ncols": ncols,
    "nrows": nrows,
    "cellsize": int(cellsize),
    "xllcorner": round(xllcorner, 6),
    "yllcorner": round(yllcorner, 6),
    "xurcorner": round(xllcorner + ncols * cellsize, 6),
    "yurcorner": round(yllcorner + nrows * cellsize, 6),
    "crs": str(ref_crs),
    "total_cells": total_cells,
    "burnable_cells": burnable_cells,
    "non_burnable_cells": non_burnable_cells,
    "nodata_cells": nodata_cells,
    "burnable_pct": round(100.0 * burnable_cells / total_cells, 2),
    "fuel_codes_present": sorted(int(c) for c in unique_codes
                                  if nodata_val is None or c != int(nodata_val)),
    "fuel_codes_mapped": True,
    "alignment_validated": True,
    "outputs": {
        "fuels_asc": fuels_asc_path,
        "elevation_asc": elev_asc_path,
        "weather_csv": weather_dst,
        "fuel_moisture_csv": fmc_path,
        "fuel_lookup_csv": lookup_path,
    },
    "generated_at": datetime.now(timezone.utc).isoformat(),
}

meta_path = os.path.join(OUT_DIR, "grid_metadata.json")
with open(meta_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"  Wrote {meta_path}")

# ---------------------------------------------------------------------------
# Close rasters and print summary
# ---------------------------------------------------------------------------
for src in rasters.values():
    src.close()

print("\n" + "=" * 60)
print("GRID ASSEMBLY COMPLETE")
print("=" * 60)
print(f"  Grid: {nrows} rows × {ncols} cols ({total_cells:,} total cells)")
print(f"  CRS: {ref_crs}  |  Cellsize: {cellsize:.0f}m")
print(f"  Burnable:     {burnable_cells:7,} cells ({metadata['burnable_pct']:.1f}%)")
print(f"  Non-burnable: {non_burnable_cells:7,} cells ({100-metadata['burnable_pct']:.1f}%)")
print(f"  NODATA:       {nodata_cells:7,} cells")
print(f"\nOutputs in {OUT_DIR}/:")
for key, path in metadata["outputs"].items():
    print(f"  {os.path.basename(path)}")
