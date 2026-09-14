"""Elevation (AWS public Terrarium tiles), slope/aspect, and the mule
deer habitat-suitability factor: an elevation-band preference (peaks
~6,500-9,500 ft, shifted down by current snow depth) blended with an
aspect preference (default: south-facing, a solar-exposure/forage
heuristic -- south slopes melt out first and retain browse longer as
snow accumulates), a slope preference (moderate ground favored,
cliff-steep avoided), and a land-cover suitability score (landcover.py,
LANDFIRE EVC) -- see README for why every one of these is tunable, not
asserted biology."""

import io
import math

import numpy as np

from geo_utils import KM_PER_DEG
from net import SESSION

TILE_ZOOM = 11
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def latlon_to_tile(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def pixel_in_tile(lat, lon, x, y, zoom):
    n = 2 ** zoom
    lat_rad = math.radians(lat)
    fx = (lon + 180.0) / 360.0 * n
    fy = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    px = int((fx - x) * 256)
    py = int((fy - y) * 256)
    return min(max(px, 0), 255), min(max(py, 0), 255)


def decode_terrarium(img_float_rgb):
    """matplotlib.image.imread gives floats in [0,1]; Terrarium's encoding
    is defined on 0-255 RGB, so scale back up first."""
    r = img_float_rgb[..., 0] * 255
    g = img_float_rgb[..., 1] * 255
    b = img_float_rgb[..., 2] * 255
    return r * 256 + g + b / 256 - 32768


def _fetch_tile(x, y, zoom, timeout=30):
    import matplotlib.image as mimg

    resp = SESSION.get(TILE_URL.format(z=zoom, x=x, y=y), timeout=timeout)
    resp.raise_for_status()
    img = mimg.imread(io.BytesIO(resp.content), format="png")
    return decode_terrarium(img)


def _tile_pixel_grid(lats, lons, zoom):
    """Vectorized form of latlon_to_tile/pixel_in_tile over the full
    meshgrid at once. Same math, numpy instead of the math module."""
    lon2d, lat2d = np.meshgrid(lons, lats)
    n = 2 ** zoom
    lat_rad = np.radians(lat2d)
    fx = (lon2d + 180.0) / 360.0 * n
    fy = (1.0 - np.log(np.tan(lat_rad) + 1 / np.cos(lat_rad)) / np.pi) / 2.0 * n
    x = fx.astype(np.int64)
    y = fy.astype(np.int64)
    px = np.clip(((fx - x) * 256).astype(np.int64), 0, 255)
    py = np.clip(((fy - y) * 256).astype(np.int64), 0, 255)
    return x, y, px, py


def fetch_elevation_grid(bbox, zoom=TILE_ZOOM, stride_deg=0.05, lat_stride_deg=None, lon_stride_deg=None):
    """Vectorized tile+pixel lookup over the whole meshgrid at once (not a
    full mosaic stitch): tile x/y and pixel px/py are computed for every
    grid point in one numpy pass, each unique tile is fetched once (cached
    per (x, y)), and the elevation grid is filled by fancy indexing. This
    matters once cells get small: a 0.25 mi grid over a typical GMU bbox is
    on the order of tens of thousands of points, and a Python-level double
    loop over that many points is too slow.

    lat_stride_deg/lon_stride_deg let the grid be non-square in degrees
    (e.g. built from a target physical cell size in miles). If omitted,
    stride_deg is used for both axes, matching the original signature."""
    lat_min, lat_max, lon_min, lon_max = bbox
    lat_stride = lat_stride_deg if lat_stride_deg is not None else stride_deg
    lon_stride = lon_stride_deg if lon_stride_deg is not None else stride_deg
    lats = np.arange(lat_min, lat_max + lat_stride, lat_stride)
    lons = np.arange(lon_min, lon_max + lon_stride, lon_stride)

    x2d, y2d, px2d, py2d = _tile_pixel_grid(lats, lons, zoom)
    unique_tiles = {(int(tx), int(ty)) for tx, ty in zip(x2d.ravel(), y2d.ravel())}

    elev = np.full(x2d.shape, np.nan)
    for tx, ty in unique_tiles:
        tile = _fetch_tile(tx, ty, zoom)
        mask = (x2d == tx) & (y2d == ty)
        elev[mask] = tile[py2d[mask], px2d[mask]]

    print(f"    elevation grid: {elev.shape[0]}x{elev.shape[1]} cells, {len(unique_tiles)} tiles (zoom {zoom})")
    return elev, lats, lons


def compute_slope_aspect(elev, lats, lons):
    dlat_m = abs(lats[1] - lats[0]) * KM_PER_DEG * 1000
    dlon_m = abs(lons[1] - lons[0]) * KM_PER_DEG * 1000 * np.cos(np.radians(np.mean(lats)))
    dzdy, dzdx = np.gradient(elev, dlat_m, dlon_m)
    slope_deg = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    aspect_deg = np.degrees(np.arctan2(-dzdx, -dzdy)) % 360
    return slope_deg, aspect_deg


def elevation_band_score(elev_m, center_m=2440.0, half_width_m=460.0, shift_m=0.0):
    effective_center = center_m - shift_m
    return np.clip(1 - np.abs(elev_m - effective_center) / half_width_m, 0, 1)


def aspect_score(aspect_deg, favor_deg=180.0):
    diff = np.radians(np.asarray(aspect_deg) - favor_deg)
    return (np.cos(diff) + 1) / 2


# Slope preference: mule deer favor moderate ground (enough relief for
# forest/opening edges and thermal cover without exhausting energy) and
# fall off toward both flat ground and cliff-steep faces, asymmetrically --
# flat ground is merely suboptimal, a sustained steep face is avoided
# outright. Tunable, not asserted biology -- same spirit as the aspect
# default above.
SLOPE_PEAK_DEG = 15.0
SLOPE_FLAT_HALF_WIDTH_DEG = 45.0   # falloff toward flat (0 deg): slow: never quite reaches 0
SLOPE_STEEP_HALF_WIDTH_DEG = 35.0  # falloff toward cliff-steep ground: faster: reaches 0 by ~50 deg


def slope_score(slope_deg, peak_deg=SLOPE_PEAK_DEG,
                 flat_half_width_deg=SLOPE_FLAT_HALF_WIDTH_DEG,
                 steep_half_width_deg=SLOPE_STEEP_HALF_WIDTH_DEG):
    slope_deg = np.asarray(slope_deg, dtype=np.float64)
    diff = slope_deg - peak_deg
    half_width = np.where(diff < 0, flat_half_width_deg, steep_half_width_deg)
    return np.clip(1 - np.abs(diff) / half_width, 0, 1)


# Habitat sub-weights: elevation band, aspect, slope, and (if a LANDFIRE
# fetch succeeded this run) land-cover suitability. Sum to 1; when a
# sub-factor's input is omitted, habitat_components renormalizes the rest
# to sum to 1 -- same graceful-degradation pattern as
# probability.compute_probability, one level down.
ELEV_WEIGHT = 0.35
ASPECT_WEIGHT = 0.20
SLOPE_WEIGHT = 0.15
COVER_WEIGHT = 0.30


def habitat_components(elev_m, aspect_deg, snow_shift_m=0.0, favor_aspect_deg=180.0,
                        slope_deg=None, cover_score=None,
                        elev_weight=ELEV_WEIGHT, aspect_weight=ASPECT_WEIGHT,
                        slope_weight=SLOPE_WEIGHT, cover_weight=COVER_WEIGHT):
    """Elevation-band, aspect, and (when given) slope and land-cover
    sub-scores, individually and blended. slope_deg/cover_score are
    optional: a caller that omits either (or both) still gets a valid
    blend, renormalized over whatever sub-factors it did provide -- this
    is what lets a failed LANDFIRE fetch degrade gracefully instead of
    aborting the run.

    Returns (blended_score, components, normalized_weights): components is
    {name: score_array} for every sub-factor actually used (elevation and
    aspect are always present; slope/cover only if their inputs were
    given), and normalized_weights is the renormalized {name: weight}."""
    band = elevation_band_score(elev_m, shift_m=snow_shift_m)
    asp = aspect_score(aspect_deg, favor_deg=favor_aspect_deg)
    parts = {"elevation": (band, elev_weight), "aspect": (asp, aspect_weight)}
    if slope_deg is not None:
        parts["slope"] = (slope_score(slope_deg), slope_weight)
    if cover_score is not None:
        parts["cover"] = (np.asarray(cover_score, dtype=np.float64), cover_weight)

    total_weight = sum(w for _, w in parts.values())
    wnorm = {name: w / total_weight for name, (_, w) in parts.items()}
    blended = sum(wnorm[name] * val for name, (val, _) in parts.items())
    components = {name: val for name, (val, _) in parts.items()}
    return blended, components, wnorm


def habitat_score(elev_m, aspect_deg, snow_shift_m=0.0, favor_aspect_deg=180.0,
                   slope_deg=None, cover_score=None,
                   elev_weight=ELEV_WEIGHT, aspect_weight=ASPECT_WEIGHT,
                   slope_weight=SLOPE_WEIGHT, cover_weight=COVER_WEIGHT):
    """Backward-compatible wrapper around habitat_components: a caller
    that only ever passed (elev_m, aspect_deg[, snow_shift_m,
    favor_aspect_deg, elev_weight, aspect_weight]) gets exactly the same
    blended array as before. slope_deg and cover_score are new, optional
    keyword args; see habitat_components for the sub-component breakdown
    (used by render.py's click-to-inspect popup and the graceful-
    degradation status panel note)."""
    blended, _, _ = habitat_components(
        elev_m, aspect_deg, snow_shift_m, favor_aspect_deg,
        slope_deg, cover_score, elev_weight, aspect_weight, slope_weight, cover_weight,
    )
    return blended
