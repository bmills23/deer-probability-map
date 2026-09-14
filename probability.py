"""Weighted blend of habitat + security + seasonal range into one 0-1
probability grid, masked to public land. If a factor is unavailable, the
remaining weight(s) renormalize to sum to 1 -- same pattern as
striper-run-tracker's compute_probability.

SEASONAL_RANGE_WEIGHT is named and kept separate from DEFAULT_WEIGHTS'
literal values (rather than inlined) so a planned follow-up can scale it
at run time: simulated snow depth is expected to raise the seasonal-range
weight, since snow pushes deer toward the CPW-delineated winter range
(deer_range.py) that factor is built from. A caller that wants that
behavior today can still do it by building its own weights dict, e.g.
`dict(DEFAULT_WEIGHTS, seasonal_range=SEASONAL_RANGE_WEIGHT * snow_factor)`."""

import numpy as np
from scipy.ndimage import gaussian_filter

# Starting weights: habitat 0.45, security 0.35, seasonal range 0.20.
# Seasonal range is deliberately the smallest of the three -- deer_range.py's
# CPW polygons are High Priority Habitat *subsets* (no Mule Deer Overall
# Range or Summer Range layer exists in that service), so a cell outside
# every polygon is scored at a neutral baseline, not zero (see deer_range.
# NEUTRAL_BASELINE); a bigger weight would let that neutral baseline pull
# too much of the blend toward "unknown" for cells CPW simply hasn't
# delineated. Habitat and security are rebalanced down proportionally from
# their old 0.55/0.45 split (0.45/0.35 keeps the same ~1.22:1 ratio between
# them) to make room for the new factor.
SEASONAL_RANGE_WEIGHT = 0.20
DEFAULT_WEIGHTS = {"habitat": 0.45, "security": 0.35, "seasonal_range": SEASONAL_RANGE_WEIGHT}
MI_PER_DEG_LAT = 69.0


def sigma_cells(sigma_mi, dlat_deg, dlon_deg, mean_lat_deg):
    """Convert a physical smoothing radius (miles) to a per-axis sigma in
    grid cells, given the grid's degree strides and mean latitude. A
    degree of longitude covers fewer miles than a degree of latitude away
    from the equator, so the two axes need separate conversions even when
    the cells themselves are square on the ground."""
    mi_per_deg_lon = MI_PER_DEG_LAT * np.cos(np.radians(mean_lat_deg))
    sigma_lat_cells = sigma_mi / (MI_PER_DEG_LAT * dlat_deg)
    sigma_lon_cells = sigma_mi / (mi_per_deg_lon * dlon_deg)
    return sigma_lat_cells, sigma_lon_cells


def compute_probability(habitat, security, public_mask, seasonal_range=None,
                         weights=None, lats=None, lons=None, sigma_mi=0.5,
                         normalize=True):
    """normalize=True (the default, and the only behavior before the
    simulated-snow slider) divides the result by its own max, so a single
    static map's brightest cell is always 1.0. That is WRONG for a stack of
    comparable grids (multiple snow levels, or multiple units in one run):
    each would independently renormalize back to full brightness regardless
    of how much worse its absolute suitability is, hiding exactly the
    intensity change a snow slider is supposed to show. Pass
    normalize=False to get the raw (smoothed, public-land-masked) grid back
    instead, then normalize the whole stack together with normalize_stack
    below."""
    weights = weights or DEFAULT_WEIGHTS
    scores = {}
    if habitat is not None:
        scores["habitat"] = habitat
    if security is not None:
        scores["security"] = security
    if seasonal_range is not None:
        scores["seasonal_range"] = seasonal_range
    used = [k for k in scores if k in weights]
    if not used:
        raise ValueError("At least one of habitat/security/seasonal_range must be provided")

    total_weight = sum(weights[k] for k in used)
    wnorm = {k: weights[k] / total_weight for k in used}

    shape = scores[used[0]].shape
    prob = np.zeros(shape)
    for k in used:
        prob += wnorm[k] * np.nan_to_num(scores[k], nan=0.0)

    if lats is not None and lons is not None and len(lats) > 1 and len(lons) > 1:
        dlat_deg = abs(float(lats[1] - lats[0]))
        dlon_deg = abs(float(lons[1] - lons[0]))
        mean_lat_deg = float(np.mean(lats))
        sigma = sigma_cells(sigma_mi, dlat_deg, dlon_deg, mean_lat_deg)
    else:
        sigma = 1.0  # backward-compatible fallback: no grid spacing given
    prob = gaussian_filter(prob, sigma=sigma)
    prob[~public_mask] = np.nan
    if normalize:
        mx = np.nanmax(prob)
        if mx and mx > 0:
            prob = prob / mx
    return prob, used


def normalize_stack(raw_probs):
    """Normalize a stack of raw (normalize=False) probability grids -- e.g.
    every simulated snow level for every unit in one run -- by a single
    shared maximum, so levels/units stay comparable to each other.

    THIS IS THE FIX FOR THE NORMALIZATION TRAP: compute_probability's own
    per-call normalization maps each call's max cell to 1.0, which is
    correct for a single static map but wrong for a stack a slider steps
    through -- independently renormalizing each level would map every
    level's brightest cell back to 1.0 no matter how much worse that
    level's absolute suitability is, so the slider would show shape
    changes (where the bright spot is) but never intensity changes
    (whether the whole unit got worse), which is actively misleading for a
    snow-depth simulation whose entire point is showing things get worse.

    NaN (non-public) cells are ignored when finding the max and stay NaN
    in every output array. Returns (normalized_list, global_max); if every
    array is entirely NaN or <=0, global_max is 0.0 and the arrays are
    returned unchanged (nothing to divide by)."""
    global_max = 0.0
    for arr in raw_probs:
        arr = np.asarray(arr, dtype=np.float64)
        if arr.size == 0 or np.all(np.isnan(arr)):
            continue
        m = np.nanmax(arr)
        if m and m > global_max:
            global_max = float(m)
    if not global_max or global_max <= 0:
        return list(raw_probs), global_max
    return [np.asarray(arr, dtype=np.float64) / global_max for arr in raw_probs], global_max


# --- Snow-driven seasonal-range weight coupling ---
#
# Deeper snow pushes deer toward CPW-delineated winter range (deer_range.py,
# the "seasonal_range" factor), so the simulated snow slider raises that
# factor's weight in the blend as simulated depth increases. There is no
# calibration data available for exactly how much -- this is a documented,
# named, disclosed-in-the-UI heuristic, not measured biology, and it is
# deliberately easy to turn off: pass enabled=False to either function
# below (the map's UI text says so too).
#
# Shape: linear ramp from SEASONAL_RANGE_WEIGHT (the no-snow/default
# weight, 0.20) at 0 in up to SEASONAL_RANGE_WEIGHT_MAX (0.40, double the
# base) at SEASONAL_RANGE_SNOW_COUPLING_MAX_DEPTH_IN in of simulated snow,
# capped beyond that -- the same 40 in cap snow.snow_elevation_shift_m
# already uses for the elevation-band shift, reused here deliberately so
# "maximum simulated snow effect" means the same depth everywhere in the
# model, not two different caps a reader has to reconcile. habitat's and
# security's weights are renormalized down proportionally (their 0.45:0.35
# ratio to each other is preserved) so the blend still sums to 1 at every
# level -- see weights_for_snow.
SEASONAL_RANGE_WEIGHT_MAX = 0.40
SEASONAL_RANGE_SNOW_COUPLING_MAX_DEPTH_IN = 40.0


def seasonal_range_weight_for_snow(depth_in, base_weight=SEASONAL_RANGE_WEIGHT,
                                    max_weight=SEASONAL_RANGE_WEIGHT_MAX,
                                    max_depth_in=SEASONAL_RANGE_SNOW_COUPLING_MAX_DEPTH_IN,
                                    enabled=True):
    """seasonal_range's weight at a given simulated snow depth. enabled=False
    (or depth_in=None) returns base_weight unchanged -- the coupling's "off
    switch"."""
    if not enabled or depth_in is None:
        return base_weight
    frac = min(max(depth_in, 0.0), max_depth_in) / max_depth_in
    return base_weight + frac * (max_weight - base_weight)


def weights_for_snow(depth_in, base_weights=None, enabled=True):
    """Full compute_probability weights dict at a given simulated snow
    depth: seasonal_range rises per seasonal_range_weight_for_snow above,
    and every other weight in base_weights is scaled down proportionally
    (their ratios to each other preserved) so the result still sums to 1."""
    base_weights = dict(base_weights or DEFAULT_WEIGHTS)
    base_seasonal = base_weights.get("seasonal_range", SEASONAL_RANGE_WEIGHT)
    seasonal = seasonal_range_weight_for_snow(depth_in, base_weight=base_seasonal, enabled=enabled)
    others = {k: v for k, v in base_weights.items() if k != "seasonal_range"}
    others_total = sum(others.values())
    remaining = max(0.0, 1.0 - seasonal)
    if others_total > 0:
        scaled = {k: v / others_total * remaining for k, v in others.items()}
    else:
        scaled = others
    scaled["seasonal_range"] = seasonal
    return scaled
