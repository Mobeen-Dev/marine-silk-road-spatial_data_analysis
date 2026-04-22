# Marine Silk Road — Global Marine Traffic Visualization & Analysis

Professional, reproducible tools and a lightweight web client for exploring global ship-density datasets.

---

## Project overview

This repository contains data-processing scripts, reproducible analysis outputs, and a browser-based webapp to visualize global marine traffic density across multiple vessel categories. It was designed to safely analyze very large raster datasets (multi-gigabyte GeoTIFFs) using a chunked workflow, produce multiscale aggregated outputs, and provide a MapLibre-based frontend for interactive exploration.

Key goals
- Map three primary categories of marine traffic (Global, Commercial, Oil & Gas, Passenger)
- Detect and visualize high-density hotspots
- Provide hierarchical filtering (top-level + subcategory explorer)
- Produce reproducible downsampled exports for fast client rendering

---

## Repository layout (high level)

- `dataset/` — original source rasters (large GeoTIFFs). These are *input* artifacts and are not tracked after processing.
- `analysis_outputs/` — algorithmic outputs, logs, and deliverables from analysis scripts (statistics, briefs, exported CSV/JSON artifacts).
- `webapp/` — static web frontend (MapLibre GL JS) and supporting scripts. `webapp/data/` is the target for generated visualization payloads (low/mid/high GeoJSON or tile outputs).
- `visuals/`, `media/` — screenshots and generated presentation artifacts.

Important scripts
- `data_exploration.py` — lightweight metadata and sample checks against source rasters.
- `data_analysis_chunked.py` — memory-safe raster sampling and statistics (chunked window reads). Produces `analysis_outputs/raster_statistics_chunked.json`.
- `export_traffic_data.py` — core downsampling/export pipeline entrypoint (builds aggregated CSV/GeoJSON artifacts).
- `webapp/build_webapp_data.py` — transforms analysis outputs into final `webapp/data/` payloads used by the frontend.
- `validate_webapp.py` — repository-specific validation to check generated webapp artifacts and configuration.
- `diagnose_current_state.py` — helper diagnostics for verifying inputs, outputs, and known issues.
- `visualize_traffic.py` — standalone visualization helper (Leaflet-based HTML artifact under `media/`).

---

## Quickstart (run from repository root)

1. Create and activate a virtual environment (Windows example):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1  # or use activate.bat on cmd.exe
   ```

2. Install dependencies

   - This repository does not enforce a centralized `requirements.txt`. Inspect the top of each script for imports (e.g., `rasterio`, `numpy`, `pandas`, `geopandas`) and install what your environment requires.
   - Example (adjust to your environment):

     ```powershell
     pip install rasterio numpy pandas geopandas shapely
     ```

3. Build the visualization payloads (two-stage pipeline):

   ```powershell
   .\.venv\Scripts\python.exe export_traffic_data.py
   .\.venv\Scripts\python.exe webapp\build_webapp_data.py
   ```

   - `export_traffic_data.py` extracts downsampled CSV/aggregates from raw rasters.
   - `webapp\build_webapp_data.py` converts those aggregates into `webapp/data/` payloads used by the frontend.

4. Run the lightweight local server and open the webapp

   ```powershell
   .\.venv\Scripts\python.exe -m http.server 8000
   # Open: http://127.0.0.1:8000/webapp/
   ```

5. Run repository validation (smoke checks):

   ```powershell
   .\.venv\Scripts\python.exe validate_webapp.py
   ```

---

## Data notes & constraints (important)

These points are derived from validated analysis runs (see `analysis_outputs/`):

- Source rasters: four main GeoTIFFs (Global, Commercial, Oil & Gas, Passenger). Each can be several gigabytes in size.
- CRS: EPSG:4326 (WGS84). Native resolution: 0.005° grid.
- NoData sentinel: 2147483647 (int32). Values are counts/densities.
- Full-coverage arrays are very large (~2.45 billion pixels per large raster). Do NOT attempt to load entire rasters into memory — use the chunked tools provided.

Because of size, the pipeline performs:
- Chunked window reads (rasterio.Window) and statistical sampling.
- Downsampling to multi-resolution aggregates (1.0°, 0.5°, 0.25° grids) for efficient client rendering.
- Log-scaling and p99 clipping are recommended preprocessing steps for visualization (scripts include optional transforms).

---

## Webapp features & current status

Implemented
- MapLibre GL JS frontend with multiscale density layers (low/mid/high).
- Hierarchical controls panel with top-level dataset toggles and a Category Explorer modal for aggregated sources.
- Toggleable heatmap, clustered hotspots, and point layers.
- Fit-world button (centers/zooms to show entire globe in one frame) and a fadeable control panel.

Known limitations
- Where the original dataset only contains top-level aggregated rasters (e.g., `ShipDensity_Commercial` aggregated across many vessel subtypes), per-subtype map updates cannot be shown until subtype-separated aggregates are produced. The UI surfaces an "Explore included types" modal in that case.
- Visual seam artifacts can appear if data layers or tile-wrapping are misconfigured — see `diagnose_current_state.py` and the Webapp `renderWorldCopies` settings.
- Generating full tile pyramids (MBTiles or vector-grid tiles) from raw rasters requires significant disk and CPU resources.

---

## Analysis outputs

Look under `analysis_outputs/` for: brief and presentation-ready text answers (Q1/Q2/Q3), chunked sampling logs, the computed raster statistics JSON, and example CSV/GeoJSON exports (when generated by the pipeline).

Recommended reproducible steps
1. Run `data_exploration.py` to validate local dataset presence and inspect metadata.
2. Run `data_analysis_chunked.py` to produce coverage and p99/p95 statistics (saved to `analysis_outputs/`).
3. Run `export_traffic_data.py` to produce downsampled CSVs.

---

## Development notes & recommended approach

- Always inspect script imports first — there is no enforced `requirements.txt` in the repo.
- For large-scale production exports, prefer running `export_traffic_data.py` on a machine with ample disk and memory or in a cloud VM. Use streaming and chunked operations.
- For the frontend, prefer MapLibre GL JS (used here) or deck.gl for GPU-accelerated aggregation and continuous zoom smoothing when you need higher interactivity.
- Precompute per-category and per-subcategory aggregates (tiles or vector-grid JSON) to enable instant client filtering; toggling layer visibility is far cheaper than re-aggregating on the client.

---

## Troubleshooting

- If the webapp shows seams or duplicate worlds, check `webapp/app.js` `renderWorldCopies` and source tile configs.
- If subcategory toggles do not change the map, check `webapp/data/filter_index.json` (produced by preprocessing) — it indicates whether per-subtype aggregates exist.
- If a script fails with memory errors, retry with smaller `--sample-windows` or configure chunk sizes in `data_analysis_chunked.py`.

---

## Roadmap & recommended next steps

1. Generate multi-resolution tile/MBTiles sets for MapLibre (or vector-grid GeoJSON per zoom) to remove client-side heavy lifting.
2. Produce per-subcategory aggregates (if subtype-level exploration is required).
3. Integrate automated dependency management (`requirements.txt` or `pyproject.toml`) and CI checks for `validate_webapp.py`.
4. Add performance benchmarks for interactive filter latency and memory usage.

---

## Contributing

Contributions are welcome. Open issues for bugs or feature requests. When proposing large processing runs (tile generation), include resource estimates so maintainers can approve cloud runs.

---

## Contact

Repository maintainer: see repository owner. For urgent questions open an issue with the `diagnostics` label and include the `analysis_outputs/raster_statistics_chunked.json` excerpt when possible.

---

*This README is intended to be a concise operational guide. For the technical background, check `analysis_outputs/q1_brief.txt`, `analysis_outputs/q2_brief.txt`, and `analysis_outputs/q3_brief.txt`.*
