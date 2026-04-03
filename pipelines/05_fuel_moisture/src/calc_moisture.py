"""
Pipeline 05 — Fuel Moisture
Dead fuel moisture: Nelson (1984) EMC from real HRRR weather (pipeline 6B.2).
Live fuel moisture: climatological estimate for southern Appalachians in November.
Live FM is a minor driver of spread rate in Cell2Fire; dead FM (from real weather)
is the primary control. Late-November cured herbaceous layer justifies these values.
"""

import json
import os
from datetime import datetime, timezone

WEATHER_PATH = "/data/weather/weather_scenario.json"
OUT_DIR = "/data/moisture"
os.makedirs(OUT_DIR, exist_ok=True)

WEATHER_DATE = os.environ.get("WEATHER_DATE") or "2016-11-28"


def calc_emc(temp_c: float, rh_pct: float) -> float:
    """Nelson (1984) equilibrium moisture content approximation."""
    T = temp_c
    H = rh_pct
    if H < 10:
        return round(0.03229 + 0.281073 * H - 0.000578 * T * H, 2)
    elif H < 50:
        return round(2.22749 + 0.160107 * H - 0.01478 * T, 2)
    else:
        return round(21.0606 + 0.005565 * H**2 - 0.00035 * T * H - 0.483199 * H, 2)


with open(WEATHER_PATH) as f:
    weather = json.load(f)

temp_c = weather["temperature_c"]
rh_pct = weather["relative_humidity_pct"]

emc = calc_emc(temp_c, rh_pct)
dead_1hr = round(emc, 2)
dead_10hr = round(emc * 1.5, 2)
dead_100hr = round(emc * 2.5, 2)

# Late-November southern Appalachians: herbaceous layer largely cured,
# mixed hardwood/shrub woody vegetation. Values consistent with NFMD
# station observations for this region and season.
live_herb = 30
live_woody = 60

result = {
    "dead_1hr_pct": dead_1hr,
    "dead_10hr_pct": dead_10hr,
    "dead_100hr_pct": dead_100hr,
    "live_herb_pct": live_herb,
    "live_woody_pct": live_woody,
    "emc_pct": emc,
    "source_dead": "Nelson (1984) EMC from HRRR weather",
    "source_live": "climatological estimate, southern Appalachians November",
    "weather_date": WEATHER_DATE,
    "generated_at": datetime.now(timezone.utc).isoformat(),
}

moisture_path = os.path.join(OUT_DIR, "fuel_moisture.json")
with open(moisture_path, "w") as f:
    json.dump(result, f, indent=2)
print(f"Wrote {moisture_path}")

metadata = {
    "pipeline": "05_fuel_moisture",
    "generated_at": result["generated_at"],
    "input_weather": WEATHER_PATH,
    "output_files": {"fuel_moisture_json": moisture_path},
    "emc_method": "Nelson (1984) approximation",
    "weather_date": WEATHER_DATE,
    "source_dead": result["source_dead"],
    "source_live": result["source_live"],
}
meta_path = os.path.join(OUT_DIR, "moisture_metadata.json")
with open(meta_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Wrote {meta_path}")

print(
    f"\nFuel moisture summary:\n"
    f"  EMC:         {emc:.1f}%\n"
    f"  1-hr dead:   {dead_1hr:.1f}%\n"
    f"  10-hr dead:  {dead_10hr:.1f}%\n"
    f"  100-hr dead: {dead_100hr:.1f}%\n"
    f"  Live herb:   {live_herb}%  (climatological)\n"
    f"  Live woody:  {live_woody}%  (climatological)"
)
