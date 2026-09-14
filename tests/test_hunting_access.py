import numpy as np
import pytest

import hunting_access
from hunting_access import (
    access_geometries,
    classify_access,
    fetch_cpw_access_features,
    fetch_cpw_managed_properties,
    fetch_slb_public_access_properties,
    fetch_slb_public_access_stl,
    fetch_walk_in_access,
)

BBOX = (38.3, 39.05, -105.2, -104.6)  # lat_min, lat_max, lon_min, lon_max


def _feature(coords, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [coords]}}


SWA_PARCEL = _feature(
    [[-105.05, 38.60], [-105.05, 38.65], [-105.00, 38.65], [-105.00, 38.60], [-105.05, 38.60]],
    PropName="Test Wildlife Area", PropType="SWA", Acres=1200.0,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_cpw_managed_properties_sends_where_1_equals_1_and_bbox_geometry(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeResponse({"features": [SWA_PARCEL], "exceededTransferLimit": False})

    monkeypatch.setattr(hunting_access.SESSION, "get", fake_get)

    features = fetch_cpw_managed_properties(BBOX)

    assert len(features) == 1
    url, params = calls[0]
    assert url == hunting_access.CPW_MANAGED_PROPERTIES_URL
    assert params["where"] == "1=1"
    assert params["geometry"] == "-105.2,38.3,-104.6,39.05"
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert params["outFields"] == "*"
    assert params["f"] == "geojson"
    assert params["maxAllowableOffset"] == hunting_access.DEFAULT_MAX_ALLOWABLE_OFFSET
    assert params["geometryPrecision"] == hunting_access.DEFAULT_GEOMETRY_PRECISION


def test_fetch_walk_in_access_returns_empty_list_cleanly(monkeypatch):
    """Walk-In Access is mostly eastern-plains -- a mountain unit's bbox
    (like GMU 59's) returning zero features is the expected, common case,
    not an error."""
    monkeypatch.setattr(
        hunting_access.SESSION, "get",
        lambda url, params=None, timeout=None: _FakeResponse({"features": []}),
    )
    assert fetch_walk_in_access(BBOX) == []


def test_fetch_paged_pages_past_the_transfer_limit(monkeypatch):
    page1 = {"features": [SWA_PARCEL], "exceededTransferLimit": True}
    page2 = {"features": [SWA_PARCEL], "exceededTransferLimit": False}
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["resultOffset"])
        return _FakeResponse(page1 if params["resultOffset"] == 0 else page2)

    monkeypatch.setattr(hunting_access.SESSION, "get", fake_get)

    features = fetch_slb_public_access_properties(BBOX, page_size=1)

    assert len(features) == 2
    assert calls == [0, 1]


def test_fetch_paged_stops_when_exceeded_flag_absent(monkeypatch):
    """Real ArcGIS responses omit exceededTransferLimit entirely when
    it's false, rather than sending it as false."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResponse({"features": [SWA_PARCEL]})  # no exceededTransferLimit key

    monkeypatch.setattr(hunting_access.SESSION, "get", fake_get)

    features = fetch_slb_public_access_stl(BBOX)

    assert len(features) == 1
    assert len(calls) == 1


def test_fetch_cpw_access_features_tags_each_source_and_handles_an_empty_source(monkeypatch):
    """Combines all four layers (managed properties, walk-in access, and
    both SLB Public Access Program layers) and tags each feature with
    which source it came from -- the empty walk-in-access source must not
    break anything."""

    def fake_get(url, params=None, timeout=None):
        if url == hunting_access.CPW_MANAGED_PROPERTIES_URL:
            return _FakeResponse({"features": [SWA_PARCEL]})
        if url == hunting_access.CPW_WALK_IN_ACCESS_URL:
            return _FakeResponse({"features": []})
        if url == hunting_access.SLB_PUBLIC_ACCESS_PROPERTIES_URL:
            return _FakeResponse({"features": [_feature(
                [[-105.15, 38.40], [-105.15, 38.45], [-105.10, 38.45], [-105.10, 38.40], [-105.15, 38.40]],
                PropName="Test SLB PAP",
            )]})
        if url == hunting_access.SLB_PUBLIC_ACCESS_STL_URL:
            return _FakeResponse({"features": [_feature(
                [[-105.19, 38.31], [-105.19, 38.32], [-105.18, 38.32], [-105.18, 38.31], [-105.19, 38.31]],
                PropName="Test SLB STL",
            )]})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(hunting_access.SESSION, "get", fake_get)

    features = fetch_cpw_access_features(BBOX)

    assert len(features) == 3  # 1 managed + 0 walk-in + 1 slb_pap + 1 slb_stl
    sources = sorted(f["properties"]["_source"] for f in features)
    assert sources == ["cpw_managed", "slb_pap", "slb_pap"]


def test_access_geometries_extracts_geometry_dicts():
    features = [SWA_PARCEL, {"type": "Feature", "properties": {}, "geometry": None}]
    geometries = access_geometries(features)
    assert geometries == [SWA_PARCEL["geometry"]]


# --- classify_access: the three-tier model ---

GMU = {"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}
LATS = np.array([0.5, 1.5])
LONS = np.array([0.5, 1.5])


def test_classify_access_oa_polygon_is_open():
    oa = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}]
    open_mask, conditional_mask, closed_mask = classify_access(LATS, LONS, oa, [], [], GMU)
    assert open_mask[0, 0] == True
    assert conditional_mask[0, 0] == False
    assert closed_mask[0, 0] == False
    # (1.5, 1.5) is inside the GMU but outside the OA polygon -> closed
    assert open_mask[1, 1] == False
    assert closed_mask[1, 1] == True


def test_classify_access_ra_polygon_not_covered_by_cpw_is_conditional():
    ra = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}]
    open_mask, conditional_mask, closed_mask = classify_access(LATS, LONS, [], ra, [], GMU)
    assert open_mask[0, 0] == False
    assert conditional_mask[0, 0] == True
    assert closed_mask[0, 0] == False


def test_classify_access_ra_polygon_covered_by_cpw_source_is_open_not_conditional():
    """The core of the fix: State Land Board (or any) land PAD-US marks
    Restricted Access is still 'open' if a CPW/SLB access source covers
    the same ground -- and must not also show up as 'conditional'."""
    ra = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}]
    cpw = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}]
    open_mask, conditional_mask, closed_mask = classify_access(LATS, LONS, [], ra, cpw, GMU)
    assert open_mask[0, 0] == True
    assert conditional_mask[0, 0] == False
    assert closed_mask[0, 0] == False


def test_classify_access_cpw_only_polygon_with_no_padus_record_is_open():
    """A CPW source can grant access to ground with no PAD-US OA/RA record
    at all -- still open."""
    cpw = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}]
    open_mask, conditional_mask, closed_mask = classify_access(LATS, LONS, [], [], cpw, GMU)
    assert open_mask[0, 0] == True


def test_classify_access_excludes_land_outside_the_gmu_boundary():
    """Same GMU-boundary-intersection fix as elk_map.combined_access_mask,
    applied to all three tiers: land outside the unit's real boundary is
    never open or conditional, even if PAD-US/CPW cover it."""
    small_gmu = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    oa = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}]
    ra = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}]
    open_mask, conditional_mask, closed_mask = classify_access(LATS, LONS, oa, ra, [], small_gmu)
    assert open_mask[0, 0] == True    # inside both OA and the small GMU
    assert open_mask[1, 1] == False   # outside the small GMU boundary
    assert conditional_mask[1, 1] == False
    assert closed_mask[1, 1] == True


def test_classify_access_masks_are_mutually_exclusive_and_exhaustive():
    oa = [{"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}]
    open_mask, conditional_mask, closed_mask = classify_access(LATS, LONS, oa, [], [], GMU)
    stacked = np.stack([open_mask, conditional_mask, closed_mask])
    assert np.all(stacked.sum(axis=0) == 1)
