/* Hierarchical high-performance filter system.
 *
 * Design:
 * - Preloaded multiscale sources (low/mid/high) with top_category index.
 * - Layer visibility/filter toggles for incremental updates (no full re-render loop).
 * - Hierarchical state (top category + subcategory selections).
 * - Cached expressions + zoom-aware source switching for smooth updates.
 */

const WORLD_BOUNDS = [
  [-180, -85],
  [180, 85]
];

const DATA_PATHS = {
  low: "./data/density_low.geojson",
  mid: "./data/density_mid.geojson",
  high: "./data/density_high.geojson",
  hotspotsCommercial: "./data/hotspots_commercial.geojson",
  hotspotsOilGas: "./data/hotspots_oil_gas.geojson",
  hotspotsPassenger: "./data/hotspots_passenger.geojson",
  dbscanClusters: "./data/clusters.geojson",
  filterIndex: "./data/filter_index.json",
  metadata: "./data/metadata.json"
};

const TOP_KEYS = ["global", "commercial", "oil_gas", "passenger"];
const CATEGORY_COLORS = {
  global: "#0369a1",
  commercial: "#e11d48",
  oil_gas: "#15803d",
  passenger: "#7c3aed"
};
const HOTSPOT_KEYS = ["commercial", "oil_gas", "passenger"];

const RESOLUTION_THRESHOLDS = { lowMaxZoom: 3.5, midMaxZoom: 5.5 };
const RESOLUTION_LABELS = {
  low: "1.0° grid (global)",
  mid: "0.5° grid (regional)",
  high: "0.25° grid (detail)"
};

const state = {
  datasets: { low: null, mid: null, high: null },
  hotspotDatasets: { commercial: null, oil_gas: null, passenger: null },
  dbscanClusters: null,
  filterIndex: null,
  metadata: null,
  currentResolution: null,
  selectedTop: {
    global: true,
    commercial: false,
    oil_gas: false,
    passenger: false
  },
  selectedSubcategories: {},
  expressionCache: new Map(),
  modalCategory: null,
  modalMode: "refine",
  modalDraft: new Set()
};

const ui = {
  panel: document.getElementById("controlPanel"),
  panelMinimizeBtn: document.getElementById("panelMinimizeBtn"),
  panelCloseBtn: document.getElementById("panelCloseBtn"),
  panelToggleBtn: document.getElementById("panelToggleBtn"),
  zoomValue: document.getElementById("zoomValue"),
  resolutionValue: document.getElementById("resolutionValue"),
  centerValue: document.getElementById("centerValue"),
  statusValue: document.getElementById("statusValue"),
  topCategoryList: document.getElementById("topCategoryList"),
  subcategoryHint: document.getElementById("subcategoryHint"),
  toggleHeat: document.getElementById("toggleHeat"),
  toggleClusters: document.getElementById("toggleClusters"),
  togglePoints: document.getElementById("togglePoints"),
  toggleDbscanClusters: document.getElementById("toggleDbscanClusters"),
  fitWorldBtn: document.getElementById("fitWorldBtn"),
  modalBackdrop: document.getElementById("refineModalBackdrop"),
  modal: document.getElementById("refineModal"),
  modalTitle: document.getElementById("refineModalTitle"),
  modalSubtitle: document.getElementById("refineModalSubtitle"),
  modalList: document.getElementById("refineModalList"),
  modalSelectAllBtn: document.getElementById("modalSelectAllBtn"),
  modalSelectNoneBtn: document.getElementById("modalSelectNoneBtn"),
  modalCancelBtn: document.getElementById("modalCancelBtn"),
  modalApplyBtn: document.getElementById("modalApplyBtn")
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
  zoom: 2.5,
  minZoom: 0,
  maxZoom: 10,
  renderWorldCopies: false,
  antialias: true,
  hash: false
});

if (map.scrollZoom?.setWheelZoomRate) map.scrollZoom.setWheelZoomRate(1 / 580);
if (map.scrollZoom?.setZoomRate) map.scrollZoom.setZoomRate(1 / 95);

map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");

function setStatus(message, isError = false) {
  ui.statusValue.textContent = message;
  ui.statusValue.style.color = isError ? "#b91c1c" : "#0f766e";
}

function isSubtypeGranular(category) {
  return !!state.filterIndex?.subcategory_granularity_available?.[category];
}

function getResolutionFromZoom(zoom) {
  if (zoom < RESOLUTION_THRESHOLDS.lowMaxZoom) return "low";
  if (zoom < RESOLUTION_THRESHOLDS.midMaxZoom) return "mid";
  return "high";
}

function updateMapMetrics() {
  const center = map.getCenter();
  ui.zoomValue.textContent = map.getZoom().toFixed(2);
  ui.centerValue.textContent = `${center.lat.toFixed(2)}°, ${center.lng.toFixed(2)}°`;
}

function isCategoryActive(category) {
  if (!state.selectedTop[category]) return false;
  if (category === "global") return true;
  const selected = state.selectedSubcategories[category];
  return !!selected && selected.size > 0;
}

function activeNonGlobalCategories() {
  return HOTSPOT_KEYS.filter((key) => isCategoryActive(key));
}

function buildCategoryFilterExpression(activeCategories) {
  const key = activeCategories.slice().sort().join("|");
  if (state.expressionCache.has(key)) return state.expressionCache.get(key);

  const expr =
    activeCategories.length === 0
      ? ["==", ["get", "top_category"], "__none__"]
      : ["in", ["get", "top_category"], ["literal", activeCategories]];

  state.expressionCache.set(key, expr);
  return expr;
}

function applyDensityFilters() {
  // Global layer only needs its own toggle.
  map.setLayoutProperty(
    "density-global",
    "visibility",
    isCategoryActive("global") && ui.toggleHeat.checked ? "visible" : "none"
  );

  const activeCats = activeNonGlobalCategories();
  for (const cat of HOTSPOT_KEYS) {
    const visible = ui.toggleHeat.checked && activeCats.includes(cat);
    map.setLayoutProperty(`density-${cat}`, "visibility", visible ? "visible" : "none");
  }
}

function applyHotspotFilters() {
  const activeCats = isCategoryActive("global") ? HOTSPOT_KEYS.slice() : activeNonGlobalCategories();
  for (const cat of HOTSPOT_KEYS) {
    const visible = activeCats.includes(cat);
    map.setLayoutProperty(
      `hotspot-clusters-${cat}`,
      "visibility",
      visible && ui.toggleClusters.checked ? "visible" : "none"
    );
    map.setLayoutProperty(
      `hotspot-cluster-count-${cat}`,
      "visibility",
      visible && ui.toggleClusters.checked ? "visible" : "none"
    );
    map.setLayoutProperty(
      `hotspot-points-${cat}`,
      "visibility",
      visible && ui.togglePoints.checked ? "visible" : "none"
    );
  }
}

function applyDbscanVisibility() {
  if (!map.getLayer("dbscan-clusters")) return;
  map.setLayoutProperty(
    "dbscan-clusters",
    "visibility",
    ui.toggleDbscanClusters.checked ? "visible" : "none"
  );
  map.setLayoutProperty(
    "dbscan-noise",
    "visibility",
    ui.toggleDbscanClusters.checked ? "visible" : "none"
  );
}

function updateCategorySummary(category) {
  const summaryNode = document.getElementById(`summary-${category}`);
  if (!summaryNode) return;
  if (category === "global") {
    summaryNode.textContent = "All ship types combined";
    return;
  }
  if (!isSubtypeGranular(category)) {
    const all = state.filterIndex.subcategories[category] || [];
    summaryNode.textContent = `${all.length} types available in explorer`;
    return;
  }
  const all = state.filterIndex.subcategories[category] || [];
  const selected = state.selectedSubcategories[category] || new Set();
  summaryNode.textContent = `${selected.size}/${all.length} subcategories selected`;
}

function applyAllFilters() {
  applyDensityFilters();
  applyHotspotFilters();
  applyDbscanVisibility();
  TOP_KEYS.forEach(updateCategorySummary);
}

function updateDensitySourceForZoom() {
  const nextResolution = getResolutionFromZoom(map.getZoom());
  ui.resolutionValue.textContent = RESOLUTION_LABELS[nextResolution];
  if (!map.getSource("density") || !state.datasets[nextResolution]) {
    state.currentResolution = nextResolution;
    return;
  }
  if (state.currentResolution === nextResolution) return;
  map.getSource("density").setData(state.datasets[nextResolution]);
  state.currentResolution = nextResolution;
}

function openRefineModal(category, keepDraft = false) {
  if (!isSubtypeGranular(category)) {
    openCategoryExplorer(category);
    return;
  }
  state.modalMode = "refine";
  state.modalCategory = category;
  if (!keepDraft) {
    state.modalDraft = new Set(state.selectedSubcategories[category] || []);
  }
  const all = state.filterIndex.subcategories[category] || [];
  const label = state.filterIndex.top_categories.find((x) => x.key === category)?.label || category;

  ui.modalTitle.textContent = `Refine ${label}`;
  ui.modalSubtitle.textContent = `${state.modalDraft.size}/${all.length} selected`;
  ui.modalList.innerHTML = "";
  ui.modalSelectAllBtn.classList.remove("hidden");
  ui.modalSelectNoneBtn.classList.remove("hidden");
  ui.modalApplyBtn.classList.remove("hidden");
  ui.modalCancelBtn.textContent = "Cancel";

  for (const sub of all) {
    const id = `modal-sub-${Math.random().toString(36).slice(2)}`;
    const wrapper = document.createElement("label");
    wrapper.innerHTML = `<input type="checkbox" id="${id}" ${state.modalDraft.has(sub) ? "checked" : ""} /> ${sub}`;
    const input = wrapper.querySelector("input");
    input.addEventListener("change", (e) => {
      if (e.target.checked) state.modalDraft.add(sub);
      else state.modalDraft.delete(sub);
      ui.modalSubtitle.textContent = `${state.modalDraft.size}/${all.length} selected`;
    });
    ui.modalList.appendChild(wrapper);
  }

  ui.modalBackdrop.classList.remove("hidden");
  ui.modal.classList.remove("hidden");
}

function openCategoryExplorer(category) {
  state.modalMode = "explore";
  state.modalCategory = category;
  state.modalDraft = new Set();
  const all = state.filterIndex.subcategories[category] || [];
  const label = state.filterIndex.top_categories.find((x) => x.key === category)?.label || category;

  ui.modalTitle.textContent = `Included types: ${label}`;
  ui.modalSubtitle.textContent =
    "This layer is aggregated in current source files. These ship types are included under this main category.";
  ui.modalList.innerHTML = "";
  ui.modalSelectAllBtn.classList.add("hidden");
  ui.modalSelectNoneBtn.classList.add("hidden");
  ui.modalApplyBtn.classList.add("hidden");
  ui.modalCancelBtn.textContent = "Close";

  for (const sub of all) {
    const row = document.createElement("div");
    row.className = "modalListItem";
    row.textContent = sub;
    ui.modalList.appendChild(row);
  }

  ui.modalBackdrop.classList.remove("hidden");
  ui.modal.classList.remove("hidden");
}

function closeRefineModal() {
  state.modalCategory = null;
  state.modalMode = "refine";
  state.modalDraft = new Set();
  ui.modal.classList.add("hidden");
  ui.modalBackdrop.classList.add("hidden");
  ui.modalSelectAllBtn.classList.remove("hidden");
  ui.modalSelectNoneBtn.classList.remove("hidden");
  ui.modalApplyBtn.classList.remove("hidden");
  ui.modalCancelBtn.textContent = "Cancel";
}

function renderTopCategoryControls() {
  ui.topCategoryList.innerHTML = "";
  for (const cfg of state.filterIndex.top_categories) {
    const item = document.createElement("div");
    item.className = "categoryItem";
    const subtypeEnabled = cfg.has_subcategories && isSubtypeGranular(cfg.key);
    item.innerHTML = `
      <div class="categoryTopRow">
        <label class="categoryTitle">
          <input type="checkbox" id="cat-${cfg.key}" ${state.selectedTop[cfg.key] ? "checked" : ""} />
          <span>${cfg.label}</span>
        </label>
        ${
          cfg.has_subcategories
            ? `<button id="refine-${cfg.key}" class="btnRefine">${
                subtypeEnabled ? "Refine selection" : "Explore included types"
              }</button>`
            : ""
        }
      </div>
      <div id="summary-${cfg.key}" class="categoryMeta"></div>
    `;
    ui.topCategoryList.appendChild(item);

    const checkbox = item.querySelector(`#cat-${cfg.key}`);
    checkbox.addEventListener("change", (e) => {
      state.selectedTop[cfg.key] = e.target.checked;
      if (cfg.has_subcategories && e.target.checked) {
        // Main category selection defaults to all subcategories.
        state.selectedSubcategories[cfg.key] = new Set(state.filterIndex.subcategories[cfg.key] || []);
      }
      applyAllFilters();
    });

    if (cfg.has_subcategories) {
      const refineBtn = item.querySelector(`#refine-${cfg.key}`);
      refineBtn.addEventListener("click", () => openRefineModal(cfg.key));
    }
  }

  const granular = state.filterIndex.subcategory_granularity_available || {};
  const nonGranular = Object.entries(granular)
    .filter(([, available]) => !available)
    .map(([key]) => key.replace("_", " & "));
  if (nonGranular.length) {
    ui.subcategoryHint.textContent =
      `Subtype-level raster split is not present in source files for: ${nonGranular.join(", ")}. ` +
      "Use 'Explore included types' to see what each main category contains.";
    ui.subcategoryHint.classList.remove("hidden");
  }

  applyAllFilters();
}

function wirePanelBehavior() {
  ui.panelMinimizeBtn.addEventListener("click", () => {
    ui.panel.classList.toggle("collapsed");
    ui.panelMinimizeBtn.textContent = ui.panel.classList.contains("collapsed") ? "+" : "-";
  });
  ui.panelCloseBtn.addEventListener("click", () => {
    ui.panel.classList.add("hidden");
    ui.panelToggleBtn.classList.remove("hidden");
  });
  ui.panelToggleBtn.addEventListener("click", () => {
    ui.panel.classList.remove("hidden");
    ui.panelToggleBtn.classList.add("hidden");
    fitWorldInFrame(false);
  });
  ui.panel.addEventListener("mouseenter", () => ui.panel.classList.remove("panel-faded"));
  ui.panel.addEventListener("mouseleave", () => ui.panel.classList.add("panel-faded"));
}

function fitWorldInFrame(animate = true) {
  const leftPad = ui.panel.classList.contains("hidden") ? 20 : 390;
  map.fitBounds(WORLD_BOUNDS, {
    padding: { top: 20, bottom: 20, left: leftPad, right: 20 },
    maxZoom: 1.05,
    duration: animate ? 550 : 0
  });
}

function wireModalBehavior() {
  ui.modalBackdrop.addEventListener("click", closeRefineModal);
  ui.modalCancelBtn.addEventListener("click", closeRefineModal);
  ui.modalSelectAllBtn.addEventListener("click", () => {
    if (state.modalMode !== "refine") return;
    const all = state.filterIndex.subcategories[state.modalCategory] || [];
    state.modalDraft = new Set(all);
    openRefineModal(state.modalCategory, true);
  });
  ui.modalSelectNoneBtn.addEventListener("click", () => {
    if (state.modalMode !== "refine") return;
    state.modalDraft = new Set();
    openRefineModal(state.modalCategory, true);
  });
  ui.modalApplyBtn.addEventListener("click", () => {
    if (state.modalMode !== "refine") return;
    const cat = state.modalCategory;
    if (!cat) return;
    state.selectedSubcategories[cat] = new Set(state.modalDraft);
    state.selectedTop[cat] = state.selectedSubcategories[cat].size > 0;
    const checkbox = document.getElementById(`cat-${cat}`);
    if (checkbox) checkbox.checked = state.selectedTop[cat];
    applyAllFilters();
    closeRefineModal();
  });
}

function wireRenderingToggles() {
  ui.toggleHeat.addEventListener("change", applyDensityFilters);
  ui.toggleClusters.addEventListener("change", applyHotspotFilters);
  ui.togglePoints.addEventListener("change", applyHotspotFilters);
  ui.toggleDbscanClusters.addEventListener("change", applyDbscanVisibility);
  ui.fitWorldBtn.addEventListener("click", () => {
    fitWorldInFrame(true);
    setStatus("Fitted whole world");
  });
}

async function loadJson(path, optional = false) {
  const response = await fetch(path);
  if (!response.ok) {
    if (optional) return { type: "FeatureCollection", features: [] };
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return response.json();
}

function addDensityLayers() {
  map.addSource("density", { type: "geojson", data: state.datasets[state.currentResolution] });

  const basePaint = {
    "heatmap-weight": ["coalesce", ["get", "weight"], 0],
    "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 2, 0.65, 5, 0.9, 8, 1.15],
    "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 2, 16, 4, 25, 6, 34, 8, 44],
    "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 2, 0.78, 8, 0.66]
  };

  const categoryPaint = {
    global: [
      "interpolate", ["linear"], ["heatmap-density"],
      0.0, "rgba(3,105,161,0)",
      0.15, "#075985",
      0.35, "#0284c7",
      0.55, "#38bdf8",
      0.75, "#a5f3fc",
      1.0, "#e0f2fe"
    ],
    commercial: [
      "interpolate", ["linear"], ["heatmap-density"],
      0.0, "rgba(225,29,72,0)",
      0.20, "#be123c",
      0.45, "#e11d48",
      0.70, "#fb7185",
      1.0, "#ffe4e6"
    ],
    oil_gas: [
      "interpolate", ["linear"], ["heatmap-density"],
      0.0, "rgba(21,128,61,0)",
      0.20, "#166534",
      0.45, "#16a34a",
      0.70, "#4ade80",
      1.0, "#dcfce7"
    ],
    passenger: [
      "interpolate", ["linear"], ["heatmap-density"],
      0.0, "rgba(124,58,237,0)",
      0.20, "#6d28d9",
      0.45, "#8b5cf6",
      0.70, "#c4b5fd",
      1.0, "#f5f3ff"
    ]
  };

  for (const category of TOP_KEYS) {
    map.addLayer({
      id: `density-${category}`,
      type: "heatmap",
      source: "density",
      filter: ["==", ["get", "top_category"], category],
      paint: {
        ...basePaint,
        "heatmap-color": categoryPaint[category]
      }
    });
  }
}

function addHotspotLayersForCategory(category) {
  const sourceId = `hotspots-${category}`;
  map.addSource(sourceId, {
    type: "geojson",
    data: state.hotspotDatasets[category],
    cluster: true,
    clusterRadius: 48,
    clusterMaxZoom: 7
  });

  map.addLayer({
    id: `hotspot-clusters-${category}`,
    type: "circle",
    source: sourceId,
    filter: ["has", "point_count"],
    paint: {
      "circle-color": CATEGORY_COLORS[category],
      "circle-radius": ["step", ["get", "point_count"], 12, 30, 18, 100, 24, 250, 30],
      "circle-opacity": 0.78,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1
    }
  });

  map.addLayer({
    id: `hotspot-cluster-count-${category}`,
    type: "symbol",
    source: sourceId,
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["get", "point_count_abbreviated"],
      "text-size": 11
    },
    paint: { "text-color": "#ffffff" }
  });

  map.addLayer({
    id: `hotspot-points-${category}`,
    type: "circle",
    source: sourceId,
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": CATEGORY_COLORS[category],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 2.4, 8, 5.2],
      "circle-opacity": 0.82,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.8
    }
  });

  map.on("click", `hotspot-points-${category}`, (e) => {
    const feature = e.features?.[0];
    if (!feature) return;
    const p = feature.properties;
    const html =
      `<b>Category:</b> ${category.replace("_", " & ")}<br>` +
      `<b>Density:</b> ${Number(p.density).toLocaleString()}<br>` +
      `<b>Intensity:</b> ${Number(p.intensity).toFixed(3)}`;
    new maplibregl.Popup().setLngLat(feature.geometry.coordinates).setHTML(html).addTo(map);
  });
}

function addDbscanClusterLayer() {
  map.addSource("dbscan-clusters-src", {
    type: "geojson",
    data: state.dbscanClusters || { type: "FeatureCollection", features: [] }
  });

  map.addLayer({
    id: "dbscan-clusters",
    type: "circle",
    source: "dbscan-clusters-src",
    filter: [">=", ["to-number", ["get", "cluster_id"], -1], 0],
    paint: {
      "circle-color": [
        "interpolate",
        ["linear"],
        ["to-number", ["get", "cluster_id"], 0],
        0, "#1d4ed8",
        8, "#0f766e",
        16, "#b45309",
        24, "#7c3aed",
        32, "#be123c"
      ],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 2.5, 8, 8.5],
      "circle-opacity": 0.58,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.7
    },
    layout: { visibility: "none" }
  });

  map.addLayer({
    id: "dbscan-noise",
    type: "circle",
    source: "dbscan-clusters-src",
    filter: ["<", ["to-number", ["get", "cluster_id"], -1], 0],
    paint: {
      "circle-color": "#334155",
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 1.4, 8, 3.2],
      "circle-opacity": 0.34
    },
    layout: { visibility: "none" }
  });

  map.on("click", "dbscan-clusters", (e) => {
    const feature = e.features?.[0];
    if (!feature) return;
    const p = feature.properties || {};
    const html =
      `<b>DBSCAN cluster:</b> ${Number(p.cluster_id)}<br>` +
      `<b>Density sum:</b> ${Number(p.density_sum || 0).toLocaleString()}<br>` +
      `<b>KDE score:</b> ${Number(p.kde_score_norm || 0).toFixed(3)}`;
    new maplibregl.Popup().setLngLat(feature.geometry.coordinates).setHTML(html).addTo(map);
  });
}

async function initializeData() {
  const [low, mid, high, hsCommercial, hsOilGas, hsPassenger, dbscanClusters, filterIndex, metadata] =
    await Promise.all([
      loadJson(DATA_PATHS.low),
      loadJson(DATA_PATHS.mid),
      loadJson(DATA_PATHS.high),
      loadJson(DATA_PATHS.hotspotsCommercial),
      loadJson(DATA_PATHS.hotspotsOilGas),
      loadJson(DATA_PATHS.hotspotsPassenger),
      loadJson(DATA_PATHS.dbscanClusters, true),
      loadJson(DATA_PATHS.filterIndex),
      loadJson(DATA_PATHS.metadata)
    ]);

  state.datasets.low = low;
  state.datasets.mid = mid;
  state.datasets.high = high;
  state.hotspotDatasets.commercial = hsCommercial;
  state.hotspotDatasets.oil_gas = hsOilGas;
  state.hotspotDatasets.passenger = hsPassenger;
  state.dbscanClusters = dbscanClusters;
  state.filterIndex = filterIndex;
  state.metadata = metadata;

  for (const category of HOTSPOT_KEYS) {
    state.selectedSubcategories[category] = new Set(filterIndex.subcategories[category] || []);
  }
}

let frameQueued = false;
function onMapFrame() {
  if (frameQueued) return;
  frameQueued = true;
  requestAnimationFrame(() => {
    updateMapMetrics();
    updateDensitySourceForZoom();
    frameQueued = false;
  });
}

map.on("zoom", onMapFrame);
map.on("move", onMapFrame);
map.on("zoomend", () => {
  updateMapMetrics();
  updateDensitySourceForZoom();
});

map.on("load", async () => {
  try {
    setStatus("Loading indexed datasets...");
    await initializeData();
    state.currentResolution = getResolutionFromZoom(map.getZoom());
    addDensityLayers();
    for (const category of HOTSPOT_KEYS) addHotspotLayersForCategory(category);
    addDbscanClusterLayer();

    wirePanelBehavior();
    wireModalBehavior();
    wireRenderingToggles();
    renderTopCategoryControls();
    updateMapMetrics();
    updateDensitySourceForZoom();
    applyAllFilters();
    fitWorldInFrame(false);
    setStatus("Ready");
  } catch (err) {
    console.error(err);
    setStatus("Data load failed. Run build_webapp_data.py and start local server.", true);
  }
});
