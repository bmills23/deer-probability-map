#!/usr/bin/env python3
"""CLI: build the mule deer probability map for GMU 59, 2nd rifle season.
See README.md for usage and docs/superpowers/specs/ for the design this
implements. Sister app to elk-probability-map."""

import argparse
import math

import numpy as np

import deer_range
import landcover
from geo_utils import polygon_mask
from gmu_boundary import fetch_gmu_geometry, unit_bbox
from harvest import get_deer_harvest_stats
from hunting_access import access_geometries, classify_access, fetch_cpw_access_features
from probability import DEFAULT_WEIGHTS, compute_probability, normalize_stack, weights_for_snow
from public_land import (
    clip_features_to_bbox,
    fetch_land_ownership_features,
    filter_min_acres,
    parse_open_access_polygons,
    parse_restricted_access_polygons,
)
from render import build_map, build_snow_level_cells, render_prob_png
from roads import distance_to_roads_km, fetch_road_segments, road_distance_score
from snow import (
    SIMULATED_SNOW_LEVELS_IN,
    current_snow_depth_in,
    fetch_co_snotel_stations,
    nearest_simulated_level_in,
    nearest_station,
    snow_elevation_shift_m,
)
from terrain import compute_slope_aspect, fetch_elevation_grid, habitat_components

DEFAULT_UNITS = [59]
DEFAULT_CELL_MI = 0.25
DEFAULT_INSPECT_MI = 0.5
MI_PER_DEG_LAT = 69.0


def combined_access_mask(lats, lons, open_polygons, gmu_geometry):
    """Public-land mask ANDed with the GMU boundary itself.

    Without this, open-access polygons that fall inside the 2 mi buffered
    analysis bbox but outside the actual GMU boundary would be shaded as
    if they were huntable land in this unit. Kept as a small, independently
    tested utility; process_unit now gets the same GMU-boundary
    intersection (for all three access tiers, not just "open") from
    hunting_access.classify_access."""
    return polygon_mask(lats, lons, open_polygons) & polygon_mask(lats, lons, [gmu_geometry])


def cell_mi_to_strides(cell_mi, mean_lat_deg):
    """Degree strides for a square-ish ground cell of cell_mi miles."""
    lat_stride = cell_mi / MI_PER_DEG_LAT
    lon_stride = cell_mi / (MI_PER_DEG_LAT * math.cos(math.radians(mean_lat_deg)))
    return lat_stride, lon_stride


def fetch_security_score(bbox, lats, lons):
    """Roads (Overpass) -> the security-cover distance score, degrading to
    None -- security omitted, compute_probability's remaining weights
    renormalize -- if the fetch fails, same graceful-degradation pattern
    already used below for LANDFIRE land cover and CPW deer seasonal range."""
    try:
        road_segments = fetch_road_segments(bbox)
        road_dist_km = distance_to_roads_km(lats, lons, road_segments)
        return road_distance_score(road_dist_km) if road_dist_km is not None else None
    except Exception as exc:
        print(f"  roads fetch failed ({exc}); security will be omitted, remaining weights renormalize")
        return None


def fetch_snow_conditions(center_lat, center_lon):
    """Nearest CO SNOTEL station + its current depth, degrading to
    (None, None, None, note) -- no station, no live reading, snow.
    snow_elevation_shift_m(None) already falls back to a zero elevation-
    band shift -- if the stations list or depth lookup fetch fails, same
    graceful-degradation pattern already used below for LANDFIRE land
    cover and CPW deer seasonal range.

    Returns (station, station_dist_km, depth_in, snow_error): snow_error
    is None on success (including the ordinary, expected case of no
    reading), or a short human-readable reason the fetch failed."""
    try:
        stations = fetch_co_snotel_stations()
        station, station_dist_km = nearest_station(center_lat, center_lon, stations)
        depth_in = current_snow_depth_in(station["triplet"]) if station else None
        return station, station_dist_km, depth_in, None
    except Exception as exc:
        print(f"  SNOTEL fetch failed ({exc}); snow depth unavailable, elevation-band shift assumed 0 in")
        return None, None, None, str(exc)


def process_unit(gmu, cell_mi=DEFAULT_CELL_MI, inspect_mi=DEFAULT_INSPECT_MI):
    geometry = fetch_gmu_geometry(gmu)
    if geometry is None:
        raise RuntimeError(f"No CPW boundary found for GMU {gmu}")
    bbox = unit_bbox(geometry)
    lat_min, lat_max, lon_min, lon_max = bbox
    mean_lat = (lat_min + lat_max) / 2
    lat_stride_deg, lon_stride_deg = cell_mi_to_strides(cell_mi, mean_lat)

    print(f"  fetching elevation... (target cell {cell_mi} mi)")
    elev, lats, lons = fetch_elevation_grid(bbox, lat_stride_deg=lat_stride_deg, lon_stride_deg=lon_stride_deg)
    slope, aspect = compute_slope_aspect(elev, lats, lons)

    print("  fetching nearest SNOTEL station...")
    center_lat, center_lon = (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
    station, station_dist_km, depth_in, snow_error = fetch_snow_conditions(center_lat, center_lon)

    print("  fetching land cover (LANDFIRE EVC)...")
    try:
        cover_score = landcover.fetch_cover_score(lats, lons)
    except Exception as exc:
        print(f"  land cover fetch failed ({exc}); habitat will renormalize without it")
        cover_score = None

    # Habitat is recomputed once per simulated snow level (elevation, roads,
    # land cover, and range polygons are each fetched exactly once above --
    # only the cheap numpy recompute below happens per level): snow only
    # ever enters habitat_components through snow_shift_m, which only moves
    # elevation_band_score's effective center, so aspect/slope/cover come
    # back byte-identical at every level and only "elevation" (and the
    # blended habitat score built from it) actually varies. See
    # deer_map.build_snow_stack for what happens with these per-level grids
    # once every unit in the run has been processed (the global
    # normalization step -- see probability.normalize_stack).
    level_habitat = []
    level_habitat_parts = []
    for depth in SIMULATED_SNOW_LEVELS_IN:
        shift = snow_elevation_shift_m(depth)
        hab, hab_parts, _ = habitat_components(
            elev, aspect, snow_shift_m=shift, slope_deg=slope, cover_score=cover_score
        )
        level_habitat.append(hab)
        level_habitat_parts.append(hab_parts)
    habitat_used = list(level_habitat_parts[0].keys())

    print("  fetching roads...")
    security = fetch_security_score(bbox, lats, lons)

    print("  fetching public land boundaries...")
    land_features = fetch_land_ownership_features(bbox)
    oa_polygons = parse_open_access_polygons({"features": land_features})
    ra_polygons = parse_restricted_access_polygons({"features": land_features})

    print("  fetching CPW hunting-access sources (managed properties, "
          "walk-in access, state trust land public access program)...")
    cpw_features = fetch_cpw_access_features(bbox)
    cpw_polygons = access_geometries(cpw_features)

    print("  fetching CPW mule deer seasonal range polygons (migration corridor, "
          "severe winter range, winter concentration area)...")
    try:
        deer_range_features = deer_range.fetch_deer_range_features(bbox)
        seasonal_range = deer_range.seasonal_range_score(lats, lons, deer_range_features)
    except Exception as exc:
        print(f"  deer seasonal range fetch failed ({exc}); seasonal range will be "
              "omitted, remaining weights renormalize")
        deer_range_features = []
        seasonal_range = None

    range_type_counts = {
        rt: len(deer_range.range_geometries(deer_range_features, rt)) for rt in deer_range.RANGE_TYPE_URLS
    }
    print(f"  deer seasonal range polygons in bbox: {range_type_counts}")

    open_mask, conditional_mask, closed_mask = classify_access(
        lats, lons, oa_polygons, ra_polygons, cpw_polygons, geometry
    )
    public_mask = open_mask

    old_oa_only_mask = combined_access_mask(lats, lons, oa_polygons, geometry)
    cell_acres = cell_mi * cell_mi * 640.0  # approx acres/sq mi; cells are square-ish (cell_mi_to_strides)
    newly_open_acres = float(np.sum(open_mask & ~old_oa_only_mask)) * cell_acres
    conditional_acres = float(np.sum(conditional_mask)) * cell_acres
    print(f"  access tiers vs. old OA-only mask: open +{newly_open_acres:,.0f} ac "
          f"from CPW sources, conditional (shown, not shaded) ~{conditional_acres:,.0f} ac")

    display_features = filter_min_acres(clip_features_to_bbox(land_features, bbox))
    cpw_display_features = clip_features_to_bbox(cpw_features, bbox)
    deer_range_display_features = deer_range.clip_deer_range_features_to_bbox(deer_range_features, bbox)
    print(f"  land ownership: {len(land_features)} PAD-US features fetched, "
          f"{len(display_features)} kept for the map display layer; "
          f"{len(cpw_features)} CPW/SLB access features")

    level_raw_prob = []
    used = []
    for depth, hab in zip(SIMULATED_SNOW_LEVELS_IN, level_habitat):
        weights_lvl = weights_for_snow(depth, base_weights=DEFAULT_WEIGHTS)
        raw_prob, used = compute_probability(
            hab, security, public_mask, seasonal_range=seasonal_range,
            weights=weights_lvl, lats=lats, lons=lons, normalize=False,
        )
        level_raw_prob.append(raw_prob)

    if seasonal_range is not None and np.any(public_mask):
        in_scoring_range = seasonal_range > deer_range.NEUTRAL_BASELINE
        coverage_frac = float(np.sum(public_mask & in_scoring_range)) / float(np.sum(public_mask))
        print(f"  fraction of huntable (open-tier) cells inside a scoring deer "
              f"seasonal range polygon (winter concentration/severe winter range/"
              f"migration corridor): {coverage_frac:.1%}")

    harvest = get_deer_harvest_stats(gmu, season="rifle_2nd")

    return {
        "gmu": gmu,
        "lats": lats,
        "lons": lons,
        "level_raw_prob": level_raw_prob,
        "level_habitat": level_habitat,
        "level_habitat_parts": level_habitat_parts,
        "security": security,
        "seasonal_range": seasonal_range,
        "public_mask": public_mask,
        "depth_in": depth_in,
        "snow_error": snow_error,
        "harvest": harvest,
        "used": used,
        "habitat_used": habitat_used,
        "station_name": station["name"] if station else None,
        "station_dist_km": station_dist_km,
        "land_features": display_features,
        "cpw_features": cpw_display_features,
        "deer_range_features": deer_range_display_features,
        "gmu_geometry": geometry,
    }


def snow_anchor(units_depth_in, levels=SIMULATED_SNOW_LEVELS_IN):
    """The simulated snow slider's initial position, anchored to the
    live SNOTEL reading(s) of the unit(s) actually built this run.

    units_depth_in: [(gmu, depth_in_or_None), ...], one entry per unit.
    Returns (anchor_depth_in, anchor_level_in, anchor_idx, note)."""
    readings = [(gmu, d) for gmu, d in units_depth_in if d is not None]
    if not readings:
        anchor_depth = 0.0
        note = ("No live SNOTEL reading was available for any unit built this run; "
                "the simulated snow slider starts at 0 in.")
    else:
        anchor_depth = sum(d for _, d in readings) / len(readings)
        if len({round(d, 1) for _, d in readings}) > 1:
            detail = "; ".join(f"GMU {gmu}: {d:.0f} in" for gmu, d in readings)
            note = (f"Units report different live readings ({detail}); the simulated "
                    f"snow slider starts at their average ({anchor_depth:.0f} in), "
                    "snapped to the nearest precomputed level.")
        else:
            note = (f"The simulated snow slider starts at the live SNOTEL reading "
                    f"({anchor_depth:.0f} in), snapped to the nearest precomputed level.")
    anchor_level = nearest_simulated_level_in(anchor_depth, levels=levels)
    anchor_idx = levels.index(anchor_level)
    return anchor_depth, anchor_level, anchor_idx, note


def build_snow_stack(units_data, inspect_mi=DEFAULT_INSPECT_MI):
    """Turn each unit's per-level RAW probability grids (process_unit's
    level_raw_prob, normalize=False) into the slider's actual payload.
    See probability.normalize_stack's docstring for why the whole stack
    shares one global maximum instead of each level normalizing to its
    own peak."""
    all_raw = [raw for u in units_data for raw in u["level_raw_prob"]]
    normalized_all, global_max = normalize_stack(all_raw)

    n_levels = len(SIMULATED_SNOW_LEVELS_IN)
    weights_by_level = [weights_for_snow(d, base_weights=DEFAULT_WEIGHTS) for d in SIMULATED_SNOW_LEVELS_IN]
    anchor_depth, anchor_level, anchor_idx, anchor_note = snow_anchor(
        [(u["gmu"], u.get("depth_in")) for u in units_data]
    )

    offset = 0
    for u in units_data:
        level_probs = normalized_all[offset:offset + n_levels]
        offset += n_levels

        snow_prob_uris = []
        prob_bounds = None
        for prob in level_probs:
            uri, prob_bounds = render_prob_png(prob, u["lats"], u["lons"])
            snow_prob_uris.append(uri)
        u["prob_uri"] = snow_prob_uris[anchor_idx]
        u["prob_bounds"] = prob_bounds
        u["snow_prob_uris"] = snow_prob_uris

        elevation_levels = [parts["elevation"] for parts in u["level_habitat_parts"]]
        static_parts = u["level_habitat_parts"][0]
        snow_cells, snow_half_lat, snow_half_lon = build_snow_level_cells(
            u["lats"], u["lons"], level_probs, u["level_habitat"], elevation_levels,
            u["public_mask"], security=u["security"], seasonal_range=u["seasonal_range"],
            aspect=static_parts.get("aspect"), slope=static_parts.get("slope"),
            cover=static_parts.get("cover"), inspect_mi=inspect_mi,
        )
        u["snow_cells"] = snow_cells
        u["snow_half_lat"] = snow_half_lat
        u["snow_half_lon"] = snow_half_lon

    snow_info = {
        "levels_in": SIMULATED_SNOW_LEVELS_IN,
        "weights_by_level": weights_by_level,
        "anchor_idx": anchor_idx,
        "anchor_depth_in": anchor_depth,
        "anchor_level_in": anchor_level,
        "anchor_note": anchor_note,
        "global_max": global_max,
    }
    return units_data, snow_info


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mule deer probability map for 2nd rifle season")
    parser.add_argument("--units", default="59", help="Comma-separated GMU numbers")
    parser.add_argument("--out", default="deer_map.html")
    parser.add_argument(
        "--cell-mi", type=float, default=DEFAULT_CELL_MI,
        help=f"Analysis grid cell size, in miles, square-ish on the ground (default: {DEFAULT_CELL_MI})",
    )
    parser.add_argument(
        "--inspect-mi", type=float, default=DEFAULT_INSPECT_MI,
        help=f"Target spacing, in miles, between click-to-inspect cells (default: {DEFAULT_INSPECT_MI})",
    )
    args = parser.parse_args(argv)

    units = [int(u) for u in args.units.split(",")]

    units_data = []
    for gmu in units:
        print(f"Processing GMU {gmu}...")
        units_data.append(process_unit(gmu, cell_mi=args.cell_mi, inspect_mi=args.inspect_mi))

    print(f"Building simulated snow stack ({SIMULATED_SNOW_LEVELS_IN} in, globally normalized "
          "across every level and unit)...")
    units_data, snow_info = build_snow_stack(units_data, inspect_mi=args.inspect_mi)
    print(f"  global normalization max (raw blended score before any level's/unit's scaling): "
          f"{snow_info['global_max']:.4f}")
    print(f"  {snow_info['anchor_note']}")

    build_map(units_data=units_data, weights=DEFAULT_WEIGHTS, out_path=args.out, snow=snow_info)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
