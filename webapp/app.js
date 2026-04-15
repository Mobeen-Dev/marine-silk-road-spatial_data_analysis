/* Key improvements:
 * 1) Seam-safe rendering: renderWorldCopies:false + bounded world extent.
 * 2) Smooth zoom: MapLibre's interpolated zoom with tuned wheel zoom rates.
 * 3) Multi-scale density: source data switches low/mid/high by zoom threshold.
 * 4) Readability: continuous heat gradient + clustered hotspots + category filters.
 */

const WORLD_BOUNDS = [
  [-180, -85],
  [180, 85]
];

const DATA_PATHS = {
  low: "./data/density_low.geojson",
  mid: "./data/density_mid.geojson",
  high: "./data/density_high.geojson",
  hotspots: "./data/hotspots.geojson"
};

const RESOLUTION_THRESHOLDS = {
  lowMaxZoom: 3.5,
  midMaxZoom: 5.5
};

const state = {
  datasets: {
    low: null,
    mid: null,
    high: null,
    hotspots: null
  },
  currentResolution: null,
  categoryFilters: ["commercial", "passenger", "oil_gas"]
};

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      cartoBase: {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png",
          "https://b.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png",
          "https://c.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png",
          "https://d.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png"
        ],
        tileSize: 256,
        maxzoom: 20
      },
      cartoLabels: {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png",
          "https://b.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png",
          "https://c.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png",
          "https://d.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png"
        ],
        tileSize: 256,
        maxzoom: 20
      }
    },
    layers: [
      { id: "carto-base", type: "raster", source: "cartoBase" },
      { id: "carto-labels", type: "raster", source: "cartoLabels" }
    ]
  },
  center: [0, 20],
  zoom: 2.35,
  minZoom: 2.0,
  maxZoom: 9.5,
  maxBounds: WORLD_BOUNDS,
  renderWorldCopies: false,
  antialias: true,
  cooperativeGestures: false,
  hash: false
});

if (map.scrollZoom && map.scrollZoom.setWheelZoomRate) {
  map.scrollZoom.setWheelZoomRate(1 / 550);
}
if (map.scrollZoom && map.scrollZoom.setZoomRate) {
  map.scrollZoom.setZoomRate(1 / 90);
}

map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");

function getResolutionFromZoom(zoom) {
  if (zoom < RESOLUTION_THRESHOLDS.lowMaxZoom) return "low";
  if (zoom < RESOLUTION_THRESHOLDS.midMaxZoom) return "mid";
  return "high";
}

function getResolutionLabel(resolution) {
  if (resolution === "low") return "1.0 degree grid (global)";
  if (resolution === "mid") return "0.5 degree grid (regional)";
  return "0.25 degree grid (detailed)";
}

function applyHotspotCategoryFilter() {
  const filterValues = state.categoryFilters;
  if (!map.getLayer("hotspot-points")) return;
  map.setFilter("hotspot-points", ["in", ["get", "category"], ["literal", filterValues]]);
}

function updateDensitySourceForZoom() {
  if (!map.getSource("density")) return;
  const zoom = map.getZoom();
  const newRes = getResolutionFromZoom(zoom);
  if (newRes === state.currentResolution) return;

  map.getSource("density").setData(state.datasets[newRes]);
  state.currentResolution = newRes;
  document.getElementById("resolutionValue").textContent = getResolutionLabel(newRes);
}

function updateZoomLabel() {
  document.getElementById("zoomValue").textContent = map.getZoom().toFixed(2);
}

function setLayerVisibility(layerId, isVisible) {
  if (!map.getLayer(layerId)) return;
  map.setLayoutProperty(layerId, "visibility", isVisible ? "visible" : "none");
}

function wireControls() {
  document.getElementById("toggleHeat").addEventListener("change", (e) => {
    setLayerVisibility("density-heat", e.target.checked);
  });
  document.getElementById("toggleCluster").addEventListener("change", (e) => {
    setLayerVisibility("hotspot-clusters", e.target.checked);
    setLayerVisibility("hotspot-cluster-count", e.target.checked);
  });
  document.getElementById("toggleHotspots").addEventListener("change", (e) => {
    setLayerVisibility("hotspot-points", e.target.checked);
  });

  function onCategoryToggle() {
    const selected = [];
    if (document.getElementById("catCommercial").checked) selected.push("commercial");
    if (document.getElementById("catPassenger").checked) selected.push("passenger");
    if (document.getElementById("catOilGas").checked) selected.push("oil_gas");
    state.categoryFilters = selected;
    applyHotspotCategoryFilter();
  }

  document.getElementById("catCommercial").addEventListener("change", onCategoryToggle);
  document.getElementById("catPassenger").addEventListener("change", onCategoryToggle);
  document.getElementById("catOilGas").addEventListener("change", onCategoryToggle);
}

async function loadGeoJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Failed to load ${path}: ${response.status}`);
  return response.json();
}

async function initLayers() {
  const [low, mid, high, hotspots] = await Promise.all([
    loadGeoJson(DATA_PATHS.low),
    loadGeoJson(DATA_PATHS.mid),
    loadGeoJson(DATA_PATHS.high),
    loadGeoJson(DATA_PATHS.hotspots)
  ]);

  state.datasets.low = low;
  state.datasets.mid = mid;
  state.datasets.high = high;
  state.datasets.hotspots = hotspots;

  const initialRes = getResolutionFromZoom(map.getZoom());
  state.currentResolution = initialRes;

  map.addSource("density", {
    type: "geojson",
    data: state.datasets[initialRes]
  });

  map.addLayer({
    id: "density-heat",
    type: "heatmap",
    source: "density",
    paint: {
      "heatmap-weight": ["coalesce", ["get", "weight"], 0],
      "heatmap-intensity": [
        "interpolate",
        ["linear"],
        ["zoom"],
        2, 0.8,
        5, 1.1,
        8, 1.3
      ],
      "heatmap-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        2, 14,
        4, 22,
        6, 32,
        8, 42
      ],
      "heatmap-opacity": [
        "interpolate",
        ["linear"],
        ["zoom"],
        2, 0.82,
        8, 0.72
      ],
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0.00, "rgba(37,52,148,0)",
        0.10, "#253494",
        0.30, "#2c7fb8",
        0.50, "#41b6c4",
        0.70, "#a1dab4",
        0.85, "#fecc5c",
        1.00, "#e31a1c"
      ]
    }
  });

  map.addSource("hotspots", {
    type: "geojson",
    data: state.datasets.hotspots,
    cluster: true,
    clusterRadius: 46,
    clusterMaxZoom: 6
  });

  map.addLayer({
    id: "hotspot-clusters",
    type: "circle",
    source: "hotspots",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": [
        "step",
        ["get", "point_count"],
        "#93c5fd", 40,
        "#60a5fa", 120,
        "#2563eb", 300,
        "#1e3a8a"
      ],
      "circle-radius": [
        "step",
        ["get", "point_count"],
        12, 40,
        18, 120,
        24, 300,
        30
      ],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.2
    }
  });

  map.addLayer({
    id: "hotspot-cluster-count",
    type: "symbol",
    source: "hotspots",
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["get", "point_count_abbreviated"],
      "text-font": ["Open Sans Bold"],
      "text-size": 11
    },
    paint: {
      "text-color": "#ffffff"
    }
  });

  map.addLayer({
    id: "hotspot-points",
    type: "circle",
    source: "hotspots",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": [
        "match",
        ["get", "category"],
        "commercial", "#ef4444",
        "passenger", "#3b82f6",
        "oil_gas", "#16a34a",
        "#6b7280"
      ],
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        3, 2.5,
        8, 5.5
      ],
      "circle-opacity": 0.8,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.8
    }
  });

  map.on("click", "hotspot-points", (e) => {
    const feature = e.features?.[0];
    if (!feature) return;
    const coords = feature.geometry.coordinates.slice();
    const p = feature.properties;
    const html =
      `<b>Category:</b> ${String(p.category).replace("_", " & ")}<br>` +
      `<b>Density:</b> ${Number(p.density).toLocaleString()}<br>` +
      `<b>Intensity:</b> ${Number(p.intensity).toFixed(3)}`;

    new maplibregl.Popup({ closeButton: true })
      .setLngLat(coords)
      .setHTML(html)
      .addTo(map);
  });

  map.on("mouseenter", "hotspot-points", () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "hotspot-points", () => {
    map.getCanvas().style.cursor = "";
  });

  map.on("click", "hotspot-clusters", (e) => {
    const features = map.queryRenderedFeatures(e.point, { layers: ["hotspot-clusters"] });
    if (!features.length) return;
    const clusterId = features[0].properties.cluster_id;
    map.getSource("hotspots").getClusterExpansionZoom(clusterId, (err, zoom) => {
      if (err) return;
      map.easeTo({ center: features[0].geometry.coordinates, zoom, duration: 500 });
    });
  });

  wireControls();
  updateZoomLabel();
  document.getElementById("resolutionValue").textContent = getResolutionLabel(initialRes);
  applyHotspotCategoryFilter();
}

let zoomTicking = false;
function onZoomFrame() {
  if (zoomTicking) return;
  zoomTicking = true;
  requestAnimationFrame(() => {
    updateZoomLabel();
    updateDensitySourceForZoom();
    zoomTicking = false;
  });
}

map.on("zoom", onZoomFrame);
map.on("zoomend", () => {
  updateZoomLabel();
  updateDensitySourceForZoom();
});

map.on("load", () => {
  initLayers().catch((err) => {
    // Visible failure helps debugging data path and server issues.
    // eslint-disable-next-line no-console
    console.error(err);
    alert(`Failed to initialize map layers: ${err.message}`);
  });
});
