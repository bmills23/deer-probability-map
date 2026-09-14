import numpy as np
import pytest

import deer_range
from deer_range import (
    NEUTRAL_BASELINE,
    RANGE_TYPE_SCORES,
    clip_deer_range_features_to_bbox,
    fetch_deer_range_features,
    range_geometries,
    seasonal_range_score,
)

BBOX = (38.3, 39.05, -105.2, -104.6)  # GMU 59's bbox


def _feature(coords, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [coords]}}


WINTER_CONC_PARCEL = _feature(
    [[-105.05, 38.60], [-105.05, 38.65], [-105.00, 38.65], [-105.00, 38.60], [-105.05, 38.60]],
    Activity_C="Winter Concentration",
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_deer_range_features_sends_where_1_equals_1_and_bbox_geometry(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeResponse({"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": False})

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = fetch_deer_range_features(BBOX)

    # Three layers fetched (no Production Area layer exists for mule deer
    # in this service), each contributing the one fixture feature.
    assert len(features) == 3
    for url, params in calls:
        assert params["where"] == "1=1"
        assert params["geometry"] == "-105.2,38.3,-104.6,39.05"
        assert params["geometryType"] == "esriGeometryEnvelope"
        assert params["outFields"] == "*"
        assert params["f"] == "geojson"
        assert params["maxAllowableOffset"] == deer_range.DEFAULT_MAX_ALLOWABLE_OFFSET
        assert params["geometryPrecision"] == deer_range.DEFAULT_GEOMETRY_PRECISION
    urls = sorted(url for url, _ in calls)
    assert urls == sorted(deer_range.RANGE_TYPE_URLS.values())


def test_fetch_deer_range_features_tags_each_range_type(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": False})

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = fetch_deer_range_features(BBOX)
    tags = sorted(f["properties"]["_range_type"] for f in features)
    assert tags == sorted(deer_range.RANGE_TYPE_URLS.keys())


def test_fetch_deer_range_features_handles_a_layer_with_no_features(monkeypatch):
    """A unit with no delineated Migration Corridor (or any one layer) at
    all is expected, not an error."""

    def fake_get(url, params=None, timeout=None):
        if url == deer_range.RANGE_TYPE_URLS["migration_corridor"]:
            return _FakeResponse({"features": []})
        return _FakeResponse({"features": [WINTER_CONC_PARCEL]})

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = fetch_deer_range_features(BBOX)
    assert len(features) == 2
    assert "migration_corridor" not in {f["properties"]["_range_type"] for f in features}


def test_fetch_paged_pages_past_the_transfer_limit(monkeypatch):
    page1 = {"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": True}
    page2 = {"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": False}
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["resultOffset"])
        return _FakeResponse(page1 if params["resultOffset"] == 0 else page2)

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = deer_range._fetch_paged(deer_range.RANGE_TYPE_URLS["winter_concentration"], BBOX, page_size=1)

    assert len(features) == 2
    assert calls == [0, 1]


def test_range_geometries_filters_to_one_type():
    features = [
        {"type": "Feature", "properties": {"_range_type": "winter_concentration"}, "geometry": {"a": 1}},
        {"type": "Feature", "properties": {"_range_type": "severe_winter_range"}, "geometry": {"b": 2}},
    ]
    assert range_geometries(features, "winter_concentration") == [{"a": 1}]


# --- seasonal_range_score ---

LATS = np.array([0.5, 1.5])
LONS = np.array([0.5, 1.5])


def test_seasonal_range_score_uses_neutral_baseline_outside_all_polygons():
    """Core requirement: absence of a polygon must NOT score as 0 (these
    layers are incomplete HPH subsets), so a cell outside everything gets
    the named neutral baseline, not zero."""
    score = seasonal_range_score(LATS, LONS, [])
    assert np.all(score == NEUTRAL_BASELINE)
    assert NEUTRAL_BASELINE > 0


def test_seasonal_range_score_scores_winter_concentration_at_full_confidence():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    features = [{"type": "Feature", "properties": {"_range_type": "winter_concentration"}, "geometry": poly}]
    score = seasonal_range_score(LATS, LONS, features)
    assert score[0, 0] == pytest.approx(RANGE_TYPE_SCORES["winter_concentration"])
    assert score[1, 1] == pytest.approx(NEUTRAL_BASELINE)  # outside the polygon


def test_seasonal_range_score_overlapping_types_take_the_max_not_the_sum():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    features = [
        {"type": "Feature", "properties": {"_range_type": "migration_corridor"}, "geometry": poly},
        {"type": "Feature", "properties": {"_range_type": "winter_concentration"}, "geometry": poly},
    ]
    score = seasonal_range_score(LATS, LONS, features)
    assert score[0, 0] == pytest.approx(RANGE_TYPE_SCORES["winter_concentration"])
    assert score[0, 0] <= 1.0


def test_seasonal_range_score_severe_winter_range_between_baseline_and_concentration():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    features = [{"type": "Feature", "properties": {"_range_type": "severe_winter_range"}, "geometry": poly}]
    score = seasonal_range_score(LATS, LONS, features)
    assert NEUTRAL_BASELINE < score[0, 0] < RANGE_TYPE_SCORES["winter_concentration"]


def test_clip_deer_range_features_to_bbox_trims_and_drops():
    big = _feature([[-106.0, 37.0], [-106.0, 40.0], [-104.0, 40.0], [-104.0, 37.0], [-106.0, 37.0]],
                    _range_type="winter_concentration")
    far_away = _feature([[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]],
                         _range_type="winter_concentration")
    clipped = clip_deer_range_features_to_bbox([big, far_away], BBOX)
    assert len(clipped) == 1
    lons = [c[0] for c in clipped[0]["geometry"]["coordinates"][0]]
    lats = [c[1] for c in clipped[0]["geometry"]["coordinates"][0]]
    assert min(lons) == pytest.approx(-105.2)
    assert max(lons) == pytest.approx(-104.6)
    assert min(lats) == pytest.approx(38.3)
    assert max(lats) == pytest.approx(39.05)
