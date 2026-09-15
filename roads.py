"""Road/trailhead distance -- a security-cover proxy: deer push away from
vehicle access during rifle season."""

import json
import subprocess
import time

import numpy as np
from scipy.spatial import cKDTree

from geo_utils import KM_PER_DEG

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ROAD_HIGHWAY_TYPES = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|track"


def fetch_road_segments(bbox, timeout=90, retries=3, backoff_s=20):
    """Shells out to curl rather than using requests/SESSION: Overpass's
    public instance 406s every python-requests/urllib3 request regardless
    of headers or retries (confirmed during development -- likely
    TLS/HTTP client fingerprinting on their WAF), while curl consistently
    succeeds against the identical query. No shell=True and the query is
    our own constructed string (not untrusted input), so this is safe.

    Retries with backoff: the public instance's fair-use rate limit can
    reject a query submitted shortly after a previous large one (observed
    processing two GMUs back-to-back) -- this is expected, transient
    behavior on a shared free resource, not a permanent failure.

    Still raises RuntimeError after exhausting retries -- that failure is
    not swallowed here. deer_map.process_unit is responsible for catching
    it and degrading (security omitted, remaining weights renormalize),
    the same graceful-degradation pattern already used for the LANDFIRE
    and deer-seasonal-range fetches."""
    lat_min, lat_max, lon_min, lon_max = bbox
    query = (
        f'[out:json][timeout:60];'
        f'way["highway"~"^({ROAD_HIGHWAY_TYPES})$"]'
        f'({lat_min},{lon_min},{lat_max},{lon_max});out geom;'
    )
    last_error = None
    for attempt in range(retries):
        if attempt > 0:
            time.sleep(backoff_s * attempt)
        result = subprocess.run(
            ["curl", "-s", "-w", "\n%{http_code}", "-X", "POST", "-d", f"data={query}", OVERPASS_URL],
            capture_output=True, timeout=timeout,
        )
        if result.returncode == 0:
            body, _, code = result.stdout.rpartition(b"\n")
            if code == b"200":
                return parse_road_segments(json.loads(body))
            last_error = f"HTTP {code.decode(errors='replace')}: {body[:300]!r}"
        else:
            last_error = f"curl exit {result.returncode}: {result.stderr.decode(errors='replace')[:300]}"
    raise RuntimeError(f"Overpass fetch failed after {retries} attempts: {last_error}")


def parse_road_segments(overpass_json):
    """(lat, lon) consecutive-vertex pairs -- one per edge of each way's
    own geometry, in the order Overpass returned it (a way's node order,
    i.e. along the road) -- NOT a flattened point cloud. distance_to_
    roads_km needs the actual line segments, not just the vertices, to
    measure perpendicular distance to the road itself rather than to its
    nearest node (see distance_to_roads_km's docstring: measuring to
    nodes overstates distance for a cell beside the middle of a long,
    straight, sparsely-noded segment)."""
    segments = []
    for element in overpass_json.get("elements", []):
        points = [(node["lat"], node["lon"]) for node in (element.get("geometry") or [])]
        for a, b in zip(points, points[1:]):
            segments.append((a, b))
    return segments


def _point_to_segments_km(q, p0, p1):
    """Exact perpendicular (or nearest-endpoint, if the projection falls
    outside the segment) distance in km from one point q (shape (2,), in
    the same (lat_km, lon_km) projected units as p0/p1) to each of the
    segments given by paired endpoint arrays p0, p1 (each shape (K, 2)).
    Standard clamped point-to-segment projection, fully vectorized over
    the K candidate segments. A degenerate zero-length segment (p0 == p1)
    falls back to plain point distance."""
    d = p1 - p0
    len_sq = np.einsum("ij,ij->i", d, d)
    len_sq_safe = np.where(len_sq == 0, 1.0, len_sq)
    t = np.einsum("ij,ij->i", q - p0, d) / len_sq_safe
    t = np.clip(t, 0.0, 1.0)
    foot = p0 + t[:, None] * d
    return np.hypot(*(q - foot).T)


def distance_to_roads_km(lats, lons, road_segments):
    """Distance (km) from every (lat, lon) grid cell to the nearest point
    on any road SEGMENT -- not to the nearest OpenStreetMap way *vertex*.

    Measuring to vertices instead of segments (the pre-fix behavior)
    overstates distance for any cell beside the *middle* of a long,
    straight, sparsely-noded segment -- exactly the shape of Overpass's
    own way geometry for a rural county road or a "track"-tagged
    two-track -- by up to about half that segment's length, which is real
    money against the 2.4 km benefit cap in road_distance_score: a cell
    that is actually right next to the road would otherwise read as
    meaningfully more secure than it is.

    Vectorized two-stage approach, kept fast for a ~30,000-cell grid:
    (1) a KD-tree over every segment's own two endpoints gives, per grid
    cell, an upper bound on the true nearest-segment distance (a segment
    is never farther from a point than either of its own endpoints, so
    the single nearest endpoint overall is always >= the true answer);
    (2) a second KD-tree over segment midpoints is queried with that
    upper bound plus the longest segment's own half-length as the search
    radius -- by the triangle inequality (distance to a segment's
    midpoint is at most its own half-length more than distance to any
    other point on it) this radius is guaranteed to catch every segment
    that could possibly beat the upper bound -- and the exact clamped
    point-to-segment distance (_point_to_segments_km) is then computed
    only for that per-cell candidate set, not the full segment list."""
    if not road_segments:
        return None
    lat0 = float(np.mean(lats))
    kx = KM_PER_DEG * np.cos(np.radians(lat0))

    a_lat = np.array([a[0] for a, _ in road_segments])
    a_lon = np.array([a[1] for a, _ in road_segments])
    b_lat = np.array([b[0] for _, b in road_segments])
    b_lon = np.array([b[1] for _, b in road_segments])
    p0 = np.column_stack([a_lat * KM_PER_DEG, a_lon * kx])
    p1 = np.column_stack([b_lat * KM_PER_DEG, b_lon * kx])

    midpoints = (p0 + p1) / 2.0
    half_len = np.hypot(*(p1 - p0).T) / 2.0
    max_half_len = float(half_len.max())

    vertex_tree = cKDTree(np.vstack([p0, p1]))
    mid_tree = cKDTree(midpoints)

    lon2d, lat2d = np.meshgrid(lons, lats)
    query = np.column_stack([(lat2d * KM_PER_DEG).ravel(), (lon2d * kx).ravel()])

    upper_bound, _ = vertex_tree.query(query)
    radius = upper_bound + max_half_len
    candidate_lists = mid_tree.query_ball_point(query, radius)

    out = upper_bound.copy()
    for i, idxs in enumerate(candidate_lists):
        if not idxs:
            continue
        idxs = np.asarray(idxs)
        exact = _point_to_segments_km(query[i], p0[idxs], p1[idxs])
        m = float(exact.min())
        if m < out[i]:
            out[i] = m
    return out.reshape(lat2d.shape)


def road_distance_score(dist_km, max_benefit_km=2.4):
    return np.clip(dist_km / max_benefit_km, 0, 1)
