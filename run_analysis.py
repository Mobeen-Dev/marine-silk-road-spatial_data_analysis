from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_step(label: str, args: list[str]) -> None:
    print(f"\n=== {label} ===")
    completed = subprocess.run(args, cwd=ROOT)
    if completed.returncode != 0:
        raise RuntimeError(f"Step failed ({label}) with exit code {completed.returncode}")


def main() -> None:
    py = sys.executable
    steps = [
        ("Export traffic CSVs", [py, "export_traffic_data.py"]),
        ("Build webapp data", [py, "webapp\\build_webapp_data.py"]),
        ("Phase 1 ESDA", [py, "spatial_phase1_esda.py"]),
        ("Phase 2 PPA", [py, "spatial_phase2_ppa.py"]),
        ("Phase 3 autocorrelation", [py, "spatial_phase3_autocorrelation.py"]),
        ("Phase 4 regression", [py, "spatial_phase4_regression.py"]),
        ("Validate webapp", [py, "validate_webapp.py"]),
    ]
    for label, args in steps:
        run_step(label, args)
    print("\nAll roadmap phases completed successfully.")


if __name__ == "__main__":
    main()

