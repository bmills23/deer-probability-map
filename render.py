"""PNG heatmap overlay, click-to-inspect cells, status panel, land
ownership/GMU boundary layers, and folium map assembly -- adapted from
striper-run-tracker's render_prob_png / build_inspection_cells / build_map,
trimmed to this project's two factors (habitat, security) and public-land
mask; no SST toggle, sightings, or time slider (none apply here).

The land ownership layer is a *display* layer, separate from the hard
"open" tier of hunting_access.classify_access that masks the probability
heatmap: it shows every PAD-US category (USFS, BLM, state, other public,
conditional, restricted/closed) plus every CPW/SLB access-program parcel
(hunting_access.py) so a user can see at a glance where they can legally
hunt -- including State Land Board and other Restricted Access land a
CPW program actually opens -- not just where the heatmap happens to be
shaded."""

import base64
import io
import json

import matplotlib
import matplotlib.image as mimg
import numpy as np
from matplotlib.colors import Normalize

from deer_range import RANGE_TYPE_LABELS
from hunting_access import SOURCE_LABELS

# Live NOAA snow depth: a *display* overlay only, toggled from the status
# panel, never a model input (the model's own snow input stays the
# SNOTEL scalar in snow.py -- see README). Verified reachable with no API
# key; layer 0 is Snow Depth (layer 4, Snow Water Equivalent, exists too
# but isn't used here). This is a dynamic (non-cached) ArcGIS MapServer,
# so it has no {z}/{x}/{y} tile endpoint -- the page instead calls its
# "export" operation per-tile (NOAA_SNOW_JS below), the standard technique
# for showing a dynamic ArcGIS MapServer in Leaflet without the
# esri-leaflet plugin.
NOAA_NOHRSC_MAPSERVER_URL = "https://mapservices.weather.noaa.gov/raster/rest/services/snow/NOHRSC_Snow_Analysis/MapServer"
NOAA_NOHRSC_ATTRIBUTION = "NOAA NOHRSC Snow Analysis"

# Land ownership display categories: manager-based first (USFS/BLM/state
# wildlife/state land board keep their own color regardless of access
# code, so the tooltip's exact Pub_Access code is what tells the user
# whether a specific USFS/BLM parcel is actually open), then "cpw_access"
# for parcels drawn from a CPW/SLB access source (see hunting_access.py --
# these are the parcels that make State Land Board and other Restricted
# Access land actually huntable, overlaid distinctly regardless of what
# PAD-US says about the same ground), then a plain "other open public"
# bucket for anything else marked OA, then "conditional" for PAD-US
# Restricted Access land with no confirmed CPW access source, then a
# catch-all "restricted" bucket for everything else (Closed/Unknown).
ACCESS_CODE_LABELS = {
    "OA": "Open Access",
    "RA": "Restricted Access",
    "XA": "Closed",
    "UK": "Unknown",
}

LAND_OWNERSHIP_STYLES = {
    "usfs": {"label": "US Forest Service", "color": "#2e7d32"},
    "blm": {"label": "Bureau of Land Management", "color": "#b8860b"},
    "swa": {"label": "State Wildlife Area (State Fish and Wildlife)", "color": "#1565c0"},
    "slb": {"label": "State Land Board (State Trust Land)", "color": "#ef6c00"},
    "cpw_access": {"label": "CPW access program land, open to licensed hunters", "color": "#c2185b"},
    "other_open": {"label": "Other open public land (city, county, NGO, regional)", "color": "#00897b"},
    "conditional": {"label": "Conditional access (Restricted Access, no confirmed CPW program)", "color": "#f9a825"},
    "restricted": {"label": "Restricted or closed to public access", "color": "#757575"},
}
LAND_OWNERSHIP_ORDER = ["usfs", "blm", "swa", "slb", "cpw_access", "other_open", "conditional", "restricted"]


def categorize_ownership(properties):
    """PAD-US properties -> one of LAND_OWNERSHIP_STYLES' keys. See module
    docstring above for the priority rationale.

    Manager-based categories (usfs/blm/swa/slb) win regardless of access
    code -- MngNm_Desc real values include "Forest Service" (not "US
    Forest Service"; a prior mismatch here meant National Forest, the
    largest huntable block in most units, never matched and fell through
    to "other_open"/"conditional"/"restricted" instead)."""
    properties = properties or {}
    manager = properties.get("MngNm_Desc") or ""
    access = properties.get("Pub_Access") or "UK"
    if manager == "Forest Service":
        return "usfs"
    if manager == "Bureau of Land Management":
        return "blm"
    if manager == "State Fish and Wildlife":
        return "swa"
    if manager == "State Land Board":
        return "slb"
    if access == "OA":
        return "other_open"
    if access == "RA":
        return "conditional"
    return "restricted"


def _ownership_feature_collection(features):
    """Copy features with display-ready tooltip properties (manager, unit
    name, access code, acres) and a precomputed '_category' so the
    style_function folium calls per-feature is a plain dict lookup."""
    out = []
    for f in features:
        props = f.get("properties", {}) or {}
        category = categorize_ownership(props)
        acres = props.get("GIS_Acres")
        acres_label = f"{acres:,.0f} ac" if isinstance(acres, (int, float)) else "unknown"
        access = props.get("Pub_Access") or "UK"
        out.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                "_category": category,
                "Manager": props.get("MngNm_Desc") or "Unknown",
                "Unit": props.get("Unit_Nm") or "Unnamed",
                "Access": f"{access} ({ACCESS_CODE_LABELS.get(access, 'Unknown')})",
                "Acres": acres_label,
            },
        })
    return {"type": "FeatureCollection", "features": out}


def _cpw_feature_label(props):
    return (
        props.get("PropName") or props.get("Name") or props.get("UNIT_NAME")
        or props.get("Unit_Nm") or props.get("SiteName") or "CPW access parcel"
    )


def _cpw_feature_acres(props):
    for key in ("Acres", "GIS_Acres", "ACRES"):
        val = props.get(key)
        if isinstance(val, (int, float)):
            return val
    return None


def _cpw_access_feature_collection(features):
    """Same shape as _ownership_feature_collection's output features, but
    for CPW/SLB access-program parcels (hunting_access.py): these are the
    parcels that actually grant hunting access to State Land Board and
    other Restricted Access land, independent of what PAD-US says about
    the same ground -- so the tooltip's 'Manager' field names the CPW/SLB
    source, per source_tag in properties['_source']."""
    out = []
    for f in features:
        props = f.get("properties") or {}
        acres = _cpw_feature_acres(props)
        acres_label = f"{acres:,.0f} ac" if isinstance(acres, (int, float)) else "unknown"
        out.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                "_category": "cpw_access",
                "Manager": SOURCE_LABELS.get(props.get("_source"), "CPW access program"),
                "Unit": _cpw_feature_label(props),
                "Access": "Open (CPW access program)",
                "Acres": acres_label,
            },
        })
    return out


def _ownership_style_function(feature):
    category = feature.get("properties", {}).get("_category", "restricted")
    color = LAND_OWNERSHIP_STYLES.get(category, LAND_OWNERSHIP_STYLES["restricted"])["color"]
    style = {"fillColor": color, "color": color, "weight": 0.6, "fillOpacity": 0.35, "opacity": 0.55}
    if category == "cpw_access":
        # A distinct dashed outline, drawn over whatever PAD-US category
        # already colors the same ground, so a CPW-access parcel is
        # visibly identifiable even where PAD-US marks it Restricted.
        style.update({"weight": 2.2, "opacity": 0.9, "fillOpacity": 0.28, "dashArray": "5,4"})
    return style


def _add_land_ownership_layer(m, padus_features, cpw_features=None):
    """'Land ownership' toggle: every PAD-US category plus every CPW/SLB
    access-program parcel in the unit(s), fills at modest opacity so the
    heatmap/topo stay readable underneath."""
    import folium

    features = _ownership_feature_collection(padus_features)["features"]
    features += _cpw_access_feature_collection(cpw_features or [])
    if not features:
        return
    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="Land ownership",
        style_function=_ownership_style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=["Manager", "Unit", "Access", "Acres"],
            aliases=["Manager:", "Unit:", "Access:", "Acres:"],
            sticky=True,
        ),
        show=True,
    ).add_to(m)


def _add_gmu_boundary_layer(m, gmu_geometries):
    """'GMU boundary' toggle: thick dark outline, no fill, so the unit's
    real legal boundary is visible regardless of the ownership layer."""
    import folium

    geometries = [g for g in gmu_geometries if g]
    if not geometries:
        return
    fc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": g} for g in geometries],
    }
    folium.GeoJson(
        fc,
        name="GMU boundary",
        style_function=lambda f: {"fillOpacity": 0, "color": "#1a1a1a", "weight": 3, "opacity": 0.9},
        show=True,
    ).add_to(m)


# 'Deer seasonal range' display layer (deer_range.py): CPW's own mule
# deer migration corridor / severe winter range / winter concentration
# area polygons, distinct from the land ownership layer above both in
# color palette (purple family, not the greens/blues/oranges
# LAND_OWNERSHIP_STYLES uses) and in what they mean -- these are CPW
# biologists' delineations of where deer actually are, not ownership.
# Unlike elk, there is no Production Area layer to include here at all.
DEER_RANGE_STYLES = {
    "winter_concentration": {"label": RANGE_TYPE_LABELS["winter_concentration"], "color": "#4a148c"},
    "severe_winter_range": {"label": RANGE_TYPE_LABELS["severe_winter_range"], "color": "#7b1fa2"},
    "migration_corridor": {"label": RANGE_TYPE_LABELS["migration_corridor"], "color": "#ab47bc"},
}
DEER_RANGE_ORDER = ["winter_concentration", "severe_winter_range", "migration_corridor"]


def _deer_range_feature_collection(features):
    out = []
    for f in features:
        props = f.get("properties") or {}
        range_type = props.get("_range_type")
        label = DEER_RANGE_STYLES.get(range_type, {}).get("label", "Deer range (unspecified)")
        out.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                "_range_type": range_type or "unknown",
                "RangeType": label,
                "Activity": props.get("Activity_C") or "n/a",
            },
        })
    return {"type": "FeatureCollection", "features": out}


DEER_RANGE_OUTLINE_COLOR = "#1a0033"  # near-black purple, deliberately distinct from
                                      # both the fill palette above and land ownership's
                                      # magenta "cpw_access" dashed outline, so a deer-range
                                      # polygon's boundary stays legible when it overlaps
                                      # either the heatmap or a land-ownership parcel.


# Legibility fix, same as elk-probability-map's identical layer: a heavy
# fill at the scale a single range polygon usually covers (often most of
# a unit) would wash out both the basemap and the probability heatmap
# underneath it. Deer seasonal range is a light outline with only a faint
# fill (0.08) so it reads as "this area is delineated" without competing
# with the heatmap for attention, and it defaults OFF (show=False) given
# how much area it typically covers -- a user who wants it can turn it on
# in the layer control, same as any other overlay.
DEER_RANGE_FILL_OPACITY = 0.08
DEER_RANGE_LINE_WEIGHT = 1.2


def _deer_range_style_function(feature):
    range_type = feature.get("properties", {}).get("_range_type")
    color = DEER_RANGE_STYLES.get(range_type, {}).get("color", "#9c27b0")
    return {
        "fillColor": color, "fillOpacity": DEER_RANGE_FILL_OPACITY,
        "color": DEER_RANGE_OUTLINE_COLOR, "weight": DEER_RANGE_LINE_WEIGHT, "opacity": 0.7,
        "dashArray": "3,3",
    }


def _add_deer_range_layer(m, features):
    """'Deer seasonal range' toggle: CPW's own mule deer seasonal-range
    polygons (deer_range.py), separate from the 'Land ownership' layer
    above -- this shows CPW biologists' delineation of where deer
    actually are, not who owns the ground. Off by default (show=False) --
    see the legibility note on _deer_range_style_function above; a user
    can turn it on in the layer control."""
    import folium

    if not features:
        return
    fc = _deer_range_feature_collection(features)
    if not fc["features"]:
        return
    folium.GeoJson(
        fc,
        name="Deer seasonal range",
        style_function=_deer_range_style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=["RangeType", "Activity"],
            aliases=["Range type:", "Activity:"],
            sticky=True,
        ),
        show=False,
    ).add_to(m)


def _png_overlay(lats, lons, rgba, px_step=1):
    """RGBA grid (row i = lats[i], ascending) -> (data-uri, bounds).

    Two corrections so the overlay lands exactly on the Leaflet (Web
    Mercator) basemap: (1) expand bounds by half a cell -- pixels are
    areas, not points; (2) resample rows to be uniform in Mercator y,
    since Leaflet stretches the image linearly in projected space while
    the data is equirectangular. (Copied from striper-run-tracker
    verbatim -- generic image-georeferencing math.)"""
    dlat = float(lats[1] - lats[0])
    dlon = float(lons[1] - lons[0])
    south, north = float(lats.min()) - dlat / 2, float(lats.max()) + dlat / 2
    west, east = float(lons.min()) - dlon / 2, float(lons.max()) + dlon / 2

    img = rgba[::-1, :, :]
    h = img.shape[0]
    merc = lambda d: np.log(np.tan(np.pi / 4 + np.radians(d) / 2))
    ys = np.linspace(merc(north), merc(south), h)
    out_lat = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)
    asc_idx = np.interp(out_lat, lats, np.arange(len(lats)))
    ri = np.clip(np.round(len(lats) - 1 - asc_idx).astype(int), 0, h - 1)
    out = img[ri, :, :]
    if px_step > 1:
        out = out[::px_step, ::px_step, :]

    buf = io.BytesIO()
    mimg.imsave(buf, out, format="png")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return uri, [[south, west], [north, east]]


def render_prob_png(prob, lats, lons, px_step=1):
    """Probability heatmap, viridis, value-ramped alpha. NaN cells (masked
    out by compute_probability) render fully transparent."""
    cmap = matplotlib.colormaps["viridis"]
    norm = Normalize(0, 1)
    safe = np.nan_to_num(prob, nan=0.0)
    rgba = cmap(norm(np.ma.masked_invalid(prob)))
    alpha = np.clip(safe, 0, 1) ** 0.7 * 0.85
    alpha[np.isnan(prob)] = 0.0
    rgba[..., 3] = alpha
    return _png_overlay(lats, lons, rgba, px_step=px_step)


# Fixed order the habitat sub-component columns are appended in (see
# build_inspection_cells below) -- must match INSPECT_JS_TMPL's HABITAT_SUB
# lookup, which indexes into the row by position, not by name.
HABITAT_SUBFACTOR_KEYS = ["elevation", "aspect", "slope", "cover"]


def _inspection_stride(lats, lons, inspect_mi, stride=None):
    """Shared by build_inspection_cells and build_snow_level_cells: derive
    a grid stride (in cells) from a target physical spacing (inspect_mi,
    miles) if one isn't given explicitly, then the physical half-cell size
    (in degrees) that stride implies -- used both to build the click
    tolerance and to draw the highlighted rectangle around a selected
    cell."""
    dlat_deg = abs(float(lats[1] - lats[0])) if len(lats) > 1 else 0.0
    dlon_deg = abs(float(lons[1] - lons[0])) if len(lons) > 1 else 0.0
    if stride is None:
        mean_lat_deg = float(np.mean(lats))
        cell_mi_lat = dlat_deg * 69.0
        cell_mi_lon = dlon_deg * 69.0 * np.cos(np.radians(mean_lat_deg))
        cell_mi = max(cell_mi_lat, cell_mi_lon) if max(cell_mi_lat, cell_mi_lon) > 0 else inspect_mi
        stride = max(1, round(inspect_mi / cell_mi))
    half_lat = round(stride * dlat_deg / 2, 4)
    half_lon = round(stride * dlon_deg / 2, 4)
    return stride, dlat_deg, dlon_deg, half_lat, half_lon


def build_inspection_cells(lats, lons, prob, habitat, security, public_mask,
                            inspect_mi=0.5, stride=None, thresh=0.03, habitat_parts=None,
                            seasonal_range=None):
    """Downsampled clickable cells (public land only). Each row:
    [lat, lon, prob_pct, habitat_score, security_score, elevation_sub,
    aspect_sub, slope_sub, cover_sub, seasonal_range_score] -- the middle
    four are the habitat factor's own sub-component scores (terrain.
    habitat_components), None for any sub-factor habitat_parts doesn't
    carry (e.g. cover, when a LANDFIRE fetch failed this run, or
    habitat_parts omitted entirely, for backward compatibility).
    seasonal_range_score (deer_range.seasonal_range_score) is appended last,
    after the habitat sub-factors, so their fixed column indices
    (HABITAT_SUBFACTOR_KEYS) don't shift; None if seasonal_range wasn't
    given (e.g. a failed deer_range fetch this run).

    stride (in grid cells) is derived from inspect_mi, a target physical
    spacing in miles between inspection cells, so the embedded JSON does
    not explode at fine analysis-grid resolutions. Pass stride explicitly
    to override that derivation."""

    def r2(x):
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)

    habitat_parts = habitat_parts or {}
    stride, dlat_deg, dlon_deg, half_lat, half_lon = _inspection_stride(lats, lons, inspect_mi, stride)

    rows = []
    for i in range(0, len(lats), stride):
        for j in range(0, len(lons), stride):
            p = prob[i, j]
            if np.isnan(p) or p < thresh or not public_mask[i, j]:
                continue
            rows.append([
                round(float(lats[i]), 3),
                round(float(lons[j]), 3),
                round(float(p) * 100),
                r2(habitat[i, j]) if habitat is not None else None,
                r2(security[i, j]) if security is not None else None,
                *[r2(habitat_parts[key][i, j]) if key in habitat_parts else None
                  for key in HABITAT_SUBFACTOR_KEYS],
                r2(seasonal_range[i, j]) if seasonal_range is not None else None,
            ])
    return rows, half_lat, half_lon


def build_snow_level_cells(lats, lons, level_probs, level_habitat, level_elevation,
                            public_mask, security=None, seasonal_range=None,
                            aspect=None, slope=None, cover=None,
                            inspect_mi=0.5, stride=None, thresh=0.03):
    """Multi-level counterpart to build_inspection_cells, for the simulated
    snow slider (see snow.SIMULATED_SNOW_LEVELS_IN and deer_map.process_unit).

    Only elevation band, habitat's blended score, and the overall
    probability actually change with simulated snow depth (elevation_band_
    score is the only sub-input snow shifts; security/aspect/slope/cover/
    the raw seasonal-range score do not). So those three are the only
    per-level values shipped -- one triple per level, not a whole new row
    per level -- to keep the popup payload from duplicating every factor at
    every level.

    level_probs/level_habitat/level_elevation are lists of grids, one per
    entry of snow.SIMULATED_SNOW_LEVELS_IN, already put through
    probability.normalize_stack (the whole point of the slider is comparing
    absolute intensity across levels, so these must already be globally
    normalized, not each independently normalized).

    Row shape: [lat, lon, security, aspect, slope, cover, seasonal_range,
    levels] where levels is [[prob_pct, habitat, elevation_sub], ...] with
    one triple per snow level, in the same order as level_probs.

    A cell is kept if it is public land (public_mask -- does not vary with
    snow) AND at least one level clears thresh; a cell that's below
    threshold at every level is exactly as irrelevant as build_inspection_
    cells' single-level thresh skip."""

    def r2(x):
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)

    n_levels = len(level_probs)
    stride, dlat_deg, dlon_deg, half_lat, half_lon = _inspection_stride(lats, lons, inspect_mi, stride)

    rows = []
    for i in range(0, len(lats), stride):
        for j in range(0, len(lons), stride):
            if not public_mask[i, j]:
                continue
            probs_ij = [level_probs[lv][i, j] for lv in range(n_levels)]
            if all(np.isnan(p) or p < thresh for p in probs_ij):
                continue
            levels_row = [
                [round(float(0.0 if np.isnan(p) else p) * 100),
                 r2(level_habitat[lv][i, j]),
                 r2(level_elevation[lv][i, j])]
                for lv, p in enumerate(probs_ij)
            ]
            rows.append([
                round(float(lats[i]), 3),
                round(float(lons[j]), 3),
                r2(security[i, j]) if security is not None else None,
                r2(aspect[i, j]) if aspect is not None else None,
                r2(slope[i, j]) if slope is not None else None,
                r2(cover[i, j]) if cover is not None else None,
                r2(seasonal_range[i, j]) if seasonal_range is not None else None,
                levels_row,
            ])
    return rows, half_lat, half_lon


MOBILE_CSS = """
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=3">
<style>
#epm-panel{position:fixed;top:12px;left:12px;z-index:9999;
  background:rgba(255,255,255,.96);padding:11px 13px;border-radius:10px;
  box-shadow:0 2px 9px rgba(0,0,0,.28);font-family:system-ui,sans-serif;
  font-size:13px;line-height:1.45;max-width:322px;
  max-height:88vh;overflow-y:auto;}
#epm-panel .epm-hd{display:flex;justify-content:space-between;align-items:center;
  gap:8px;cursor:pointer;}
#epm-toggle{border:none;background:#eef2f8;border-radius:6px;padding:1px 9px;
  cursor:pointer;font-size:14px;line-height:1.2;color:#333;}
#epm-panel input[type=range]{-webkit-appearance:none;appearance:none;width:100%;
  height:22px;background:transparent;touch-action:pan-x;}
#epm-panel input[type=range]::-webkit-slider-runnable-track{height:6px;border-radius:3px;background:#ccc;}
#epm-panel input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
  width:22px;height:22px;border-radius:50%;background:#2e7d32;margin-top:-8px;cursor:pointer;}
#epm-panel input[type=range]::-moz-range-track{height:6px;border-radius:3px;background:#ccc;}
#epm-panel input[type=range]::-moz-range-thumb{width:22px;height:22px;border-radius:50%;
  background:#2e7d32;border:none;cursor:pointer;}
@media (max-width:600px){
  #epm-panel{max-width:74vw;font-size:11px;padding:8px 10px;top:8px;left:8px;
    border-radius:8px;max-height:40vh;}
}
</style>
"""

TOGGLE_JS = """
<script>
function epmToggle(){var b=document.getElementById('epm-body'),
 t=document.getElementById('epm-toggle');
 if(b.style.display==='none'){b.style.display='block';t.textContent='–';}
 else{b.style.display='none';t.textContent='+';}}
</script>
"""

# The land ownership legend is its own collapsible sub-section (same
# header/toggle-button pattern as epmToggle above, not a <details>
# element, so it matches the panel's existing interaction style). Open by
# default on desktop; the IIFE below collapses it by default on narrow
# screens only, since the legend is what pushed the panel tall enough to
# cover most of a phone screen -- the GMU stats above it stay visible
# either way. The deer seasonal range legend (epm-legend2-*) is a second,
# independent instance of the same pattern.
LEGEND_JS = """
<script>
function epmLegendToggle(){var b=document.getElementById('epm-legend-body'),
 t=document.getElementById('epm-legend-toggle');
 if(b.style.display==='none'){b.style.display='block';t.textContent='–';}
 else{b.style.display='none';t.textContent='+';}}
function epmLegend2Toggle(){var b=document.getElementById('epm-legend2-body'),
 t=document.getElementById('epm-legend2-toggle');
 if(b.style.display==='none'){b.style.display='block';t.textContent='–';}
 else{b.style.display='none';t.textContent='+';}}
(function(){
  ['epm-legend-body','epm-legend2-body'].forEach(function(bodyId, i){
    var b=document.getElementById(bodyId),
        t=document.getElementById(i===0?'epm-legend-toggle':'epm-legend2-toggle');
    if(b && t && window.matchMedia('(max-width:600px)').matches){
      b.style.display='none';
      t.textContent='+';
    }
  });
})();
</script>
"""

INSPECT_JS_TMPL = """
<script>
document.addEventListener('DOMContentLoaded', function(){
  var CELLS = __CELLS__, W = __W__, HALF_LAT = __HALF_LAT__, HALF_LON = __HALF_LON__;
  var LBL = {"habitat":"Habitat suitability","security":"Distance from roads",
    "seasonal_range":"Deer seasonal range (CPW)"};
  var COL = {"habitat":3,"security":4,"seasonal_range":9};
  // Habitat's own sub-components (terrain.habitat_components), appended
  // to each row after the top-level columns in this fixed order -- see
  // render.HABITAT_SUBFACTOR_KEYS. A null entry means that sub-factor
  // wasn't available this run (e.g. cover, when a LANDFIRE fetch failed)
  // and habitat's remaining weights were renormalized around it.
  var HABITAT_SUB = [
    {idx:5, label:"Elevation band"},
    {idx:6, label:"Aspect"},
    {idx:7, label:"Slope"},
    {idx:8, label:"Land cover"}
  ];
  var map = __MAP__, hl = null;
  map.on('click', function(e){
    var la=e.latlng.lat, lo=e.latlng.lng, best=null, bd=1e9, i, c, d;
    for(i=0;i<CELLS.length;i++){c=CELLS[i];d=Math.abs(c[0]-la)+Math.abs(c[1]-lo);if(d<bd){bd=d;best=c;}}
    if(!best || Math.abs(best[0]-la)>HALF_LAT*2 || Math.abs(best[1]-lo)>HALF_LON*2){return;}
    var keys=Object.keys(W), tot=0, contrib={}, k, kk, sc;
    for(k=0;k<keys.length;k++){kk=keys[k];sc=best[COL[kk]];if(sc==null)continue;contrib[kk]=W[kk]*sc;tot+=contrib[kk];}
    var html='<div style="font-family:system-ui,sans-serif;font-size:12.5px;min-width:188px;">'
      +'<b>Deer probability: '+best[2]+'%</b>'
      +'<div style="color:#888;font-size:10.5px;margin:2px 0 5px;">'+best[0].toFixed(2)+', '+best[1].toFixed(2)+'</div>'
      +'<div style="font-size:11px;color:#555;margin-bottom:2px;">what it is based on:</div>';
    for(k=0;k<keys.length;k++){kk=keys[k];sc=best[COL[kk]];if(sc==null)continue;
      var share=tot>0?Math.round(100*contrib[kk]/tot):0;
      html+='<div style="display:flex;justify-content:space-between;gap:12px;">'
        +'<span>'+LBL[kk]+' <span style="color:#aaa;">('+sc.toFixed(2)+')</span></span>'
        +'<b>'+share+'%</b></div>';
      if(kk==='habitat'){
        for(var s=0;s<HABITAT_SUB.length;s++){
          var sub=HABITAT_SUB[s], subVal=best[sub.idx];
          if(subVal==null){continue;}
          html+='<div style="display:flex;justify-content:space-between;padding-left:11px;'
            +'font-size:10px;color:#888;"><span>'+sub.label+'</span><span>'+subVal.toFixed(2)+'</span></div>';
        }
      }
    }
    html+='<div style="font-size:9.5px;color:#aaa;margin-top:5px;">share of weighted blend &middot; relative suitability, not calibrated probability</div></div>';
    if(hl){map.removeLayer(hl);}
    hl=L.rectangle([[best[0]-HALF_LAT,best[1]-HALF_LON],[best[0]+HALF_LAT,best[1]+HALF_LON]],{color:'#111',weight:1,fill:false,interactive:false}).addTo(map);
    L.popup({maxWidth:280}).setLatLng([best[0],best[1]]).setContent(html).openOn(map);
  });
});
</script>
"""

# Snow-aware counterpart to INSPECT_JS_TMPL, used instead of it whenever
# build_map is given a `snow` stack (see build_map's docstring): CELLS here
# is build_snow_level_cells' row shape ([lat, lon, security, aspect, slope,
# cover, seasonal_range, [[prob_pct, habitat, elevation_sub], ...levels]]),
# WBYLVL is one weights dict per level (probability.weights_for_snow), and
# UNIT_OVERLAYS maps each unit's already-rendered folium ImageOverlay (by
# its generated JS variable name) to that unit's list of per-level PNG data
# URIs -- moving the slider calls .setUrl() on the existing overlay object
# rather than adding/removing sixteen separate map layers. Requirement #1
# ("do not reimplement the blend in JS") holds here exactly as it does in
# INSPECT_JS_TMPL: every prob/habitat/elevation number the popup shows was
# computed by probability.py/terrain.py in Python, this script only looks
# up and displays precomputed numbers.
SNOW_JS_TMPL = """
<script>
document.addEventListener('DOMContentLoaded', function(){
  var LEVELS = __LEVELS__, WBYLVL = __WEIGHTS_BY_LEVEL__, UNIT_OVERLAYS = __UNIT_OVERLAYS__;
  var CELLS = __CELLS__, HALF_LAT = __HALF_LAT__, HALF_LON = __HALF_LON__;
  var LBL = {"habitat":"Habitat suitability","security":"Distance from roads",
    "seasonal_range":"Deer seasonal range (CPW)"};
  var map = __MAP__, idx = __ANCHOR_IDX__, hl = null, popup = null, lastCell = null;

  function overlaysForIdx(i){
    Object.keys(UNIT_OVERLAYS).forEach(function(gmu){
      var u = UNIT_OVERLAYS[gmu];
      if (window[u.varName] && u.uris[i] != null) { window[u.varName].setUrl(u.uris[i]); }
    });
  }

  function popupHtml(cell, i){
    var W = WBYLVL[i], lvl = cell[7][i];
    var probPct = lvl[0], habitat = lvl[1], elevationSub = lvl[2];
    var security = cell[2], aspect = cell[3], slope = cell[4], cover = cell[5], seasonalRaw = cell[6];
    var scores = {habitat: habitat, security: security, seasonal_range: seasonalRaw};
    var keys = Object.keys(W), tot = 0, contrib = {};
    keys.forEach(function(k){ if(scores[k]==null) return; contrib[k]=W[k]*scores[k]; tot+=contrib[k]; });
    var html = '<div style="font-family:system-ui,sans-serif;font-size:12.5px;min-width:188px;">'
      + '<b>Deer probability: '+probPct+'%</b>'
      + '<div style="color:#888;font-size:10.5px;margin:2px 0 5px;">'+cell[0].toFixed(2)+', '+cell[1].toFixed(2)+'</div>'
      + '<div style="font-size:9.5px;color:#c62828;margin-bottom:4px;">simulated at '+LEVELS[i]+' in of snow</div>'
      + '<div style="font-size:11px;color:#555;margin-bottom:2px;">what it is based on:</div>';
    keys.forEach(function(k){
      if(scores[k]==null) return;
      var share = tot>0 ? Math.round(100*contrib[k]/tot) : 0;
      html += '<div style="display:flex;justify-content:space-between;gap:12px;">'
        +'<span>'+LBL[k]+' <span style="color:#aaa;">('+scores[k].toFixed(2)+')</span></span>'
        +'<b>'+share+'%</b></div>';
      if(k==='habitat'){
        [['Elevation band', elevationSub], ['Aspect', aspect], ['Slope', slope], ['Land cover', cover]]
          .forEach(function(pair){
            if(pair[1]==null) return;
            html += '<div style="display:flex;justify-content:space-between;padding-left:11px;'
              +'font-size:10px;color:#888;"><span>'+pair[0]+'</span><span>'+pair[1].toFixed(2)+'</span></div>';
          });
      }
    });
    html += '<div style="font-size:9.5px;color:#aaa;margin-top:5px;">share of weighted blend at the '
      +'simulated snow depth above, relative suitability, not calibrated probability</div></div>';
    return html;
  }

  map.on('click', function(e){
    var la=e.latlng.lat, lo=e.latlng.lng, best=null, bd=1e9, i, c, d;
    for(i=0;i<CELLS.length;i++){c=CELLS[i];d=Math.abs(c[0]-la)+Math.abs(c[1]-lo);if(d<bd){bd=d;best=c;}}
    if(!best || Math.abs(best[0]-la)>HALF_LAT*2 || Math.abs(best[1]-lo)>HALF_LON*2){return;}
    lastCell = best;
    if(hl){map.removeLayer(hl);}
    hl = L.rectangle([[best[0]-HALF_LAT,best[1]-HALF_LON],[best[0]+HALF_LAT,best[1]+HALF_LON]],
      {color:'#111',weight:1,fill:false,interactive:false}).addTo(map);
    popup = L.popup({maxWidth:280}).setLatLng([best[0],best[1]]).setContent(popupHtml(best, idx)).openOn(map);
  });

  function applyIdx(i){
    idx = i;
    var lbl = document.getElementById('epm-snow-value');
    if(lbl){ lbl.textContent = LEVELS[i] + ' in'; }
    overlaysForIdx(i);
    if(lastCell && popup && map.hasLayer(popup)){ popup.setContent(popupHtml(lastCell, idx)); }
  }

  var slider = document.getElementById('epm-snow-slider');
  if(slider){
    slider.addEventListener('input', function(){ applyIdx(parseInt(this.value, 10)); });
    slider.addEventListener('change', function(){ applyIdx(parseInt(this.value, 10)); });
  }
  applyIdx(idx);

  // Live NOAA snow depth toggle -- a display overlay only (see render.py's
  // NOAA_NOHRSC_MAPSERVER_URL docstring), off by default. NOHRSC is a
  // dynamic (non-cached) ArcGIS MapServer with no {z}/{x}/{y} tile
  // endpoint, so each tile is requested from its "export" operation with
  // that tile's own bbox in Web Mercator meters -- the standard technique
  // for a dynamic ArcGIS MapServer in plain Leaflet, no esri-leaflet
  // plugin required.
  var NoaaSnowLayer = L.TileLayer.extend({
    getTileUrl: function(coords){
      var n = Math.pow(2, coords.z), originShift = 20037508.342789244;
      var tileSize = originShift * 2 / n;
      var minX = -originShift + coords.x * tileSize, maxX = minX + tileSize;
      var maxY = originShift - coords.y * tileSize, minY = maxY - tileSize;
      var bbox = [minX, minY, maxX, maxY].join(',');
      return __NOAA_BASE__ + '/export?bbox=' + bbox + '&bboxSR=102100&imageSR=102100'
        + '&size=256,256&format=png32&transparent=true&layers=show:0&f=image';
    }
  });
  var noaaLayer = null;
  var noaaToggle = document.getElementById('epm-noaa-snow-toggle');
  if(noaaToggle){
    noaaToggle.addEventListener('change', function(){
      if(this.checked){
        if(!noaaLayer){ noaaLayer = new NoaaSnowLayer('', {opacity:0.65, maxNativeZoom:12, attribution:'__NOAA_ATTR__'}); }
        noaaLayer.addTo(map);
      } else if(noaaLayer){
        map.removeLayer(noaaLayer);
      }
    });
  }
});
</script>
"""


def _legend_html():
    def _swatch(key):
        style = LAND_OWNERSHIP_STYLES[key]
        border = "dashed 2px" if key == "cpw_access" else "solid 0"
        return f"""<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;
          background:{style['color']};opacity:.75;flex:none;border:{border} {style['color']};"></span>
          <span>{style['label']}</span>
        </div>"""

    swatches = "".join(_swatch(key) for key in LAND_OWNERSHIP_ORDER)
    return f"""
    <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;">
      <div id="epm-legend-hd" onclick="epmLegendToggle()"
           style="display:flex;justify-content:space-between;align-items:center;
           gap:8px;cursor:pointer;">
        <span style="font-size:11px;font-weight:600;">Land ownership</span>
        <button id="epm-legend-toggle" onclick="event.stopPropagation();epmLegendToggle()"
          style="border:none;background:#eef2f8;border-radius:6px;padding:1px 8px;
          cursor:pointer;font-size:13px;line-height:1.2;color:#333;">&#8211;</button>
      </div>
      <div id="epm-legend-body" style="margin-top:3px;">
        {swatches}
        <div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
          <span style="display:inline-block;width:16px;height:0;border-top:3px solid #1a1a1a;flex:none;"></span>
          <span>GMU boundary</span>
        </div>
        <div style="font-size:9.5px;color:#888;margin-top:4px;">Unshaded land inside
        the GMU boundary is private with no public access. Land with a dashed
        magenta outline is confirmed open through a CPW access program (a
        State Wildlife Area, Walk-In Access, or State Trust Land enrolled in
        the Public Access Program) even where PAD-US marks the same ground
        Restricted Access -- click it to see which program grants access.
        Amber "Conditional access" parcels are PAD-US Restricted Access with
        no confirmed CPW program: they may still be huntable with a permit,
        lease, or seasonal exception, but this map does not shade them.
        Sources: USGS PAD-US and CPW/State Land Board, which can lag reality,
        so always check CPW's hunting atlas before you hunt.</div>
      </div>
    </div>"""


def _deer_range_legend_html():
    """'Deer seasonal range' legend: a second, independent collapsible
    sub-section (epm-legend2-*), same pattern as _legend_html above but
    for deer_range.py's polygons rather than land ownership."""

    def _swatch(key):
        style = DEER_RANGE_STYLES[key]
        return f"""<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;
          background:{style['color']};opacity:.75;flex:none;"></span>
          <span>{style['label']}</span>
        </div>"""

    swatches = "".join(_swatch(key) for key in DEER_RANGE_ORDER)
    return f"""
    <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;">
      <div id="epm-legend2-hd" onclick="epmLegend2Toggle()"
           style="display:flex;justify-content:space-between;align-items:center;
           gap:8px;cursor:pointer;">
        <span style="font-size:11px;font-weight:600;">Deer seasonal range</span>
        <button id="epm-legend2-toggle" onclick="event.stopPropagation();epmLegend2Toggle()"
          style="border:none;background:#eef2f8;border-radius:6px;padding:1px 8px;
          cursor:pointer;font-size:13px;line-height:1.2;color:#333;">&#8211;</button>
      </div>
      <div id="epm-legend2-body" style="margin-top:3px;">
        {swatches}
        <div style="font-size:9.5px;color:#888;margin-top:4px;">CPW's own delineation of
        where mule deer actually are (`deer_range.py`), a stronger signal than anything
        the habitat factor infers from terrain alone. These are High Priority Habitat
        <i>subsets</i>, not a complete deer-range product: there is no Mule Deer Overall
        Range or Mule Deer Summer Range layer, so ground with no polygon here is not
        evidence deer are absent, it may simply be un-delineated. Off by default and
        drawn as a light outline with a faint fill (these polygons often cover most of
        a unit, and a heavy fill washed out the basemap and heatmap underneath it) --
        turn it on in the layer control.</div>
      </div>
    </div>"""


def _snow_slider_html(levels_in, anchor_idx, anchor_note, seasonal_range_gmus=None, total_units=0):
    """Simulated snow depth slider (status panel): moving it swaps between
    Python-precomputed overlays at these exact depths (see SNOW_JS_TMPL),
    it never recomputes anything in JS. anchor_note (deer_map.snow_anchor)
    explains, in plain text, where the initial position came from -- the
    live SNOTEL reading(s) for the units actually built this run.

    seasonal_range_gmus/total_units: which of this run's units actually
    have the deer seasonal range factor in their blend (probability.
    weights_for_snow only has a weight to raise if seasonal_range is
    actually one of the factors -- when a unit's CPW fetch failed and
    that factor was dropped, probability.compute_probability renormalizes
    to a level-invariant split instead, and asserting a weight shift for
    that unit would be false; see README's deer-seasonal-range section)."""
    anchor_depth = levels_in[anchor_idx]
    seasonal_range_gmus = seasonal_range_gmus or []
    if not seasonal_range_gmus:
        weight_sentence = (
            " The deer seasonal range factor is unavailable this run (its CPW fetch "
            "failed) for every unit built, so simulated snow depth here only shifts "
            "the elevation-band sweet spot -- it does not change any factor's weight."
        )
    elif len(seasonal_range_gmus) == total_units:
        weight_sentence = (
            " Deeper simulated snow also raises the deer seasonal range factor's weight in the "
            "blend (an uncalibrated heuristic, see the README), with the other weights scaled "
            "down to keep the total at 100%."
        )
    else:
        gmu_list = ", ".join(f"GMU {g}" for g in seasonal_range_gmus)
        weight_sentence = (
            f" Deeper simulated snow also raises the deer seasonal range factor's weight in the "
            f"blend (an uncalibrated heuristic, see the README) for {gmu_list}, where that factor "
            f"is available this run, with the other weights scaled down to keep the total at 100%; "
            f"its CPW fetch failed for the rest, so snow only shifts their elevation-band sweet spot."
        )
    return f"""
    <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;">
      <div style="font-size:11px;font-weight:600;">Simulated snow depth
        <span style="font-weight:400;color:#c62828;">(SIMULATED, not live -- valid
        only for the GMU(s) built in this run)</span>
      </div>
      <input type="range" id="epm-snow-slider" min="0" max="{len(levels_in) - 1}" step="1"
        value="{anchor_idx}" style="width:100%;margin:6px 0 2px;height:22px;">
      <div style="display:flex;justify-content:space-between;font-size:10.5px;color:#555;">
        <span>{levels_in[0]} in</span>
        <span id="epm-snow-value" style="font-weight:700;">{anchor_depth} in</span>
        <span>{levels_in[-1]} in</span>
      </div>
      <div style="font-size:9.5px;color:#888;margin-top:3px;">{anchor_note} Dragging swaps between
      {len(levels_in)} probability layers precomputed in Python at fixed depths (0 to
      {levels_in[-1]} in) and globally normalized together, so brightness is comparable
      across levels rather than each level independently rescaling back to full
      brightness -- a unit that gets worse overall renders dimmer, not bright everywhere.
      {weight_sentence}</div>
    </div>"""


def _noaa_snow_toggle_html():
    """Live NOAA snow depth toggle (status panel): a display overlay only,
    default off. See render.py's NOAA_NOHRSC_MAPSERVER_URL docstring and
    SNOW_JS_TMPL for the actual layer; this is just the checkbox."""
    return f"""
    <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;">
      <label style="font-size:11px;display:flex;align-items:center;gap:7px;cursor:pointer;">
        <input type="checkbox" id="epm-noaa-snow-toggle" style="width:17px;height:17px;">
        Live snow depth (NOAA NOHRSC)
      </label>
      <div style="font-size:9.5px;color:#888;margin-top:2px;">Rendered map image from
      NOAA's National Operational Hydrologic Remote Sensing Center Snow Analysis, a
      display overlay only, not a model input -- the model's own snow input is still
      the SNOTEL reading above. Off by default so it does not obscure the map.</div>
    </div>"""


def _panel_html(unit_stats, snow=None):
    sections = []
    for u in unit_stats:
        h = u["harvest"]
        harvest_html = (
            f"Bucks: {h['bucks']} &middot; Hunters: {h['total_hunters']} &middot; "
            f"Success: {h['pct_success']}%"
            if h else "No 2023 harvest data for this GMU/season."
        )
        depth_note = (
            f", live reading {u['depth_in']:.0f} in" if u.get("depth_in") is not None else ""
        )
        if u.get("station_name"):
            snow_html = f"Snow: {u['station_name']} ({u['station_dist_km']:.0f} km away{depth_note})"
        elif u.get("snow_error"):
            # Distinct from "no nearby SNOTEL station" below: the fetch
            # itself failed (network error, bad status), not "there
            # genuinely is no station near this unit" -- conflating the
            # two would be dishonest about why the shift is 0.
            snow_html = "Snow: SNOTEL fetch failed; elevation-band shift assumed 0 in"
        else:
            snow_html = "Snow: no nearby SNOTEL station"
        factor_list = ", ".join(u["used"])
        habitat_used = u.get("habitat_used") or []
        habitat_inputs_html = ""
        if habitat_used:
            habitat_inputs = ", ".join(habitat_used)
            degraded_note = (
                " (cover unavailable this run -- LANDFIRE fetch failed, remaining weights renormalized)"
                if "cover" not in habitat_used else ""
            )
            habitat_inputs_html = (
                f'<br><span style="font-size:9.5px;color:#aaa;">habitat inputs: '
                f'{habitat_inputs}{degraded_note}</span>'
            )
        sections.append(f"""
        <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;">
          <b>GMU {u['gmu']}</b><br>
          <span style="font-size:11px;color:#666;">2nd rifle 2023: {harvest_html}</span><br>
          <span style="font-size:11px;color:#666;">{snow_html}</span><br>
          <span style="font-size:10px;color:#aaa;">factors: {factor_list}</span>{habitat_inputs_html}
        </div>""")
    return f"""
    <div id="epm-panel">
      <div class="epm-hd" onclick="epmToggle()">
        <span style="font-weight:700;font-size:14.5px;">Mule Deer Probability</span>
        <button id="epm-toggle" onclick="event.stopPropagation();epmToggle()">&#8211;</button>
      </div>
      <div id="epm-body">
        <div style="font-size:11px;">Probability
          <span style="display:inline-block;width:118px;height:10px;border-radius:3px;
          background:linear-gradient(to right,#440154,#31688e,#35b779,#fde725);
          vertical-align:middle;margin-left:4px;"></span>
        </div>
        {''.join(sections)}
        <div style="font-size:10px;color:#aaa;margin-top:6px;">Habitat/access
        suitability index, <i>not</i> calibrated probability or live
        animal telemetry. Probability shading is limited to legally open
        land: PAD-US Open Access, plus land opened by a CPW access
        program (State Wildlife Areas, Walk-In Access, State Trust Land
        Public Access Program); see the land ownership legend below for
        conditional and closed land.</div>
        {_legend_html()}
        {_deer_range_legend_html()}
        {_snow_slider_html(
            snow["levels_in"], snow["anchor_idx"], snow["anchor_note"],
            seasonal_range_gmus=[u["gmu"] for u in unit_stats if "seasonal_range" in (u.get("used") or [])],
            total_units=len(unit_stats),
        ) if snow else ""}
        {_noaa_snow_toggle_html() if snow else ""}
      </div>
    </div>"""


def build_map(*, units_data, weights, out_path, snow=None):
    """units_data: list of dicts, one per unit:
    {gmu, prob_uri, prob_bounds, cells, half_lat, half_lon, harvest, used,
     station_name, station_dist_km, land_features, cpw_features,
     deer_range_features, gmu_geometry}.
    land_features, cpw_features, deer_range_features, and gmu_geometry are
    optional (a unit missing any of them just contributes nothing to that
    layer).

    snow (optional; see deer_map.process_unit/main): enables the simulated
    snow depth slider. A dict {levels_in, weights_by_level, anchor_idx,
    anchor_note} (levels_in: snow.SIMULATED_SNOW_LEVELS_IN; weights_by_level:
    one probability.weights_for_snow() dict per level, shared by every
    unit, since the simulated depth is one slider for the whole map, not
    per unit; anchor_idx/anchor_note: deer_map.snow_anchor's initial slider
    position and the plain-text explanation of how it was chosen from the
    unit(s)' live SNOTEL reading(s)). Each unit dict must then also carry
    depth_in (that unit's own live reading, for display), snow_prob_uris
    (per-level PNG for that unit, aligned to levels_in), and snow_cells/
    snow_half_lat/snow_half_lon (render.build_snow_level_cells' output).
    When omitted, build_map's output is byte-for-byte the same as before
    the slider existed."""
    import folium
    from folium.raster_layers import ImageOverlay

    all_lats = [lat for u in units_data for lat in (u["prob_bounds"][0][0], u["prob_bounds"][1][0])]
    all_lons = [lon for u in units_data for lon in (u["prob_bounds"][0][1], u["prob_bounds"][1][1])]
    center = [sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)]

    m = folium.Map(location=center, zoom_start=8, tiles=None)
    folium.TileLayer(
        tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        attr="USGS The National Map",
        name="USGS Topo",
        max_zoom=16, max_native_zoom=16,
        overlay=False, control=True, show=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False, control=True, show=False,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri World Imagery",
        overlay=False, control=True, show=False,
    ).add_to(m)
    m.get_root().header.add_child(folium.Element(MOBILE_CSS))

    all_cells = []
    unit_overlays = {}
    for u in units_data:
        overlay = ImageOverlay(image=u["prob_uri"], bounds=u["prob_bounds"], opacity=0.7,
                                name=f"GMU {u['gmu']} deer probability", show=True)
        overlay.add_to(m)
        unit_overlays[u["gmu"]] = overlay
        if snow is None:
            all_cells.extend(u["cells"])

    all_land_features = [f for u in units_data for f in (u.get("land_features") or [])]
    all_cpw_features = [f for u in units_data for f in (u.get("cpw_features") or [])]
    all_deer_range_features = [f for u in units_data for f in (u.get("deer_range_features") or [])]
    _add_land_ownership_layer(m, all_land_features, all_cpw_features)
    _add_deer_range_layer(m, all_deer_range_features)
    _add_gmu_boundary_layer(m, [u.get("gmu_geometry") for u in units_data])

    m.fit_bounds([[min(all_lats), min(all_lons)], [max(all_lats), max(all_lons)]])

    if snow is not None:
        all_snow_cells = [c for u in units_data for c in (u.get("snow_cells") or [])]
        half_lat = units_data[0].get("snow_half_lat", 0.05) if units_data else 0.05
        half_lon = units_data[0].get("snow_half_lon", 0.05) if units_data else 0.05
        unit_overlay_js = {
            str(u["gmu"]): {"varName": unit_overlays[u["gmu"]].get_name(), "uris": u.get("snow_prob_uris") or []}
            for u in units_data
        }
        interactive_js = (
            SNOW_JS_TMPL
            .replace("__LEVELS__", json.dumps(snow["levels_in"]))
            .replace("__WEIGHTS_BY_LEVEL__", json.dumps(snow["weights_by_level"]))
            .replace("__UNIT_OVERLAYS__", json.dumps(unit_overlay_js))
            .replace("__CELLS__", json.dumps(all_snow_cells))
            .replace("__HALF_LAT__", str(half_lat))
            .replace("__HALF_LON__", str(half_lon))
            .replace("__MAP__", m.get_name())
            .replace("__ANCHOR_IDX__", str(snow.get("anchor_idx", 0)))
            .replace("__NOAA_BASE__", json.dumps(NOAA_NOHRSC_MAPSERVER_URL))
            .replace("__NOAA_ATTR__", NOAA_NOHRSC_ATTRIBUTION)
        )
    else:
        half_lat = units_data[0]["half_lat"] if units_data else 0.05
        half_lon = units_data[0]["half_lon"] if units_data else 0.05
        interactive_js = (
            INSPECT_JS_TMPL
            .replace("__CELLS__", json.dumps(all_cells))
            .replace("__W__", json.dumps(weights))
            .replace("__HALF_LAT__", str(half_lat))
            .replace("__HALF_LON__", str(half_lon))
            .replace("__MAP__", m.get_name())
        )

    panel = _panel_html([
        {"gmu": u["gmu"], "used": u["used"], "harvest": u["harvest"],
         "station_name": u.get("station_name"), "station_dist_km": u.get("station_dist_km"),
         "habitat_used": u.get("habitat_used"), "depth_in": u.get("depth_in"),
         "snow_error": u.get("snow_error")}
        for u in units_data
    ], snow=snow)

    m.get_root().html.add_child(folium.Element(panel))
    m.get_root().html.add_child(folium.Element(TOGGLE_JS))
    m.get_root().html.add_child(folium.Element(LEGEND_JS))
    m.get_root().html.add_child(folium.Element(interactive_js))
    folium.LayerControl().add_to(m)
    m.save(out_path)
