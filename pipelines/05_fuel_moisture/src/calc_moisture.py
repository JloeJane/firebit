"""
Pipeline 05 — Fuel Moisture
Calculates equilibrium moisture content (EMC) from synthetic weather data
and derives dead/live fuel moisture values for Cell2Fire input.

Dead fuel moisture is derived from EMC using standard time-lag scaling.
Live fuel moisture is hardcoded for late-fall conditions in the Smokies.
"""

import json
import os
from datetime import datetime, timezone

WEATHER_PATH = "/data/weather/weather_scenario.json"
OUT_DIR = "/data/moisture"
os.makedirs(OUT_DIR, exist_ok=True)


def calc_emc(temp_c: float, rh_pct: float) -> float:
    """
    Nelson (1984) equilibrium moisture content approximation.
    T in Celsius, RH in percent. Returns EMC as percent.
    """
    T = temp_c
    H = rh_pct
    if H < 10:
        emc = 0.03229 + 0.281073 * H - 0.000578 * T * H
    elif H < 50:
        emc = 2.22749 + 0.160107 * H - 0.01478 * T
    else:
        emc = 21.0606 + 0.005565 * H**2 - 0.00035 * T * H - 0.483199 * H
    return round(emc, 2)


# --- Load weather ---
with open(WEATHER_PATH) as f:
    weather = json.load(f)

temp_c = weather["temperature_c"]
rh_pct = weather["relative_humidity_pct"]

emc = calc_emc(temp_c, rh_pct)

dead_1hr = round(emc, 2)
dead_10hr = round(emc * 1.5, 2)
dead_100hr = round(emc * 2.5, 2)
live_herb = 30
live_woody = 60

result = {
    "dead_1hr_pct": dead_1hr,
    "dead_10hr_pct": dead_10hr,
    "dead_100hr_pct": dead_100hr,
    "live_herb_pct": live_herb,
    "live_woody_pct": live_woody,
    "emc_pct": emc,
    "source": "derived_from_synthetic_weather",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "notes": (
        "Dead fuel moisture derived from EMC (Nelson 1984). "
        "Live fuel moisture hardcoded for late-fall cured conditions in southern Appalachians. "
        "REPLACE WITH MEASURED/MODELED VALUES POST-MVP."
    ),
}

# --- Write fuel_moisture.json ---
moisture_path = os.path.join(OUT_DIR, "fuel_moisture.json")
with open(moisture_path, "w") as f:
    json.dump(result, f, indent=2)
print(f"Wrote {moisture_path}")

# --- Write metadata ---
metadata = {
    "pipeline": "05_fuel_moisture",
    "generated_at": result["generated_at"],
    "input_weather": WEATHER_PATH,
    "output_files": {"fuel_moisture_json": moisture_path},
    "emc_method": "Nelson (1984) approximation",
    "data_type": "DERIVED_FROM_SYNTHETIC",
    "warning": "NOT REAL FUEL MOISTURE DATA — for MVP only",
}
meta_path = os.path.join(OUT_DIR, "moisture_metadata.json")
with open(meta_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Wrote {meta_path}")

print(
    f"\nFuel moisture summary:\n"
    f"  EMC:       {emc:.1f}%\n"
    f"  1-hr dead: {dead_1hr:.1f}%\n"
    f"  10-hr dead:{dead_10hr:.1f}%\n"
    f"  100-hr dead:{dead_100hr:.1f}%\n"
    f"  Live herb: {live_herb}%  (cured, late fall)\n"
    f"  Live woody:{live_woody}%"
)
print("WARNING: DERIVED FROM SYNTHETIC WEATHER — replace post-MVP")
