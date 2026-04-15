from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(".")
WEBAPP = ROOT / "webapp"
DATA = WEBAPP / "data"
OUT = ROOT / "analysis_outputs" / "webapp_validation.json"


def load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def feature_range_checks(fc: dict) -> dict:
    features = fc.get("features", [])
    invalid_lat = 0
    invalid_lon = 0
    for feat in features:
        lon, lat = feat["geometry"]["coordinates"]
        if lat < -90 or lat > 90:
            invalid_lat += 1
        if lon < -180 or lon >= 180:
            invalid_lon += 1
    return {
        "feature_count": len(features),
        "invalid_lat": invalid_lat,
        "invalid_lon": invalid_lon,
    }


def main() -> None:
    required_files = [
        WEBAPP / "index.html",
        WEBAPP / "app.js",
        WEBAPP / "styles.css",
        DATA / "density_low.geojson",
        DATA / "density_mid.geojson",
        DATA / "density_high.geojson",
        DATA / "hotspots.geojson",
        DATA / "metadata.json",
    ]
    exists = {str(p.relative_to(ROOT)): p.exists() for p in required_files}

    low = load_geojson(DATA / "density_low.geojson")
    mid = load_geojson(DATA / "density_mid.geojson")
    high = load_geojson(DATA / "density_high.geojson")
    hotspots = load_geojson(DATA / "hotspots.geojson")
    metadata = json.loads((DATA / "metadata.json").read_text(encoding="utf-8"))

    app_js = (WEBAPP / "app.js").read_text(encoding="utf-8")
    config_flags = {
        "renderWorldCopies_false": "renderWorldCopies: false" in app_js,
        "maxBounds_present": "maxBounds: WORLD_BOUNDS" in app_js,
        "smooth_zoom_tuning": (
            "setWheelZoomRate" in app_js and "setZoomRate" in app_js
        ),
        "heatmap_layer_present": 'type: "heatmap"' in app_js,
        "continuous_gradient_present": "heatmap-color" in app_js,
        "cluster_source_present": "cluster: true" in app_js,
        "multiscale_switching_present": "getResolutionFromZoom" in app_js,
    }

    out = {
        "required_files_exist": exists,
        "geojson_checks": {
            "density_low": feature_range_checks(low),
            "density_mid": feature_range_checks(mid),
            "density_high": feature_range_checks(high),
            "hotspots": feature_range_checks(hotspots),
        },
        "metadata": metadata,
        "config_flags": config_flags,
        "file_sizes_mb": {
            "density_low": round((DATA / "density_low.geojson").stat().st_size / (1024 * 1024), 3),
            "density_mid": round((DATA / "density_mid.geojson").stat().st_size / (1024 * 1024), 3),
            "density_high": round((DATA / "density_high.geojson").stat().st_size / (1024 * 1024), 3),
            "hotspots": round((DATA / "hotspots.geojson").stat().st_size / (1024 * 1024), 3),
        },
    }

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
