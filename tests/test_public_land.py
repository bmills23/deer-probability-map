import json
import os

import pytest

import public_land
from public_land import (
    clip_features_to_bbox,
    fetch_land_ownership_features,
    fetch_open_access_polygons,
    filter_min_acres,
    parse_open_access_polygons,
    parse_restricted_access_polygons,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "padus_public_access_sample.json")


def test_parse_open_access_polygons_filters_to_oa_only():
    data = json.load(open(FIXTURE))
    polygons = parse_open_access_polygons(data)
    assert len(polygons) == 5


def test_parse_open_access_polygons_returns_geometry_dicts():
    data = json.load(open(FIXTURE))
    polygons = parse_open_access_polygons(data)
    assert all(p["type"] in ("Polygon", "MultiPolygon") for p in polygons)


def test_parse_open_access_polygons_handles_no_features():
    assert parse_open_access_polygons({"features": []}) == []


def test_parse_restricted_access_polygons_filters_to_ra_only():
    """The pool hunting_access.classify_access draws the 'conditional'
    tier from -- everything not covered by parse_open_access_polygons."""
    data = json.load(open(FIXTURE))
    oa = parse_open_access_polygons(data)
    ra = parse_restricted_access_polygons(data)
    assert len(ra) > 0
    assert len(ra) + len(oa) <= len(data["features"])


def test_parse_restricted_access_polygons_handles_no_features():
    assert parse_restricted_access_polygons({"features": []}) == []


# --- small synthetic feature fixture for the ownership fetch/clip/filter
# tests below (the real fixture lacks MngTp_Desc/DesTp_Desc/GIS_Acres and
# is 2+ MB, unnecessary for testing this pure logic) ---

def _feature(unit_nm, pub_access, mng_nm, acres, coords):
    return {
        "type": "Feature",
        "properties": {
            "Pub_Access": pub_access,
            "MngNm_Desc": mng_nm,
            "MngTp_Desc": "Federal" if mng_nm != "Private" else "Private",
            "Unit_Nm": unit_nm,
            "DesTp_Desc": "National Forest",
            "GIS_Acres": acres,
        },
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


SMALL_PARCEL = _feature(
    "Tiny City Park", "OA", "City Land", 3.5,
    [[-105.01, 38.60], [-105.01, 38.61], [-105.00, 38.61], [-105.00, 38.60], [-105.01, 38.60]],
)
BIG_PARCEL = _feature(
    "Big National Forest", "OA", "US Forest Service", 500000.0,
    [[-106.0, 37.0], [-106.0, 40.0], [-104.0, 40.0], [-104.0, 37.0], [-106.0, 37.0]],
)
UNKNOWN_ACRES_PARCEL = _feature(
    "Mystery Parcel", "RA", "State Land Board", None,
    [[-105.05, 38.65], [-105.05, 38.66], [-105.04, 38.66], [-105.04, 38.65], [-105.05, 38.65]],
)
FAR_AWAY_PARCEL = _feature(
    "Somewhere Else", "OA", "Bureau of Land Management", 100.0,
    [[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]],
)

BBOX = (38.3, 39.05, -105.2, -104.6)  # lat_min, lat_max, lon_min, lon_max


def test_clip_features_to_bbox_trims_a_huge_polygon():
    clipped = clip_features_to_bbox([BIG_PARCEL], BBOX)
    assert len(clipped) == 1
    lons = [c[0] for c in clipped[0]["geometry"]["coordinates"][0]]
    lats = [c[1] for c in clipped[0]["geometry"]["coordinates"][0]]
    assert min(lons) == pytest.approx(-105.2)
    assert max(lons) == pytest.approx(-104.6)
    assert min(lats) == pytest.approx(38.3)
    assert max(lats) == pytest.approx(39.05)
    # properties survive the clip untouched
    assert clipped[0]["properties"]["Unit_Nm"] == "Big National Forest"


def test_clip_features_to_bbox_drops_features_entirely_outside():
    clipped = clip_features_to_bbox([FAR_AWAY_PARCEL], BBOX)
    assert clipped == []


def test_filter_min_acres_drops_small_parcels():
    kept = filter_min_acres([SMALL_PARCEL, BIG_PARCEL], min_acres=20)
    names = [f["properties"]["Unit_Nm"] for f in kept]
    assert names == ["Big National Forest"]


def test_filter_min_acres_keeps_unknown_acreage():
    """A feature with no GIS_Acres value should not be dropped blindly."""
    kept = filter_min_acres([UNKNOWN_ACRES_PARCEL], min_acres=20)
    assert kept == [UNKNOWN_ACRES_PARCEL]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_land_ownership_features_pages_until_transfer_not_exceeded(monkeypatch):
    """exceededTransferLimit True on page 1 must trigger a second request
    at the next resultOffset; page 2's absence of the flag must stop
    paging. The old fetch never checked this at all."""
    page1 = {
        "features": [SMALL_PARCEL, BIG_PARCEL],
        "exceededTransferLimit": True,
    }
    page2 = {
        "features": [UNKNOWN_ACRES_PARCEL],
        "exceededTransferLimit": False,
    }
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))
        return _FakeResponse(page1 if params["resultOffset"] == 0 else page2)

    monkeypatch.setattr(public_land.SESSION, "get", fake_get)

    features = fetch_land_ownership_features(BBOX, page_size=2)

    assert len(features) == 3
    assert [c["resultOffset"] for c in calls] == [0, 2]
    assert calls[0]["resultRecordCount"] == 2


def test_fetch_land_ownership_features_stops_after_one_page_when_not_exceeded(monkeypatch):
    page1 = {"features": [SMALL_PARCEL], "exceededTransferLimit": False}
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResponse(page1)

    monkeypatch.setattr(public_land.SESSION, "get", fake_get)

    features = fetch_land_ownership_features(BBOX)

    assert len(features) == 1
    assert len(calls) == 1


def test_fetch_land_ownership_features_stops_when_exceeded_flag_absent(monkeypatch):
    """Real ArcGIS responses omit exceededTransferLimit entirely when it's
    false, rather than sending it as false."""
    page1 = {"features": [SMALL_PARCEL]}  # no exceededTransferLimit key at all
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResponse(page1)

    monkeypatch.setattr(public_land.SESSION, "get", fake_get)

    features = fetch_land_ownership_features(BBOX)

    assert len(features) == 1
    assert len(calls) == 1


def test_fetch_open_access_polygons_wraps_the_new_fetch_and_still_filters_to_oa(monkeypatch):
    page1 = {
        "features": [SMALL_PARCEL, UNKNOWN_ACRES_PARCEL],  # OA, RA
        "exceededTransferLimit": False,
    }
    monkeypatch.setattr(public_land.SESSION, "get", lambda url, params=None, timeout=None: _FakeResponse(page1))

    polygons = fetch_open_access_polygons(BBOX)

    assert len(polygons) == 1
    assert polygons[0] == SMALL_PARCEL["geometry"]
