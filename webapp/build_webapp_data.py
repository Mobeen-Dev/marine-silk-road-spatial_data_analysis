from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / "analysis_outputs"
WEBAPP_DIR = ROOT / "webapp"
DATA_DIR = WEBAPP_DIR / "data"


CATEGORY_FILES = {
    "commercial": ANALYSIS_DIR / "traffic_commercial_world.csv",
    "passenger": ANALYSIS_DIR / "traffic_passenger_world.csv",
    "oil_gas": ANALYSIS_DIR / "traffic_oil_gas_world.csv",
}

HOTSPOT_FILE = ANALYSIS_DIR / "traffic_combined_hotspots.csv"


def wrap_longitude(series: pd.Series) -> pd.Series:
    """Normalize longitudes to [-180, 180) for antimeridian-safe rendering."""
    return ((series + 180.0) % 360.0) - 180.0


def aggregate_density(df: pd.DataFrame, grid_deg: float) -> dict:
    """
    Aggregate weighted intensity into a regular WGS84 grid.

    Returns a GeoJSON FeatureCollection with properties:
      - weight: normalized [0, 1], robustly clipped by p99
      - raw_weight: summed pre-normalized weight
      - points: number of samples in the cell
    """
    work = df[["latitude", "longitude", "weight"]].copy()
    work["longitude"] = wrap_longitude(work["longitude"])

    work["lat_bin"] = (
        np.floor((work["latitude"] + 90.0) / grid_deg) * grid_deg - 90.0 + grid_deg / 2.0
    )
    work["lon_bin"] = (
        np.floor((work["longitude"] + 180.0) / grid_deg) * grid_deg - 180.0 + grid_deg / 2.0
    )

    grouped = (
        work.groupby(["lat_bin", "lon_bin"], as_index=False)
        .agg(raw_weight=("weight", "sum"), points=("weight", "size"))
        .sort_values("raw_weight", ascending=False)
    )

    p99 = float(grouped["raw_weight"].quantile(0.99)) if not grouped.empty else 1.0
    p99 = p99 if p99 > 0 else 1.0
    grouped["weight"] = np.clip(grouped["raw_weight"] / p99, 0.0, 1.0)

    features = []
    for row in grouped.itertuples(index=False):
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(row.lon_bin), 6), round(float(row.lat_bin), 6)],
                },
                "properties": {
                    "weight": round(float(row.weight), 6),
                    "raw_weight": round(float(row.raw_weight), 6),
                    "points": int(row.points),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def to_hotspot_geojson(df: pd.DataFrame) -> dict:
    work = df.copy()
    work["longitude"] = wrap_longitude(work["longitude"])

    features = []
    for row in work.itertuples(index=False):
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(row.longitude), 6), round(float(row.latitude), 6)],
                },
                "properties": {
                    "category": str(row.category),
                    "density": int(row.density),
                    "intensity": float(row.intensity),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    category_frames = []
    counts = {}

    for category, file_path in CATEGORY_FILES.items():
        df = pd.read_csv(file_path)
        required = {"latitude", "longitude", "intensity", "density"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"{file_path.name} missing required columns: {sorted(missing)}")

        # Weight uses log density already in dataset; this gives smoother global diffusion surfaces.
        frame = df[["latitude", "longitude", "intensity"]].copy()
        frame["weight"] = frame["intensity"]
        frame["category"] = category
        category_frames.append(frame)
        counts[f"{category}_rows"] = int(len(frame))

    merged = pd.concat(category_frames, ignore_index=True)
    low = aggregate_density(merged, grid_deg=1.0)
    mid = aggregate_density(merged, grid_deg=0.5)
    high = aggregate_density(merged, grid_deg=0.25)

    hotspots_df = pd.read_csv(HOTSPOT_FILE)
    hotspots = to_hotspot_geojson(hotspots_df)

    write_json(DATA_DIR / "density_low.geojson", low)
    write_json(DATA_DIR / "density_mid.geojson", mid)
    write_json(DATA_DIR / "density_high.geojson", high)
    write_json(DATA_DIR / "hotspots.geojson", hotspots)

    metadata = {
        "crs": "EPSG:4326",
        "grid_degrees": {"low": 1.0, "mid": 0.5, "high": 0.25},
        "source_csv_rows": counts,
        "output_features": {
            "density_low": len(low["features"]),
            "density_mid": len(mid["features"]),
            "density_high": len(high["features"]),
            "hotspots": len(hotspots["features"]),
        },
        "bounds": {"west": -180.0, "south": -85.0, "east": 180.0, "north": 85.0},
    }
    (DATA_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("Webapp data written to:", DATA_DIR)
    for key, value in metadata["output_features"].items():
        print(f"  {key}: {value:,}")


if __name__ == "__main__":
    main()
