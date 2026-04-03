.PHONY: all clean test build run-01 run-02 run-03 run-04 run-05 run-06 run-07 run-08 run-09 run-10 ui ui-dev

DOCKER_RUN = docker run --rm --env-file .env -v $(PWD)/data:/data

all: run-01 run-03 run-02 run-04 run-05 run-06 run-07 run-08 run-09 run-10
	@echo "=== Full pipeline complete ==="

build-%:
	docker build -t wildfire-$* pipelines/$*

run-01: build-01_shapefile_ingestion
	@echo "=== Step 1: Shapefile Ingestion ==="
	$(DOCKER_RUN) wildfire-01_shapefile_ingestion

run-02: build-02_fuel
	@echo "=== Step 2: Fuel Pipeline ==="
	$(DOCKER_RUN) wildfire-02_fuel

run-03: build-03_topography
	@echo "=== Step 3: Topography Pipeline ==="
	$(DOCKER_RUN) wildfire-03_topography

run-04: build-04_weather
	@echo "=== Step 4: Weather Pipeline ==="
	$(DOCKER_RUN) wildfire-04_weather

run-05: build-05_fuel_moisture
	@echo "=== Step 5: Fuel Moisture Pipeline ==="
	$(DOCKER_RUN) wildfire-05_fuel_moisture

run-06: build-06_assets
	@echo "=== Step 6: Assets Pipeline ==="
	$(DOCKER_RUN) wildfire-06_assets

run-07: build-07_grid_assembly
	@echo "=== Step 7: Grid Assembly ==="
	$(DOCKER_RUN) wildfire-07_grid_assembly

run-08: build-08_ignition
	@echo "=== Step 8: Ignition ==="
	$(DOCKER_RUN) wildfire-08_ignition

run-09: build-09_cell2fire
	@echo "=== Step 9: Cell2Fire Simulation ==="
	$(DOCKER_RUN) wildfire-09_cell2fire

run-10: build-10_consequence
	@echo "=== Step 10: Consequence Analysis ==="
	$(DOCKER_RUN) wildfire-10_consequence

# Port 8000 may be occupied; UI binds to 8001 on the host
ui: build-11_web_ui
	@echo "=== Launching Web UI on http://localhost:8001 ==="
	docker run --rm --env-file .env \
	  -v $(PWD)/data:/data \
	  -v /var/run/docker.sock:/var/run/docker.sock \
	  -e HOST_DATA_DIR=$(PWD)/data \
	  -p 8001:8000 wildfire-11_web_ui

# Dev mode: src/ and templates/ are live-mounted; uvicorn --reload picks up changes instantly
ui-dev: build-11_web_ui
	@echo "=== Launching Web UI (dev/reload) on http://localhost:8001 ==="
	docker run --rm --name ui-dev --env-file .env \
	  -v $(PWD)/data:/data \
	  -v /var/run/docker.sock:/var/run/docker.sock \
	  -e HOST_DATA_DIR=$(PWD)/data \
	  -v $(PWD)/pipelines/11_web_ui/src:/app/src \
	  -v $(PWD)/pipelines/11_web_ui/templates:/app/templates \
	  -p 8001:8000 \
	  wildfire-11_web_ui \
	  uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

clean:
	rm -rf data/input/aoi_metadata.json data/input/aoi_reprojected.*
	rm -rf data/fuel/* data/topography/* data/weather/* data/moisture/*
	rm -rf data/assets/* data/grid/* data/consequence/* data/output/*
	docker run --rm -v $(PWD)/data:/data alpine sh -c "rm -rf /data/simulation/*"

# ── Validation test suite ────────────────────────────────────────────────────
test:
	@echo "=== Wildfire Platform — Validation Tests ==="
	@PASS=0; FAIL=0; \
	check() { \
	  if eval "$$1" >/dev/null 2>&1; then \
	    echo "PASS: $$2"; PASS=$$((PASS+1)); \
	  else \
	    echo "FAIL: $$2"; FAIL=$$((FAIL+1)); \
	  fi; \
	}; \
	\
	echo "--- Pipeline outputs ---"; \
	check "test -f data/input/aoi_metadata.json"           "01 aoi_metadata.json"; \
	check "test -f data/input/aoi_reprojected.shp"         "01 aoi_reprojected.shp"; \
	check "test -f data/fuel/fuel_clipped.tif"             "02 fuel_clipped.tif"; \
	check "test -f data/topography/elevation.tif"          "03 elevation.tif"; \
	check "test -f data/topography/slope.tif"              "03 slope.tif"; \
	check "test -f data/weather/Weather.csv"               "04 Weather.csv"; \
	check "test -f data/moisture/fuel_moisture.json"       "05 fuel_moisture.json"; \
	check "test -f data/assets/buildings.geojson"          "06 buildings.geojson"; \
	check "test -f data/assets/assets_metadata.json"       "06 assets_metadata.json"; \
	check "test -f data/grid/fuels.asc"                    "07 fuels.asc"; \
	check "test -f data/grid/grid_metadata.json"           "07 grid_metadata.json"; \
	check "test -f data/grid/Weather.csv"                  "07 grid Weather.csv"; \
	check "test -f data/grid/Ignitions.csv"                "08 Ignitions.csv"; \
	check "test -f data/grid/ignition_metadata.json"       "08 ignition_metadata.json"; \
	check "test -f data/simulation/fire_perimeter_final.geojson" "09 fire_perimeter_final.geojson"; \
	check "test -f data/simulation/summary.json"           "09 summary.json"; \
	check "test -f data/simulation/burn_scar.tif"          "09 burn_scar.tif"; \
	check "test -f data/consequence/consequence_summary.json"    "10 consequence_summary.json"; \
	check "test -f data/consequence/exposed_buildings.geojson"   "10 exposed_buildings.geojson"; \
	check "test -f data/output/consequence_summary.json"   "10 output copy"; \
	\
	echo ""; \
	echo "--- Integration checks ---"; \
	check "python3 -c \"\
import json; \
sim=json.load(open('data/simulation/summary.json')); \
assert sim['total_cells_burned'] > 0; \
\"" "09 cells burned > 0"; \
	check "python3 -c \"\
import json; \
con=json.load(open('data/consequence/consequence_summary.json')); \
assert con['total_area_burned_ha'] > 10; \
assert con['total_area_burned_ha'] < 15000; \
\"" "10 area burned in sane range"; \
	check "python3 -c \"\
import csv; \
rows=list(csv.DictReader(open('data/grid/Ignitions.csv'))); \
assert len(rows)==1; \
assert int(rows[0]['Ncell']) > 0; \
\"" "08 Ignitions.csv has 1 valid cell"; \
	\
	echo ""; \
	echo "--- Results ---"; \
	python3 -c "\
import json; \
sim=json.load(open('data/simulation/summary.json')); \
con=json.load(open('data/consequence/consequence_summary.json')); \
print(f'  Area burned:        {con[\"total_area_burned_ha\"]:.0f} ha ({con[\"total_area_burned_acres\"]:.0f} acres)'); \
print(f'  Structures exposed: {con[\"structures_exposed\"]}'); \
print(f'  Population at risk: {con[\"estimated_population_at_risk\"]}'); \
print(f'  Cells burned:       {sim[\"total_cells_burned\"]:,} / {sim[\"nrows\"]*sim[\"ncols\"]:,}'); \
" 2>/dev/null || true; \
	echo ""; \
	echo "=== $$PASS passed, $$FAIL failed ==="
