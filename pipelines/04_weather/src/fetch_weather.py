"""
Pipeline 04 — Weather
Generates a synthetic fire weather scenario based on Nov 28, 2016 Gatlinburg conditions
and writes outputs for Cell2Fire consumption.

SYNTHETIC DATA — replace with real RAWS/HRRR integration post-MVP.
See IMPLEMENTATION_PLAN.md Step 4 dev notes for guidance.
"""

import json
import csv
import os
from datetime import datetime, timedelta, timezone

OUT_DIR = "/data/weather"
os.makedirs(OUT_DIR, exist_ok=True)

# --- Scenario definition ---
SCENARIO = {
    "wind_speed_kmh": 30,
    "wind_direction_deg": 200,
    "temperature_c": 21,
    "relative_humidity_pct": 18,
    "scenario_name": "hot_dry_southwest_wind",
    "source": "SYNTHETIC — based on Nov 28 2016 Gatlinburg conditions",
    "notes": (
        "REPLACE WITH REAL WEATHER DATA POST-MVP. "
        "See IMPLEMENTATION_PLAN.md Step 4 dev notes for RAWS/HRRR integration guidance."
    ),
}

# --- Write weather_scenario.json ---
scenario_path = os.path.join(OUT_DIR, "weather_scenario.json")
with open(scenario_path, "w") as f:
    json.dump(SCENARIO, f, indent=2)
print(f"Wrote {scenario_path}")

# --- Write Cell2Fire-compatible Weather.csv (24 hourly rows) ---
csv_path = os.path.join(OUT_DIR, "Weather.csv")
base_dt = datetime(2026, 1, 1, 0, 0, 0)
rows = []
for hour in range(24):
    dt = base_dt + timedelta(hours=hour)
    rows.append({
        "Instance": 1,
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "WS": SCENARIO["wind_speed_kmh"],
        "WD": SCENARIO["wind_direction_deg"],
        "TMP": SCENARIO["temperature_c"],
        "RH": SCENARIO["relative_humidity_pct"],
    })

with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["Instance", "datetime", "WS", "WD", "TMP", "RH"])
    writer.writeheader()
    writer.writerows(rows)
print(f"Wrote {csv_path} ({len(rows)} hourly rows)")

# --- Write metadata ---
metadata = {
    "pipeline": "04_weather",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "output_files": {
        "weather_scenario_json": scenario_path,
        "weather_csv": csv_path,
    },
    "scenario": SCENARIO["scenario_name"],
    "data_type": "SYNTHETIC",
    "warning": "NOT REAL WEATHER DATA — for MVP only",
}
meta_path = os.path.join(OUT_DIR, "weather_metadata.json")
with open(meta_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Wrote {meta_path}")

print(
    f"\nWeather summary: {SCENARIO['wind_speed_kmh']} km/h from {SCENARIO['wind_direction_deg']}°, "
    f"{SCENARIO['temperature_c']}°C, {SCENARIO['relative_humidity_pct']}% RH"
)
print("WARNING: SYNTHETIC DATA — replace with RAWS/HRRR post-MVP")
