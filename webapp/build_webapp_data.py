from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / "analysis_outputs"
WEBAPP_DIR = ROOT / "webapp"
DATA_DIR = WEBAPP_DIR / "data"

TOP_CATEGORY_FILES = {
    "commercial": ANALYSIS_DIR / "traffic_commercial_world.csv",
    "oil_gas": ANALYSIS_DIR / "traffic_oil_gas_world.csv",
    "passenger": ANALYSIS_DIR / "traffic_passenger_world.csv",
}

DATASET_CLASSES = {
    "global": "ShipDensity_Global",
    "commercial": "ShipDensity_Commercial",
    "oil_gas": "ShipDensity_OilGas",
    "passenger": "ShipDensity_Passenger",
}

SUBCATEGORIES = {
    "global": ["ALL SHIP TYPES"],
    "commercial": [
        "BULK CARRIER",
        "GENERAL CARGO",
        "TUG",
        "OFFSHORE SUPPLY SHIP",
        "CONTAINER SHIP",
        "OIL/CHEMICAL TANKER",
        "OIL PRODUCTS TANKER",
        "CRUDE OIL TANKER",
        "LPG TANKER",
        "VEHICLES CARRIER",
        "RESEARCH/SURVEY VESSEL",
        "REEFER",
        "CHEMICAL TANKER",
        "RO-RO CARGO",
        "CREW BOAT",
        "LNG TANKER",
        "SUPPLY VESSEL",
        "INLAND TANKER",
        "LANDING CRAFT",
        "HOPPER DREDGER",
        "BUNKERING TANKER",
        "PATROL VESSEL",
        "MULTI PURPOSE OFFSHORE VESSEL",
        "CEMENT CARRIER",
        "PUSHER TUG",
        "FIRE FIGHTING VESSEL",
        "UTILITY VESSEL",
        "SPECIAL VESSEL",
        "ANCHOR HANDLING VESSEL",
        "TANKER",
        "CARGO / CONTAINERSHIP",
        "TOWING VESSEL",
        "ORE CARRIER",
        "FISH CARRIER",
        "ASPHALT / BITUMEN TANKER",
        "DECK CARGO SHIP",
        "PASSENGER / CARGO SHIP",
        "LIVESTOCK CARRIER",
        "SHUTTLE TANKER",
        "RO-RO / CONTAINER CARRIER",
        "WATER TANKER",
        "ORE / OIL CARRIER",
        "LIMESTONE CARRIER",
    ],
    "oil_gas": [
        "PLATFORM",
        "FLOATING STORAGE / PRODUCTION",
        "DRILLING JACK UP",
        "DRILLING RIG",
        "WELL STIMULATION VESSEL",
    ],
    "passenger": [
        "PASSENGER SHIP",
        "RO-RO / PASSENGER SHIP",
    ],
}

RESOLUTION_GRIDS = {"low": 1.0, "mid": 0.5, "high": 0.25}
HOTSPOT_FILE = ANALYSIS_DIR / "traffic_combined_hotspots.csv"
CLUSTERS_FILE = DATA_DIR / "clusters.geojson"


def wrap_longitude(series: pd.Series) -> pd.Series:
    """Normalize longitudes to [-180, 180) for antimeridian-safe rendering."""
    return ((series + 180.0) % 360.0) - 180.0


def aggregate_density_for_category(df: pd.DataFrame, grid_deg: float, category: str) -> list[dict]:
    """
    Aggregate weighted intensity into regular lat/lon bins for one top-level category.

    Output properties include top_category so frontend can toggle layers without reloading files.
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
    # Drop very low-energy bins to keep rendering responsive at world scale.
    grouped = grouped[grouped["weight"] >= 0.01]

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
                    "top_category": category,
                    "dataset_class": DATASET_CLASSES[category],
                    "weight": round(float(row.weight), 6),
                    "raw_weight": round(float(row.raw_weight), 6),
                    "points": int(row.points),
                },
            }
        )
    return features


def build_resolution_geojson(frames: dict[str, pd.DataFrame], grid_deg: float) -> dict:
    features: list[dict] = []
    for category in ("global", "commercial", "oil_gas", "passenger"):
        features.extend(aggregate_density_for_category(frames[category], grid_deg, category))
    return {"type": "FeatureCollection", "features": features}


def to_hotspot_geojson(df: pd.DataFrame, category: str) -> dict:
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
                    "top_category": category,
                    "dataset_class": DATASET_CLASSES[category],
                    "density": int(row.density),
                    "intensity": float(row.intensity),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def validate_required_columns(df: pd.DataFrame, filename: str) -> None:
    required = {"latitude", "longitude", "intensity", "density"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{filename} missing required columns: {sorted(missing)}")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    frames: dict[str, pd.DataFrame] = {}
    source_rows: dict[str, int] = {}

    for category, file_path in TOP_CATEGORY_FILES.items():
        df = pd.read_csv(file_path)
        validate_required_columns(df, file_path.name)

        frame = df[["latitude", "longitude", "intensity"]].copy()
        # Intensity already log-scaled upstream; use it as weight to preserve diffusion shape.
        frame["weight"] = frame["intensity"]
        frames[category] = frame
        source_rows[category] = int(len(frame))

    frames["global"] = pd.concat(
        [frames["commercial"], frames["oil_gas"], frames["passenger"]], ignore_index=True
    )
    source_rows["global"] = int(len(frames["global"]))

    feature_counts_by_res: dict[str, dict[str, int]] = {}
    for resolution, grid_deg in RESOLUTION_GRIDS.items():
        fc = build_resolution_geojson(frames, grid_deg)
        write_json(DATA_DIR / f"density_{resolution}.geojson", fc)

        counts = Counter(f["properties"]["top_category"] for f in fc["features"])
        feature_counts_by_res[resolution] = dict(counts)

    hotspots_df = pd.read_csv(HOTSPOT_FILE)
    hotspot_counts: dict[str, int] = {}
    for category in ("commercial", "oil_gas", "passenger"):
        cat_df = hotspots_df[hotspots_df["category"] == category].copy()
        cat_geojson = to_hotspot_geojson(cat_df, category)
        write_json(DATA_DIR / f"hotspots_{category}.geojson", cat_geojson)
        hotspot_counts[category] = len(cat_geojson["features"])

    if not CLUSTERS_FILE.exists():
        write_json(CLUSTERS_FILE, {"type": "FeatureCollection", "features": []})
    cluster_feature_count = len(json.loads(CLUSTERS_FILE.read_text(encoding="utf-8")).get("features", []))

    filter_index = {
        "top_categories": [
            {
                "key": "global",
                "label": "Global",
                "dataset_class": DATASET_CLASSES["global"],
                "has_subcategories": False,
            },
            {
                "key": "commercial",
                "label": "Commercial",
                "dataset_class": DATASET_CLASSES["commercial"],
                "has_subcategories": True,
            },
            {
                "key": "oil_gas",
                "label": "Oil & Gas",
                "dataset_class": DATASET_CLASSES["oil_gas"],
                "has_subcategories": True,
            },
            {
                "key": "passenger",
                "label": "Passenger",
                "dataset_class": DATASET_CLASSES["passenger"],
                "has_subcategories": True,
            },
        ],
        "subcategories": SUBCATEGORIES,
        # Current source files are aggregated by top category only.
        # Frontend keeps subcategory state now and can apply true subtype filtering
        # once subtype-resolved rasters/CSVs are added.
        "subcategory_granularity_available": {
            "commercial": False,
            "oil_gas": False,
            "passenger": False,
        },
    }
    (DATA_DIR / "filter_index.json").write_text(json.dumps(filter_index, indent=2), encoding="utf-8")

    metadata = {
        "crs": "EPSG:4326",
        "bounds": {"west": -180.0, "south": -85.0, "east": 180.0, "north": 85.0},
        "grid_degrees": RESOLUTION_GRIDS,
        "source_csv_rows": source_rows,
        "density_feature_counts_by_resolution": feature_counts_by_res,
        "hotspot_feature_counts": hotspot_counts,
        "dbscan_cluster_feature_count": cluster_feature_count,
        "top_categories": list(DATASET_CLASSES.keys()),
    }
    (DATA_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("Webapp data written to:", DATA_DIR)
    for res, counts in feature_counts_by_res.items():
        print(f"  density_{res}: {sum(counts.values()):,} features -> {counts}")
    print(f"  hotspots by category: {hotspot_counts}")


if __name__ == "__main__":
    main()
