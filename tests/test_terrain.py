import os

import matplotlib.image as mimg
import numpy as np
import pytest

import terrain
from terrain import (
    aspect_score,
    compute_slope_aspect,
    decode_terrarium,
    elevation_band_score,
    habitat_components,
    habitat_score,
    latlon_to_tile,
    pixel_in_tile,
    slope_score,
)

FIXTURE_TILE = os.path.join(os.path.dirname(__file__), "fixtures", "terrarium_tile_11_427_785.png")


def _synth_tile(x, y):
    """Deterministic per-tile elevation surface, unique per (x, y)."""
    base = x * 100000 + y * 100
    return np.arange(256 * 256).reshape(256, 256).astype(float) + base


def test_latlon_to_tile_matches_known_gmu59_tile():
    assert latlon_to_tile(38.63617, -104.930919, 11) == (427, 785)


def test_pixel_in_tile_matches_hand_computed_offset():
    px, py = pixel_in_tile(38.63617, -104.930919, 427, 785, 11)
    assert (px, py) == (15, 92)


def test_decode_terrarium_matches_hand_verified_elevation():
    img = mimg.imread(FIXTURE_TILE)
    elev = decode_terrarium(img)
    assert elev.shape == (256, 256)
    assert elev[128, 128] == pytest.approx(1942.74, abs=0.1)


def test_slope_aspect_pure_north_south_gradient_faces_south():
    # Elevation rises going north (row index up), no east-west variation --
    # the slope faces south (downhill toward the south).
    lats = np.array([10.0, 10.01, 10.02])
    lons = np.array([20.0, 20.01, 20.02])
    elev = np.array([[0.0, 0.0, 0.0], [100.0, 100.0, 100.0], [200.0, 200.0, 200.0]])
    slope, aspect = compute_slope_aspect(elev, lats, lons)
    assert aspect[1, 1] == pytest.approx(180.0, abs=1.0)
    assert slope[1, 1] > 0


def test_elevation_band_score_peaks_at_center_and_falls_off():
    elev = np.array([2440.0, 2440.0 + 460.0, 2440.0 + 920.0])
    scores = elevation_band_score(elev)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0, abs=1e-6)
    assert scores[2] == 0.0


def test_elevation_band_score_shifts_down_with_snow():
    # A 460m downward shift moves the ideal elevation to center - shift.
    elev = np.array([2440.0 - 460.0])
    scores = elevation_band_score(elev, shift_m=460.0)
    assert scores[0] == pytest.approx(1.0)


def test_aspect_score_favors_south_by_default():
    aspect = np.array([0.0, 90.0, 180.0])
    scores = aspect_score(aspect)
    assert scores[0] == pytest.approx(0.0)
    assert scores[1] == pytest.approx(0.5)
    assert scores[2] == pytest.approx(1.0)


def test_habitat_score_blends_elevation_and_aspect():
    elev = np.array([2440.0])  # perfect elevation
    aspect = np.array([180.0])  # perfect (south) aspect
    score = habitat_score(elev, aspect, elev_weight=0.6, aspect_weight=0.4)
    assert score[0] == pytest.approx(1.0)


def test_slope_score_peaks_at_moderate_slope():
    slopes = np.array([0.0, 15.0, 45.0, 70.0])
    scores = slope_score(slopes)
    assert scores[1] == pytest.approx(1.0)  # the peak itself
    assert scores[1] > scores[0]  # peak beats flat ground
    assert scores[1] > scores[2]  # peak beats a steep face
    assert scores[2] > scores[3]  # a steep face still beats a cliff
    assert scores[3] == pytest.approx(0.0)  # cliff-steep: fully avoided


def test_slope_score_falls_off_faster_toward_cliffs_than_toward_flat():
    """Asymmetric falloff: flat ground is merely suboptimal, a sustained
    steep face is avoided outright -- so equal distance from the peak on
    either side should not score equally."""
    scores = slope_score(np.array([15.0 - 12.0, 15.0 + 12.0]))
    assert scores[0] > scores[1]  # 12 deg flatter than peak beats 12 deg steeper


def test_habitat_components_matches_habitat_score_when_slope_and_cover_given():
    elev = np.array([2895.0, 2895.0])
    aspect = np.array([0.0, 90.0])
    slope = np.array([15.0, 40.0])
    cover = np.array([0.9, 0.2])
    blended, components, wnorm = habitat_components(elev, aspect, slope_deg=slope, cover_score=cover)
    expected = habitat_score(elev, aspect, slope_deg=slope, cover_score=cover)
    np.testing.assert_allclose(blended, expected)
    assert set(components) == {"elevation", "aspect", "slope", "cover"}
    assert pytest.approx(sum(wnorm.values())) == 1.0


def test_habitat_components_renormalizes_when_cover_is_missing():
    """Graceful degradation: if a LANDFIRE fetch fails at run time and
    cover_score is None, the remaining sub-weights (elevation, aspect,
    slope) must renormalize to sum to 1, not just silently drop cover's
    share of the blend."""
    elev = np.array([2440.0])
    aspect = np.array([180.0])
    slope = np.array([15.0])
    blended, components, wnorm = habitat_components(elev, aspect, slope_deg=slope, cover_score=None)
    assert "cover" not in components
    assert set(wnorm) == {"elevation", "aspect", "slope"}
    assert pytest.approx(sum(wnorm.values())) == 1.0
    # Perfect elevation, perfect (south) aspect, and slope at its own peak
    # -- with all three sub-factors at 1.0, the renormalized blend must
    # also be 1.0 regardless of how the three weights were split.
    assert blended[0] == pytest.approx(1.0)


def test_habitat_components_renormalizes_when_slope_is_also_missing():
    elev = np.array([2895.0])
    aspect = np.array([0.0])
    blended, components, wnorm = habitat_components(elev, aspect)
    assert set(components) == {"elevation", "aspect"}
    assert pytest.approx(sum(wnorm.values())) == 1.0


def test_fetch_elevation_grid_vectorized_matches_per_point_loop(monkeypatch):
    """The vectorized meshgrid lookup must produce exactly the same values
    as the original per-point tile+pixel loop, and fetch each unique tile
    exactly once (not once per grid point)."""
    fetch_log = []

    def fake_fetch_tile(x, y, zoom, timeout=30):
        fetch_log.append((x, y))
        return _synth_tile(x, y)

    monkeypatch.setattr(terrain, "_fetch_tile", fake_fetch_tile)

    bbox = (38.60, 38.66, -104.96, -104.90)  # spans multiple zoom-11 tiles
    elev, lats, lons = terrain.fetch_elevation_grid(bbox, lat_stride_deg=0.011, lon_stride_deg=0.017)

    expected = np.full((len(lats), len(lons)), np.nan)
    seen_tiles = set()
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            x, y = terrain.latlon_to_tile(lat, lon, terrain.TILE_ZOOM)
            seen_tiles.add((x, y))
            px, py = terrain.pixel_in_tile(lat, lon, x, y, terrain.TILE_ZOOM)
            expected[i, j] = _synth_tile(x, y)[py, px]

    np.testing.assert_allclose(elev, expected)
    assert sorted(fetch_log) == sorted(seen_tiles)  # each unique tile fetched exactly once


def test_fetch_elevation_grid_backward_compatible_stride_deg(monkeypatch):
    """A single stride_deg still works and yields a square grid, for
    callers that have not been updated to separate lat/lon strides."""
    monkeypatch.setattr(terrain, "_fetch_tile", lambda x, y, zoom, timeout=30: _synth_tile(x, y))
    bbox = (38.60, 38.65, -104.95, -104.90)
    elev, lats, lons = terrain.fetch_elevation_grid(bbox, stride_deg=0.02)
    assert elev.shape == (len(lats), len(lons))
    assert lats[1] - lats[0] == pytest.approx(0.02)
    assert lons[1] - lons[0] == pytest.approx(0.02)
