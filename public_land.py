"""USGS PAD-US Public Access + land ownership layer.

`fetch_open_access_polygons` -- hard mask (0/1), not a weighted factor:
OTC hunting is only actionable on land you can legally access (spec,
Probability model). That mask logic is unchanged by anything below.

`fetch_land_ownership_features` -- full features (geometry plus manager,
unit name, access code, and acreage) for the map's ownership-overlay
*display* layer, so public/private/restricted land is visible on the map
itself, not just baked into an invisible mask. Paged past the server's
per-request feature cap and simplified (maxAllowableOffset,
geometryPrecision) so two units of embedded GeoJSON stay well under the
map's HTML size budget; see README's "Land ownership layer" section for
measured sizes."""

from geo_utils import clip_geometry_to_bbox
from net import SESSION

PADUS_URL = (
    "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
    "PADUS_Public_Access/FeatureServer/0/query"
)

# Fields needed for both the OA mask (Pub_Access) and the ownership
# display layer's categorization/tooltip (manager, unit name, designation,
# access code, acres).
LAND_OWNERSHIP_FIELDS = (
    "Pub_Access", "MngNm_Desc", "MngTp_Desc", "Unit_Nm", "DesTp_Desc", "GIS_Acres",
)

# ArcGIS query simplification, applied server-side. maxAllowableOffset is
# in output-SR units (degrees, since outSR=4326 below); ~0.0004 deg is
# roughly 30-50m at Colorado latitudes -- imperceptible at map scale but
# enough to noticeably shrink vertex-heavy polygons (a national forest
# boundary, a BLM field-office aggregate). geometryPrecision truncates
# coordinate decimals in the output.
DEFAULT_MAX_ALLOWABLE_OFFSET = 0.0004
DEFAULT_GEOMETRY_PRECISION = 5

PAGE_SIZE = 2000  # PAD-US Public Access layer's maxRecordCount
MIN_DISPLAY_ACRES = 20  # drop tiny slivers from the display layer only


def fetch_land_ownership_features(bbox, timeout=60,
                                   max_allowable_offset=DEFAULT_MAX_ALLOWABLE_OFFSET,
                                   geometry_precision=DEFAULT_GEOMETRY_PRECISION,
                                   page_size=PAGE_SIZE):
    """Full PAD-US features (geometry + LAND_OWNERSHIP_FIELDS) intersecting
    bbox. Pages via resultOffset/resultRecordCount and checks
    exceededTransferLimit on every page, continuing until it is absent or
    false -- required for any unit whose feature count exceeds
    page_size (measured: GMU 59 returns 564 features, under the 2000 cap,
    but nothing here assumes that holds for every unit)."""
    lat_min, lat_max, lon_min, lon_max = bbox
    base_params = {
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join(LAND_OWNERSHIP_FIELDS),
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
        resp = SESSION.get(PADUS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        page = resp.json()
        page_features = page.get("features", [])
        features.extend(page_features)
        if not page_features or not page.get("exceededTransferLimit"):
            break
        offset += len(page_features)
    return features


def fetch_open_access_polygons(bbox, timeout=60):
    """Back-compat wrapper around fetch_land_ownership_features: OA-only
    geometries for the hard access mask. Paging/simplification now apply
    here too, but the mask semantics (Pub_Access == 'OA' only) are
    unchanged."""
    features = fetch_land_ownership_features(bbox, timeout=timeout)
    return parse_open_access_polygons({"features": features})


def parse_open_access_polygons(geojson_obj):
    return [
        f["geometry"]
        for f in geojson_obj.get("features", [])
        if f.get("properties", {}).get("Pub_Access") == "OA"
    ]


def parse_restricted_access_polygons(geojson_obj):
    """Same shape as parse_open_access_polygons, but Pub_Access == 'RA' --
    the pool hunting_access.classify_access draws the 'conditional' tier
    from (RA land not already covered by a CPW/SLB access source)."""
    return [
        f["geometry"]
        for f in geojson_obj.get("features", [])
        if f.get("properties", {}).get("Pub_Access") == "RA"
    ]


def clip_features_to_bbox(features, bbox):
    """Clip each feature's geometry to bbox (see geo_utils.
    clip_geometry_to_bbox) -- trims huge multi-county polygons down to
    just the sliver inside this unit. This is the single biggest lever
    for keeping the embedded ownership GeoJSON under budget; simplification
    alone (maxAllowableOffset/geometryPrecision) does not touch the vertex
    count of the parts of a polygon that lie far outside the unit. Drops
    any feature that clips away to nothing."""
    out = []
    for f in features:
        geometry = clip_geometry_to_bbox(f["geometry"], bbox)
        if geometry is None:
            continue
        clipped = dict(f)
        clipped["geometry"] = geometry
        out.append(clipped)
    return out


def filter_min_acres(features, min_acres=MIN_DISPLAY_ACRES):
    """Drop display features under min_acres, using the GIS_Acres
    attribute (the parcel's real acreage, not the clipped-to-bbox sliver)
    -- declutters the rendered map of tiny parcels without touching the OA
    mask, which is built from the unfiltered feature set. Features with no
    GIS_Acres value are kept (unknown acreage should not be dropped
    blindly)."""
    out = []
    for f in features:
        acres = f.get("properties", {}).get("GIS_Acres")
        if acres is not None and acres < min_acres:
            continue
        out.append(f)
    return out
