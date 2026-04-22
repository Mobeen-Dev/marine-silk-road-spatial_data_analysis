from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(".")
WEBAPP = ROOT / "webapp"
DATA = WEBAPP / "data"
OUT = ROOT / "analysis_outputs" / "webapp_validation.json"


def load_json(path: Path) -> dict:
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
    return {"feature_count": len(features), "invalid_lat": invalid_lat, "invalid_lon": invalid_lon}


def main() -> None:
    required_files = [
        WEBAPP / "index.html",
        WEBAPP / "app.js",
        WEBAPP / "styles.css",
        DATA / "density_low.geojson",
        DATA / "density_mid.geojson",
        DATA / "density_high.geojson",
        DATA / "hotspots_commercial.geojson",
        DATA / "hotspots_oil_gas.geojson",
        DATA / "hotspots_passenger.geojson",
        DATA / "filter_index.json",
        DATA / "metadata.json",
    ]
    exists = {str(p.relative_to(ROOT)): p.exists() for p in required_files}

    low = load_json(DATA / "density_low.geojson")
    mid = load_json(DATA / "density_mid.geojson")
    high = load_json(DATA / "density_high.geojson")
    hs_commercial = load_json(DATA / "hotspots_commercial.geojson")
    hs_oil_gas = load_json(DATA / "hotspots_oil_gas.geojson")
    hs_passenger = load_json(DATA / "hotspots_passenger.geojson")
    filter_index = load_json(DATA / "filter_index.json")
    metadata = load_json(DATA / "metadata.json")

    app_js = (WEBAPP / "app.js").read_text(encoding="utf-8")
    index_html = (WEBAPP / "index.html").read_text(encoding="utf-8")
    styles_css = (WEBAPP / "styles.css").read_text(encoding="utf-8")
    config_flags = {
        "renderWorldCopies_false": "renderWorldCopies: false" in app_js,
        "axis_lock_removed": "maxBounds: WORLD_BOUNDS" not in app_js,
        "smooth_zoom_tuning": ("setWheelZoomRate" in app_js and "setZoomRate" in app_js),
        "heatmap_layers_present": ('type: "heatmap"' in app_js and "density-${category}" in app_js),
        "hierarchical_controls_present": ("topCategoryList" in index_html and ".btnRefine" in styles_css),
        "modal_present": "refineModal" in index_html and "modalApplyBtn" in index_html,
        "multiscale_switching_present": "getResolutionFromZoom" in app_js,
    }

    top_category_values = set()
    for fc in (low, mid, high):
        for feat in fc["features"]:
            top_category_values.add(feat["properties"].get("top_category"))

    out = {
        "required_files_exist": exists,
        "geojson_checks": {
            "density_low": feature_range_checks(low),
            "density_mid": feature_range_checks(mid),
            "density_high": feature_range_checks(high),
            "hotspots_commercial": feature_range_checks(hs_commercial),
            "hotspots_oil_gas": feature_range_checks(hs_oil_gas),
            "hotspots_passenger": feature_range_checks(hs_passenger),
        },
        "top_category_values_sample": sorted(v for v in top_category_values if v is not None),
        "filter_index_summary": {
            "top_categories": [x["key"] for x in filter_index.get("top_categories", [])],
            "commercial_subcategories": len(filter_index.get("subcategories", {}).get("commercial", [])),
            "oil_gas_subcategories": len(filter_index.get("subcategories", {}).get("oil_gas", [])),
            "passenger_subcategories": len(filter_index.get("subcategories", {}).get("passenger", [])),
        },
        "metadata": metadata,
        "config_flags": config_flags,
        "file_sizes_mb": {
            "density_low": round((DATA / "density_low.geojson").stat().st_size / (1024 * 1024), 3),
            "density_mid": round((DATA / "density_mid.geojson").stat().st_size / (1024 * 1024), 3),
            "density_high": round((DATA / "density_high.geojson").stat().st_size / (1024 * 1024), 3),
            "hotspots_commercial": round((DATA / "hotspots_commercial.geojson").stat().st_size / (1024 * 1024), 3),
            "hotspots_oil_gas": round((DATA / "hotspots_oil_gas.geojson").stat().st_size / (1024 * 1024), 3),
            "hotspots_passenger": round((DATA / "hotspots_passenger.geojson").stat().st_size / (1024 * 1024), 3),
        },
    }

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
