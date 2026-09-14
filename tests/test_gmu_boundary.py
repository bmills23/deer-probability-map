import json
import os

import pytest

from gmu_boundary import parse_gmu_geometry, unit_bbox

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "gmu_boundary_38_59.geojson")


def test_parse_gmu_geometry_finds_the_requested_unit():
    data = json.load(open(FIXTURE))
    geometry = parse_gmu_geometry(data, 38)
    assert geometry["type"] == "Polygon"


def test_parse_gmu_geometry_returns_none_for_unknown_unit():
    data = json.load(open(FIXTURE))
    assert parse_gmu_geometry(data, 9999) is None


def test_unit_bbox_matches_hand_verified_gmu38_bounds():
    data = json.load(open(FIXTURE))
    geometry = parse_gmu_geometry(data, 38)
    lat_min, lat_max, lon_min, lon_max = unit_bbox(geometry, buffer_mi=0)
    assert lat_min == pytest.approx(39.6951971329585, abs=1e-6)
    assert lat_max == pytest.approx(39.9417182983529, abs=1e-6)
    assert lon_min == pytest.approx(-105.81569803127, abs=1e-6)
    assert lon_max == pytest.approx(-104.982874740245, abs=1e-6)


def test_unit_bbox_buffer_expands_the_bounds():
    data = json.load(open(FIXTURE))
    geometry = parse_gmu_geometry(data, 59)
    unbuffered = unit_bbox(geometry, buffer_mi=0)
    buffered = unit_bbox(geometry, buffer_mi=2.0)
    assert buffered[0] < unbuffered[0]
    assert buffered[1] > unbuffered[1]
