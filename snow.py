"""Nearest CO SNOTEL station's current snow depth, used as a single
area-wide reading (not a per-cell grid -- there's no free spatial snow
grid in scope here) that shifts the elevation-band sweet spot downward,
same role as striper-run-tracker's buoys."""

import datetime as dt

import numpy as np

from geo_utils import KM_PER_DEG
from net import SESSION

STATIONS_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations"
DATA_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"


def fetch_co_snotel_stations(timeout=30):
    params = {"stationTriplets": "*:CO:SNTL", "elementCds": "WTEQ"}
    resp = SESSION.get(STATIONS_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return parse_stations(resp.json())


def parse_stations(stations_json):
    return [
        {"triplet": s["stationTriplet"], "name": s["name"], "lat": s["latitude"], "lon": s["longitude"]}
        for s in stations_json
    ]


def nearest_station(lat, lon, stations):
    if not stations:
        return None, None
    kx = KM_PER_DEG * np.cos(np.radians(lat))
    best, best_dist = None, None
    for s in stations:
        dlat_km = (s["lat"] - lat) * KM_PER_DEG
        dlon_km = (s["lon"] - lon) * kx
        dist = float(np.hypot(dlat_km, dlon_km))
        if best_dist is None or dist < best_dist:
            best, best_dist = s, dist
    return best, best_dist


def current_snow_depth_in(station_triplet, lookback_days=10, timeout=30):
    end = dt.date.today()
    begin = end - dt.timedelta(days=lookback_days)
    params = {
        "stationTriplets": station_triplet,
        "elements": "SNWD",
        "duration": "DAILY",
        "beginDate": begin.isoformat(),
        "endDate": end.isoformat(),
    }
    resp = SESSION.get(DATA_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return parse_latest_snow_depth(resp.json())


def parse_latest_snow_depth(data_json):
    if not data_json:
        return None
    values = data_json[0].get("data", [{}])[0].get("values", [])
    for entry in reversed(values):
        if entry.get("value") is not None:
            return float(entry["value"])
    return None


def snow_elevation_shift_m(depth_in, max_shift_m=610.0, max_depth_in=40.0):
    if depth_in is None:
        return 0.0
    return min(depth_in, max_depth_in) / max_depth_in * max_shift_m


# Fixed depths (inches) the simulated snow slider precomputes in Python --
# see deer_map.process_unit and render.build_snow_level_cells. Picked to
# bracket 0 through snow_elevation_shift_m's own 40 in cap (deeper than
# that has no further effect on the elevation-band shift, so there is
# nothing new to show past it), with finer spacing at the low end (0, 4,
# 8, 12) where the elevation band is most sensitive to the first few
# inches of snow, and coarser spacing higher up (18, 24, 30, 40) where the
# shift is already large and slowing its marginal effect on the blend.
# Eight levels was chosen as a balance between a visibly smooth slider and
# the HTML payload (one PNG overlay per level per unit); see README.
SIMULATED_SNOW_LEVELS_IN = [0, 4, 8, 12, 18, 24, 30, 40]


def nearest_simulated_level_in(depth_in, levels=SIMULATED_SNOW_LEVELS_IN):
    """Nearest of the precomputed simulated snow levels to an actual depth
    reading (or any target depth) -- used to snap the slider's initial
    position to the live SNOTEL reading, since only the precomputed levels
    actually have a rendered overlay. None (no station/reading) snaps to
    the lowest level (0 in), not an arbitrary middle value. Ties (equal
    distance to two levels) resolve to the lower one."""
    if depth_in is None:
        return levels[0]
    return min(levels, key=lambda lv: (abs(lv - depth_in), lv))
