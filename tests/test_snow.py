import json
import os

import pytest

from snow import (
    SIMULATED_SNOW_LEVELS_IN,
    nearest_simulated_level_in,
    nearest_station,
    parse_latest_snow_depth,
    parse_stations,
    snow_elevation_shift_m,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "snotel_stations_co.json")


def test_parse_stations_extracts_triplet_name_lat_lon():
    data = json.load(open(FIXTURE))
    stations = parse_stations(data)
    assert len(stations) == 118
    assert stations[0]["triplet"] == "1344:CO:SNTL"
    assert stations[0]["name"] == "Alta Lakes"


def test_nearest_station_picks_the_closer_one():
    stations = [
        {"triplet": "A", "name": "Near", "lat": 38.64, "lon": -104.93},
        {"triplet": "B", "name": "Far", "lat": 40.0, "lon": -104.0},
    ]
    station, dist_km = nearest_station(38.636, -104.931, stations)
    assert station["name"] == "Near"
    assert dist_km < 5


def test_nearest_station_handles_no_stations():
    assert nearest_station(38.6, -104.9, []) == (None, None)


def test_parse_latest_snow_depth_skips_null_values():
    data_json = [{
        "stationTriplet": "1344:CO:SNTL",
        "data": [{"values": [
            {"date": "2026-01-01", "value": 24},
            {"date": "2026-01-02", "value": 28},
            {"date": "2026-01-03", "value": None},
        ]}],
    }]
    assert parse_latest_snow_depth(data_json) == 28.0


def test_parse_latest_snow_depth_handles_no_data():
    assert parse_latest_snow_depth([]) is None


def test_snow_elevation_shift_scales_linearly_and_caps():
    assert snow_elevation_shift_m(0) == 0.0
    assert snow_elevation_shift_m(20) == pytest.approx(305.0)
    assert snow_elevation_shift_m(100) == 610.0  # capped
    assert snow_elevation_shift_m(None) == 0.0


def test_simulated_snow_levels_span_zero_to_the_shift_cap():
    assert SIMULATED_SNOW_LEVELS_IN[0] == 0
    assert SIMULATED_SNOW_LEVELS_IN[-1] == 40
    assert SIMULATED_SNOW_LEVELS_IN == sorted(SIMULATED_SNOW_LEVELS_IN)


def test_nearest_simulated_level_in_exact_match():
    assert nearest_simulated_level_in(8) == 8
    assert nearest_simulated_level_in(40) == 40


def test_nearest_simulated_level_in_rounds_to_closer_level():
    assert nearest_simulated_level_in(9) == 8    # closer to 8 than 12
    assert nearest_simulated_level_in(11) == 12  # closer to 12 than 8
    assert nearest_simulated_level_in(35) == 30  # closer to 30 than 40


def test_nearest_simulated_level_in_ties_resolve_to_lower_level():
    assert nearest_simulated_level_in(10) == 8  # equidistant from 8 and 12


def test_nearest_simulated_level_in_none_snaps_to_lowest():
    assert nearest_simulated_level_in(None) == 0
