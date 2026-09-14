"""CPW's own mule deer seasonal-range polygons -- the third top-level
probability factor. These are Colorado Parks and Wildlife biologists'
delineations of where mule deer actually are, which is better evidence
than anything habitat.py or terrain.py infer from elevation/aspect/land
cover alone.

Source: `CPWHPHTerrestrialData/FeatureServer`, the same ArcGIS host
gmu_boundary.py and hunting_access.py already use (no API key). Layers:

    29  Mule Deer Migration Corridor HPHD
    30  Mule Deer Severe Winter Range HPHD
    31  Mule Deer Winter Concentration Area HPHD

The same elk-probability-map repo's elk_range.py queries layers 20-23 on
this identical service. Unlike elk, there is no Mule Deer Production Area
(or any other fourth) layer in this service at all -- nothing to
fetch-but-exclude from scoring.

IMPORTANT LIMITATION -- must be handled in scoring, not just noted: these
are "High Priority Habitat" *subsets*, not a complete mule deer range
product. There is no Mule Deer Overall Range layer and no Mule Deer
Summer Range layer in this service at all. A grid cell outside every
polygon fetched here is therefore NOT evidence that deer are absent from
that cell -- it may simply be un-delineated range, or a season/category
this service doesn't cover. See NEUTRAL_BASELINE below for how that is
handled.

SEASON RELEVANCE (the map targets 2nd rifle, roughly late October into
early November): Winter Concentration Area and Severe Winter Range are
directly relevant -- deer are moving onto winter range as the season
progresses and snow accumulates. Migration Corridor is relevant too,
since deer are actively moving between summer and winter range through
this window -- the same reasoning elk_range.py uses for elk's 3rd rifle
(also November), just slightly earlier in the season."""

import numpy as np

from geo_utils import clip_geometry_to_bbox, polygon_mask
from hunting_access import ARCGIS_BASE
from net import SESSION

DEER_RANGE_BASE = ARCGIS_BASE + "CPWHPHTerrestrialData/FeatureServer/"

RANGE_TYPE_URLS = {
    "migration_corridor": DEER_RANGE_BASE + "29/query",
    "severe_winter_range": DEER_RANGE_BASE + "30/query",
    "winter_concentration": DEER_RANGE_BASE + "31/query",
}

RANGE_TYPE_LABELS = {
    "migration_corridor": "Mule Deer Migration Corridor",
    "severe_winter_range": "Mule Deer Severe Winter Range",
    "winter_concentration": "Mule Deer Winter Concentration Area",
}

# Same server-side simplification public_land.fetch_land_ownership_features
# and hunting_access._fetch_paged use: maxAllowableOffset in output-SR
# degrees (~30-50m at CO latitudes, imperceptible at map scale),
# geometryPrecision truncating output decimals.
DEFAULT_MAX_ALLOWABLE_OFFSET = 0.0004
DEFAULT_GEOMETRY_PRECISION = 5
PAGE_SIZE = 1000


def _fetch_paged(url, bbox, out_fields="*", timeout=60,
                  max_allowable_offset=DEFAULT_MAX_ALLOWABLE_OFFSET,
                  geometry_precision=DEFAULT_GEOMETRY_PRECISION,
                  page_size=PAGE_SIZE):
    """Same paging/simplification treatment as hunting_access._fetch_paged
    and public_land.fetch_land_ownership_features: resultOffset paging
    with an exceededTransferLimit check (continuing until it is absent or
    false), plus maxAllowableOffset + geometryPrecision server-side
    simplification. Returns [] cleanly for a layer with no features in
    bbox -- not an error (e.g. a unit with no delineated Migration
    Corridor at all)."""
    lat_min, lat_max, lon_min, lon_max = bbox
    base_params = {
        "where": "1=1",
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "true",
        "f": "geojson",
        "resultRecordCount": page_size,
    }
    if max_allowable_offset is not None:
        base_params["maxAllowableOffset"] = max_allowable_offset
    if geometry_precision is not None:
        base_params["geometryPrecision"] = geometry_precision

    features = []
    offset = 0
    while True:
        params = dict(base_params, resultOffset=offset)
        resp = SESSION.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        page = resp.json()
        page_features = page.get("features", [])
        features.extend(page_features)
        if not page_features or not page.get("exceededTransferLimit"):
            break
        offset += len(page_features)
    return features


def _tag_range_type(features, range_type):
    """Copy each feature with properties['_range_type'] = range_type, so
    downstream scoring/display can tell which of the three layers a
    feature came from (all three share the same field schema)."""
    out = []
    for f in features:
        tagged = dict(f)
        props = dict(f.get("properties") or {})
        props["_range_type"] = range_type
        tagged["properties"] = props
        out.append(tagged)
    return out


def fetch_deer_range_features(bbox, timeout=60, **kwargs):
    """Fetch and tag all three mule-deer-range layers for bbox. Returns a
    flat list of GeoJSON features, each carrying properties['_range_type'].
    A layer with zero features in bbox simply contributes nothing to the
    result -- expected, not an error."""
    features = []
    for range_type, url in RANGE_TYPE_URLS.items():
        raw = _fetch_paged(url, bbox, timeout=timeout, **kwargs)
        features += _tag_range_type(raw, range_type)
    return features


def range_geometries(features, range_type):
    """Geometry dicts for one range type only (for geo_utils.polygon_mask),
    from a feature list carrying mixed range types
    (fetch_deer_range_features' output)."""
    return [f["geometry"] for f in features
            if f.get("properties", {}).get("_range_type") == range_type and f.get("geometry")]


# --- Scoring ---
#
# A cell outside every polygon fetched here is NOT evidence deer are
# absent (see module docstring): these layers are HPH *subsets*, not a
# complete deer-range product. Scoring absence as 0 would act as a de
# facto mask and black out everything outside a handful of polygons,
# which is exactly wrong for a factor meant to ADD confidence where CPW
# has delineated range, not subtract it everywhere else. NEUTRAL_BASELINE
# is therefore a named, tunable "we don't know" value: below every scored
# range type's in-polygon contribution, but well above 0. Same value as
# elk_range.py's NEUTRAL_BASELINE (0.5) -- no reason to differ by species.
NEUTRAL_BASELINE = 0.5

# Per-range-type score for a cell inside that range type's polygon (see
# seasonal_range_score). Same relative ordering and values as
# elk_range.py's RANGE_TYPE_SCORES -- no calibration data exists to
# justify a different confidence ordering for mule deer.
WINTER_CONCENTRATION_SCORE = 1.0   # CPW's own delineation of where deer actually concentrate in winter -- the single strongest signal this service offers for a 2nd-rifle hunt
SEVERE_WINTER_RANGE_SCORE = 0.85   # occupied once conditions turn severe; by 2nd rifle (late Oct/early Nov), early snow is already plausible, just a notch below confirmed concentration areas
MIGRATION_CORRIDOR_SCORE = 0.7     # deer actively moving through these corridors toward winter range, but transiently passing through rather than concentrated -- lower confidence than ground they occupy and stay in

RANGE_TYPE_SCORES = {
    "winter_concentration": WINTER_CONCENTRATION_SCORE,
    "severe_winter_range": SEVERE_WINTER_RANGE_SCORE,
    "migration_corridor": MIGRATION_CORRIDOR_SCORE,
}


def seasonal_range_score(lats, lons, features, baseline=NEUTRAL_BASELINE):
    """0..1 grid: NEUTRAL_BASELINE everywhere a cell falls outside every
    scored range type (see module docstring -- absence here is not
    evidence of deer absence), else the highest-confidence scored range
    type the cell falls inside (RANGE_TYPE_SCORES), via a per-type mask
    and an elementwise max -- a cell inside two overlapping range types
    (e.g. Severe Winter Range AND a Migration Corridor) scores once, at
    the more confident type's value, not double-counted by summing."""
    shape = (len(lats), len(lons))
    score = np.full(shape, baseline, dtype=np.float64)
    for range_type, type_score in RANGE_TYPE_SCORES.items():
        geometries = range_geometries(features, range_type)
        if not geometries:
            continue
        mask = polygon_mask(lats, lons, geometries)
        score = np.where(mask, np.maximum(score, type_score), score)
    return score


def clip_deer_range_features_to_bbox(features, bbox):
    """Same clip-to-bbox treatment as public_land.clip_features_to_bbox,
    for the map's display layer: trims each polygon down to the sliver
    inside this unit's bbox. Drops any feature that clips away to
    nothing."""
    out = []
    for f in features:
        geometry = clip_geometry_to_bbox(f["geometry"], bbox)
        if geometry is None:
            continue
        clipped = dict(f)
        clipped["geometry"] = geometry
        out.append(clipped)
    return out
