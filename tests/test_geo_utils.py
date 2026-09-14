import numpy as np
import pytest

from geo_utils import bounds_of_coords, buffer_bounds, clip_geometry_to_bbox, polygon_mask


def test_bounds_of_coords_handles_polygon_ring():
    coords = [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]
    assert bounds_of_coords(coords) == (0.0, 1.0, 0.0, 1.0)


def test_buffer_bounds_expands_symmetrically_in_degrees():
    # ~69 miles ~ 1 degree of latitude
    lat_min, lat_max, lon_min, lon_max = buffer_bounds((10.0, 10.0, 20.0, 20.0), 69.0)
    assert lat_min == pytest.approx(9.0, abs=0.01)
    assert lat_max == pytest.approx(11.0, abs=0.01)


def test_polygon_mask_true_inside_false_outside():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}
    lats = np.array([0.5, 1.5, 3.0])
    lons = np.array([0.5, 1.5, 3.0])
    mask = polygon_mask(lats, lons, [square])
    assert mask[0, 0] == True
    assert mask[1, 1] == True
    assert mask[2, 2] == False


def test_polygon_mask_bbox_prefilter_still_finds_points_in_later_rings():
    """A per-ring bounding-box prefilter must not drop points that fall
    outside an earlier ring's bbox but inside a later, disjoint ring."""
    sq1 = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    sq2 = {"type": "Polygon", "coordinates": [[[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]]]}
    lats = np.array([0.5, 5.5, 10.0])
    lons = np.array([0.5, 5.5, 10.0])
    mask = polygon_mask(lats, lons, [sq1, sq2])
    assert mask[0, 0] == True   # inside sq1 only
    assert mask[1, 1] == True   # inside sq2 only, outside sq1's bbox
    assert mask[2, 2] == False  # outside both


def test_polygon_mask_matches_brute_force_over_many_disjoint_rings():
    """Correctness check for the bbox-prefiltered implementation against a
    naive brute-force contains_points scan, over enough scattered rings and
    points that a prefilter bug (e.g. skipping a point that should have
    been tested) would show up."""
    from matplotlib.path import Path as MplPath

    rng = np.random.default_rng(0)
    geometries = []
    for k in range(15):
        cx, cy = rng.uniform(0, 20, size=2)
        r = rng.uniform(0.3, 1.0)
        ring = [
            [cx + r * np.cos(t), cy + r * np.sin(t)]
            for t in np.linspace(0, 2 * np.pi, 8)
        ]
        geometries.append({"type": "Polygon", "coordinates": [ring]})

    lats = np.linspace(0, 20, 40)
    lons = np.linspace(0, 20, 40)
    lon2d, lat2d = np.meshgrid(lons, lats)
    points = np.column_stack([lon2d.ravel(), lat2d.ravel()])

    expected = np.zeros(points.shape[0], dtype=bool)
    for geometry in geometries:
        ring = geometry["coordinates"][0]
        expected |= MplPath(ring).contains_points(points)
    expected = expected.reshape(lat2d.shape)

    mask = polygon_mask(lats, lons, geometries)
    np.testing.assert_array_equal(mask, expected)


def test_clip_geometry_to_bbox_trims_a_polygon_extending_beyond_the_box():
    """A huge polygon (simulating a national-forest boundary) that only
    partly overlaps the box should come back clipped to the box, not with
    its original far-outside vertices intact."""
    huge_square = {"type": "Polygon", "coordinates": [[[-10, -10], [-10, 10], [10, 10], [10, -10], [-10, -10]]]}
    bbox = (0.0, 1.0, 0.0, 1.0)  # lat_min, lat_max, lon_min, lon_max
    clipped = clip_geometry_to_bbox(huge_square, bbox)
    assert clipped["type"] == "Polygon"
    lons = [c[0] for c in clipped["coordinates"][0]]
    lats = [c[1] for c in clipped["coordinates"][0]]
    assert min(lons) == pytest.approx(0.0)
    assert max(lons) == pytest.approx(1.0)
    assert min(lats) == pytest.approx(0.0)
    assert max(lats) == pytest.approx(1.0)


def test_clip_geometry_to_bbox_returns_none_when_fully_outside():
    square = {"type": "Polygon", "coordinates": [[[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]]]}
    bbox = (0.0, 1.0, 0.0, 1.0)
    assert clip_geometry_to_bbox(square, bbox) is None


def test_clip_geometry_to_bbox_leaves_a_fully_contained_polygon_unchanged_in_extent():
    small_square = {"type": "Polygon", "coordinates": [[[0.2, 0.2], [0.2, 0.4], [0.4, 0.4], [0.4, 0.2], [0.2, 0.2]]]}
    bbox = (0.0, 1.0, 0.0, 1.0)
    clipped = clip_geometry_to_bbox(small_square, bbox)
    lons = sorted({round(c[0], 6) for c in clipped["coordinates"][0]})
    lats = sorted({round(c[1], 6) for c in clipped["coordinates"][0]})
    assert lons == [0.2, 0.4]
    assert lats == [0.2, 0.4]


def test_polygon_mask_excludes_points_inside_an_interior_ring_hole():
    """A private inholding represented as an interior ring (hole) of a
    National Forest polygon must not be shaded as huntable: a point inside
    the hole is inside the exterior ring but must read as outside the
    polygon overall."""
    donut = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],       # exterior
            [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]],           # hole (private inholding)
        ],
    }
    lats = np.array([1.0, 5.0, 9.0])
    lons = np.array([1.0, 5.0, 9.0])
    mask = polygon_mask(lats, lons, [donut])
    assert mask[0, 0] == True   # inside the annulus (outside the hole)
    assert mask[1, 1] == False  # inside the hole -- must not read as huntable
    assert mask[2, 2] == True   # inside the annulus, other corner


def test_polygon_mask_hole_in_one_multipolygon_component_does_not_affect_another():
    """A hole belongs to its own polygon component only -- it must not
    exclude points that fall inside a different, disjoint polygon in the
    same MultiPolygon."""
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
                [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]],
            ],
            [[[20, 20], [20, 21], [21, 21], [21, 20], [20, 20]]],
        ],
    }
    lats = np.array([5.0, 20.5])
    lons = np.array([5.0, 20.5])
    mask = polygon_mask(lats, lons, [multi])
    assert mask[0, 0] == False  # inside the first component's hole
    assert mask[1, 1] == True   # inside the second, hole-free component


def test_clip_geometry_to_bbox_preserves_a_hole_fully_inside_the_box():
    """The ownership display layer must keep rendering a hole as a hole
    after bbox-clipping, not silently fill it back in."""
    donut = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
            [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]],
        ],
    }
    bbox = (-1.0, 11.0, -1.0, 11.0)  # box fully contains the donut
    clipped = clip_geometry_to_bbox(donut, bbox)
    assert clipped["type"] == "Polygon"
    assert len(clipped["coordinates"]) == 2  # exterior + the surviving hole
    hole = clipped["coordinates"][1]
    hole_lons = [c[0] for c in hole]
    hole_lats = [c[1] for c in hole]
    assert min(hole_lons) == pytest.approx(4.0)
    assert max(hole_lons) == pytest.approx(6.0)
    assert min(hole_lats) == pytest.approx(4.0)
    assert max(hole_lats) == pytest.approx(6.0)


def test_clip_geometry_to_bbox_multipolygon_with_one_ring_clipped_away():
    """One ring fully inside the box, one fully outside -- only the inside
    ring should survive, collapsing to a Polygon rather than a
    MultiPolygon with an empty part."""
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0.2, 0.2], [0.2, 0.4], [0.4, 0.4], [0.4, 0.2], [0.2, 0.2]]],
            [[[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]]],
        ],
    }
    bbox = (0.0, 1.0, 0.0, 1.0)
    clipped = clip_geometry_to_bbox(multi, bbox)
    assert clipped["type"] == "Polygon"
