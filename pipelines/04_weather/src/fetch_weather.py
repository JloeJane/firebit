"""
Pipeline 04 — Weather
Fetches real NOAA HRRR analysis data for the target date via the herbie package.
Falls back to RAWS (IEM ASOS) if HRRR is unavailable.
"""

import json
import csv
import os
import sys
import math
import requests
from datetime import datetime, timezone
from io import StringIO

import numpy as np

OUT_DIR = "/data/weather"
AOI_META_PATH = "/data/input/aoi_metadata.json"
CACHE_DIR = "/data/weather/hrrr_cache"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# --- Config ---
WEATHER_DATE = os.environ.get("WEATHER_DATE", "").strip() or "2016-11-28 18:00"
date_part = datetime.strptime(WEATHER_DATE.split()[0], "%Y-%m-%d")

# --- AOI centroid ---
with open(AOI_META_PATH) as f:
    aoi = json.load(f)

bbox = aoi["bbox_4326"]
centroid_lat = aoi.get("centroid_lat_4326", (bbox["north"] + bbox["south"]) / 2)
centroid_lon = aoi.get("centroid_lon_4326", (bbox["east"] + bbox["west"]) / 2)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def uv_to_ws_wd(u, v):
    ws_ms = math.sqrt(u ** 2 + v ** 2)
    ws_kmh = ws_ms * 3.6
    wd_deg = (270 - math.degrees(math.atan2(v, u))) % 360
    return ws_kmh, wd_deg


def get_point_value(ds, lat, lon):
    """Extract value at the nearest grid point to (lat, lon) from an xarray Dataset."""
    # Find latitude and longitude coordinate arrays
    lat_arr = lon_arr = None
    for name, coord in ds.coords.items():
        nl = name.lower()
        if nl in ("latitude", "lat") and lat_arr is None:
            lat_arr = coord.values
        elif nl in ("longitude", "lon") and lon_arr is None:
            lon_arr = coord.values

    if lat_arr is None or lon_arr is None:
        raise ValueError(f"Could not find lat/lon coords in dataset; coords: {list(ds.coords)}")

    # Handle 0-360 longitude grids
    lon_query = lon
    if lon < 0 and float(np.nanmin(lon_arr)) >= 0:
        lon_query = lon + 360.0

    if lat_arr.ndim == 2:
        dist2 = (lat_arr - lat) ** 2 + (lon_arr - lon_query) ** 2
        iy, ix = np.unravel_index(int(np.argmin(dist2)), dist2.shape)
        for vname in ds.data_vars:
            vals = ds[vname].values
            # vals shape: (..., y, x)
            return float(vals.flat[iy * dist2.shape[1] + ix])
    else:
        ilat = int(np.argmin(np.abs(lat_arr - lat)))
        ilon = int(np.argmin(np.abs(lon_arr - lon_query)))
        for vname in ds.data_vars:
            da = ds[vname]
            # Try to select by coordinate name
            lat_dim = next((d for d in da.dims if "lat" in d.lower()), None)
            lon_dim = next((d for d in da.dims if "lon" in d.lower()), None)
            if lat_dim and lon_dim:
                return float(da.isel(**{lat_dim: ilat, lon_dim: ilon}).values.squeeze())
            return float(da.values.flat[ilat * len(lon_arr) + ilon])

    raise ValueError("Could not extract point value")


def fetch_hrrr():
    """Fetch 24 hourly HRRR analysis rows. Returns (rows, source_label) or None."""
    try:
        from herbie import Herbie
    except ImportError as e:
        print(f"herbie not available: {e}")
        return None

    rows_by_hour = {}
    failed_hours = []

    for hour in range(24):
        dt = date_part.replace(hour=hour)
        dt_str = dt.strftime("%Y-%m-%d %H:%M")
        try:
            H = Herbie(dt_str, model="hrrr", product="sfc", fxx=0,
                       save_dir=CACHE_DIR, verbose=False)

            ds_tmp = H.xarray("TMP:2 m")
            ds_rh = H.xarray("RH:2 m")
            ds_u = H.xarray("UGRD:10 m")
            ds_v = H.xarray("VGRD:10 m")

            tmp_k = get_point_value(ds_tmp, centroid_lat, centroid_lon)
            tmp_c = tmp_k - 273.15 if tmp_k > 200 else tmp_k
            rh = get_point_value(ds_rh, centroid_lat, centroid_lon)
            u = get_point_value(ds_u, centroid_lat, centroid_lon)
            v = get_point_value(ds_v, centroid_lat, centroid_lon)
            ws_kmh, wd_deg = uv_to_ws_wd(u, v)

            rows_by_hour[hour] = {
                "hour": hour,
                "datetime": dt,
                "WS": round(ws_kmh, 2),
                "WD": round(wd_deg, 1),
                "TMP": round(tmp_c, 2),
                "RH": round(rh, 1),
            }
            print(f"  Hour {hour:02d}: TMP={tmp_c:.1f}°C RH={rh:.0f}% WS={ws_kmh:.1f}km/h WD={wd_deg:.0f}°")

        except Exception as e:
            print(f"  Hour {hour:02d}: FAILED — {e}")
            failed_hours.append(hour)

    n_good = len(rows_by_hour)
    if n_good < 6:
        print(f"Only {n_good}/24 HRRR hours succeeded — falling through to RAWS")
        return None

    # Interpolate missing hours from neighbors
    if failed_hours:
        print(f"Interpolating {len(failed_hours)} missing hours: {failed_hours}")
        available = sorted(rows_by_hour)
        for h in failed_hours:
            before = next((x for x in reversed(available) if x < h), None)
            after = next((x for x in available if x > h), None)
            if before is not None and after is not None:
                b, a = rows_by_hour[before], rows_by_hour[after]
                frac = (h - before) / (after - before)
                rows_by_hour[h] = {
                    "hour": h,
                    "datetime": date_part.replace(hour=h),
                    "WS": round(b["WS"] + frac * (a["WS"] - b["WS"]), 2),
                    "WD": round(b["WD"] + frac * (a["WD"] - b["WD"]), 1),
                    "TMP": round(b["TMP"] + frac * (a["TMP"] - b["TMP"]), 2),
                    "RH": round(b["RH"] + frac * (a["RH"] - b["RH"]), 1),
                }
            elif before is not None:
                r = dict(rows_by_hour[before])
                r["hour"] = h
                r["datetime"] = date_part.replace(hour=h)
                rows_by_hour[h] = r
            elif after is not None:
                r = dict(rows_by_hour[after])
                r["hour"] = h
                r["datetime"] = date_part.replace(hour=h)
                rows_by_hour[h] = r

    rows = [rows_by_hour[h] for h in sorted(rows_by_hour)]
    source_label = f"NOAA HRRR analysis {date_part.strftime('%Y-%m-%d')} via herbie"
    return rows, source_label


def fetch_raws():
    """Fetch hourly obs from nearest IEM ASOS station. Returns (rows, station_id) or None."""
    print("Attempting RAWS/IEM ASOS fallback...")

    try:
        resp = requests.get(
            "https://mesonet.agron.iastate.edu/geojson/network.geojson?network=TN_ASOS",
            timeout=30,
        )
        resp.raise_for_status()
        network = resp.json()
    except Exception as e:
        print(f"Failed to fetch IEM station list: {e}")
        return None

    nearest_id = None
    nearest_dist = float("inf")
    for feat in network.get("features", []):
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        s_lon, s_lat = float(coords[0]), float(coords[1])
        dist = haversine_km(centroid_lat, centroid_lon, s_lat, s_lon)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_id = props.get("sid")

    if nearest_id is None or nearest_dist > 150:
        print(f"No ASOS station within 150km (nearest: {nearest_dist:.1f}km)")
        return None

    print(f"Using IEM station {nearest_id} ({nearest_dist:.1f}km from centroid)")

    yr = date_part.year
    mo = date_part.month
    dy = date_part.day
    url = (
        f"https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
        f"?station={nearest_id}&data=tmpf,relh,sknt,drct"
        f"&year1={yr}&month1={mo}&day1={dy}"
        f"&year2={yr}&month2={mo}&day2={dy}"
        f"&tz=UTC&format=onlycomma&latlon=yes&elev=yes"
    )
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        print(f"Failed to fetch IEM ASOS data: {e}")
        return None

    obs_by_hour = {}
    try:
        reader = csv.DictReader(StringIO(text))
        for row in reader:
            try:
                tmpf = float(row["tmpf"])
                relh = float(row["relh"])
                sknt = float(row["sknt"])
                drct = float(row["drct"])
                valid = datetime.strptime(row["valid"].strip(), "%Y-%m-%d %H:%M")
                tmp_c = (tmpf - 32) * 5 / 9
                ws_kmh = sknt * 1.852
                obs_by_hour[valid.hour] = {
                    "TMP": round(tmp_c, 2),
                    "RH": round(relh, 1),
                    "WS": round(ws_kmh, 2),
                    "WD": round(drct, 1),
                }
            except (ValueError, KeyError):
                continue
    except Exception as e:
        print(f"Failed to parse IEM ASOS response: {e}")
        return None

    if not obs_by_hour:
        print(f"No usable observations from station {nearest_id} for {date_part.strftime('%Y-%m-%d')}")
        sys.exit(1)

    available = sorted(obs_by_hour)
    rows = []
    for hour in range(24):
        if hour in obs_by_hour:
            o = obs_by_hour[hour]
            rows.append({"hour": hour, "datetime": date_part.replace(hour=hour), **o})
        else:
            before = next((x for x in reversed(available) if x < hour), None)
            after = next((x for x in available if x > hour), None)
            if before is not None and after is not None:
                b, a = obs_by_hour[before], obs_by_hour[after]
                frac = (hour - before) / (after - before)
                rows.append({
                    "hour": hour,
                    "datetime": date_part.replace(hour=hour),
                    "WS": round(b["WS"] + frac * (a["WS"] - b["WS"]), 2),
                    "WD": round(b["WD"] + frac * (a["WD"] - b["WD"]), 1),
                    "TMP": round(b["TMP"] + frac * (a["TMP"] - b["TMP"]), 2),
                    "RH": round(b["RH"] + frac * (a["RH"] - b["RH"]), 1),
                })
            elif before is not None:
                o = obs_by_hour[before]
                rows.append({"hour": hour, "datetime": date_part.replace(hour=hour), **o})
            elif after is not None:
                o = obs_by_hour[after]
                rows.append({"hour": hour, "datetime": date_part.replace(hour=hour), **o})

    return rows, nearest_id


# ── Main ────────────────────────────────────────────────────────────────────
print(f"Fetching weather for {date_part.strftime('%Y-%m-%d')} (WEATHER_DATE={WEATHER_DATE!r})")
print(f"AOI centroid: {centroid_lat:.4f}°N, {centroid_lon:.4f}°")

hrrr_result = fetch_hrrr()

if hrrr_result is not None:
    rows, source_str = hrrr_result
    source_type = "HRRR"
    station_id = None
else:
    raws_result = fetch_raws()
    if raws_result is None:
        print("ERROR: Both HRRR and RAWS IEM fetches failed.")
        sys.exit(1)
    rows, station_id = raws_result
    source_type = "RAWS_IEM"
    source_str = f"IEM ASOS {station_id} {date_part.strftime('%Y-%m-%d')}"

# Representative values: hour 18 if present, else first row
rep = next((r for r in rows if r["hour"] == 18), rows[0])

# ── Write weather_scenario.json ─────────────────────────────────────────────
scenario = {
    "wind_speed_kmh": rep["WS"],
    "wind_direction_deg": rep["WD"],
    "temperature_c": rep["TMP"],
    "relative_humidity_pct": rep["RH"],
    "source": source_str,
}
scenario_path = os.path.join(OUT_DIR, "weather_scenario.json")
with open(scenario_path, "w") as f:
    json.dump(scenario, f, indent=2)
print(f"Wrote {scenario_path}")

# ── Write Weather.csv ────────────────────────────────────────────────────────
csv_path = os.path.join(OUT_DIR, "Weather.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["Instance", "datetime", "WS", "WD", "TMP", "RH"])
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "Instance": 1,
            "datetime": r["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
            "WS": r["WS"],
            "WD": r["WD"],
            "TMP": r["TMP"],
            "RH": r["RH"],
        })
print(f"Wrote {csv_path} ({len(rows)} hourly rows)")

# ── Write weather_metadata.json ──────────────────────────────────────────────
metadata = {
    "pipeline": "04_weather",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "output_files": {
        "weather_scenario_json": scenario_path,
        "weather_csv": csv_path,
    },
    "source": source_type,
    "weather_date": WEATHER_DATE,
}
if station_id:
    metadata["station_id"] = station_id

meta_path = os.path.join(OUT_DIR, "weather_metadata.json")
with open(meta_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Wrote {meta_path}")

print(
    f"\nWeather summary ({source_type}): "
    f"{rep['WS']:.1f} km/h from {rep['WD']:.0f}°, "
    f"{rep['TMP']:.1f}°C, {rep['RH']:.0f}% RH"
)
