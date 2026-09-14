"""Colorado hunting-access data sources beyond PAD-US, plus the three-tier
legal-access model that replaces the old PAD-US-Open-Access-only mask.

PAD-US alone under-represents real huntable public land in Colorado: it
codes most State Land Board (state trust) parcels, and some State
Wildlife Areas, as "Restricted Access" (RA), when CPW's own data shows
many of them open to licensed hunters. This module fetches the CPW/State
Land Board sources that actually determine hunting access for that land:

- CPW State Wildlife Areas / managed properties (public access only) --
  the SWAs, walk-in parcels, etc. CPW itself manages for hunting.
- CPW's Walk-In Access Program -- mostly eastern-plains private land
  enrolled for public hunting access; can be empty for a given unit (the
  program barely reaches the mountains), which is expected, not an error.
- State Trust Land parcels enrolled in CPW's Public Access Program (two
  companion layers, "CPWPublicAccessProperties" and its "_STL" variant) --
  the State Land Board acreage that is actually huntable, versus the much
  larger pool of State Land Board land PAD-US marks Restricted Access.

See README's "Access tiers" section for the full model and measured
acreage deltas versus the old OA-only mask.
"""

from geo_utils import polygon_mask
from net import SESSION

ARCGIS_BASE = "https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/arcgis/rest/services/"

CPW_MANAGED_PROPERTIES_URL = ARCGIS_BASE + "CPWAdminData/FeatureServer/5/query"
CPW_WALK_IN_ACCESS_URL = ARCGIS_BASE + "CPWAdminData/FeatureServer/12/query"
SLB_PUBLIC_ACCESS_PROPERTIES_URL = ARCGIS_BASE + "SLB_PAP_map/FeatureServer/3/query"
SLB_PUBLIC_ACCESS_STL_URL = ARCGIS_BASE + "SLB_PAP_map/FeatureServer/2/query"

# Same server-side simplification public_land.fetch_land_ownership_features
# uses: maxAllowableOffset in output-SR degrees (~30-50m at CO latitudes,
# imperceptible at map scale), geometryPrecision truncating output decimals.
DEFAULT_MAX_ALLOWABLE_OFFSET = 0.0004
DEFAULT_GEOMETRY_PRECISION = 5
PAGE_SIZE = 1000

# Tooltip/legend label for each source -- "which source granted access",
# per feature, via properties['_source'] (see _tag_source/fetch_cpw_access_features).
SOURCE_LABELS = {
    "cpw_managed": "CPW State Wildlife Area / managed property",
    "walk_in_access": "CPW Walk-In Access Program",
    "slb_pap": "State Trust Land, CPW Public Access Program",
}


def _fetch_paged(url, bbox, out_fields="*", timeout=60,
                  max_allowable_offset=DEFAULT_MAX_ALLOWABLE_OFFSET,
                  geometry_precision=DEFAULT_GEOMETRY_PRECISION,
                  page_size=PAGE_SIZE):
    """Same paging/simplification treatment as
    public_land.fetch_land_ownership_features: resultOffset paging with an
    exceededTransferLimit check (continuing until it is absent or false),
    plus maxAllowableOffset + geometryPrecision server-side simplification.
    Shared here since all four CPW/SLB sources use identical ArcGIS
    FeatureServer query semantics. Returns [] cleanly for a source with no
    features in bbox (e.g. Walk-In Access outside the eastern plains) --
    not an error."""
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


def fetch_cpw_managed_properties(bbox, timeout=60, **kwargs):
    """CPW State Wildlife Areas / managed properties (public access
    only). Fields: FID, PropName, PropType, Acres, LastUpdate, GlobalID,
    CPW_URL."""
    return _fetch_paged(CPW_MANAGED_PROPERTIES_URL, bbox, timeout=timeout, **kwargs)


def fetch_walk_in_access(bbox, timeout=60, **kwargs):
    """CPW Walk-In Access Program parcels. This program is mostly
    eastern-plains, so an empty list is the expected, common case for
    mountain units (e.g. GMU 59 returns 0 features) -- callers must treat
    an empty list as "nothing here", not a failure."""
    return _fetch_paged(CPW_WALK_IN_ACCESS_URL, bbox, timeout=timeout, **kwargs)


def fetch_slb_public_access_properties(bbox, timeout=60, **kwargs):
    """State Trust Land parcels enrolled in CPW's Public Access Program
    (SLB_PAP_map/FeatureServer/3, "CPWPublicAccessProperties")."""
    return _fetch_paged(SLB_PUBLIC_ACCESS_PROPERTIES_URL, bbox, timeout=timeout, **kwargs)


def fetch_slb_public_access_stl(bbox, timeout=60, **kwargs):
    """State Trust Land parcels enrolled in CPW's Public Access Program,
    the companion layer (SLB_PAP_map/FeatureServer/2,
    "CPWPublicAccessProperties_STL")."""
    return _fetch_paged(SLB_PUBLIC_ACCESS_STL_URL, bbox, timeout=timeout, **kwargs)


def _tag_source(features, source_key):
    """Copy each feature with properties['_source'] = source_key, so the
    ownership tooltip can say which CPW/SLB source granted access."""
    out = []
    for f in features:
        tagged = dict(f)
        props = dict(f.get("properties") or {})
        props["_source"] = source_key
        tagged["properties"] = props
        out.append(tagged)
    return out


def fetch_cpw_access_features(bbox, timeout=60):
    """Fetch and tag all three CPW/SLB access sources for bbox (four
    layers -- the two SLB Public Access Program layers share one source
    tag, "slb_pap", since both represent the same program). Returns a
    flat list of GeoJSON features, each carrying properties['_source'].
    A source that returns zero features simply contributes nothing."""
    features = []
    features += _tag_source(fetch_cpw_managed_properties(bbox, timeout=timeout), "cpw_managed")
    features += _tag_source(fetch_walk_in_access(bbox, timeout=timeout), "walk_in_access")
    features += _tag_source(fetch_slb_public_access_properties(bbox, timeout=timeout), "slb_pap")
    features += _tag_source(fetch_slb_public_access_stl(bbox, timeout=timeout), "slb_pap")
    return features


def access_geometries(features):
    """Plain geometry dicts (for geo_utils.polygon_mask) from a feature
    list. Source tagging only matters for the display layer's tooltip,
    not for the boolean access mask."""
    return [f["geometry"] for f in features if f.get("geometry")]


def classify_access(lats, lons, oa_polygons, ra_polygons, cpw_polygons, gmu_geometry):
    """Three-tier legal-access classification per grid cell, replacing the
    old PAD-US-Open-Access-only hard mask.

    - open: PAD-US Open Access ('OA'), OR inside a CPW managed property,
      Walk-In Access parcel, or SLB Public Access Program parcel.
    - conditional: PAD-US Restricted Access ('RA') that is not already
      open. Not shaded in the probability heatmap, but should be shown
      distinctly in the ownership layer so a user can see it and check it
      themselves (CPW's hunting atlas is the authority).
    - closed: everything else -- private land, land with no PAD-US
      record, and (via the GMU-boundary intersection below) any land
      outside the unit's real legal boundary, even if it falls inside the
      buffered analysis bbox.

    All three masks are intersected with gmu_geometry, not just the
    buffered bbox -- same boundary-correctness fix as
    elk_map.combined_access_mask, applied here to all three tiers at
    once. Returns (open_mask, conditional_mask, closed_mask): bool grids
    shaped like the lats/lons meshgrid, mutually exclusive and
    exhaustive."""
    gmu_mask = polygon_mask(lats, lons, [gmu_geometry])
    open_mask = polygon_mask(lats, lons, list(oa_polygons) + list(cpw_polygons)) & gmu_mask
    ra_mask = polygon_mask(lats, lons, ra_polygons) & gmu_mask
    conditional_mask = ra_mask & ~open_mask
    closed_mask = ~open_mask & ~conditional_mask
    return open_mask, conditional_mask, closed_mask
