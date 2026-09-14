"""LANDFIRE Existing Vegetation Cover (EVC) -- the land-cover input to the
habitat factor. Fetches an EVC raster for the analysis grid's own extent,
decodes it into a numpy array aligned index-for-index with that grid, and
reduces it to a single 0..1 "cover suitability" score.

Why EVC and not EVT: LANDFIRE also publishes Existing Vegetation *Type*
(EVT), an ~830-class vegetation-community product (e.g. "Southern Rocky
Mountain Ponderosa Pine Woodland") that would let a species-level rule
single out aspen. But EVT's ImageServer has no usable attribute table
(`rasterAttributeTable` returns empty; confirmed live against
LF2024_EVT_CONUS) -- turning a raw EVT code into a name requires LANDFIRE's
~830-row CSV (https://www.landfire.gov/sites/default/files/CSV/2024/
LF2024_EVT.csv), which this module does not bundle or fetch at run time.
EVC, by contrast, verified against its own official CSV
(https://www.landfire.gov/sites/default/files/CSV/2024/LF2024_EVC.csv),
encodes both land-cover *class* and canopy *percent* directly in the
pixel value, with no lookup table needed:

    11            Open water
    12            Snow/Ice
    13-17         Developed, by dominant lifeform (upland forest/herb/shrub)
    21-25         Developed, by intensity (open space .. high intensity, roads)
    31, 32        Barren; quarries/mines/gravel pits/pads
    61-69, 82     Agriculture (NASS crop classes, cultivated crops)
    100           Sparse vegetation canopy
    110-199       Tree cover:       value - 100 = percent canopy (10-99%)
    210-299       Shrub cover:      value - 200 = percent canopy (10-99%)
    310-399       Herbaceous cover: value - 300 = percent canopy (10-99%)

Documented limitation: because EVC carries no species information, "aspen
and mixed forest" cannot be distinguished from conifer timber by cover
value alone. This module approximates that distinction with open/moderate
tree canopy and shrub cover generally (see TREE_SECURITY_FULL_PCT /
SHRUB_FORAGE_FULL_PCT below) rather than true aspen detection -- see
README for the same caveat in context.

HUNTING HEURISTIC, NOT SETTLED BIOLOGY: every constant below is a tunable
guess about what a mule deer prefers, not a sourced wildlife-biology
parameter -- same spirit as terrain.py's aspect-preference note. Tune
freely if your own scouting says otherwise."""

import io

import numpy as np
from PIL import Image
from scipy.ndimage import uniform_filter

from net import SESSION

EVC_SERVICE = "https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2024/LF2024_EVC_CONUS"

# --- EVC value bands (verified against LF2024_EVC.csv; see module docstring) ---
EVC_WATER = {11}
EVC_SNOW_ICE = {12}
EVC_DEVELOPED = set(range(13, 18)) | set(range(21, 26))
EVC_BARREN = {31, 32}
EVC_AGRICULTURE = {61, 63, 64, 65, 68, 69, 82}
EVC_SPARSE = {100}
EVC_TREE_MIN, EVC_TREE_MAX = 110, 199
EVC_SHRUB_MIN, EVC_SHRUB_MAX = 210, 299
EVC_HERB_MIN, EVC_HERB_MAX = 310, 399
EVC_NONHABITAT_CODES = sorted(EVC_WATER | EVC_SNOW_ICE | EVC_DEVELOPED | EVC_AGRICULTURE | EVC_BARREN)

# --- Cover -> mule deer score tunables ---
# Developed/agriculture/open water/barren/snow: "near zero", not literally
# 0, so one misclassified or edge-of-raster pixel can't blank out a whole
# cell's habitat score outright.
NONHABITAT_SCORE = 0.05
SPARSE_VEG_SCORE = 0.15          # sparse vegetation canopy: a little better than bare ground
UNKNOWN_SCORE = 0.5              # any code this module doesn't recognize (incl. nodata): neutral

TREE_SECURITY_FULL_PCT = 65.0    # tree canopy % at which the security-cover score saturates at 1.0 --
                                  # higher than elk's 50%: mule deer rely less on big timber
SHRUB_FORAGE_FULL_PCT = 25.0     # shrub canopy % at which the forage score saturates at 1.0 --
                                  # lower than elk's 40%: mule deer are primarily browsers, so even
                                  # moderate mountain-shrub cover is prime habitat
HERB_MODERATE_CAP = 0.6          # open grassland/herbaceous never scores as high as prime timber/shrub

EDGE_WEIGHT = 0.25                # blend weight of the forest/opening edge bonus into the final score
EDGE_WINDOW_CELLS = 3             # neighborhood window (grid cells) used to detect the edge
EDGE_STD_FULL = 0.25              # local std of tree-canopy-fraction at which the edge bonus saturates

_CACHE = {}  # (service, bbox..., width, height) -> decoded EVC grid; per-process, not persisted to disk


def decode_evc_tiff(tiff_bytes, width, height):
    """TIFF bytes -> numpy grid aligned to an ascending-lat/ascending-lon
    grid of shape (height, width). ImageServer returns mode I;16 for
    pixelType=U16 (same as terrain.py's Terrarium PNGs, different codec).

    Two corrections, verified against the live service (see README):
    (1) resize defensively if the service didn't honor the requested
    size exactly (adjustAspectRatio-type behavior); (2) flip vertically --
    raster row 0 is the north edge of the requested bbox, while this
    project's lats arrays are ascending south-to-north everywhere else."""
    img = Image.open(io.BytesIO(tiff_bytes))
    if img.size != (width, height):
        img = img.resize((width, height), Image.NEAREST)
    arr = np.array(img).astype(np.int32)
    return np.flipud(arr)


def fetch_landcover_grid(lats, lons, service=EVC_SERVICE, timeout=60):
    """Fetch one EVC raster sized and aligned to the (lats, lons) analysis
    grid: bbox is expanded by half a cell on every side so that each of
    the requested (len(lons), len(lats)) output pixels' *center* lands
    exactly on one (lat, lon) grid point, and imageSR=4326 keeps the
    export lat/lon-aligned so no reprojection is needed to sample it by
    index. Cached per (bbox, size) for the life of the process."""
    dlat = float(lats[1] - lats[0]) if len(lats) > 1 else 0.001
    dlon = float(lons[1] - lons[0]) if len(lons) > 1 else 0.001
    lat_min = float(lats.min()) - dlat / 2
    lat_max = float(lats.max()) + dlat / 2
    lon_min = float(lons.min()) - dlon / 2
    lon_max = float(lons.max()) + dlon / 2
    width, height = len(lons), len(lats)

    cache_key = (service, round(lat_min, 6), round(lat_max, 6),
                 round(lon_min, 6), round(lon_max, 6), width, height)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    params = {
        "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "bboxSR": 4326,
        "imageSR": 4326,
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "U16",
        "interpolation": "RSP_NearestNeighbor",
        "f": "image",
    }
    resp = SESSION.get(f"{service}/ImageServer/exportImage", params=params, timeout=timeout)
    resp.raise_for_status()
    grid = decode_evc_tiff(resp.content, width, height)
    _CACHE[cache_key] = grid
    return grid


def _forest_edge_bonus(evc_values, tree_mask):
    """Local standard deviation of tree-canopy fraction over a small
    neighborhood: near 0 in a uniform stand (all timber or all opening),
    largest where dense forest sits right next to open ground -- exactly
    the transition zone mule deer favor for feeding near cover."""
    canopy = np.where(tree_mask, (evc_values - 100.0) / 100.0, 0.0)
    mean = uniform_filter(canopy, size=EDGE_WINDOW_CELLS, mode="nearest")
    mean_sq = uniform_filter(canopy ** 2, size=EDGE_WINDOW_CELLS, mode="nearest")
    local_std = np.sqrt(np.clip(mean_sq - mean ** 2, 0.0, None))
    return np.clip(local_std / EDGE_STD_FULL, 0.0, 1.0)


def _known_code_masks(v):
    """The five disjoint boolean masks cover_suitability_score itself
    computes (tree/shrub/herb/nonhabitat/sparse), split out so
    known_evc_coverage_frac (and cover_suitability_score, below) share one
    definition of "a code this module actually recognizes" -- anything
    outside all five bands, including LANDFIRE's nodata sentinel, falls
    through to UNKNOWN_SCORE and is not counted as known."""
    tree_mask = (v >= EVC_TREE_MIN) & (v <= EVC_TREE_MAX)
    shrub_mask = (v >= EVC_SHRUB_MIN) & (v <= EVC_SHRUB_MAX)
    herb_mask = (v >= EVC_HERB_MIN) & (v <= EVC_HERB_MAX)
    nonhabitat_mask = np.isin(v, EVC_NONHABITAT_CODES)
    sparse_mask = np.isin(v, list(EVC_SPARSE))
    return tree_mask, shrub_mask, herb_mask, nonhabitat_mask, sparse_mask


def known_evc_coverage_frac(evc_values):
    """Fraction of pixels whose EVC value falls into any band this module
    recognizes (tree/shrub/herb/nonhabitat/sparse) -- the complement is
    nodata plus any other code the module doesn't know, which
    cover_suitability_score silently scores UNKNOWN_SCORE (neutral 0.5)
    rather than flagging. A raster that is effectively all nodata (a
    LANDFIRE export that failed to actually cover this extent, e.g. an
    edge-of-coverage bbox or a service-side hiccup) would otherwise come
    back as a flat 0.5 land-cover input that the status panel reports as
    "cover" being a real, used factor -- see fetch_cover_score."""
    v = np.asarray(evc_values, dtype=np.float64)
    known = np.zeros(v.shape, dtype=bool)
    for mask in _known_code_masks(v):
        known |= mask
    return float(np.mean(known)) if known.size else 0.0


# Below this fraction of recognized pixels, a fetched EVC raster is treated
# as effectively empty (see fetch_cover_score) rather than as real land
# cover data. 0.0 (the literal "every pixel is nodata" case the review
# flagged) would also be caught by requiring >0, but a raster that is 99%
# nodata with a handful of coincidentally-valid-looking codes at the edge
# is just as untrustworthy as one that is 100% nodata, so the threshold is
# a small, forgiving cutoff rather than a strict >0 check.
MIN_KNOWN_EVC_COVERAGE_FRAC = 0.05


def cover_suitability_score(evc_values):
    """EVC raster values -> mule deer cover-suitability score, 0..1. See
    module docstring for the verified value bands and the mapping
    rationale."""
    v = np.asarray(evc_values, dtype=np.float64)
    score = np.full(v.shape, UNKNOWN_SCORE)

    tree_mask, shrub_mask, herb_mask, nonhabitat_mask, sparse_mask = _known_code_masks(v)

    score = np.where(tree_mask, np.clip((v - 100.0) / TREE_SECURITY_FULL_PCT, 0.0, 1.0), score)
    score = np.where(shrub_mask, np.clip((v - 200.0) / SHRUB_FORAGE_FULL_PCT, 0.0, 1.0), score)
    score = np.where(herb_mask, np.clip((v - 300.0) / 100.0, 0.0, 1.0) * HERB_MODERATE_CAP, score)
    score = np.where(nonhabitat_mask, NONHABITAT_SCORE, score)
    score = np.where(sparse_mask, SPARSE_VEG_SCORE, score)

    # Additive, not a weighted average: an edge bonus should top up a cell
    # that already has decent cover, not drag every uniform interior cell
    # down toward whatever the (usually low, non-tree) edge value is.
    edge = _forest_edge_bonus(v, tree_mask)
    return np.clip(score + EDGE_WEIGHT * edge, 0.0, 1.0)


def fetch_cover_score(lats, lons, service=EVC_SERVICE, timeout=60):
    """Convenience: fetch + decode + score in one call. Raises on fetch
    failure (network error, bad status) -- callers should catch and treat
    a failure as "cover unavailable this run" (terrain.habitat_components
    already renormalizes around a missing cover_score).

    Also raises if the fetched raster is effectively all nodata/
    unrecognized codes (known_evc_coverage_frac below
    MIN_KNOWN_EVC_COVERAGE_FRAC): without this check, such a raster would
    silently score every pixel UNKNOWN_SCORE (a flat, contentless 0.5)
    while still being reported everywhere else (the status panel's
    "habitat inputs" line, deer_map.process_unit's habitat_used) as if
    cover were real, used data. Treating it as a failed fetch instead lets
    it degrade exactly like a genuine HTTP failure does."""
    grid = fetch_landcover_grid(lats, lons, service=service, timeout=timeout)
    coverage = known_evc_coverage_frac(grid)
    if coverage < MIN_KNOWN_EVC_COVERAGE_FRAC:
        raise RuntimeError(
            f"LANDFIRE EVC raster is effectively empty ({coverage:.1%} of pixels "
            "recognized) -- treating as a failed fetch so habitat renormalizes without cover"
        )
    return cover_suitability_score(grid)
