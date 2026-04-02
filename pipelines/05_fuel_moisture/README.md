# Pipeline 05 — Fuel Moisture

Estimates dead fuel moisture from the synthetic weather scenario using the Nelson equilibrium moisture content (EMC) model; sets live fuel moisture to hardcoded late-fall southern Appalachian values.

## Inputs

| File | Description |
|------|-------------|
| `data/weather/weather_scenario.json` | Temperature and RH from pipeline 04 |

## Outputs

| File | Description |
|------|-------------|
| `data/moisture/fuel_moisture.json` | Dead (1-hr, 10-hr, 100-hr) and live (herbaceous, woody) moisture percentages |
| `data/moisture/moisture_metadata.json` | Pipeline run metadata |

## Docker image

`wildfire-05_fuel_moisture`

## Run standalone

```bash
docker build -t wildfire-05_fuel_moisture pipelines/05_fuel_moisture
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-05_fuel_moisture
```

## Dependencies

Python: `json`, `math` (stdlib only)
System: none beyond python:3.12-slim

## Known limitations

- All moisture values are derived from synthetic weather — not real observed moisture
- Live fuel moisture (30% herbaceous, 60% woody) is hardcoded for late-fall post-senescence conditions and is not dynamically computed
