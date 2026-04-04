# Architecture Decision Record: ELMFIRE as Primary Simulation Engine

**Status:** Accepted  
**Date:** April 2026  
**Branch:** `elmfire_main` (branched from `main`)

---

## Context

The wildfire modeling platform MVP was built using C2FSB (Cell2Fire + Scott & Burgan) as the fire spread simulation engine. C2FSB is a cellular automata model that simulates surface fire spread using Rothermel's semi-empirical equations. It is fast, open source, and works well for grass and shrub-dominated landscapes.

However, the platform's primary target geography — the Great Smoky Mountains and southern Appalachian forests — is dominated by dense hardwood and pine canopy on steep, complex terrain. The 2016 Chimney Tops 2 / Gatlinburg wildfire demonstrated that crown fire runs and long-distance ember transport (spotting) are critical fire behavior phenomena in this region that directly drive community impact.

C2FSB cannot model crown fire, ember transport, or spatially varying wind. These are not minor enhancements — they represent fundamentally different physics that cannot be bolted onto C2FSB's architecture without essentially rebuilding what already exists in other tools.

## Decision

Replace C2FSB with ELMFIRE (Eulerian Level Set Model of Fire Spread) as the primary simulation engine. Retain C2FSB as a secondary engine for surface-fire-dominant scenarios and fast screening runs.

## Why ELMFIRE

### Capability comparison

| Feature | C2FSB | ELMFIRE |
|---|---|---|
| Surface fire (Rothermel) | ✓ | ✓ |
| Crown fire initiation (Van Wagner) | ✗ | ✓ |
| Crown fire spread (Rothermel 1991) | ✗ | ✓ |
| Spotting / ember transport | ✗ | ✓ (Lagrangian particle model) |
| Spatially varying wind (WindNinja grids) | ✗ | ✓ (native GeoTIFF input) |
| Time-varying weather | Single CSV | Multiband GeoTIFF rasters |
| Dead fuel moisture conditioning | ✗ | ✓ (Nelson model, terrain-aware) |
| Monte Carlo / burn probability | Manual (run N times) | Built-in with probability output |
| Fire type classification | Surface only | Surface / passive crown / active crown |
| Flame length output | ✗ | ✓ |
| Open source | ✓ (MIT-like) | ✓ (EPL 2.0, commercially usable) |
| Linux native | ✓ | ✓ |
| Docker support | Built manually | CI workflows on GitHub |
| LANDFIRE input format | Requires ASCII conversion | Native GeoTIFF |
| Built-in validation tools | ✗ | ✓ (fire perimeter microservices) |

### Operational track record

- ELMFIRE is used by Pyrecast to forecast most large fires in the Continental US (2020–present)
- First Street Foundation uses ELMFIRE for CONUS-wide 30m wildfire risk assessment across 140 million properties
- It is one of three fire spread models in the Federal Risk Management Assistance (RMA) Fires Comparison Dashboard
- UC Berkeley integrated wildland-urban interface modeling achieving 85% perimeter accuracy on the Tubbs and Thomas fires
- The original paper dates to 2013 with continuous development since

### Licensing

ELMFIRE is licensed under Eclipse Public License 2.0 (EPL-2.0). This is a commercially-friendly copyleft license that:
- Permits commercial use without conditions
- Requires source release only for modifications to ELMFIRE itself (not for code that calls it)
- Provides royalty-free patent license
- Our platform code, running ELMFIRE as a separate containerized binary, has no copyleft obligations

### Why not FlamMap / FARSITE?

FlamMap and FARSITE (same codebase from USFS Missoula Fire Lab) have equivalent fire modeling capabilities. However:
- FlamMap is Windows-only (no native Linux binary)
- FARSITE has been deprecated and merged into FlamMap
- The source code exists on GitHub (firelab/wfips) but is embedded in a larger system and difficult to extract for standalone Linux builds
- ELMFIRE provides equivalent capabilities (surface, crown, spotting, Monte Carlo) in a clean, standalone, Linux-native, open-source package

### Why keep C2FSB?

C2FSB remains valuable for:
- Surface-fire-dominant landscapes (Florida grasslands, Texas brush, western sagebrush)
- Fast scenario screening (30x faster than ELMFIRE for surface-only)
- Monte Carlo batch runs where speed matters more than crown fire fidelity
- Development iteration (2 min vs 15 min per run)

## Architecture Impact

### What changes

1. **Fuel pipeline (02_fuel):** Expanded to fetch 8 LANDFIRE layers instead of 1 (add CC, CH, CBH, CBD)
2. **WindNinja pipeline (04b_windninja, NEW):** Generates terrain-adjusted wind grids from DEM + raw weather
3. **Grid assembly (07_grid_assembly):** Rewritten to produce ELMFIRE-format GeoTIFF rasters and elmfire.data config instead of C2FSB ASCII grids
4. **Ignition (08_ignition):** Updated to write ELMFIRE ignition format
5. **Simulation (09_elmfire, NEW):** New pipeline running ELMFIRE in Docker
6. **Makefile:** Engine selector variable (`ENGINE=elmfire` or `ENGINE=c2fsb`)

### What stays the same

1. **Shapefile ingestion (01):** No change
2. **Topography (03):** No change (ELMFIRE reads same DEM/slope/aspect)
3. **Weather fetch (04):** Minor update for gridMET, but same concept
4. **Fuel moisture (05):** Same approach, different output format
5. **Assets (06):** No change
6. **Consequence analysis (10):** No change — reads fire_perimeter_final.geojson regardless of engine
7. **Web UI (11):** Minor update to display crown fire type if available
8. **Validation pipeline (12-15, Phase 8):** No change — compares simulated vs observed perimeters regardless of engine

### Compute impact

For the 50 sq mi Townsend AOI at 30m resolution:

| Scenario | C2FSB | ELMFIRE |
|---|---|---|
| Single scenario, surface only | ~3 min | ~15 min |
| Single scenario, crown + spotting | N/A | ~30 min |
| 100x Monte Carlo | ~5 hrs (manual) | ~6 hrs (built-in) |
| RAM usage | 1-2 GB | 2-3 GB |

All within the 16GB RAM constraint.

## Branch Strategy

- **`main`** — current working C2FSB-based platform. Untouched.
- **`elmfire_main`** — branched from `main`. All ELMFIRE integration work happens here.
- Once ELMFIRE pipeline is working end-to-end and validated, `elmfire_main` merges to `main`.
- C2FSB pipeline code stays in the repo as secondary engine.

## Data Sources (all free, no accounts required for most)

| Data | Source | Cost | Account needed |
|---|---|---|---|
| Fuel models (FBFM40) | LANDFIRE via `landfire` Python package | Free | No |
| Canopy (CC, CH, CBH, CBD) | LANDFIRE (same request) | Free | No |
| Elevation | USGS 3DEP | Free | No |
| Weather (historical) | gridMET / RAWS | Free | No |
| Wind (terrain-adjusted) | WindNinja (open source) | Free | No |
| Fuel moisture | Derived from weather + NFMD | Free | No |
| Buildings | OpenStreetMap / MS Building Footprints | Free | No |
| Population | Census TIGER | Free | No |
| Fire validation data | NIFC perimeters / FIREDpy | Free | No |

## References

- ELMFIRE GitHub: https://github.com/lautenberger/elmfire
- ELMFIRE documentation: https://elmfire.io
- ELMFIRE original paper: Lautenberger, C. (2013). Wildland fire modeling with an Eulerian level set method and automated calibration.
- C2FSB GitHub: https://github.com/fire2a/C2FSB
- WindNinja: https://github.com/firelab/windninja
- LANDFIRE: https://landfire.gov
- EPL 2.0 License: https://www.eclipse.org/legal/epl-2.0/

---

# Branch Setup — Claude Code Prompt

Use this as the FIRST prompt in Claude Code when starting ELMFIRE integration.

```
We are starting ELMFIRE integration. Before ANY code changes:

1. Create a new branch from main:
   git checkout main
   git pull
   git checkout -b elmfire_main
   git push -u origin elmfire_main

2. Verify the current C2FSB pipeline still works on main:
   git stash (if any uncommitted changes)
   git checkout main
   make all
   (confirm it completes)
   git checkout elmfire_main

3. Copy these files to the repo root:
   - PHASE6_7_ELMFIRE_INTEGRATION.md (the implementation plan)
   - This ADR file as docs/ADR_001_ELMFIRE_ENGINE.md

4. Create the docs/ directory if it doesn't exist.

5. Commit:
   git add .
   git commit -m "docs: add ELMFIRE integration plan and architecture decision record"
   git push

6. Confirm you are on elmfire_main branch before proceeding:
   git branch --show-current
   (must show: elmfire_main)

Do NOT modify any existing pipeline code yet. Just set up the branch and documentation.
Then proceed with Prompt 6.0 from PHASE6_7_ELMFIRE_INTEGRATION.md.
```
