import { useState } from "react";

const services = [
  {
    id: "shapefile",
    label: "Shapefile Ingestion",
    desc: "Accepts user shapefile (AOI), validates geometry, reprojects to common CRS (EPSG:5070), computes bounding box for all downstream tile fetches.",
    color: "#E8D5B7",
    borderColor: "#8B6914",
    category: "input",
  },
  {
    id: "fuel",
    label: "Fuel Pipeline",
    desc: "Pulls LANDFIRE FBFM40 raster tiles for AOI extent. Clips to shapefile boundary, resamples to target resolution, assigns Scott & Burgan fuel model codes per cell.",
    color: "#C4D9A0",
    borderColor: "#4A7023",
    category: "pipeline",
    sources: ["LANDFIRE FBFM40 (30m)", "Custom local fuel surveys"],
  },
  {
    id: "topography",
    label: "Topography Pipeline",
    desc: "Fetches USGS 3DEP DEM tiles. Derives slope (degrees), aspect (degrees from north), and elevation grids. Aligns resolution with fuel grid.",
    color: "#A0C4D9",
    borderColor: "#23567A",
    category: "pipeline",
    sources: ["USGS 3DEP / NED (10m/30m)", "SRTM (global fallback)"],
  },
  {
    id: "weather",
    label: "Weather Pipeline",
    desc: "Ingests wind speed/direction, temperature, relative humidity. Historical mode pulls from RAWS/gridMET for scenario distributions. Operational mode streams NOAA RTMA/HRRR forecasts.",
    color: "#D9A0C4",
    borderColor: "#7A2356",
    category: "pipeline",
    sources: ["RAWS stations", "NOAA RTMA/HRRR", "gridMET historical"],
  },
  {
    id: "moisture",
    label: "Fuel Moisture Pipeline",
    desc: "Estimates dead fuel moisture (1hr, 10hr, 100hr) from weather inputs using Nelson model. Live fuel moisture from NFMD station obs + NDVI satellite proxies.",
    color: "#D9C4A0",
    borderColor: "#7A5623",
    category: "pipeline",
    sources: ["National Fuel Moisture DB", "MODIS/VIIRS NDVI", "Weather pipeline (derived)"],
  },
  {
    id: "assets",
    label: "Assets & Exposure Pipeline",
    desc: "Building footprints (MS/OSM), population (Census TIGER), critical infrastructure (HIFLD), property values (county assessor). Geocoded and indexed to simulation grid.",
    color: "#D9A0A0",
    borderColor: "#7A2323",
    category: "pipeline",
    sources: ["MS Building Footprints", "Census/TIGER", "HIFLD", "County assessor data"],
  },
  {
    id: "grid",
    label: "Grid Assembly Service",
    desc: "Merges all pipeline outputs into a unified Cell2Fire-compatible grid. Each cell gets: fuel model, slope, aspect, elevation, moisture values. Validates consistency across layers.",
    color: "#B7B7E8",
    borderColor: "#3A3A8B",
    category: "core",
  },
  {
    id: "ignition",
    label: "Ignition Service",
    desc: "User-defined points for scenario analysis, or probabilistic ignition sampling from historical fire occurrence databases (FPA FOD) weighted by fuel/weather conditions.",
    color: "#E8B7D5",
    borderColor: "#8B1464",
    category: "core",
  },
  {
    id: "cell2fire",
    label: "Cell2Fire Simulation Engine",
    desc: "Runs fire spread simulations on assembled grid. Supports single deterministic runs or Monte Carlo batches (100-10,000 scenarios) with varied weather/ignition inputs. Outputs fire perimeters, ROS, intensity per cell per timestep.",
    color: "#FF6B35",
    borderColor: "#8B3A1D",
    category: "engine",
  },
  {
    id: "consequence",
    label: "Consequence Analysis",
    desc: "Overlays fire spread outputs with asset layer. Calculates: structures exposed, population at risk, estimated damage ($), critical infrastructure threatened. Aggregates across Monte Carlo runs for probabilistic risk.",
    color: "#E85050",
    borderColor: "#8B1A1A",
    category: "output",
  },
  {
    id: "output",
    label: "Output & Reporting",
    desc: "Generates burn probability maps, risk heatmaps, evacuation trigger zones, structure-level exposure reports. Exports as GeoJSON, GeoTIFF, shapefiles, PDF reports.",
    color: "#50C878",
    borderColor: "#1A6B3A",
    category: "output",
  },
];

const flowConnections = [
  { from: "shapefile", to: "fuel" },
  { from: "shapefile", to: "topography" },
  { from: "shapefile", to: "weather" },
  { from: "shapefile", to: "assets" },
  { from: "weather", to: "moisture" },
  { from: "fuel", to: "grid" },
  { from: "topography", to: "grid" },
  { from: "weather", to: "grid" },
  { from: "moisture", to: "grid" },
  { from: "grid", to: "cell2fire" },
  { from: "ignition", to: "cell2fire" },
  { from: "cell2fire", to: "consequence" },
  { from: "assets", to: "consequence" },
  { from: "consequence", to: "output" },
  { from: "cell2fire", to: "output" },
];

const categoryLabels = {
  input: "USER INPUT",
  pipeline: "DATA PIPELINES",
  core: "ASSEMBLY & IGNITION",
  engine: "SIMULATION",
  output: "ANALYSIS & OUTPUT",
};

const categoryOrder = ["input", "pipeline", "core", "engine", "output"];

export default function WildfireArchitecture() {
  const [selected, setSelected] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);

  const selectedService = services.find((s) => s.id === selected);

  const getConnected = (id) => {
    if (!id) return new Set();
    const connected = new Set([id]);
    flowConnections.forEach((c) => {
      if (c.from === id) connected.add(c.to);
      if (c.to === id) connected.add(c.from);
    });
    return connected;
  };

  const connectedSet = getConnected(hoveredId || selected);
  const hasHighlight = hoveredId || selected;

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0D0D0D",
        color: "#E0E0E0",
        fontFamily: "'IBM Plex Mono', 'Courier New', monospace",
        padding: "24px",
      }}
    >
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 32, borderBottom: "2px solid #FF6B35", paddingBottom: 16 }}>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: "#FF6B35",
              margin: 0,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            Wildfire Modeling Platform
          </h1>
          <p style={{ fontSize: 12, color: "#888", margin: "6px 0 0 0", letterSpacing: "0.04em" }}>
            Service Architecture — Cell2Fire Engine with Modular Data Pipelines
          </p>
        </div>

        {/* Architecture Flow */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {categoryOrder.map((cat) => {
            const catServices = services.filter((s) => s.category === cat);
            return (
              <div key={cat}>
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.2em",
                    color: "#666",
                    textTransform: "uppercase",
                    marginBottom: 8,
                    fontWeight: 600,
                  }}
                >
                  {categoryLabels[cat]}
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    flexWrap: "wrap",
                  }}
                >
                  {catServices.map((svc) => {
                    const isActive = !hasHighlight || connectedSet.has(svc.id);
                    const isSelected = selected === svc.id;
                    return (
                      <div
                        key={svc.id}
                        onClick={() => setSelected(isSelected ? null : svc.id)}
                        onMouseEnter={() => setHoveredId(svc.id)}
                        onMouseLeave={() => setHoveredId(null)}
                        style={{
                          flex: cat === "engine" ? "1 1 100%" : cat === "input" ? "1 1 100%" : "1 1 0",
                          minWidth: cat === "pipeline" ? 170 : 200,
                          background: isActive ? svc.color + "18" : "#1a1a1a08",
                          border: `2px solid ${isSelected ? "#FF6B35" : isActive ? svc.borderColor : "#333"}`,
                          borderRadius: 6,
                          padding: "14px 16px",
                          cursor: "pointer",
                          opacity: isActive ? 1 : 0.3,
                          transition: "all 0.2s ease",
                          position: "relative",
                        }}
                      >
                        <div
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: "50%",
                            background: svc.color,
                            position: "absolute",
                            top: 14,
                            left: 16,
                          }}
                        />
                        <div
                          style={{
                            fontSize: 13,
                            fontWeight: 700,
                            color: isActive ? svc.color : "#555",
                            marginLeft: 16,
                            letterSpacing: "0.02em",
                          }}
                        >
                          {svc.label}
                        </div>
                        <div
                          style={{
                            fontSize: 10,
                            color: isActive ? "#999" : "#444",
                            marginTop: 6,
                            lineHeight: 1.5,
                          }}
                        >
                          {svc.desc}
                        </div>
                        {svc.sources && (
                          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
                            {svc.sources.map((src, i) => (
                              <span
                                key={i}
                                style={{
                                  fontSize: 8,
                                  background: svc.borderColor + "33",
                                  color: svc.color,
                                  padding: "2px 6px",
                                  borderRadius: 3,
                                  letterSpacing: "0.03em",
                                }}
                              >
                                {src}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Flow arrows between categories */}
                {cat !== "output" && (
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "center",
                      padding: "6px 0",
                    }}
                  >
                    <div style={{ color: "#444", fontSize: 18 }}>▼</div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Data Flow Legend */}
        <div
          style={{
            marginTop: 32,
            padding: 16,
            border: "1px solid #333",
            borderRadius: 6,
            background: "#141414",
          }}
        >
          <div
            style={{
              fontSize: 10,
              letterSpacing: "0.15em",
              color: "#666",
              textTransform: "uppercase",
              marginBottom: 12,
              fontWeight: 600,
            }}
          >
            Data Flow Summary
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 10 }}>
            {[
              { step: "1", text: "User uploads shapefile defining AOI" },
              { step: "2", text: "Shapefile extent triggers parallel data pipeline fetches" },
              { step: "3", text: "Fuel, topography, weather, moisture pipelines pull & process public data" },
              { step: "4", text: "Grid Assembly merges all layers into Cell2Fire-compatible input" },
              { step: "5", text: "Ignition points defined (user or probabilistic sampling)" },
              { step: "6", text: "Cell2Fire runs N simulations across weather scenarios" },
              { step: "7", text: "Fire spread outputs overlaid with asset/exposure data" },
              { step: "8", text: "Burn probability maps, risk reports, and exports generated" },
            ].map((item) => (
              <div key={item.step} style={{ display: "flex", gap: 8, color: "#aaa", lineHeight: 1.5 }}>
                <span
                  style={{
                    color: "#FF6B35",
                    fontWeight: 700,
                    minWidth: 14,
                  }}
                >
                  {item.step}.
                </span>
                {item.text}
              </div>
            ))}
          </div>
        </div>

        {/* Tech Stack */}
        <div
          style={{
            marginTop: 16,
            padding: 16,
            border: "1px solid #333",
            borderRadius: 6,
            background: "#141414",
          }}
        >
          <div
            style={{
              fontSize: 10,
              letterSpacing: "0.15em",
              color: "#666",
              textTransform: "uppercase",
              marginBottom: 12,
              fontWeight: 600,
            }}
          >
            Recommended Tech Stack
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, fontSize: 10 }}>
            {[
              { label: "Orchestration", items: "Airflow / Prefect" },
              { label: "Compute", items: "Kubernetes + spot instances" },
              { label: "Storage", items: "PostGIS + S3/MinIO (rasters)" },
              { label: "Geo Processing", items: "GDAL/OGR, Rasterio, GeoPandas" },
              { label: "Simulation", items: "Cell2Fire (C++ core)" },
              { label: "API Layer", items: "FastAPI + Celery workers" },
              { label: "Message Queue", items: "Redis / RabbitMQ" },
              { label: "Visualization", items: "Mapbox GL / Deck.gl" },
              { label: "Export", items: "GeoTIFF, GeoJSON, GPKG, PDF" },
            ].map((item) => (
              <div key={item.label} style={{ color: "#aaa", lineHeight: 1.5 }}>
                <span style={{ color: "#FF6B35", fontWeight: 600 }}>{item.label}: </span>
                {item.items}
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 16, fontSize: 9, color: "#444", textAlign: "center" }}>
          Click any service to highlight its connections. Hover to preview data flow.
        </div>
      </div>
    </div>
  );
}
