from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image


ROOT = Path(".")
VISUALS_DIR = ROOT / "visuals"
ANALYSIS_DIR = ROOT / "analysis_outputs"
MEDIA_DIR = ROOT / "media"


def image_metrics(path: Path) -> dict:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, w, _ = rgb.shape

    strip = max(8, min(40, w // 30))
    left_right_diff = float(np.abs(rgb[:, :strip] - rgb[:, -strip:]).mean())
    top_bottom_diff = float(np.abs(rgb[:strip, :] - rgb[-strip:, :]).mean())

    vertical_edges = [c for c in range(256, w, 256) if 1 <= c < w]
    horizontal_edges = [r for r in range(256, h, 256) if 1 <= r < h]

    v_contrast = [
        float(np.abs(rgb[:, c] - rgb[:, c - 1]).mean()) for c in vertical_edges
    ]
    h_contrast = [
        float(np.abs(rgb[r, :] - rgb[r - 1, :]).mean()) for r in horizontal_edges
    ]

    return {
        "file": path.name,
        "width": w,
        "height": h,
        "left_right_diff": left_right_diff,
        "top_bottom_diff": top_bottom_diff,
        "tile_vertical_contrast_mean": float(np.mean(v_contrast)) if v_contrast else 0.0,
        "tile_horizontal_contrast_mean": float(np.mean(h_contrast)) if h_contrast else 0.0,
    }


def csv_metrics(path: Path) -> dict:
    df = pd.read_csv(path)
    lat = df["latitude"]
    lon = df["longitude"]
    intensity = df["intensity"]
    density = df["density"]

    return {
        "file": path.name,
        "rows": int(len(df)),
        "lat_min": float(lat.min()),
        "lat_max": float(lat.max()),
        "lon_min": float(lon.min()),
        "lon_max": float(lon.max()),
        "invalid_lat_rows": int(((lat < -90) | (lat > 90)).sum()),
        "invalid_lon_rows": int(((lon < -180) | (lon > 180)).sum()),
        "missing_rows": int(df.isna().any(axis=1).sum()),
        "density_min": float(density.min()),
        "density_max": float(density.max()),
        "intensity_min": float(intensity.min()),
        "intensity_max": float(intensity.max()),
        "intensity_p95": float(intensity.quantile(0.95)),
        "intensity_p99": float(intensity.quantile(0.99)),
    }


def main() -> None:
    visuals = sorted(VISUALS_DIR.glob("*.png"))
    csvs = [
        ANALYSIS_DIR / "traffic_commercial_world.csv",
        ANALYSIS_DIR / "traffic_passenger_world.csv",
        ANALYSIS_DIR / "traffic_oil_gas_world.csv",
        ANALYSIS_DIR / "traffic_combined_hotspots.csv",
    ]

    out = {
        "visual_metrics": [image_metrics(v) for v in visuals],
        "csv_metrics": [csv_metrics(c) for c in csvs],
        "artifact_sizes_mb": {
            "advanced_html": round((MEDIA_DIR / "shipping_visualization_advanced.html").stat().st_size / (1024 * 1024), 3)
            if (MEDIA_DIR / "shipping_visualization_advanced.html").exists()
            else None,
            "combined_html": round((MEDIA_DIR / "shipping_heatmap_combined.html").stat().st_size / (1024 * 1024), 3)
            if (MEDIA_DIR / "shipping_heatmap_combined.html").exists()
            else None,
        },
    }

    output_json = ANALYSIS_DIR / "diagnostics_current_state.json"
    output_txt = ANALYSIS_DIR / "diagnostics_current_state.txt"
    output_json.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = []
    lines.append("Current Visualization Diagnostics")
    lines.append("=" * 40)
    lines.append("")
    lines.append("Image diagnostics:")
    for row in out["visual_metrics"]:
        lines.append(
            f"- {row['file']}: size={row['width']}x{row['height']}, "
            f"LR diff={row['left_right_diff']:.2f}, TB diff={row['top_bottom_diff']:.2f}, "
            f"tile contrast(v/h)={row['tile_vertical_contrast_mean']:.2f}/{row['tile_horizontal_contrast_mean']:.2f}"
        )

    lines.append("")
    lines.append("CSV diagnostics:")
    for row in out["csv_metrics"]:
        lines.append(
            f"- {row['file']}: rows={row['rows']:,}, "
            f"lat=[{row['lat_min']:.4f}, {row['lat_max']:.4f}], "
            f"lon=[{row['lon_min']:.4f}, {row['lon_max']:.4f}], "
            f"invalid_lat={row['invalid_lat_rows']}, invalid_lon={row['invalid_lon_rows']}, "
            f"missing={row['missing_rows']}, intensity_max={row['intensity_max']:.4f}"
        )

    lines.append("")
    lines.append("Artifact sizes (MB):")
    for key, val in out["artifact_sizes_mb"].items():
        lines.append(f"- {key}: {val}")

    output_txt.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote: {output_json}")
    print(f"Wrote: {output_txt}")


if __name__ == "__main__":
    main()
