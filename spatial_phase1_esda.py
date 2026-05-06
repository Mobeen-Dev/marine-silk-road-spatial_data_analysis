from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

from spatial_analysis_common import (
    ANALYSIS_DIR,
    CATEGORY_FILES,
    aggregate_grid,
    ensure_country_boundaries,
    ensure_directories,
    read_category_frames,
    with_global,
)


matplotlib.use("Agg")
import matplotlib.pyplot as plt


def build_data_structure_report() -> dict:
    entries = []
    for category, path in CATEGORY_FILES.items():
        entries.append(
            {
                "category": category,
                "source_file": str(path),
                "spatial_data_structure": "surface",
                "rationale": (
                    "Ship density is represented as a continuous field sampled on a regular raster grid. "
                    "Each cell stores magnitude, so the data is modeled as a surface rather than discrete vectors or a graph."
                ),
                "analysis_implication": (
                    "Use gridded aggregation, zonal statistics, and spatial autocorrelation methods before deriving point/cluster views."
                ),
            }
        )
    return {"classification": entries}


def build_summary_stats(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for category, frame in frames.items():
        density = frame["density"].astype(float)
        intensity = frame["intensity"].astype(float)
        rows.append(
            {
                "category": category,
                "rows": int(len(frame)),
                "density_min": float(density.min()),
                "density_max": float(density.max()),
                "density_mean": float(density.mean()),
                "density_median": float(density.median()),
                "density_p95": float(density.quantile(0.95)),
                "density_p99": float(density.quantile(0.99)),
                "intensity_min": float(intensity.min()),
                "intensity_max": float(intensity.max()),
                "intensity_mean": float(intensity.mean()),
                "intensity_median": float(intensity.median()),
                "intensity_p95": float(intensity.quantile(0.95)),
                "intensity_p99": float(intensity.quantile(0.99)),
            }
        )
    return pd.DataFrame(rows).sort_values("category").reset_index(drop=True)


def write_histograms(frames: dict[str, pd.DataFrame], output_path: Path) -> None:
    categories = list(frames.keys())
    n_cols = 2
    n_rows = int(np.ceil(len(categories) / n_cols))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(12, 4 * n_rows))
    axes = np.array(axes).reshape(-1)

    for idx, category in enumerate(categories):
        ax = axes[idx]
        density = frames[category]["density"].astype(float)
        log_density = np.log10(density + 1.0)
        ax.hist(log_density, bins=60, color="#1d4ed8", alpha=0.85)
        ax.set_title(f"{category}: log10(density + 1)")
        ax.set_xlabel("log10(density + 1)")
        ax.set_ylabel("Cell count")
        ax.grid(alpha=0.2)

    for idx in range(len(categories), len(axes)):
        axes[idx].axis("off")

    fig.suptitle("Phase 1 ESDA Density Distributions", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def build_country_choropleth(global_frame: pd.DataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    grid = aggregate_grid(global_frame, grid_deg=1.0)
    points = gpd.GeoDataFrame(
        grid,
        geometry=gpd.points_from_xy(grid["lon_bin"], grid["lat_bin"]),
        crs="EPSG:4326",
    )
    countries = ensure_country_boundaries()
    joined = gpd.sjoin(
        points,
        countries[["country", "geometry"]],
        how="inner",
        predicate="within",
    )
    country_stats = (
        joined.groupby("country", as_index=False)
        .agg(
            mean_density=("density_mean", "mean"),
            mean_intensity=("intensity_mean", "mean"),
            summed_density=("density_sum", "sum"),
            points=("points", "sum"),
            occupied_cells=("country", "size"),
        )
        .sort_values("mean_density", ascending=False)
    )
    choropleth = countries.merge(country_stats, on="country", how="left")
    for col in ("mean_density", "mean_intensity", "summed_density", "points", "occupied_cells"):
        choropleth[col] = choropleth[col].fillna(0)
    return choropleth, country_stats


def write_notebook_stub(summary_csv: Path, choropleth_geojson: Path, hist_png: Path) -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Marine Silk Road - Phase 1 ESDA Report\n",
                    "\n",
                    "This notebook captures Phase 1 deliverables requested in the roadmap:\n",
                    "1. Raster data structure classification as surfaces.\n",
                    "2. Global summary statistics by vessel category.\n",
                    "3. Country-level choropleth-ready output from gridded traffic data.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import pandas as pd\n",
                    "import geopandas as gpd\n",
                    f"summary = pd.read_csv(r'{summary_csv.as_posix()}')\n",
                    "summary\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    f"choropleth = gpd.read_file(r'{choropleth_geojson.as_posix()}')\n",
                    "choropleth[['country', 'mean_density', 'occupied_cells']].sort_values('mean_density', ascending=False).head(20)\n",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"Histogram output: `{hist_png.as_posix()}`\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.x"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (ANALYSIS_DIR / "esda_report.ipynb").write_text(
        json.dumps(notebook, indent=2), encoding="utf-8"
    )


def main() -> None:
    ensure_directories()
    frames = with_global(read_category_frames())

    structure_report = build_data_structure_report()
    (ANALYSIS_DIR / "phase1_data_structure.json").write_text(
        json.dumps(structure_report, indent=2), encoding="utf-8"
    )

    summary = build_summary_stats(frames)
    summary_csv = ANALYSIS_DIR / "phase1_summary_statistics.csv"
    summary_json = ANALYSIS_DIR / "phase1_summary_statistics.json"
    summary.to_csv(summary_csv, index=False)
    summary_json.write_text(summary.to_json(orient="records", indent=2), encoding="utf-8")

    hist_png = ANALYSIS_DIR / "phase1_density_histograms.png"
    write_histograms(frames, hist_png)

    choropleth_gdf, country_stats = build_country_choropleth(frames["global"])
    choropleth_path = ANALYSIS_DIR / "phase1_country_choropleth.geojson"
    country_stats_csv = ANALYSIS_DIR / "phase1_country_stats.csv"
    choropleth_gdf.to_file(choropleth_path, driver="GeoJSON")
    country_stats.to_csv(country_stats_csv, index=False)

    write_notebook_stub(summary_csv, choropleth_path, hist_png)

    print(f"Wrote: {ANALYSIS_DIR / 'phase1_data_structure.json'}")
    print(f"Wrote: {summary_csv}")
    print(f"Wrote: {summary_json}")
    print(f"Wrote: {hist_png}")
    print(f"Wrote: {choropleth_path}")
    print(f"Wrote: {country_stats_csv}")
    print(f"Wrote: {ANALYSIS_DIR / 'esda_report.ipynb'}")


if __name__ == "__main__":
    main()

