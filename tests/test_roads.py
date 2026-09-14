import json
import os

import numpy as np
import pytest

from geo_utils import KM_PER_DEG
from roads import distance_to_roads_km, parse_road_segments, road_distance_score

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "overpass_roads_sample.json")


def test_parse_road_segments_builds_consecutive_vertex_pairs_from_fixture():
    data = json.load(open(FIXTURE))
    segments = parse_road_segments(data)
    # fixture: 84 ways, 1981 total geometry nodes -> 1981 - 84 = 1897 edges
    assert len(segments) == 1897
    assert segments[0] == (
        (38.611554, -104.881785),
        (38.611691, -104.881581),
    )


def test_parse_road_segments_returns_empty_list_for_no_elements():
    assert parse_road_segments({"elements": []}) == []


def test_parse_road_segments_skips_ways_with_fewer_than_two_nodes():
    assert parse_road_segments({"elements": [{"geometry": [{"lat": 1.0, "lon": 2.0}]}]}) == []
    assert parse_road_segments({"elements": [{"geometry": []}]}) == []


def test_distance_to_roads_km_is_zero_at_a_segment_endpoint():
    lats = np.array([38.60, 38.61, 38.62])
    lons = np.array([-104.90, -104.89, -104.88])
    segment = ((38.61, -104.89), (38.62, -104.88))
    dist = distance_to_roads_km(lats, lons, [segment])
    assert dist[1, 1] == pytest.approx(0.0, abs=1e-6)
    assert dist[0, 0] > 0


def test_distance_to_roads_km_returns_none_for_no_roads():
    lats = np.array([38.60, 38.61])
    lons = np.array([-104.90, -104.89])
    assert distance_to_roads_km(lats, lons, []) is None


def test_distance_to_roads_km_measures_perpendicular_distance_to_a_long_straight_segment():
    """THE DEFECT THIS REGRESSION-TESTS: a cell beside the MIDDLE of a
    long, straight, sparsely-noded segment (no intermediate vertices --
    exactly Overpass's own geometry for a rural county road or a
    "track") must get the true perpendicular distance to the segment,
    not the much larger distance to either of its two endpoints.

    Hand-computed: the segment runs east-west at a constant latitude
    (38.0) from lon -105.01 to -104.99; the query point sits at
    (38.005, -105.0), directly north of the segment's own geometric
    midpoint (lon -105.0, the numeric average of the two endpoints'
    longitudes). Because the segment is a pure east-west line, the
    perpendicular distance from the query point down to it is a pure
    north-south offset -- 0.005 deg of latitude -- independent of the
    longitude->km scale factor (which depends on latitude and would
    otherwise complicate a hand computation): 0.005 * KM_PER_DEG.

    The pre-fix, vertex-only distance would instead be the distance to
    the nearer of the two endpoints, roughly double this (see the
    assertion below) -- the exact failure mode the review flagged."""
    lats = np.array([38.005])
    lons = np.array([-105.0])
    segment = ((38.0, -105.01), (38.0, -104.99))

    dist = distance_to_roads_km(lats, lons, [segment])

    expected_perp_km = 0.005 * KM_PER_DEG
    assert dist[0, 0] == pytest.approx(expected_perp_km, rel=1e-9)

    lat0 = 38.005  # distance_to_roads_km's own projection reference (mean of lats)
    kx = KM_PER_DEG * np.cos(np.radians(lat0))
    old_vertex_only_dist = min(
        np.hypot((38.005 - 38.0) * KM_PER_DEG, (-105.0 - -105.01) * kx),
        np.hypot((38.005 - 38.0) * KM_PER_DEG, (-105.0 - -104.99) * kx),
    )
    assert old_vertex_only_dist > expected_perp_km * 1.8  # today's bug: ~87% too far
    assert dist[0, 0] < old_vertex_only_dist


def test_distance_to_roads_km_falls_back_to_endpoint_distance_beyond_segment_ends():
    """A query point past one END of a short segment (not beside its
    middle) should get the distance to that nearest endpoint, not an
    extrapolated point off the end of the road."""
    lats = np.array([38.02])
    lons = np.array([-105.0])
    segment = ((38.0, -105.0), (38.01, -105.0))  # short segment running due north

    dist = distance_to_roads_km(lats, lons, [segment])
    expected = (38.02 - 38.01) * KM_PER_DEG  # distance to the nearer endpoint (38.01)
    assert dist[0, 0] == pytest.approx(expected, rel=1e-9)


def test_road_distance_score_saturates_at_max_benefit_distance():
    dist = np.array([0.0, 1.2, 2.4, 5.0])
    scores = road_distance_score(dist, max_benefit_km=2.4)
    assert scores[0] == 0.0
    assert scores[1] == pytest.approx(0.5)
    assert scores[2] == pytest.approx(1.0)
    assert scores[3] == 1.0
