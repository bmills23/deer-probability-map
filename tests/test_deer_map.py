import numpy as np
import pytest

import deer_map
from deer_map import (
    build_snow_stack,
    combined_access_mask,
    fetch_security_score,
    fetch_snow_conditions,
    snow_anchor,
)
from snow import SIMULATED_SNOW_LEVELS_IN


def test_combined_access_mask_excludes_land_outside_gmu_boundary():
    """Regression test for a defect found while re-scoping the analysis
    grid: process_unit only masked to PAD-US open-access polygons over the
    buffered bbox, never to the GMU boundary itself, so public land just
    outside the unit would be shaded as if it were huntable in this GMU."""
    gmu = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    # PAD-US polygon extends beyond the GMU boundary (simulates open-access
    # land in the 2 mi buffer zone around the unit).
    pad_us = {"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}
    lats = np.array([0.5, 1.5])
    lons = np.array([0.5, 1.5])

    mask = combined_access_mask(lats, lons, [pad_us], gmu)

    assert mask[0, 0] == True   # inside both the GMU boundary and PAD-US
    assert mask[1, 1] == False  # inside PAD-US but outside the GMU boundary


def test_combined_access_mask_still_respects_pad_us_mask():
    """A cell inside the GMU boundary but outside any open-access polygon
    must still be excluded."""
    gmu = {"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}
    pad_us = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    lats = np.array([0.5, 1.5])
    lons = np.array([0.5, 1.5])

    mask = combined_access_mask(lats, lons, [pad_us], gmu)

    assert mask[0, 0] == True   # inside both
    assert mask[1, 1] == False  # inside GMU but outside PAD-US


def test_fetch_security_score_degrades_to_none_when_roads_fetch_fails(monkeypatch, capsys):
    """THE DEFECT THIS REGRESSION-TESTS: before fetch_security_score
    existed, a failed Overpass fetch (roads.fetch_road_segments raises
    RuntimeError after exhausting its retries) propagated straight out of
    process_unit and aborted the whole run -- no map at all. Now it must
    degrade the same way a failed LANDFIRE or elk-range fetch already
    does: security omitted (None), so compute_probability drops it from
    the blend and renormalizes the remaining weights, and the failure is
    printed so it isn't silent."""
    def boom(bbox, **kwargs):
        raise RuntimeError("Overpass fetch failed after 3 attempts: HTTP 429")

    monkeypatch.setattr(deer_map, "fetch_road_segments", boom)
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])

    security = fetch_security_score((38.0, 38.1, -105.0, -104.9), lats, lons)

    assert security is None
    assert "roads fetch failed" in capsys.readouterr().out


def test_fetch_security_score_returns_scores_on_success(monkeypatch):
    """Sanity check alongside the degradation test above: a successful
    fetch must still produce a real security score array, not None."""
    def fake_segments(bbox, **kwargs):
        return [((38.0, -105.0), (38.1, -105.0))]

    monkeypatch.setattr(deer_map, "fetch_road_segments", fake_segments)
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])

    security = fetch_security_score((38.0, 38.1, -105.0, -104.9), lats, lons)

    assert security is not None
    assert security.shape == (2, 2)
    assert np.all((security >= 0) & (security <= 1))


def test_fetch_snow_conditions_degrades_to_zero_shift_when_snotel_fetch_fails(monkeypatch, capsys):
    """THE DEFECT THIS REGRESSION-TESTS: before fetch_snow_conditions
    existed, a failed SNOTEL stations fetch propagated straight out of
    process_unit and aborted the whole run. Now it must degrade to
    (None, None, None, <error>) -- snow.snow_elevation_shift_m(None)
    already falls back to a zero elevation-band shift -- and the panel's
    'no nearby SNOTEL station' branch must be able to tell this case
    apart from a genuinely empty station list (see render.py's
    _panel_html snow_error branch)."""
    def boom(**kwargs):
        raise RuntimeError("503 Service Unavailable")

    monkeypatch.setattr(deer_map, "fetch_co_snotel_stations", boom)

    station, station_dist_km, depth_in, snow_error = fetch_snow_conditions(38.5, -105.0)

    assert station is None
    assert station_dist_km is None
    assert depth_in is None
    assert snow_error is not None
    assert "SNOTEL fetch failed" in capsys.readouterr().out


def test_fetch_snow_conditions_returns_reading_on_success(monkeypatch):
    stations = [{"triplet": "123:CO:SNTL", "name": "Test Station", "lat": 38.5, "lon": -105.0}]
    monkeypatch.setattr(deer_map, "fetch_co_snotel_stations", lambda **kwargs: stations)
    monkeypatch.setattr(deer_map, "current_snow_depth_in", lambda triplet, **kwargs: 12.0)

    station, station_dist_km, depth_in, snow_error = fetch_snow_conditions(38.5, -105.0)

    assert station["name"] == "Test Station"
    assert station_dist_km == pytest.approx(0.0)
    assert depth_in == pytest.approx(12.0)
    assert snow_error is None


def test_snow_anchor_uses_live_reading_when_only_one_unit_has_it():
    depth, level, idx, note = snow_anchor([(38, None), (59, 9.0)])
    assert depth == pytest.approx(9.0)
    assert level == 8  # nearest simulated level to 9 in
    assert SIMULATED_SNOW_LEVELS_IN[idx] == 8
    assert "live SNOTEL reading" in note


def test_snow_anchor_averages_and_discloses_differing_readings():
    """Requirement: if the two units report different current depths,
    handle it sensibly (average, snapped to a precomputed level) and say
    what was chosen -- not silently pick one unit's reading."""
    depth, level, idx, note = snow_anchor([(38, 4.0), (59, 20.0)])
    assert depth == pytest.approx(12.0)
    assert level == 12
    assert SIMULATED_SNOW_LEVELS_IN[idx] == 12
    assert "different live readings" in note
    assert "GMU 38: 4 in" in note
    assert "GMU 59: 20 in" in note


def test_snow_anchor_no_readings_defaults_to_zero_and_says_so():
    depth, level, idx, note = snow_anchor([(38, None), (59, None)])
    assert depth == 0.0
    assert level == 0
    assert idx == 0
    assert "No live SNOTEL reading" in note


def _synthetic_snow_unit(gmu, peak, depth_in=None):
    """Minimal process_unit-shaped dict for build_snow_stack, entirely
    offline: same raw grid at every simulated level (only `peak` differs
    between units), standing in for one unit being genuinely less suitable
    overall than another."""
    n_levels = len(SIMULATED_SNOW_LEVELS_IN)
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    mask = np.ones((2, 2), dtype=bool)
    level_raw_prob = [np.array([[peak, 0.0], [0.0, 0.0]]) for _ in range(n_levels)]
    level_habitat = [np.full((2, 2), 0.5) for _ in range(n_levels)]
    level_habitat_parts = [
        {"elevation": np.full((2, 2), 0.5), "aspect": np.full((2, 2), 0.6),
         "slope": np.full((2, 2), 0.4), "cover": np.full((2, 2), 0.3)}
        for _ in range(n_levels)
    ]
    return {
        "gmu": gmu, "lats": lats, "lons": lons,
        "level_raw_prob": level_raw_prob, "level_habitat": level_habitat,
        "level_habitat_parts": level_habitat_parts,
        "security": np.full((2, 2), 0.4), "seasonal_range": np.full((2, 2), 0.7),
        "public_mask": mask, "depth_in": depth_in,
    }


def test_build_snow_stack_renders_genuinely_worse_unit_dimmer_not_renormalized():
    """THE CRITICAL CORRECTNESS TEST, at the deer_map integration level
    (see also test_probability.py's normalize_stack test): two synthetic
    units, one genuinely less suitable overall (lower raw peak) than the
    other. After build_snow_stack's global normalization, the weaker
    unit's rendered inspection-cell probability must be dimmer than the
    stronger unit's, not independently renormalized back to 100% the way
    compute_probability's default per-call normalization would do."""
    strong = _synthetic_snow_unit(38, peak=0.9)
    weak = _synthetic_snow_unit(59, peak=0.3)
    units_data, snow_info = build_snow_stack([strong, weak])

    assert snow_info["global_max"] == pytest.approx(0.9)

    strong_cell = next(c for c in units_data[0]["snow_cells"] if c[0] == 38.0 and c[1] == -105.0)
    weak_cell = next(c for c in units_data[1]["snow_cells"] if c[0] == 38.0 and c[1] == -105.0)
    strong_pct = strong_cell[7][0][0]  # level 0's [prob_pct, habitat, elevation_sub]
    weak_pct = weak_cell[7][0][0]

    assert strong_pct == 100  # the true global peak still normalizes to itself
    assert weak_pct == pytest.approx(round(0.3 / 0.9 * 100))  # ~33%, not 100%
    assert weak_pct < strong_pct  # genuinely dimmer, not reset to full brightness

    # Every unit's rendered PNG and slider metadata must also be populated.
    for u in units_data:
        assert len(u["snow_prob_uris"]) == len(SIMULATED_SNOW_LEVELS_IN)
        assert u["prob_uri"] == u["snow_prob_uris"][snow_info["anchor_idx"]]
    assert len(snow_info["weights_by_level"]) == len(SIMULATED_SNOW_LEVELS_IN)
