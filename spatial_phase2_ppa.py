from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
from pointpats import k_test
from scipy.stats import gaussian_kde
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors

from spatial_analysis_common import (
    ANALYSIS_DIR,
    WEBAPP_DATA_DIR,
    aggregate_grid,
    ensure_directories,
    haversine_km,
    read_category_frames,
    with_global,
    write_json,
)


def to_geojson(df, *, value_columns: list[str]) -> dict:
    features = []
    for row in df.itertuples(index=False):
        properties = {}
        for col in value_columns:
            value = getattr(row, col)
            if isinstance(value, (np.integer,)):
                properties[col] = int(value)
            elif isinstance(value, (np.floating,)):
                properties[col] = float(value)
            elif isinstance(value, (np.bool_,)):
                properties[col] = bool(value)
            else:
                properties[col] = value
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(row.lon_bin), 6), round(float(row.lat_bin), 6)],
                },
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def compute_nearest_neighbor_km(coords_lonlat: np.ndarray) -> tuple[float, float]:
    if coords_lonlat.shape[0] < 2:
        return 0.0, 0.0
    radians = np.radians(coords_lonlat[:, ::-1])
    nn = NearestNeighbors(n_neighbors=2, metric="haversine")
    nn.fit(radians)
    distances, _ = nn.kneighbors(radians)
    observed_km = float(np.mean(distances[:, 1]) * 6371.0088)

    lon = coords_lonlat[:, 0]
    lat = coords_lonlat[:, 1]
    lat_min, lat_max = np.min(lat), np.max(lat)
    lon_min, lon_max = np.min(lon), np.max(lon)
    width_km = float(np.mean(haversine_km(np.array([lon_min]), np.array([lat_min]), np.array([lon_max]), np.array([lat_min]))))
    height_km = float(np.mean(haversine_km(np.array([lon_min]), np.array([lat_min]), np.array([lon_min]), np.array([lat_max]))))
    area_km2 = max(width_km * height_km, 1.0)
    intensity = coords_lonlat.shape[0] / area_km2
    expected_km = 0.5 / np.sqrt(intensity) if intensity > 0 else 0.0
    return observed_km, expected_km


def run_ripley_k(coords_lonlat: np.ndarray) -> dict:
    if coords_lonlat.shape[0] < 20:
        return {"supports_deg": [], "k_observed": [], "k_pvalues": []}
    supports = np.linspace(0.2, 6.0, 20)
    result = k_test(
        coords_lonlat,
        support=supports,
        n_simulations=199,
        n_jobs=1,
    )
    return {
        "supports_deg": [float(x) for x in np.asarray(result.support)],
        "k_observed": [float(x) for x in np.asarray(result.statistic)],
        "k_pvalues": [float(x) for x in np.asarray(result.pvalue)],
    }


def run_dbscan(coords_lonlat: np.ndarray) -> np.ndarray:
    radians = np.radians(coords_lonlat[:, ::-1])
    model = DBSCAN(
        eps=150.0 / 6371.0088,  # 150 km neighborhood
        min_samples=6,
        metric="haversine",
        algorithm="ball_tree",
    )
    return model.fit_predict(radians)


def main() -> None:
    ensure_directories()
    frames = with_global(read_category_frames())
    global_grid = aggregate_grid(frames["global"], grid_deg=0.5)

    threshold = float(global_grid["density_sum"].quantile(0.95))
    hotspots = global_grid[global_grid["density_sum"] >= threshold].copy().reset_index(drop=True)
    hotspots["hotspot_rank"] = np.arange(1, len(hotspots) + 1)

    coords = hotspots[["lon_bin", "lat_bin"]].to_numpy(dtype=float)
    kde = gaussian_kde(coords.T, weights=hotspots["intensity_sum"].to_numpy(dtype=float))
    hotspots["kde_score"] = kde(coords.T)
    max_kde = float(hotspots["kde_score"].max()) if len(hotspots) else 1.0
    hotspots["kde_score_norm"] = hotspots["kde_score"] / (max_kde if max_kde > 0 else 1.0)

    observed_nn_km, expected_nn_km = compute_nearest_neighbor_km(coords)
    ripley = run_ripley_k(coords)

    labels = run_dbscan(coords)
    hotspots["cluster_id"] = labels
    hotspots["is_noise"] = hotspots["cluster_id"] < 0

    cluster_counts = (
        hotspots[hotspots["cluster_id"] >= 0]["cluster_id"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    cluster_counts = {int(k): int(v) for k, v in cluster_counts.items()}

    hotspot_geojson = to_geojson(
        hotspots,
        value_columns=[
            "density_sum",
            "density_mean",
            "intensity_sum",
            "intensity_mean",
            "points",
            "hotspot_rank",
            "kde_score",
            "kde_score_norm",
            "cluster_id",
            "is_noise",
        ],
    )

    kde_geojson = to_geojson(
        hotspots[["lat_bin", "lon_bin", "kde_score", "kde_score_norm", "cluster_id"]],
        value_columns=["kde_score", "kde_score_norm", "cluster_id"],
    )

    phase_hotspots_csv = ANALYSIS_DIR / "phase2_hotspot_points.csv"
    phase_hotspots_geojson = ANALYSIS_DIR / "phase2_hotspot_points.geojson"
    phase_kde_geojson = ANALYSIS_DIR / "phase2_kde_surface.geojson"
    phase_clusters_geojson = ANALYSIS_DIR / "phase2_clusters.geojson"
    webapp_clusters_geojson = WEBAPP_DATA_DIR / "clusters.geojson"
    phase_metrics_json = ANALYSIS_DIR / "phase2_ppa_metrics.json"

    hotspots.to_csv(phase_hotspots_csv, index=False)
    write_json(phase_hotspots_geojson, hotspot_geojson)
    write_json(phase_kde_geojson, kde_geojson)
    write_json(phase_clusters_geojson, hotspot_geojson)
    write_json(webapp_clusters_geojson, hotspot_geojson)

    metrics = {
        "p95_density_threshold": threshold,
        "hotspot_points": int(len(hotspots)),
        "dbscan_clusters": int(len(cluster_counts)),
        "dbscan_cluster_sizes": cluster_counts,
        "dbscan_noise_points": int((hotspots["cluster_id"] < 0).sum()),
        "nearest_neighbor_km_observed": observed_nn_km,
        "nearest_neighbor_km_expected_csr": expected_nn_km,
        "nearest_neighbor_ratio": observed_nn_km / expected_nn_km if expected_nn_km > 0 else None,
        "ripley_k_test": ripley,
    }
    write_json(phase_metrics_json, metrics)

    gdf = gpd.GeoDataFrame(
        hotspots,
        geometry=gpd.points_from_xy(hotspots["lon_bin"], hotspots["lat_bin"]),
        crs="EPSG:4326",
    )
    gdf.to_file(ANALYSIS_DIR / "phase2_hotspot_points.gpkg", layer="hotspots", driver="GPKG")

    print(f"Wrote: {phase_hotspots_csv}")
    print(f"Wrote: {phase_hotspots_geojson}")
    print(f"Wrote: {phase_kde_geojson}")
    print(f"Wrote: {phase_clusters_geojson}")
    print(f"Wrote: {webapp_clusters_geojson}")
    print(f"Wrote: {phase_metrics_json}")
    print(f"Wrote: {ANALYSIS_DIR / 'phase2_hotspot_points.gpkg'}")


if __name__ == "__main__":
    main()

