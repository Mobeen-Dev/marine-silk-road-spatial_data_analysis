#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

.venv/Scripts/python.exe export_traffic_data.py
.venv/Scripts/python.exe webapp/build_webapp_data.py
.venv/Scripts/python.exe spatial_phase1_esda.py
.venv/Scripts/python.exe spatial_phase2_ppa.py
.venv/Scripts/python.exe spatial_phase3_autocorrelation.py
.venv/Scripts/python.exe spatial_phase4_regression.py
.venv/Scripts/python.exe validate_webapp.py

echo "All roadmap phases completed successfully."

