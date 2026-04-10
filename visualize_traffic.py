"""
Generate a seamless, smooth-zoom marine traffic visualization (HTML + JavaScript).

Key upgrades:
1. Single-world rendering (no repeated world copies at antimeridian)
2. Smooth/fractional zoom transitions
3. Multi-resolution heatmap for better readability at each zoom level
4. Continuous density gradient legend
5. Clustered hotspot layer to reduce clutter on zoom-out
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


DATA_DIR = Path("analysis_outputs")
OUTPUT_DIR = Path("media")
OUTPUT_FILE = OUTPUT_DIR / "shipping_visualization_advanced.html"


def aggregate_grid(df: pd.DataFrame, grid_deg: float) -> list[list[float]]:
    """Aggregate points to a lat/lon grid and return heat triples [lat, lon, weight]."""
    if df.empty:
        return []

    work = df[["latitude", "longitude", "intensity_normalized"]].copy()

    work["lat_bin"] = (
        np.floor((work["latitude"] + 90.0) / grid_deg) * grid_deg - 90.0 + grid_deg / 2.0
    )
    work["lon_bin"] = (
        np.floor((work["longitude"] + 180.0) / grid_deg) * grid_deg - 180.0 + grid_deg / 2.0
    )

    grouped = (
        work.groupby(["lat_bin", "lon_bin"], as_index=False)["intensity_normalized"]
        .sum()
        .rename(columns={"intensity_normalized": "weight"})
    )
    max_weight = float(grouped["weight"].max()) or 1.0
    grouped["weight"] = grouped["weight"] / max_weight

    return grouped[["lat_bin", "lon_bin", "weight"]].round(5).values.tolist()


def build_hotspot_payload(df: pd.DataFrame) -> list[dict[str, float | str]]:
    """Build compact hotspot payload for clustered markers."""
    out: list[dict[str, float | str]] = []
    for row in df.itertuples(index=False):
        out.append(
            {
                "lat": round(float(row.latitude), 5),
                "lon": round(float(row.longitude), 5),
                "density": int(row.density),
                "intensity": round(float(row.intensity), 4),
                "category": str(row.category),
            }
        )
    return out


def main() -> None:
    print("=" * 72)
    print("BUILDING ADVANCED MARINE TRAFFIC VISUALIZATION")
    print("=" * 72)

    OUTPUT_DIR.mkdir(exist_ok=True)

    commercial = pd.read_csv(DATA_DIR / "traffic_commercial_world.csv")
    passenger = pd.read_csv(DATA_DIR / "traffic_passenger_world.csv")
    oil_gas = pd.read_csv(DATA_DIR / "traffic_oil_gas_world.csv")
    hotspots = pd.read_csv(DATA_DIR / "traffic_combined_hotspots.csv")

    print(f"Commercial points: {len(commercial):,}")
    print(f"Passenger points : {len(passenger):,}")
    print(f"Oil & Gas points : {len(oil_gas):,}")
    print(f"Hotspot points   : {len(hotspots):,}")

    # Merge categories for a single global density surface.
    merged = pd.concat([commercial, passenger, oil_gas], ignore_index=True)

    # Multi-resolution layers keep the map readable at each zoom level.
    heat_low = aggregate_grid(merged, grid_deg=1.0)    # zoomed-out global view
    heat_mid = aggregate_grid(merged, grid_deg=0.5)    # regional view
    heat_high = aggregate_grid(merged, grid_deg=0.25)  # local detail

    print(f"Heat points (low/mid/high): {len(heat_low):,} / {len(heat_mid):,} / {len(heat_high):,}")

    hotspot_payload = build_hotspot_payload(hotspots)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Marine Traffic Density - Advanced Visualization</title>

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />

  <style>
    html, body, #map {{
      height: 100%;
      width: 100%;
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
    }}
    .panel {{
      position: absolute;
      z-index: 1000;
      top: 12px;
      left: 12px;
      background: rgba(255, 255, 255, 0.95);
      border-radius: 10px;
      padding: 12px 14px;
      box-shadow: 0 2px 14px rgba(0, 0, 0, 0.25);
      max-width: 340px;
      font-size: 13px;
      line-height: 1.4;
    }}
    .panel h2 {{
      margin: 0 0 6px 0;
      font-size: 16px;
      color: #1e2a38;
    }}
    .legend {{
      margin-top: 10px;
    }}
    .gradient-bar {{
      height: 12px;
      border-radius: 8px;
      border: 1px solid #c7d1db;
      background: linear-gradient(
        to right,
        #1e3a8a 0%,
        #2563eb 20%,
        #06b6d4 40%,
        #22c55e 60%,
        #eab308 80%,
        #ef4444 100%
      );
    }}
    .legend-labels {{
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
      color: #374151;
      font-size: 11px;
    }}
    .hotspot-dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 1px solid rgba(255, 255, 255, 0.8);
      box-shadow: 0 0 3px rgba(0, 0, 0, 0.45);
    }}
    .cat-commercial {{ background: #ef4444; }}
    .cat-passenger {{ background: #3b82f6; }}
    .cat-oilgas {{ background: #22c55e; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <h2>Global Marine Traffic Density</h2>
    <div><b>Improvements:</b> seamless world bounds, smooth zoom, adaptive heat resolution, continuous gradient, clustered hotspots.</div>
    <div style="margin-top:6px;">
      <b>Zoom:</b> <span id="zoom-level">-</span> |
      <b>Resolution:</b> <span id="resolution-level">-</span>
    </div>
    <div class="legend">
      <b>Density gradient</b>
      <div class="gradient-bar"></div>
      <div class="legend-labels"><span>Low</span><span>High</span></div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>

  <script>
    // Embedded preprocessed payloads from Python.
    const HEAT_LOW = {json.dumps(heat_low, separators=(",", ":"))};
    const HEAT_MID = {json.dumps(heat_mid, separators=(",", ":"))};
    const HEAT_HIGH = {json.dumps(heat_high, separators=(",", ":"))};
    const HOTSPOTS = {json.dumps(hotspot_payload, separators=(",", ":"))};

    // Smooth zoom + seamless single-world rendering configuration.
    const map = L.map("map", {{
      center: [20, 0],
      zoom: 2.3,
      minZoom: 2,
      maxZoom: 9,
      zoomSnap: 0.1,        // fractional zoom for smoother transitions
      zoomDelta: 0.25,      // smaller step than default
      wheelPxPerZoomLevel: 90,
      zoomAnimation: true,
      markerZoomAnimation: true,
      fadeAnimation: true,
      inertia: true,
      worldCopyJump: false,
      maxBounds: [[-85, -180], [85, 180]],
      maxBoundsViscosity: 1.0,
      preferCanvas: true
    }});

    L.tileLayer(
      "https://{{s}}.basemaps.cartocdn.com/light_nolabels/{{z}}/{{x}}/{{y}}{{r}}.png",
      {{
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        subdomains: "abcd",
        noWrap: true, // prevents repeated world copies
        bounds: [[-85, -180], [85, 180]],
        detectRetina: true,
        maxNativeZoom: 7,
        maxZoom: 9
      }}
    ).addTo(map);

    const heatGradient = {{
      0.00: "#1e3a8a",
      0.20: "#2563eb",
      0.40: "#06b6d4",
      0.60: "#22c55e",
      0.80: "#eab308",
      1.00: "#ef4444"
    }};

    const heatLayer = L.heatLayer([], {{
      radius: 28,
      blur: 20,
      maxZoom: 9,
      minOpacity: 0.30,
      gradient: heatGradient
    }}).addTo(map);

    // Clustered hotspots keep zoomed-out view readable.
    const clusters = L.markerClusterGroup({{
      showCoverageOnHover: false,
      spiderfyOnEveryZoom: false,
      maxClusterRadius: 48,
      disableClusteringAtZoom: 6
    }});

    function categoryColor(category) {{
      if (category === "commercial") return "#ef4444";
      if (category === "passenger") return "#3b82f6";
      return "#22c55e";
    }}

    function categoryClass(category) {{
      if (category === "commercial") return "cat-commercial";
      if (category === "passenger") return "cat-passenger";
      return "cat-oilgas";
    }}

    HOTSPOTS.forEach((h) => {{
      const marker = L.marker([h.lat, h.lon], {{
        icon: L.divIcon({{
          className: "",
          html: `<div class="hotspot-dot ${{categoryClass(h.category)}}"></div>`,
          iconSize: [10, 10],
          iconAnchor: [5, 5]
        }})
      }});
      marker.bindPopup(
        `<b>Category:</b> ${{h.category.replace("_", " & ")}}<br>` +
        `<b>Density:</b> ${{h.density.toLocaleString()}}<br>` +
        `<b>Intensity:</b> ${{h.intensity}}`
      );
      clusters.addLayer(marker);
    }});

    clusters.addTo(map);
    L.control.layers(null, {{
      "Density Heatmap": heatLayer,
      "Hotspot Clusters": clusters
    }}, {{ collapsed: false }}).addTo(map);

    function resolutionLabel(z) {{
      if (z < 3.5) return "1.0° grid (global)";
      if (z < 5.5) return "0.5° grid (regional)";
      return "0.25° grid (detailed)";
    }}

    function chooseDataset(z) {{
      if (z < 3.5) return HEAT_LOW;
      if (z < 5.5) return HEAT_MID;
      return HEAT_HIGH;
    }}

    function dynamicRadius(z) {{
      // Interpolated radius keeps diffusion patterns visible across zoom levels.
      return Math.max(10, Math.min(34, 34 - (z - 2) * 2.8));
    }}

    function dynamicBlur(z) {{
      return Math.max(8, Math.min(24, 24 - (z - 2) * 1.8));
    }}

    let currentDatasetName = "";

    function updateHeatLayer() {{
      const z = map.getZoom();
      const dataset = chooseDataset(z);
      const datasetName = resolutionLabel(z);

      if (datasetName !== currentDatasetName) {{
        heatLayer.setLatLngs(dataset);
        currentDatasetName = datasetName;
      }}

      heatLayer.setOptions({{
        radius: dynamicRadius(z),
        blur: dynamicBlur(z)
      }});

      document.getElementById("zoom-level").textContent = z.toFixed(1);
      document.getElementById("resolution-level").textContent = datasetName;
    }}

    map.on("zoom", updateHeatLayer);
    map.on("zoomend", updateHeatLayer);
    updateHeatLayer();
  </script>
</body>
</html>
"""

    OUTPUT_FILE.write_text(html, encoding="utf-8")

    print(f"\nOutput written: {OUTPUT_FILE}")
    print("\nRun:")
    print("  .venv\\Scripts\\python.exe visualize_traffic.py")
    print("Then open:")
    print(f"  start {OUTPUT_FILE.as_posix().replace('/', chr(92))}")
    print("=" * 72)


if __name__ == "__main__":
    main()
