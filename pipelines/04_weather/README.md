# Pipeline 04 — Weather

Generates a synthetic 24-hour fire weather scenario modelled on November 28, 2016 Gatlinburg conditions (30 km/h SW wind, 21°C, 18% RH) and writes it as a Cell2Fire-compatible Weather.csv.

## Inputs

| File | Description |
|------|-------------|
| none | All values are hardcoded |

## Outputs

| File | Description |
|------|-------------|
| `data/weather/weather_scenario.json` | Named scenario with wind speed, direction, temperature, and RH values |
| `data/weather/Weather.csv` | Cell2Fire-compatible hourly weather (24 rows, constant conditions) |
| `data/weather/weather_metadata.json` | Pipeline run metadata |

## Docker image

`wildfire-04_weather`

## Run standalone

```bash
docker build -t wildfire-04_weather pipelines/04_weather
docker run --rm --env-file .env -v $(pwd)/data:/data wildfire-04_weather
```

## Dependencies

Python: `json`, `csv` (stdlib only)
System: none beyond python:3.12-slim

## Known limitations

- Fully synthetic — no real weather observations are fetched
- Replace with RAWS station data or HRRR model output before any operational use
