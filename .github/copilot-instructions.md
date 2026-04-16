# Copilot Instructions for `marine-silk-road`

## Build, test, and lint commands

This repository is script-driven (no in-repo `pyproject.toml`, `requirements*.txt`, `pytest.ini`, or lint config).

Run commands from the repository root with the project virtualenv interpreter:

```powershell
.venv\Scripts\python.exe <script>
```

Primary build pipeline:

```powershell
.venv\Scripts\python.exe export_traffic_data.py
.venv\Scripts\python.exe webapp\build_webapp_data.py
```

Run the web app locally:

```powershell
.venv\Scripts\python.exe -m http.server 8000
```

Open: `http://127.0.0.1:8000/webapp/`

Validation commands (test-equivalent in this repo):

```powershell
.venv\Scripts\python.exe validate_webapp.py
```

Single targeted check example:

```powershell
Get-Content analysis_outputs\webapp_validation.json -Raw | ConvertFrom-Json | Select-Object -ExpandProperty config_flags | Select-Object -ExpandProperty renderWorldCopies_false
```

Supporting diagnostics/analysis scripts:

```powershell
.venv\Scripts\python.exe data_exploration.py
.venv\Scripts\python.exe data_analysis_chunked.py
.venv\Scripts\python.exe diagnose_current_state.py
```

## High-level architecture

The project has a two-stage data pipeline plus a browser client:

1. `dataset\` contains raw shipping density GeoTIFF rasters (commercial, passenger, oil/gas, and global context metadata).
2. `export_traffic_data.py` converts raw rasters into downsampled CSV artifacts in `analysis_outputs\`:
   - `traffic_*_world.csv` for density surfaces
   - `traffic_*_hotspots.csv` and `traffic_combined_hotspots.csv` for hotspot layers
3. `webapp\build_webapp_data.py` transforms CSV outputs into web-ready GeoJSON in `webapp\data\`:
   - `density_low.geojson` (1.0°), `density_mid.geojson` (0.5°), `density_high.geojson` (0.25°)
   - `hotspots.geojson` and `metadata.json`
4. `webapp\index.html` + `webapp\styles.css` + `webapp\app.js` load those files in MapLibre GL JS, switch density resolution by zoom, and render heatmap + clustered hotspots + category filters.
5. `validate_webapp.py` and `diagnose_current_state.py` are the main regression checks for generated artifacts and map configuration.

Related but separate output path:
- `visualize_traffic.py` creates a standalone Leaflet HTML artifact in `media\shipping_visualization_advanced.html` (not the main `webapp\` MapLibre app).

## Key repository conventions

- **Longitude normalization is mandatory** before GeoJSON export: use the existing `wrap_longitude()` convention (`[-180, 180)`). `validate_webapp.py` enforces `< 180` upper bound.
- **Use the existing multiscale contract** end-to-end:
  - file keys: `low`, `mid`, `high`
  - grids: `1.0°`, `0.5°`, `0.25°`
  - frontend thresholds in `app.js`: `3.5` and `5.5` zoom cutovers
- **Preserve data schema assumptions in `build_webapp_data.py`**:
  - category CSVs must include `latitude`, `longitude`, `intensity`, `density`
  - hotspot CSV must include `latitude`, `longitude`, `density`, `intensity`, `category`
- **Web density aggregation uses `intensity` as weight** (already log-scaled upstream by `export_traffic_data.py`), then applies robust `p99` clipping/normalization.
- **Generated data locations are intentional**: `analysis_outputs\*.csv` and `webapp\data\*` are treated as generated artifacts (see `.gitignore`) and are rebuilt by scripts rather than edited manually.
- **Run scripts from repo root**; most paths are relative and assume that working directory.
