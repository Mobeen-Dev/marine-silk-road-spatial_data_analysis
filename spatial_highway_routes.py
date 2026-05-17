from __future__ import annotations

import heapq
from collections import defaultdict, deque
from typing import Any

import geopandas as gpd
import numpy as np
from shapely.geometry import MultiPoint, Point, mapping

from spatial_analysis_common import (
    ANALYSIS_DIR,
    WEBAPP_DATA_DIR,
    aggregate_grid,
    ensure_country_boundaries,
    ensure_directories,
    haversine_km,
    read_category_frames,
    with_global,
    write_json,
)


# Tuned for global corridor extraction (not only ultra-dense regional hubs).
GRID_DEG = 0.5
BLOB_QUANTILE = 0.95
GRAPH_QUANTILE = 0.25
MIN_BLOB_CELLS = 4
GATEWAYS_PER_BLOB = 6
MAX_HUBS = 60
LAT_BAND_DEG = 20.0
LON_BAND_DEG = 30.0
LOCAL_LINKS_PER_HUB = 3
LONG_LINKS_PER_HUB = 2
NEAR_MIN_KM = 250.0
LOCAL_MAX_KM = 4200.0
LONG_MIN_KM = 4200.0
LONG_MAX_KM = 14000.0

LAT_CELLS = int(round(180.0 / GRID_DEG))
LON_CELLS = int(round(360.0 / GRID_DEG))


def idx_to_latlon(lat_idx: int, lon_idx: int) -> tuple[float, float]:
    lat = -90.0 + GRID_DEG / 2.0 + lat_idx * GRID_DEG
    lon = -180.0 + GRID_DEG / 2.0 + lon_idx * GRID_DEG
    return lat, lon


def latlon_to_idx(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat_idx = np.round((lat + 90.0 - GRID_DEG / 2.0) / GRID_DEG).astype(int)
    lon_idx = np.round((lon + 180.0 - GRID_DEG / 2.0) / GRID_DEG).astype(int)
    lat_idx = np.clip(lat_idx, 0, LAT_CELLS - 1)
    lon_idx = np.mod(lon_idx, LON_CELLS)
    return lat_idx, lon_idx


def neighbors8(node: tuple[int, int]) -> list[tuple[int, int]]:
    lat_idx, lon_idx = node
    out: list[tuple[int, int]] = []
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            if dlat == 0 and dlon == 0:
                continue
            n_lat = lat_idx + dlat
            if n_lat < 0 or n_lat >= LAT_CELLS:
                continue
            n_lon = (lon_idx + dlon) % LON_CELLS
            out.append((n_lat, n_lon))
    return out


def connected_components(nodes: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    remaining = set(nodes)
    components: list[list[tuple[int, int]]] = []
    while remaining:
        start = remaining.pop()
        q = deque([start])
        component = [start]
        while q:
            node = q.popleft()
            for nbr in neighbors8(node):
                if nbr in remaining:
                    remaining.remove(nbr)
                    q.append(nbr)
                    component.append(nbr)
        components.append(component)
    return components


def edge_key(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    return (a, b) if a <= b else (b, a)


def route_length_km(
    path: list[tuple[int, int]],
    latlon_by_node: dict[tuple[int, int], tuple[float, float]],
) -> float:
    if len(path) < 2:
        return 0.0
    lon1 = np.array([latlon_by_node[n][1] for n in path[:-1]], dtype=float)
    lat1 = np.array([latlon_by_node[n][0] for n in path[:-1]], dtype=float)
    lon2 = np.array([latlon_by_node[n][1] for n in path[1:]], dtype=float)
    lat2 = np.array([latlon_by_node[n][0] for n in path[1:]], dtype=float)
    return float(haversine_km(lon1, lat1, lon2, lat2).sum())


def choose_gateways(
    candidates: list[tuple[int, int]],
    intensity_by_node: dict[tuple[int, int], float],
    max_count: int,
) -> list[tuple[int, int]]:
    ordered = sorted(candidates, key=lambda n: intensity_by_node[n], reverse=True)
    picked: list[tuple[int, int]] = []
    for node in ordered:
        if len(picked) >= max_count:
            break
        # Keep gateway points spatially spread so routing doesn't lock into one port core.
        far_enough = True
        for p in picked:
            if abs(p[0] - node[0]) <= 3 and abs(p[1] - node[1]) <= 3:
                far_enough = False
                break
        if far_enough:
            picked.append(node)
    if not picked and ordered:
        picked = ordered[:1]
    return picked


def build_adjacency(
    nodes: set[tuple[int, int]],
    intensity_norm_by_node: dict[tuple[int, int], float],
    latlon_by_node: dict[tuple[int, int], tuple[float, float]],
) -> dict[tuple[int, int], list[tuple[tuple[int, int], float]]]:
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], float]]] = {}
    for node in nodes:
        lat_u, lon_u = latlon_by_node[node]
        norm_u = intensity_norm_by_node[node]
        node_edges: list[tuple[tuple[int, int], float]] = []
        for nbr in neighbors8(node):
            if nbr not in nodes:
                continue
            lat_v, lon_v = latlon_by_node[nbr]
            norm_v = intensity_norm_by_node[nbr]
            step_km = float(
                haversine_km(
                    np.array([lon_u], dtype=float),
                    np.array([lat_u], dtype=float),
                    np.array([lon_v], dtype=float),
                    np.array([lat_v], dtype=float),
                )[0]
            )
            avg_norm = (norm_u + norm_v) / 2.0
            # Port-core suppression: very high density gets a cost uplift so major blobs
            # are traversed via exits/gateways rather than dominating the whole network.
            core_penalty = 1.0 + 1.8 * max(0.0, (avg_norm - 0.88) / 0.12) ** 2
            flow_gain = 0.25 + 0.75 * min(avg_norm, 0.9)
            edge_cost = step_km * core_penalty / max(flow_gain, 1e-6)
            node_edges.append((nbr, edge_cost))
        adjacency[node] = node_edges
    return adjacency


def dijkstra_shortest_path(
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], float]]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> tuple[list[tuple[int, int]], float] | None:
    if start not in adjacency or goal not in adjacency:
        return None
    pq: list[tuple[float, tuple[int, int]]] = [(0.0, start)]
    dist: dict[tuple[int, int], float] = {start: 0.0}
    prev: dict[tuple[int, int], tuple[int, int]] = {}

    while pq:
        cur_dist, node = heapq.heappop(pq)
        if node == goal:
            break
        if cur_dist > dist.get(node, float("inf")):
            continue
        for nbr, edge_cost in adjacency[node]:
            nd = cur_dist + edge_cost
            if nd < dist.get(nbr, float("inf")):
                dist[nbr] = nd
                prev[nbr] = node
                heapq.heappush(pq, (nd, nbr))

    if goal not in dist:
        return None

    path = [goal]
    cur = goal
    while cur != start:
        cur = prev[cur]
        path.append(cur)
    path.reverse()
    return path, dist[goal]


def spatial_bin(lat: float, lon: float) -> tuple[int, int]:
    return (int((lat + 90.0) // LAT_BAND_DEG), int((lon + 180.0) // LON_BAND_DEG))


def select_global_hubs(blob_records: list[dict[str, Any]]) -> list[int]:
    by_bin: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for blob in blob_records:
        by_bin[spatial_bin(blob["centroid_lat"], blob["centroid_lon"])].append(blob)
    selected: list[int] = []
    for _, group in by_bin.items():
        group_sorted = sorted(group, key=lambda b: b["total_intensity"], reverse=True)
        # Keep up to 2 per spatial bin to preserve regional coverage.
        for b in group_sorted[:2]:
            selected.append(int(b["blob_id"]))

    if len(selected) < MAX_HUBS:
        selected_set = set(selected)
        for blob in sorted(blob_records, key=lambda b: b["total_intensity"], reverse=True):
            b_id = int(blob["blob_id"])
            if b_id in selected_set:
                continue
            selected.append(b_id)
            selected_set.add(b_id)
            if len(selected) >= MAX_HUBS:
                break
    else:
        # Too many selected by bins, keep strongest overall among selected.
        selected_set = set(selected)
        selected = [
            int(b["blob_id"])
            for b in sorted(
                [b for b in blob_records if int(b["blob_id"]) in selected_set],
                key=lambda x: x["total_intensity"],
                reverse=True,
            )[:MAX_HUBS]
        ]
    return selected


def build_route_pairs(routing_blobs: list[dict[str, Any]]) -> set[tuple[int, int]]:
    pair_ids: set[tuple[int, int]] = set()
    if len(routing_blobs) < 2:
        return pair_ids

    centroids = np.array(
        [[b["centroid_lon"], b["centroid_lat"]] for b in routing_blobs],
        dtype=float,
    )
    blob_ids = [int(b["blob_id"]) for b in routing_blobs]

    for idx, blob in enumerate(routing_blobs):
        lon0 = centroids[idx, 0]
        lat0 = centroids[idx, 1]
        dists = haversine_km(
            np.full(len(routing_blobs), lon0),
            np.full(len(routing_blobs), lat0),
            centroids[:, 0],
            centroids[:, 1],
        )
        order = np.argsort(dists)

        local_picked = 0
        long_picked = 0
        for j in order:
            if j == idx:
                continue
            dist_km = float(dists[j])
            if dist_km < NEAR_MIN_KM:
                continue

            a, b = sorted((int(blob["blob_id"]), blob_ids[j]))
            if dist_km <= LOCAL_MAX_KM and local_picked < LOCAL_LINKS_PER_HUB:
                pair_ids.add((a, b))
                local_picked += 1
            elif LONG_MIN_KM <= dist_km <= LONG_MAX_KM and long_picked < LONG_LINKS_PER_HUB:
                pair_ids.add((a, b))
                long_picked += 1

            if local_picked >= LOCAL_LINKS_PER_HUB and long_picked >= LONG_LINKS_PER_HUB:
                break
    return pair_ids


def best_gateway_path(
    blob_a: dict[str, Any],
    blob_b: dict[str, Any],
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], float]]],
    intensity_by_node: dict[tuple[int, int], float],
) -> tuple[list[tuple[int, int]], float] | None:
    start_candidates = sorted(
        blob_a["gateways"] or [blob_a["hub_node"]],
        key=lambda n: intensity_by_node[n],
        reverse=True,
    )[:4]
    end_candidates = sorted(
        blob_b["gateways"] or [blob_b["hub_node"]],
        key=lambda n: intensity_by_node[n],
        reverse=True,
    )[:4]

    best_path: list[tuple[int, int]] | None = None
    best_cost = float("inf")
    for s in start_candidates:
        for g in end_candidates:
            result = dijkstra_shortest_path(adjacency, s, g)
            if result is None:
                continue
            path, cost = result
            if len(path) < 2:
                continue
            if cost < best_cost:
                best_cost = cost
                best_path = path
    if best_path is None:
        return None
    return best_path, best_cost


def main() -> None:
    ensure_directories()

    frames = with_global(read_category_frames())
    grid = aggregate_grid(frames["global"], grid_deg=GRID_DEG).reset_index(drop=True)
    if grid.empty:
        raise ValueError("No density grid rows available for highway extraction.")

    intensity_raw = grid["intensity_sum"].to_numpy(dtype=float)
    intensity_scale = max(float(np.percentile(intensity_raw, 99)), 1.0)
    intensity_norm = np.clip(intensity_raw / intensity_scale, 0.0, 1.0)
    grid["intensity_norm"] = intensity_norm

    lat_idx, lon_idx = latlon_to_idx(
        grid["lat_bin"].to_numpy(dtype=float),
        grid["lon_bin"].to_numpy(dtype=float),
    )
    grid["lat_idx"] = lat_idx
    grid["lon_idx"] = lon_idx

    latlon_by_node: dict[tuple[int, int], tuple[float, float]] = {}
    intensity_by_node: dict[tuple[int, int], float] = {}
    intensity_norm_by_node: dict[tuple[int, int], float] = {}
    for row in grid.itertuples(index=False):
        node = (int(row.lat_idx), int(row.lon_idx))
        lat, lon = idx_to_latlon(*node)
        latlon_by_node[node] = (lat, lon)
        intensity_by_node[node] = float(row.intensity_sum)
        intensity_norm_by_node[node] = float(row.intensity_norm)

    blob_threshold = float(np.quantile(intensity_raw, BLOB_QUANTILE))
    high_nodes = {
        (int(r.lat_idx), int(r.lon_idx))
        for r in grid.itertuples(index=False)
        if float(r.intensity_sum) >= blob_threshold
    }
    blob_components = connected_components(high_nodes)
    blob_components = [c for c in blob_components if len(c) >= MIN_BLOB_CELLS]
    blob_components.sort(
        key=lambda comp: sum(intensity_by_node[n] for n in comp),
        reverse=True,
    )

    blob_records: list[dict[str, Any]] = []
    for i, comp in enumerate(blob_components, start=1):
        comp_set = set(comp)
        total_intensity = float(sum(intensity_by_node[n] for n in comp))
        peak_node = max(comp, key=lambda n: intensity_by_node[n])
        hub_lat, hub_lon = latlon_by_node[peak_node]

        boundary_nodes = []
        for n in comp:
            if any(nei not in comp_set for nei in neighbors8(n)):
                boundary_nodes.append(n)
        gateways = choose_gateways(boundary_nodes or comp, intensity_by_node, GATEWAYS_PER_BLOB)

        lats = np.array([latlon_by_node[n][0] for n in comp], dtype=float)
        lons = np.array([latlon_by_node[n][1] for n in comp], dtype=float)
        weights = np.array([intensity_by_node[n] for n in comp], dtype=float)
        centroid_lat = float(np.average(lats, weights=weights))
        centroid_lon = float(np.average(lons, weights=weights))

        blob_records.append(
            {
                "blob_id": i,
                "nodes": comp,
                "node_set": comp_set,
                "gateways": gateways,
                "hub_node": peak_node,
                "hub_lat": hub_lat,
                "hub_lon": hub_lon,
                "centroid_lat": centroid_lat,
                "centroid_lon": centroid_lon,
                "cell_count": len(comp),
                "total_intensity": total_intensity,
                "peak_intensity": float(intensity_by_node[peak_node]),
                "mean_intensity": total_intensity / len(comp),
            }
        )

    if not blob_records:
        empty_fc = {"type": "FeatureCollection", "features": []}
        write_json(ANALYSIS_DIR / "highway_routes.geojson", empty_fc)
        write_json(ANALYSIS_DIR / "highway_blobs.geojson", empty_fc)
        write_json(WEBAPP_DATA_DIR / "highways.geojson", empty_fc)
        write_json(WEBAPP_DATA_DIR / "highway_blobs.geojson", empty_fc)
        write_json(
            ANALYSIS_DIR / "highway_summary.json",
            {"message": "No high-density blobs found for configured thresholds."},
        )
        print("No blobs found. Wrote empty highway outputs.")
        return

    countries = ensure_country_boundaries()
    blob_points = []
    for blob in blob_records:
        for node in blob["nodes"]:
            lat, lon = latlon_by_node[node]
            blob_points.append({"blob_id": blob["blob_id"], "geometry": Point(lon, lat)})
    blob_points_gdf = gpd.GeoDataFrame(blob_points, crs="EPSG:4326")
    joined = gpd.sjoin(blob_points_gdf, countries[["country", "geometry"]], how="left", predicate="within")
    country_map = (
        joined.dropna(subset=["country"])
        .groupby("blob_id")["country"]
        .apply(lambda x: sorted(set(str(v) for v in x)))
        .to_dict()
    )
    for blob in blob_records:
        blob_countries = country_map.get(blob["blob_id"], [])
        blob["countries"] = blob_countries
        blob["country_count"] = len(blob_countries)
        blob["multi_country"] = len(blob_countries) > 1

    graph_threshold = float(np.quantile(intensity_raw, GRAPH_QUANTILE))
    graph_nodes = {
        (int(r.lat_idx), int(r.lon_idx))
        for r in grid.itertuples(index=False)
        if float(r.intensity_sum) >= graph_threshold
    }
    for blob in blob_records:
        graph_nodes.add(blob["hub_node"])
        for g in blob["gateways"]:
            graph_nodes.add(g)

    adjacency = build_adjacency(graph_nodes, intensity_norm_by_node, latlon_by_node)

    selected_hub_ids = set(select_global_hubs(blob_records))
    routing_blobs = [b for b in blob_records if int(b["blob_id"]) in selected_hub_ids]
    blob_by_id = {int(b["blob_id"]): b for b in blob_records}

    pair_ids = build_route_pairs(routing_blobs)

    routes: list[dict[str, Any]] = []
    edge_usage: dict[tuple[tuple[int, int], tuple[int, int]], int] = defaultdict(int)
    node_usage: dict[tuple[int, int], int] = defaultdict(int)
    for a_id, b_id in sorted(pair_ids):
        a_blob = blob_by_id[a_id]
        b_blob = blob_by_id[b_id]
        result = best_gateway_path(a_blob, b_blob, adjacency, intensity_by_node)
        if result is None:
            continue
        path, cost = result
        path_len_km = route_length_km(path, latlon_by_node)
        if path_len_km < 150.0:
            continue

        for node in path:
            node_usage[node] += 1
        for u, v in zip(path[:-1], path[1:]):
            edge_usage[edge_key(u, v)] += 1

        routes.append(
            {
                "start_blob": a_id,
                "end_blob": b_id,
                "path": path,
                "path_cost": float(cost),
                "length_km": path_len_km,
                "centroid_dist_km": float(
                    haversine_km(
                        np.array([a_blob["centroid_lon"]], dtype=float),
                        np.array([a_blob["centroid_lat"]], dtype=float),
                        np.array([b_blob["centroid_lon"]], dtype=float),
                        np.array([b_blob["centroid_lat"]], dtype=float),
                    )[0]
                ),
            }
        )

    for route in routes:
        edges = [edge_key(u, v) for u, v in zip(route["path"][:-1], route["path"][1:])]
        if edges:
            usage_values = [edge_usage[e] for e in edges]
            route["usage_score"] = float(np.mean(usage_values))
            route["usage_sum"] = int(np.sum(usage_values))
            support_values = [intensity_norm_by_node[n] for n in route["path"]]
            route["intensity_support"] = float(np.mean(support_values))
        else:
            route["usage_score"] = 0.0
            route["usage_sum"] = 0
            route["intensity_support"] = 0.0

        span_gain = np.log1p(route["centroid_dist_km"] / 1200.0)
        route["route_score"] = float(
            route["usage_score"] * (0.85 + route["intensity_support"]) * (1.0 + span_gain)
        )

    routes.sort(key=lambda r: (r["route_score"], r["usage_sum"]), reverse=True)
    if routes:
        score_cut = float(np.percentile([r["route_score"] for r in routes], 45))
        selected_routes = [r for r in routes if r["route_score"] >= score_cut]
    else:
        selected_routes = []

    # Ensure each selected hub contributes at least one route for global coverage.
    covered_blobs = {
        b
        for r in selected_routes
        for b in (int(r["start_blob"]), int(r["end_blob"]))
    }
    for hub_id in selected_hub_ids:
        if hub_id in covered_blobs:
            continue
        candidates = [r for r in routes if hub_id in (int(r["start_blob"]), int(r["end_blob"]))]
        if not candidates:
            continue
        selected_routes.append(max(candidates, key=lambda r: r["route_score"]))
        covered_blobs.add(hub_id)

    dedup = {}
    for r in selected_routes:
        k = tuple(sorted((int(r["start_blob"]), int(r["end_blob"]))))
        if k not in dedup or r["route_score"] > dedup[k]["route_score"]:
            dedup[k] = r
    selected_routes = sorted(dedup.values(), key=lambda r: r["route_score"], reverse=True)[:180]

    route_features = []
    blob_to_routes: dict[int, list[str]] = defaultdict(list)
    for idx, route in enumerate(selected_routes, start=1):
        route_id = f"H{idx:03d}"
        route["route_id"] = route_id
        coords = [[latlon_by_node[n][1], latlon_by_node[n][0]] for n in route["path"]]
        start_blob = blob_by_id[int(route["start_blob"])]
        end_blob = blob_by_id[int(route["end_blob"])]
        blob_to_routes[int(route["start_blob"])].append(route_id)
        blob_to_routes[int(route["end_blob"])].append(route_id)
        route_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "route_id": route_id,
                    "route_rank": idx,
                    "start_blob": int(route["start_blob"]),
                    "end_blob": int(route["end_blob"]),
                    "start_countries": start_blob["countries"],
                    "end_countries": end_blob["countries"],
                    "length_km": round(float(route["length_km"]), 2),
                    "centroid_dist_km": round(float(route["centroid_dist_km"]), 2),
                    "path_cost": round(float(route["path_cost"]), 2),
                    "usage_score": round(float(route["usage_score"]), 3),
                    "usage_sum": int(route["usage_sum"]),
                    "intensity_support": round(float(route["intensity_support"]), 4),
                    "route_score": round(float(route["route_score"]), 4),
                    "vertex_count": len(route["path"]),
                },
            }
        )

    for blob in blob_records:
        candidates = [
            r
            for r in selected_routes
            if int(blob["blob_id"]) in (int(r["start_blob"]), int(r["end_blob"]))
        ]
        if candidates:
            top = max(candidates, key=lambda r: r["route_score"])
            blob["reference_route_id"] = top["route_id"]
        else:
            blob["reference_route_id"] = None

    blob_features = []
    for blob in blob_records:
        points = [Point(latlon_by_node[n][1], latlon_by_node[n][0]) for n in blob["nodes"]]
        hull = MultiPoint(points).convex_hull.buffer(GRID_DEG * 0.3)
        gateways_coords = [[latlon_by_node[g][1], latlon_by_node[g][0]] for g in blob["gateways"]]
        blob_features.append(
            {
                "type": "Feature",
                "geometry": mapping(hull),
                "properties": {
                    "blob_id": int(blob["blob_id"]),
                    "cell_count": int(blob["cell_count"]),
                    "total_intensity": round(float(blob["total_intensity"]), 2),
                    "peak_intensity": round(float(blob["peak_intensity"]), 2),
                    "mean_intensity": round(float(blob["mean_intensity"]), 4),
                    "country_count": int(blob["country_count"]),
                    "countries": blob["countries"],
                    "multi_country": bool(blob["multi_country"]),
                    "hub_lat": round(float(blob["hub_lat"]), 5),
                    "hub_lon": round(float(blob["hub_lon"]), 5),
                    "centroid_lat": round(float(blob["centroid_lat"]), 5),
                    "centroid_lon": round(float(blob["centroid_lon"]), 5),
                    "gateway_count": len(gateways_coords),
                    "gateways": gateways_coords,
                    "reference_route_id": blob["reference_route_id"],
                    "candidate_routes": blob_to_routes.get(int(blob["blob_id"]), []),
                },
            }
        )

    routes_fc = {"type": "FeatureCollection", "features": route_features}
    blobs_fc = {"type": "FeatureCollection", "features": blob_features}

    write_json(ANALYSIS_DIR / "highway_routes.geojson", routes_fc)
    write_json(ANALYSIS_DIR / "highway_blobs.geojson", blobs_fc)
    write_json(WEBAPP_DATA_DIR / "highways.geojson", routes_fc)
    write_json(WEBAPP_DATA_DIR / "highway_blobs.geojson", blobs_fc)

    endpoint_country_counter: dict[str, int] = defaultdict(int)
    for route in selected_routes:
        for c in blob_by_id[int(route["start_blob"])]["countries"]:
            endpoint_country_counter[c] += 1
        for c in blob_by_id[int(route["end_blob"])]["countries"]:
            endpoint_country_counter[c] += 1
    top_endpoint_countries = sorted(
        endpoint_country_counter.items(), key=lambda x: x[1], reverse=True
    )[:20]

    summary = {
        "algorithm": "global-stratified-hub-shortest-path",
        "grid_degrees": GRID_DEG,
        "blob_quantile": BLOB_QUANTILE,
        "graph_quantile": GRAPH_QUANTILE,
        "blob_count": len(blob_records),
        "routing_blob_count": len(routing_blobs),
        "candidate_route_pairs": len(pair_ids),
        "selected_route_count": len(selected_routes),
        "multi_country_blob_count": int(sum(1 for b in blob_records if b["multi_country"])),
        "max_route_score": max((r["route_score"] for r in selected_routes), default=0.0),
        "top_endpoint_countries": top_endpoint_countries,
    }
    write_json(ANALYSIS_DIR / "highway_summary.json", summary)

    print(f"Wrote: {ANALYSIS_DIR / 'highway_routes.geojson'}")
    print(f"Wrote: {ANALYSIS_DIR / 'highway_blobs.geojson'}")
    print(f"Wrote: {WEBAPP_DATA_DIR / 'highways.geojson'}")
    print(f"Wrote: {WEBAPP_DATA_DIR / 'highway_blobs.geojson'}")
    print(f"Wrote: {ANALYSIS_DIR / 'highway_summary.json'}")


if __name__ == "__main__":
    main()

