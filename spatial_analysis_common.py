from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
ANALYSIS_DIR = ROOT / "analysis_outputs"
WEBAPP_DATA_DIR = ROOT / "webapp" / "data"

CATEGORY_FILES = {
    "commercial": ANALYSIS_DIR / "traffic_commercial_world.csv",
    "oil_gas": ANALYSIS_DIR / "traffic_oil_gas_world.csv",
    "passenger": ANALYSIS_DIR / "traffic_passenger_world.csv",
}

COUNTRIES_URL = (
    "https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json"
)
COUNTRIES_PATH = ANALYSIS_DIR / "reference_countries.geojson"

STRAIT_ANCHORS = np.array(
    [
        [101.0, 2.5],   # Strait of Malacca
        [56.2, 26.0],   # Strait of Hormuz
        [32.6, 30.6],   # Suez Canal
        [-5.5, 35.95],  # Strait of Gibraltar
        [-0.9, 50.9],   # English Channel
        [120.7, 24.3],  # Taiwan Strait
        [40.2, 12.7],   # Bab-el-Mandeb
    ],
    dtype=float,
)

PORT_ANCHORS = np.array(
    [
        [103.8, 1.3],    # Singapore
        [121.5, 31.2],   # Shanghai
        [4.3, 51.9],     # Rotterdam
        [55.3, 25.3],    # Jebel Ali
        [-74.0, 40.7],   # New York
        [139.8, 35.6],   # Tokyo Bay
        [106.9, -6.1],   # Jakarta
        [72.9, 19.1],    # Mumbai
        [-95.0, 29.7],   # Houston
        [3.0, 6.4],      # Lagos
        [18.4, -33.9],   # Cape Town
        [151.2, -33.9],  # Sydney
    ],
    dtype=float,
)


def ensure_directories() -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    WEBAPP_DATA_DIR.mkdir(parents=True, exist_ok=True)


def wrap_longitude(series: pd.Series) -> pd.Series:
    return ((series + 180.0) % 360.0) - 180.0


def read_category_frames() -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    required = {"latitude", "longitude", "density", "intensity"}
    for category, path in CATEGORY_FILES.items():
        if not path.exists():
            raise FileNotFoundError(
                f"Missing required input file: {path}. Run export_traffic_data.py first."
            )
        df = pd.read_csv(path)
        missing = sorted(required.difference(df.columns))
        if missing:
            raise ValueError(f"{path.name} missing required columns: {missing}")
        frames[category] = df
    return frames


def with_global(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    merged = dict(frames)
    merged["global"] = pd.concat(
        [frames["commercial"], frames["oil_gas"], frames["passenger"]],
        ignore_index=True,
    )
    return merged


def aggregate_grid(
    df: pd.DataFrame,
    grid_deg: float,
    *,
    density_col: str = "density",
    intensity_col: str = "intensity",
) -> pd.DataFrame:
    work = df[["latitude", "longitude", density_col, intensity_col]].copy()
    work["longitude"] = wrap_longitude(work["longitude"])
    work["lat_bin"] = (
        np.floor((work["latitude"] + 90.0) / grid_deg) * grid_deg - 90.0 + grid_deg / 2.0
    )
    work["lon_bin"] = (
        np.floor((work["longitude"] + 180.0) / grid_deg) * grid_deg - 180.0 + grid_deg / 2.0
    )
    grouped = (
        work.groupby(["lat_bin", "lon_bin"], as_index=False)
        .agg(
            density_sum=(density_col, "sum"),
            density_mean=(density_col, "mean"),
            intensity_sum=(intensity_col, "sum"),
            intensity_mean=(intensity_col, "mean"),
            points=(density_col, "size"),
        )
        .sort_values("intensity_sum", ascending=False)
        .reset_index(drop=True)
    )
    return grouped


def ensure_country_boundaries() -> gpd.GeoDataFrame:
    ensure_directories()
    if not COUNTRIES_PATH.exists():
        urllib.request.urlretrieve(COUNTRIES_URL, COUNTRIES_PATH)
    countries = gpd.read_file(COUNTRIES_PATH)
    if countries.empty:
        raise ValueError(f"Country boundary file has no features: {COUNTRIES_PATH}")
    name_col = next(
        (c for c in ("name", "NAME", "ADMIN", "country") if c in countries.columns),
        None,
    )
    if name_col is None:
        object_cols = [
            c for c in countries.columns if c != "geometry" and countries[c].dtype == object
        ]
        if not object_cols:
            raise ValueError("Country boundary data has no usable name field.")
        name_col = object_cols[0]
    out = countries[[name_col, "geometry"]].rename(columns={name_col: "country"})
    out["country"] = out["country"].astype(str)
    out = out.to_crs("EPSG:4326")
    return out


def haversine_km(
    lon1: np.ndarray,
    lat1: np.ndarray,
    lon2: np.ndarray,
    lat2: np.ndarray,
) -> np.ndarray:
    lon1r = np.radians(lon1)
    lat1r = np.radians(lat1)
    lon2r = np.radians(lon2)
    lat2r = np.radians(lat2)
    dlon = lon2r - lon1r
    dlat = lat2r - lat1r
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * np.arcsin(np.sqrt(a))
    return 6371.0088 * c


def nearest_anchor_distance_km(
    lon: np.ndarray,
    lat: np.ndarray,
    anchors_lonlat: np.ndarray,
) -> np.ndarray:
    lon = np.asarray(lon, dtype=float).reshape(-1, 1)
    lat = np.asarray(lat, dtype=float).reshape(-1, 1)
    anchor_lon = anchors_lonlat[:, 0].reshape(1, -1)
    anchor_lat = anchors_lonlat[:, 1].reshape(1, -1)
    distances = haversine_km(lon, lat, anchor_lon, anchor_lat)
    return distances.min(axis=1)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

