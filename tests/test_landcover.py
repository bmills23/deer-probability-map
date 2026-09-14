import io

import numpy as np
import pytest
from PIL import Image

import landcover
from landcover import (
    HERB_MODERATE_CAP,
    NONHABITAT_SCORE,
    SPARSE_VEG_SCORE,
    UNKNOWN_SCORE,
    cover_suitability_score,
    decode_evc_tiff,
    fetch_cover_score,
    fetch_landcover_grid,
    known_evc_coverage_frac,
)


def _tiff_bytes(arr):
    """A tiny synthetic single-band uint16 TIFF -- the "small synthetic
    raster fixture" this module's tests run against instead of the network."""
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint16)).save(buf, format="TIFF")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_decode_evc_tiff_flips_vertically_row0_becomes_south():
    # Raster row 0 (as returned by the service) is the north edge; row -1
    # the south edge. decode_evc_tiff must flip so index 0 is south,
    # matching every lats array elsewhere in this project (ascending).
    raw = np.array([[11, 11], [130, 130]], dtype=np.uint16)  # north=water, south=tree
    decoded = decode_evc_tiff(_tiff_bytes(raw), width=2, height=2)
    assert decoded[0, 0] == 130  # south row now first
    assert decoded[1, 0] == 11   # north row now last


def test_decode_evc_tiff_resizes_if_service_returns_unexpected_size():
    raw = np.array([[130, 130], [130, 130]], dtype=np.uint16)
    decoded = decode_evc_tiff(_tiff_bytes(raw), width=4, height=4)
    assert decoded.shape == (4, 4)


def test_fetch_landcover_grid_requests_expanded_half_cell_bbox(monkeypatch):
    """bbox sent to exportImage must be expanded by half a grid cell on
    each side, so each output pixel's center lands exactly on a (lat, lon)
    grid point (see docstring)."""
    lats = np.array([38.0, 38.1, 38.2])
    lons = np.array([-105.0, -104.9])
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        raw = np.full((3, 2), 130, dtype=np.uint16)
        return _FakeResponse(_tiff_bytes(raw))

    monkeypatch.setattr(landcover.SESSION, "get", fake_get)
    landcover._CACHE.clear()
    grid = fetch_landcover_grid(lats, lons)

    assert grid.shape == (3, 2)
    bbox = captured["params"]["bbox"]
    lon_min, lat_min, lon_max, lat_max = (float(x) for x in bbox.split(","))
    assert lat_min == pytest.approx(38.0 - 0.05)
    assert lat_max == pytest.approx(38.2 + 0.05)
    assert lon_min == pytest.approx(-105.0 - 0.05)
    assert lon_max == pytest.approx(-104.9 + 0.05)
    assert captured["params"]["size"] == "2,3"
    assert captured["params"]["imageSR"] == 4326


def test_fetch_landcover_grid_caches_per_bbox(monkeypatch):
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        raw = np.full((2, 2), 130, dtype=np.uint16)
        return _FakeResponse(_tiff_bytes(raw))

    monkeypatch.setattr(landcover.SESSION, "get", fake_get)
    landcover._CACHE.clear()
    fetch_landcover_grid(lats, lons)
    fetch_landcover_grid(lats, lons)
    assert len(calls) == 1  # second call hit the cache, no second fetch


def test_cover_suitability_score_nonhabitat_codes_score_near_zero():
    v = np.array([11, 12, 22, 82, 31])  # water, snow/ice, developed, ag, barren
    scores = cover_suitability_score(v)
    assert np.all(scores <= NONHABITAT_SCORE + 1e-9)


def test_cover_suitability_score_sparse_is_low_but_above_nonhabitat():
    scores = cover_suitability_score(np.array([100]))
    assert scores[0] == pytest.approx(SPARSE_VEG_SCORE, abs=0.05)
    assert scores[0] > NONHABITAT_SCORE


def test_cover_suitability_score_dense_timber_scores_high():
    # 170 = tree cover 70%, at/above TREE_SECURITY_FULL_PCT -- deep in a
    # uniform stand (no edge effect from neighbors), should score high.
    v = np.full((5, 5), 170)
    scores = cover_suitability_score(v)
    assert scores[2, 2] > 0.8


def test_cover_suitability_score_moderate_shrub_cover_scores_high_for_deer():
    # 225 = shrub cover 25%, at SHRUB_FORAGE_FULL_PCT -- mule deer are
    # primarily browsers, so even moderate (not dense) shrub cover should
    # already read as prime habitat, unlike elk's higher timber threshold.
    v = np.full((5, 5), 225)
    scores = cover_suitability_score(v)
    assert scores[2, 2] == pytest.approx(1.0)


def test_cover_suitability_score_sparse_tree_cover_scores_low():
    v = np.full((5, 5), 110)  # tree cover = 10%, well below the security saturation point
    scores = cover_suitability_score(v)
    assert scores[2, 2] < 0.3


def test_cover_suitability_score_herb_cover_is_moderate_never_maxes_out():
    v = np.full((5, 5), 399)  # herb cover ~99%, the highest herb band exists
    scores = cover_suitability_score(v)
    assert scores[2, 2] <= HERB_MODERATE_CAP + 0.05
    assert scores[2, 2] > NONHABITAT_SCORE


def test_cover_suitability_score_unknown_code_is_neutral():
    scores = cover_suitability_score(np.array([9999]))
    assert scores[0] == pytest.approx(UNKNOWN_SCORE, abs=1e-9)


def test_cover_suitability_score_forest_edge_scores_higher_than_uniform_interior():
    """The whole point of adding the edge bonus: a cell sitting on the
    boundary between dense timber and open ground should score higher
    than an equivalent cell deep inside a uniform block of the same
    timber, even though its raw tree-cover value is identical or lower."""
    # 140 = 40% tree cover, below TREE_SECURITY_FULL_PCT so the base score
    # isn't already saturated at 1.0 -- otherwise the edge bonus would have
    # no headroom to show up against the outer clip.
    size = 9
    uniform_forest = np.full((size, size), 140)
    uniform_score = cover_suitability_score(uniform_forest)[size // 2, size // 2]

    half_forest_half_open = np.full((size, size), 140)
    half_forest_half_open[:, size // 2:] = 330  # open herb ground on one side
    edge_score = cover_suitability_score(half_forest_half_open)[size // 2, size // 2 - 1]

    assert edge_score > uniform_score


def test_fetch_cover_score_returns_0_1_array(monkeypatch):
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])

    def fake_get(url, params=None, timeout=None):
        raw = np.array([[130, 22], [330, 11]], dtype=np.uint16)
        return _FakeResponse(_tiff_bytes(raw))

    monkeypatch.setattr(landcover.SESSION, "get", fake_get)
    landcover._CACHE.clear()
    scores = fetch_cover_score(lats, lons)
    assert scores.shape == (2, 2)
    assert np.all(scores >= 0.0) and np.all(scores <= 1.0)


def test_known_evc_coverage_frac_is_zero_for_all_nodata():
    v = np.full((4, 4), 65535)  # unrecognized sentinel value, not any real EVC band
    assert known_evc_coverage_frac(v) == 0.0


def test_known_evc_coverage_frac_is_one_for_fully_recognized_raster():
    v = np.full((4, 4), 130)  # tree cover, a recognized band
    assert known_evc_coverage_frac(v) == pytest.approx(1.0)


def test_known_evc_coverage_frac_is_partial_for_a_mixed_raster():
    v = np.array([[130, 65535], [65535, 65535]])  # 1 of 4 pixels recognized
    assert known_evc_coverage_frac(v) == pytest.approx(0.25)


def test_fetch_cover_score_raises_when_raster_is_effectively_all_nodata(monkeypatch):
    """THE DEFECT THIS REGRESSION-TESTS: an all-nodata (or effectively
    empty) LANDFIRE raster must be treated as a failed fetch -- same as an
    HTTP error -- so deer_map.process_unit's existing try/except drops
    cover and habitat renormalizes, instead of silently scoring every
    pixel UNKNOWN_SCORE while the status panel still reports cover as a
    real, used input."""
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])

    def fake_get(url, params=None, timeout=None):
        raw = np.full((2, 2), 65535, dtype=np.uint16)  # entirely unrecognized/nodata
        return _FakeResponse(_tiff_bytes(raw))

    monkeypatch.setattr(landcover.SESSION, "get", fake_get)
    landcover._CACHE.clear()
    with pytest.raises(RuntimeError, match="effectively empty"):
        fetch_cover_score(lats, lons)


def test_fetch_cover_score_succeeds_on_a_normal_mixed_raster(monkeypatch):
    """Sanity check alongside the all-nodata test above: a raster with
    real cover data must NOT be rejected by the new emptiness check."""
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])

    def fake_get(url, params=None, timeout=None):
        raw = np.array([[130, 22], [330, 11]], dtype=np.uint16)
        return _FakeResponse(_tiff_bytes(raw))

    monkeypatch.setattr(landcover.SESSION, "get", fake_get)
    landcover._CACHE.clear()
    scores = fetch_cover_score(lats, lons)
    assert scores.shape == (2, 2)


def test_fetch_cover_score_propagates_http_errors(monkeypatch):
    """A LANDFIRE fetch failure must raise, not silently return a fake
    score -- deer_map.process_unit is responsible for catching this and
    renormalizing habitat's remaining sub-weights (graceful degradation
    lives in terrain.habitat_components, not here)."""
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])

    class _FailingResponse:
        def raise_for_status(self):
            raise RuntimeError("503 Service Unavailable")

    monkeypatch.setattr(landcover.SESSION, "get", lambda *a, **k: _FailingResponse())
    landcover._CACHE.clear()
    with pytest.raises(RuntimeError):
        fetch_cover_score(lats, lons)
