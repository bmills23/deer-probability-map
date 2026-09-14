"""Shared geometry helpers: bbox math and polygon-to-grid-mask rasterizing.
Used by both gmu_boundary.py (unit boundaries) and public_land.py (PAD-US
open-access polygons) -- same GeoJSON-ish shape, same math either way."""

import numpy as np
from matplotlib.path import Path

KM_PER_DEG = 111.32


def bounds_of_coords(coords):
    """(lat_min, lat_max, lon_min, lon_max) from an arbitrarily nested
    GeoJSON coordinates array (Polygon or MultiPolygon), [lon, lat] pairs."""
    lats, lons = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            lons.append(c[0])
            lats.append(c[1])
        else:
            for item in c:
                walk(item)

    walk(coords)
    return min(lats), max(lats), min(lons), max(lons)


def buffer_bounds(bounds, buffer_mi):
    """Expand a (lat_min, lat_max, lon_min, lon_max) bbox by buffer_mi miles
    on every side."""
    lat_min, lat_max, lon_min, lon_max = bounds
    mean_lat = (lat_min + lat_max) / 2
    dlat = buffer_mi / 69.0
    dlon = buffer_mi / (69.0 * np.cos(np.radians(mean_lat)))
    return lat_min - dlat, lat_max + dlat, lon_min - dlon, lon_max + dlon


def _polygon_components(geometry):
    """Yield (exterior_ring, hole_rings) for each polygon component of a
    GeoJSON Polygon or MultiPolygon -- hole_rings is the (possibly empty)
    list of that component's interior rings, per the GeoJSON convention
    that a Polygon's coordinates are [exterior, hole, hole, ...] and a
    MultiPolygon is a list of such Polygons.

    Interior rings represent real holes (e.g. a private inholding carved
    out of a National Forest polygon): a point inside a hole is NOT inside
    the polygon, even though it is inside the exterior ring. Both the
    huntable-land mask (polygon_mask) and the ownership display's bbox
    clipping (clip_geometry_to_bbox) need this distinction -- shading a
    hole as huntable, or drawing it filled in on the ownership layer, is
    the wrong answer either way."""
    if geometry["type"] == "Polygon":
        coords = geometry["coordinates"]
        yield coords[0], list(coords[1:])
    elif geometry["type"] == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            yield polygon[0], list(polygon[1:])


def _ring_bbox(ring):
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return min(lats), max(lats), min(lons), max(lons)


def _clip_edge(points, inside, intersect):
    """Sutherland-Hodgman: clip a point list against one half-plane."""
    if not points:
        return []
    out = []
    prev = points[-1]
    prev_in = inside(prev)
    for curr in points:
        curr_in = inside(curr)
        if curr_in:
            if not prev_in:
                out.append(intersect(prev, curr))
            out.append(curr)
        elif prev_in:
            out.append(intersect(prev, curr))
        prev, prev_in = curr, curr_in
    return out


def _clip_ring_to_bbox(ring, bbox):
    """Clip one ring ([lon, lat] pairs) to an axis-aligned
    (lat_min, lat_max, lon_min, lon_max) box via Sutherland-Hodgman -- the
    box is convex, so clipping against its four half-planes in sequence is
    exact. Returns None if the ring clips away to nothing."""
    lat_min, lat_max, lon_min, lon_max = bbox
    points = ring[:-1] if ring and ring[0] == ring[-1] else list(ring)

    def edge(axis, value, keep_ge):
        def inside(p):
            return p[axis] >= value if keep_ge else p[axis] <= value

        def intersect(a, b):
            t = (value - a[axis]) / (b[axis] - a[axis])
            other = 1 - axis
            mid = a[other] + t * (b[other] - a[other])
            return [value, mid] if axis == 0 else [mid, value]

        return inside, intersect

    for axis, value, keep_ge in (
        (0, lon_min, True), (0, lon_max, False),
        (1, lat_min, True), (1, lat_max, False),
    ):
        inside, intersect = edge(axis, value, keep_ge)
        points = _clip_edge(points, inside, intersect)
        if not points:
            return None

    if len(points) < 3:
        return None
    return points + [points[0]]


def clip_geometry_to_bbox(geometry, bbox):
    """Clip a Polygon/MultiPolygon to a (lat_min, lat_max, lon_min,
    lon_max) box, holes included: each polygon component's exterior AND
    interior rings are clipped independently (the box is convex, so
    clipping each ring to it in isolation is exact), preserving which
    rings are holes so the ownership display still renders them as holes
    rather than filling them in. A hole that clips away to nothing (it
    isn't in view) is simply dropped; a component whose exterior ring
    clips away to nothing is dropped entirely, holes included. This is
    the single biggest lever for keeping embedded ownership GeoJSON
    small: a handful of huge multi-county polygons (a national forest, a
    state trust land aggregate) otherwise carry thousands of vertices
    that trace boundary far outside any one GMU.

    Returns None if nothing survives, a Polygon if exactly one component
    survives, otherwise a MultiPolygon."""
    polygons = []
    for exterior, holes in _polygon_components(geometry):
        clipped_exterior = _clip_ring_to_bbox(exterior, bbox)
        if clipped_exterior is None:
            continue
        clipped_holes = [
            clipped for hole in holes
            if (clipped := _clip_ring_to_bbox(hole, bbox)) is not None
        ]
        polygons.append([clipped_exterior] + clipped_holes)
    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def polygon_mask(lats, lons, geometries):
    """bool grid, True where a cell center falls inside any geometry,
    honoring interior rings (holes): a point inside a hole (e.g. a private
    inholding carved out of a National Forest polygon) is excluded even
    though it is inside that polygon's exterior ring.

    matplotlib's Path.contains_points does not do this for a compound
    path on its own -- verified empirically: it tests each MOVETO subpath
    independently and ORs the results, regardless of winding order, so a
    hole ring included via the standard exterior+hole path-codes
    convention is not actually subtracted. Holes are therefore subtracted
    explicitly below, per polygon component, using each ring's own
    contains_points result.

    Per-component bounding-box prefilter on the exterior ring:
    contains_points is only run on the points that fall inside a
    component's own bbox and are not already known to be inside some
    other component (a point outside the exterior's bbox can never be
    inside that component -- its holes are always contained within it).
    Behavior is identical to a full scan, this just skips work once the
    grid gets large (fine analysis grids, or many PAD-US polygons)."""
    lon2d, lat2d = np.meshgrid(lons, lats)
    points = np.column_stack([lon2d.ravel(), lat2d.ravel()])
    inside = np.zeros(points.shape[0], dtype=bool)
    for geometry in geometries:
        for exterior, holes in _polygon_components(geometry):
            remaining = ~inside
            if not remaining.any():
                break
            lat_min, lat_max, lon_min, lon_max = _ring_bbox(exterior)
            candidate = (
                remaining
                & (points[:, 1] >= lat_min) & (points[:, 1] <= lat_max)
                & (points[:, 0] >= lon_min) & (points[:, 0] <= lon_max)
            )
            if not candidate.any():
                continue
            candidate_points = points[candidate]
            in_component = Path(exterior).contains_points(candidate_points)
            if holes and in_component.any():
                in_hole = np.zeros(len(candidate_points), dtype=bool)
                for hole in holes:
                    pending = in_component & ~in_hole
                    if not pending.any():
                        break
                    in_hole[pending] = Path(hole).contains_points(candidate_points[pending])
                in_component &= ~in_hole
            idx = np.flatnonzero(candidate)
            inside[idx[in_component]] = True
    return inside.reshape(lat2d.shape)
