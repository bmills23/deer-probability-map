import numpy as np
import pytest

from render import (
    HABITAT_SUBFACTOR_KEYS,
    _deer_range_style_function,
    _panel_html,
    _snow_slider_html,
    build_inspection_cells,
    build_map,
    build_snow_level_cells,
    categorize_ownership,
    render_prob_png,
)


def test_render_prob_png_returns_data_uri_and_bounds():
    prob = np.array([[0.2, 0.8], [np.nan, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    uri, bounds = render_prob_png(prob, lats, lons)
    assert uri.startswith("data:image/png;base64,")
    assert bounds[0][0] < bounds[1][0]  # south < north
    assert bounds[0][1] < bounds[1][1]  # west < east


def test_build_inspection_cells_skips_masked_and_below_threshold_cells():
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob = np.array([[0.5, 0.01], [0.9, 0.5]])
    habitat = np.array([[0.6, 0.6], [0.6, 0.6]])
    security = np.array([[0.4, 0.4], [0.4, 0.4]])
    mask = np.array([[True, True], [False, True]])
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, habitat, security, mask, stride=1, thresh=0.03
    )
    # (0,0) kept: prob 0.5, masked in; (0,1) dropped: below thresh;
    # (1,0) dropped: masked out; (1,1) kept: prob 0.5, masked in
    assert len(rows) == 2
    assert rows[0][:3] == [38.0, -105.0, 50]
    assert half_lat > 0
    assert half_lon > 0


def test_build_inspection_cells_derives_stride_from_inspect_mi():
    """With no explicit stride, the spacing between inspection cells should
    come from inspect_mi (a target physical spacing), not a fixed stride --
    at fine cell sizes a fixed stride would make the embedded JSON explode."""
    lats = np.arange(38.0, 38.0 + 0.0036 * 20, 0.0036)  # ~0.25 mi cells
    lons = np.arange(-105.0, -105.0 + 0.0046 * 20, 0.0046)  # ~0.25 mi cells at this latitude
    prob = np.full((len(lats), len(lons)), 0.5)
    habitat = np.full(prob.shape, 0.6)
    security = np.full(prob.shape, 0.4)
    mask = np.ones(prob.shape, dtype=bool)

    rows_fine, half_lat_fine, half_lon_fine = build_inspection_cells(
        lats, lons, prob, habitat, security, mask, inspect_mi=0.5, thresh=0.03
    )
    rows_coarse, half_lat_coarse, half_lon_coarse = build_inspection_cells(
        lats, lons, prob, habitat, security, mask, inspect_mi=1.0, thresh=0.03
    )
    # A coarser target spacing means a bigger stride -> fewer rows, bigger half.
    assert len(rows_coarse) < len(rows_fine)
    assert half_lat_coarse > half_lat_fine
    assert half_lon_coarse > half_lon_fine


def test_build_inspection_cells_appends_habitat_subcomponents_when_given():
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob = np.full((2, 2), 0.5)
    habitat = np.full((2, 2), 0.6)
    security = np.full((2, 2), 0.4)
    mask = np.ones((2, 2), dtype=bool)
    habitat_parts = {
        "elevation": np.full((2, 2), 0.9),
        "aspect": np.full((2, 2), 0.7),
        "slope": np.full((2, 2), 0.5),
        # "cover" intentionally omitted -- simulates a failed LANDFIRE fetch
    }
    rows, _, _ = build_inspection_cells(
        lats, lons, prob, habitat, security, mask, stride=1, thresh=0.0, habitat_parts=habitat_parts
    )
    assert HABITAT_SUBFACTOR_KEYS == ["elevation", "aspect", "slope", "cover"]
    # columns 5,6,7 = elevation, aspect, slope; column 8 = cover, None (missing this run)
    assert rows[0][5:9] == [0.9, 0.7, 0.5, None]


def test_build_inspection_cells_habitat_subcomponents_default_to_none():
    """Callers that don't pass habitat_parts (old call sites, or tests)
    still get a valid, backward-compatible row shape."""
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob = np.full((2, 2), 0.5)
    habitat = np.full((2, 2), 0.6)
    security = np.full((2, 2), 0.4)
    mask = np.ones((2, 2), dtype=bool)
    rows, _, _ = build_inspection_cells(lats, lons, prob, habitat, security, mask, stride=1, thresh=0.0)
    assert rows[0][5:9] == [None, None, None, None]


def test_build_inspection_cells_explicit_stride_overrides_inspect_mi():
    lats = np.array([38.0, 38.1, 38.2, 38.3])
    lons = np.array([-105.0, -104.9, -104.8, -104.7])
    prob = np.full((4, 4), 0.5)
    habitat = np.full((4, 4), 0.6)
    security = np.full((4, 4), 0.4)
    mask = np.ones((4, 4), dtype=bool)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, habitat, security, mask, stride=2, inspect_mi=100.0, thresh=0.03
    )
    assert half_lat == pytest.approx(0.1)  # stride(2) * dlat(0.1) / 2


def test_build_inspection_cells_appends_seasonal_range_after_habitat_subcomponents():
    """seasonal_range_score (deer_range.py) must be appended after the four
    fixed habitat sub-factor columns so HABITAT_SUBFACTOR_KEYS' indices
    (5-8) never shift."""
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob = np.full((2, 2), 0.5)
    habitat = np.full((2, 2), 0.6)
    security = np.full((2, 2), 0.4)
    seasonal_range = np.full((2, 2), 0.85)
    mask = np.ones((2, 2), dtype=bool)
    rows, _, _ = build_inspection_cells(
        lats, lons, prob, habitat, security, mask, stride=1, thresh=0.0, seasonal_range=seasonal_range
    )
    assert rows[0][9] == pytest.approx(0.85)


def test_build_inspection_cells_seasonal_range_defaults_to_none():
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob = np.full((2, 2), 0.5)
    habitat = np.full((2, 2), 0.6)
    security = np.full((2, 2), 0.4)
    mask = np.ones((2, 2), dtype=bool)
    rows, _, _ = build_inspection_cells(lats, lons, prob, habitat, security, mask, stride=1, thresh=0.0)
    assert rows[0][9] is None


def test_build_snow_level_cells_row_shape_and_thresh_across_levels():
    """A cell that clears thresh at ANY level must be kept, with static
    factors (security/aspect/slope/cover/seasonal_range) stored once and a
    per-level [prob_pct, habitat, elevation_sub] triple for each level."""
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    mask = np.ones((2, 2), dtype=bool)
    # cell (0,0): below thresh at level 0, above at level 1.
    level0_prob = np.array([[0.01, 0.5], [0.5, 0.5]])
    level1_prob = np.array([[0.5, 0.5], [0.5, 0.5]])
    level0_habitat = np.full((2, 2), 0.2)
    level1_habitat = np.full((2, 2), 0.6)
    level0_elev = np.full((2, 2), 0.1)
    level1_elev = np.full((2, 2), 0.9)
    security = np.full((2, 2), 0.4)
    aspect = np.full((2, 2), 0.7)
    slope = np.full((2, 2), 0.5)
    cover = np.full((2, 2), 0.3)
    seasonal_range = np.full((2, 2), 0.85)

    rows, half_lat, half_lon = build_snow_level_cells(
        lats, lons, [level0_prob, level1_prob], [level0_habitat, level1_habitat],
        [level0_elev, level1_elev], mask, security=security, seasonal_range=seasonal_range,
        aspect=aspect, slope=slope, cover=cover, stride=1, thresh=0.03,
    )
    assert len(rows) == 4  # all cells clear thresh at level 1
    row = next(r for r in rows if r[0] == 38.0 and r[1] == -105.0)
    assert row[2:7] == [0.4, 0.7, 0.5, 0.3, 0.85]
    assert row[7][0] == [1, 0.2, 0.1]    # level 0: below thresh -> prob_pct 1 (0.01*100 rounded)
    assert row[7][1] == [50, 0.6, 0.9]   # level 1: 0.5 -> 50%
    assert half_lat > 0 and half_lon > 0


def test_build_snow_level_cells_skips_cell_below_thresh_at_every_level():
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    mask = np.ones((2, 2), dtype=bool)
    level0_prob = np.array([[0.01, 0.5], [0.5, 0.5]])
    level1_prob = np.array([[0.02, 0.5], [0.5, 0.5]])
    habitat = np.full((2, 2), 0.5)
    elev = np.full((2, 2), 0.5)
    rows, _, _ = build_snow_level_cells(
        lats, lons, [level0_prob, level1_prob], [habitat, habitat], [elev, elev],
        mask, stride=1, thresh=0.03,
    )
    assert len(rows) == 3  # (0,0) dropped: below thresh at both levels


def test_build_snow_level_cells_skips_masked_out_cells():
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    mask = np.array([[True, False], [True, True]])
    prob = np.full((2, 2), 0.5)
    habitat = np.full((2, 2), 0.5)
    elev = np.full((2, 2), 0.5)
    rows, _, _ = build_snow_level_cells(
        lats, lons, [prob], [habitat], [elev], mask, stride=1, thresh=0.03,
    )
    assert len(rows) == 3  # (0,1) masked out


def test_build_snow_level_cells_static_factors_default_to_none():
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    mask = np.ones((2, 2), dtype=bool)
    prob = np.full((2, 2), 0.5)
    habitat = np.full((2, 2), 0.5)
    elev = np.full((2, 2), 0.5)
    rows, _, _ = build_snow_level_cells(lats, lons, [prob], [habitat], [elev], mask, stride=1, thresh=0.03)
    assert rows[0][2:7] == [None, None, None, None, None]


def test_build_snow_level_cells_half_lat_lon_matches_build_inspection_cells():
    """Both functions derive stride/half-cell size from inspect_mi the same
    way -- given identical grid spacing they must agree exactly."""
    lats = np.array([38.0, 38.1, 38.2, 38.3])
    lons = np.array([-105.0, -104.9, -104.8, -104.7])
    mask = np.ones((4, 4), dtype=bool)
    prob = np.full((4, 4), 0.5)
    habitat = np.full((4, 4), 0.5)
    security = np.full((4, 4), 0.4)

    _, half_lat_a, half_lon_a = build_inspection_cells(
        lats, lons, prob, habitat, security, mask, inspect_mi=0.5, thresh=0.03
    )
    _, half_lat_b, half_lon_b = build_snow_level_cells(
        lats, lons, [prob], [habitat], [habitat], mask, security=security, inspect_mi=0.5, thresh=0.03
    )
    assert half_lat_a == half_lat_b
    assert half_lon_a == half_lon_b


def test_categorize_ownership_forest_service_is_usfs():
    """Regression test: PAD-US's real MngNm_Desc value for National Forest
    land is 'Forest Service', not 'US Forest Service'. The old string
    comparison never matched, so National Forest -- the largest huntable
    block in most GMUs -- silently fell through to other_open/restricted
    and rendered with the wrong color, with a dead USFS legend swatch."""
    assert categorize_ownership({"MngNm_Desc": "Forest Service", "Pub_Access": "RA"}) == "usfs"
    assert categorize_ownership({"MngNm_Desc": "Forest Service", "Pub_Access": "OA"}) == "usfs"


def test_categorize_ownership_manager_based_categories_win_regardless_of_access():
    assert categorize_ownership({"MngNm_Desc": "Forest Service", "Pub_Access": "RA"}) == "usfs"
    assert categorize_ownership({"MngNm_Desc": "Bureau of Land Management", "Pub_Access": "OA"}) == "blm"
    assert categorize_ownership({"MngNm_Desc": "State Fish and Wildlife", "Pub_Access": "RA"}) == "swa"
    assert categorize_ownership({"MngNm_Desc": "State Land Board", "Pub_Access": "XA"}) == "slb"


def test_categorize_ownership_other_open_public_when_oa_and_unlisted_manager():
    assert categorize_ownership({"MngNm_Desc": "City Land", "Pub_Access": "OA"}) == "other_open"
    assert categorize_ownership({"MngNm_Desc": "Non-Governmental Organization", "Pub_Access": "OA"}) == "other_open"


def test_categorize_ownership_conditional_when_ra_and_unlisted_manager():
    """A Restricted Access parcel with no manager-specific category (not
    USFS/BLM/state wildlife/state land board) is 'conditional', distinct
    from the 'restricted' (Closed/Unknown) catch-all."""
    assert categorize_ownership({"MngNm_Desc": "County Land", "Pub_Access": "RA"}) == "conditional"
    assert categorize_ownership({"MngNm_Desc": "Joint", "Pub_Access": "RA"}) == "conditional"


def test_build_map_panel_notes_degraded_habitat_when_cover_missing(tmp_path):
    """When a LANDFIRE fetch fails at run time, habitat's remaining
    sub-weights renormalize (terrain.habitat_components) and the status
    panel must say so -- same graceful-degradation visibility
    compute_probability's top-level 'used' list already gives."""
    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, prob, prob, np.ones(prob.shape, dtype=bool), stride=1, thresh=0.0
    )
    units_data = [{
        "gmu": 59, "prob_uri": prob_uri, "prob_bounds": prob_bounds,
        "cells": rows, "half_lat": half_lat, "half_lon": half_lon,
        "harvest": None, "used": ["habitat", "security"],
        "habitat_used": ["elevation", "aspect", "slope"],  # no "cover"
        "station_name": None, "station_dist_km": None,
    }]
    out_path = tmp_path / "map.html"
    build_map(units_data=units_data, weights={"habitat": 0.55, "security": 0.45}, out_path=str(out_path))
    html = out_path.read_text()
    assert "habitat inputs: elevation, aspect, slope" in html
    assert "LANDFIRE fetch failed" in html
    assert "—" not in html
    assert "&mdash;" not in html


def test_categorize_ownership_restricted_catch_all():
    assert categorize_ownership({"MngNm_Desc": "Non-Governmental Organization", "Pub_Access": "XA"}) == "restricted"
    assert categorize_ownership({}) == "restricted"
    assert categorize_ownership(None) == "restricted"


def test_build_map_uses_usgs_topo_basemap_not_cartodb(tmp_path):
    """CartoDB's free tiles now return an "API Key Required" placeholder,
    so the default base layer must be a keyless source (USGS Topo), and
    the saved HTML must not reference cartocdn at all."""
    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, prob, prob, np.ones(prob.shape, dtype=bool), stride=1, thresh=0.0
    )
    units_data = [{
        "gmu": 59,
        "prob_uri": prob_uri,
        "prob_bounds": prob_bounds,
        "cells": rows,
        "half_lat": half_lat,
        "half_lon": half_lon,
        "harvest": None,
        "used": ["habitat", "security"],
        "station_name": None,
        "station_dist_km": None,
    }]
    out_path = tmp_path / "map.html"
    build_map(units_data=units_data, weights={"habitat": 0.55, "security": 0.45}, out_path=str(out_path))
    html = out_path.read_text()
    assert "basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile" in html
    assert "cartocdn" not in html.lower()


def test_build_map_includes_land_ownership_layer_boundary_layer_and_legend(tmp_path):
    """Synthetic feature list, entirely offline: the saved HTML must carry
    a toggleable 'Land ownership' overlay (styled by category, with a
    manager/unit/access/acres tooltip), a toggleable 'GMU boundary'
    outline, and a legend in the status panel that names every category
    plus the private-land and PAD-US-can-lag-reality notes."""
    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, prob, prob, np.ones(prob.shape, dtype=bool), stride=1, thresh=0.0
    )

    land_features = [
        {
            "type": "Feature",
            "properties": {
                "Pub_Access": "OA", "MngNm_Desc": "Forest Service",
                "Unit_Nm": "Test National Forest", "GIS_Acres": 12345.0,
            },
            "geometry": {"type": "Polygon", "coordinates": [[
                [-105.02, 38.02], [-105.02, 38.04], [-105.00, 38.04], [-105.00, 38.02], [-105.02, 38.02],
            ]]},
        },
        {
            "type": "Feature",
            "properties": {
                "Pub_Access": "RA", "MngNm_Desc": "State Land Board",
                "Unit_Nm": "Test State Trust Parcel", "GIS_Acres": 640.0,
            },
            "geometry": {"type": "Polygon", "coordinates": [[
                [-105.06, 38.06], [-105.06, 38.08], [-105.04, 38.08], [-105.04, 38.06], [-105.06, 38.06],
            ]]},
        },
        {
            "type": "Feature",
            "properties": {
                "Pub_Access": "RA", "MngNm_Desc": "County Land",
                "Unit_Nm": "Test County Parcel", "GIS_Acres": 80.0,
            },
            "geometry": {"type": "Polygon", "coordinates": [[
                [-105.08, 38.01], [-105.08, 38.02], [-105.07, 38.02], [-105.07, 38.01], [-105.08, 38.01],
            ]]},
        },
    ]
    cpw_features = [
        {
            "type": "Feature",
            "properties": {"_source": "slb_pap", "PropName": "Test SLB Access Parcel", "Acres": 640.0},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-105.06, 38.06], [-105.06, 38.08], [-105.04, 38.08], [-105.04, 38.06], [-105.06, 38.06],
            ]]},
        },
    ]
    gmu_geometry = {"type": "Polygon", "coordinates": [[
        [-105.1, 38.0], [-105.1, 38.1], [-104.9, 38.1], [-104.9, 38.0], [-105.1, 38.0],
    ]]}

    units_data = [{
        "gmu": 59,
        "prob_uri": prob_uri,
        "prob_bounds": prob_bounds,
        "cells": rows,
        "half_lat": half_lat,
        "half_lon": half_lon,
        "harvest": None,
        "used": ["habitat", "security"],
        "station_name": None,
        "station_dist_km": None,
        "land_features": land_features,
        "cpw_features": cpw_features,
        "gmu_geometry": gmu_geometry,
    }]
    out_path = tmp_path / "map.html"
    build_map(units_data=units_data, weights={"habitat": 0.55, "security": 0.45}, out_path=str(out_path))
    html = out_path.read_text()

    # Layer control toggles
    assert "Land ownership" in html
    assert "GMU boundary" in html

    # Tooltip fields/data made it into the embedded GeoJSON
    assert "Manager" in html
    assert "Test National Forest" in html
    assert "Test State Trust Parcel" in html
    assert "Test SLB Access Parcel" in html
    assert "State Trust Land, CPW Public Access Program" in html  # which source granted access

    # Legend in the status panel names every category, including the new
    # CPW-access and conditional-access tiers
    assert "US Forest Service" in html
    assert "Bureau of Land Management" in html
    assert "State Wildlife Area" in html
    assert "State Land Board" in html
    assert "CPW access program land, open to licensed hunters" in html
    assert "Other open public land" in html
    assert "Conditional access" in html
    assert "Restricted or closed" in html
    assert "private with no public access" in html
    assert "Public Access Program" in html
    assert "can lag reality" in html

    # A CPW-sourced parcel gets a visibly distinct (dashed) outline.
    assert "dashArray" in html

    # Legend is its own collapsible section (independent of the epm-body
    # panel toggle), collapsed by default on narrow screens only.
    assert 'id="epm-legend-hd"' in html
    assert 'id="epm-legend-body"' in html
    assert "epmLegendToggle" in html
    assert "matchMedia('(max-width:600px)')" in html
    assert "max-height:40vh" in html

    # Hard rule: no em dash anywhere in the generated page.
    assert "—" not in html
    assert "&mdash;" not in html


def test_build_map_includes_deer_seasonal_range_layer_and_legend_and_popup_factor(tmp_path):
    """The deer seasonal range display layer (deer_range.py) must be a
    toggleable layer distinct from land ownership, with a tooltip naming
    the range type, a legend entry, and a 'seasonal_range' factor row in
    the click-to-inspect popup's weights-driven column map."""
    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)
    seasonal_range = np.full(prob.shape, 0.85)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, prob, prob, np.ones(prob.shape, dtype=bool),
        stride=1, thresh=0.0, seasonal_range=seasonal_range,
    )

    deer_range_features = [
        {
            "type": "Feature",
            "properties": {"_range_type": "winter_concentration", "Activity_C": "Winter Concentration"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-105.02, 38.02], [-105.02, 38.04], [-105.00, 38.04], [-105.00, 38.02], [-105.02, 38.02],
            ]]},
        },
    ]

    units_data = [{
        "gmu": 59,
        "prob_uri": prob_uri,
        "prob_bounds": prob_bounds,
        "cells": rows,
        "half_lat": half_lat,
        "half_lon": half_lon,
        "harvest": None,
        "used": ["habitat", "security", "seasonal_range"],
        "station_name": None,
        "station_dist_km": None,
        "deer_range_features": deer_range_features,
    }]
    out_path = tmp_path / "map.html"
    build_map(
        units_data=units_data,
        weights={"habitat": 0.45, "security": 0.35, "seasonal_range": 0.20},
        out_path=str(out_path),
    )
    html = out_path.read_text()

    # Toggleable layer, distinct from "Land ownership".
    assert "Deer seasonal range" in html
    assert "Mule Deer Winter Concentration Area" in html

    # Popup column map / label for the new factor.
    assert '"seasonal_range":9' in html
    assert "Deer seasonal range (CPW)" in html

    # Legend entry for the new layer.
    assert 'id="epm-legend2-hd"' in html
    assert 'id="epm-legend2-body"' in html
    assert "epmLegend2Toggle" in html

    assert "—" not in html
    assert "&mdash;" not in html


def test_deer_range_style_is_light_not_a_heavy_wash(tmp_path):
    """Regression test for the illegible-heavy-purple-fill visual bug: the
    deer seasonal range layer's fill must be low opacity (a light outline),
    not the old 0.4 wash that obscured the basemap and heatmap underneath
    it over most of a unit."""
    style = _deer_range_style_function({"properties": {"_range_type": "winter_concentration"}})
    assert style["fillOpacity"] <= 0.15

    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, prob, prob, np.ones(prob.shape, dtype=bool), stride=1, thresh=0.0
    )
    deer_range_features = [{
        "type": "Feature",
        "properties": {"_range_type": "winter_concentration", "Activity_C": "Winter Concentration"},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-105.02, 38.02], [-105.02, 38.04], [-105.00, 38.04], [-105.00, 38.02], [-105.02, 38.02],
        ]]},
    }]
    units_data = [{
        "gmu": 59, "prob_uri": prob_uri, "prob_bounds": prob_bounds,
        "cells": rows, "half_lat": half_lat, "half_lon": half_lon,
        "harvest": None, "used": ["habitat", "security"],
        "station_name": None, "station_dist_km": None,
        "deer_range_features": deer_range_features,
    }]
    out_path = tmp_path / "map.html"
    build_map(units_data=units_data, weights={"habitat": 0.55, "security": 0.45}, out_path=str(out_path))
    html = out_path.read_text()
    assert '"fillOpacity": 0.4' not in html  # the old heavy-wash value must be gone
    assert "off by default" in html.lower()


def test_build_map_with_snow_renders_slider_noaa_toggle_and_level_aware_popup(tmp_path):
    """When build_map is given a `snow` stack, the status panel must carry
    a simulated-snow slider (labeled SIMULATED and scoped to the unit(s)
    built this run), a live-reading anchor note, a NOAA NOHRSC toggle
    (default off), and the click-to-inspect popup JS must be the
    level-aware SNOW_JS_TMPL (per-level cell data + a weights-by-level
    table), not the old single-level INSPECT_JS_TMPL."""
    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    mask = np.ones(prob.shape, dtype=bool)
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)

    levels_in = [0, 8, 40]
    level_probs = [prob, prob * 0.8, prob * 0.5]
    level_habitat = [prob, prob, prob]
    level_elevation = [prob, prob, prob]
    security = np.full(prob.shape, 0.4)
    snow_cells, snow_half_lat, snow_half_lon = build_snow_level_cells(
        lats, lons, level_probs, level_habitat, level_elevation, mask,
        security=security, stride=1, thresh=0.0,
    )
    snow_prob_uris = [render_prob_png(p, lats, lons)[0] for p in level_probs]
    weights_by_level = [
        {"habitat": 0.45, "security": 0.35, "seasonal_range": 0.20},
        {"habitat": 0.40, "security": 0.31, "seasonal_range": 0.29},
        {"habitat": 0.30, "security": 0.30, "seasonal_range": 0.40},
    ]

    units_data = [{
        "gmu": 59, "prob_uri": prob_uri, "prob_bounds": prob_bounds,
        "cells": [], "half_lat": 0.05, "half_lon": 0.05,
        "harvest": None, "used": ["habitat", "security"],
        "station_name": "Test SNOTEL", "station_dist_km": 5.0, "depth_in": 8.0,
        "snow_prob_uris": snow_prob_uris, "snow_cells": snow_cells,
        "snow_half_lat": snow_half_lat, "snow_half_lon": snow_half_lon,
    }]
    snow = {
        "levels_in": levels_in,
        "weights_by_level": weights_by_level,
        "anchor_idx": 1,
        "anchor_note": "The simulated snow slider starts at the live SNOTEL reading (8 in).",
    }
    out_path = tmp_path / "map.html"
    build_map(units_data=units_data, weights={"habitat": 0.55, "security": 0.45},
              out_path=str(out_path), snow=snow)
    html = out_path.read_text()

    assert 'id="epm-snow-slider"' in html
    assert 'id="epm-snow-value"' in html
    assert "SIMULATED" in html
    assert "valid" in html.lower() and "GMU(s) built in this run" in html
    assert "live SNOTEL reading (8 in)" in html
    assert "live reading 8 in" in html  # per-unit panel line

    assert 'id="epm-noaa-snow-toggle"' in html
    assert "NOAA NOHRSC" in html or "NOHRSC" in html
    assert "not a model input" in html

    # New level-aware popup script, not the old fixed-weights one.
    assert "WBYLVL" in html
    assert "simulated at" in html
    assert '"seasonal_range":9' not in html  # old fixed column-map literal must be gone

    assert "—" not in html
    assert "&mdash;" not in html


def test_snow_slider_html_asserts_weight_shift_only_when_seasonal_range_is_used():
    """Regression test for the review finding: the slider caption must not
    claim deeper snow raises the seasonal-range weight when that factor
    isn't actually in the blend (e.g. its CPW fetch failed and
    probability.compute_probability renormalized without it -- in that
    case the weight shift never happens, so asserting it is false)."""
    used_html = _snow_slider_html([0, 8, 40], 0, "note.", seasonal_range_gmus=[59], total_units=1)
    assert "raises the deer seasonal range factor's weight" in used_html

    unused_html = _snow_slider_html([0, 8, 40], 0, "note.", seasonal_range_gmus=[], total_units=1)
    assert "raises the deer seasonal range factor's weight" not in unused_html
    assert "unavailable this run" in unused_html
    assert "does not change any factor's weight" in unused_html


def test_snow_slider_html_mixed_units_names_which_gmu_gets_the_weight_shift():
    html = _snow_slider_html([0, 8, 40], 0, "note.", seasonal_range_gmus=[38], total_units=2)
    assert "GMU 38" in html
    assert "its CPW fetch failed for the rest" in html


def test_panel_html_snow_caption_reflects_actual_used_factors():
    unit_stats_with = [{"gmu": 59, "used": ["habitat", "security", "seasonal_range"],
                         "harvest": None}]
    html_with = _panel_html(unit_stats_with, snow={
        "levels_in": [0, 8, 40], "anchor_idx": 0, "anchor_note": "note.",
    })
    assert "raises the deer seasonal range factor's weight" in html_with

    unit_stats_without = [{"gmu": 59, "used": ["habitat", "security"], "harvest": None}]
    html_without = _panel_html(unit_stats_without, snow={
        "levels_in": [0, 8, 40], "anchor_idx": 0, "anchor_note": "note.",
    })
    assert "raises the deer seasonal range factor's weight" not in html_without


def test_panel_html_distinguishes_snotel_fetch_failure_from_no_nearby_station():
    """render.py's 'no nearby SNOTEL station' branch must stay honest once
    a network failure can also reach it (deer_map.fetch_snow_conditions
    degrades instead of aborting the run) -- the two must read
    differently, since one means 'this unit has no station nearby' and
    the other means 'we don't know, the fetch failed'."""
    failed = _panel_html([{"gmu": 59, "used": ["habitat"], "harvest": None,
                            "station_name": None, "snow_error": "HTTPError 503"}])
    assert "SNOTEL fetch failed" in failed

    no_station = _panel_html([{"gmu": 59, "used": ["habitat"], "harvest": None,
                                "station_name": None, "snow_error": None}])
    assert "no nearby SNOTEL station" in no_station
    assert "fetch failed" not in no_station


def test_build_map_without_snow_has_no_slider_or_noaa_toggle(tmp_path):
    """Backward compatibility: omitting `snow` must not add any of the new
    UI (already covered structurally by the other build_map tests passing
    unchanged, this asserts it directly)."""
    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, prob, prob, np.ones(prob.shape, dtype=bool), stride=1, thresh=0.0
    )
    units_data = [{
        "gmu": 59, "prob_uri": prob_uri, "prob_bounds": prob_bounds,
        "cells": rows, "half_lat": half_lat, "half_lon": half_lon,
        "harvest": None, "used": ["habitat", "security"],
        "station_name": None, "station_dist_km": None,
    }]
    out_path = tmp_path / "map.html"
    build_map(units_data=units_data, weights={"habitat": 0.55, "security": 0.45}, out_path=str(out_path))
    html = out_path.read_text()
    assert 'id="epm-snow-slider"' not in html
    assert 'id="epm-noaa-snow-toggle"' not in html


def test_add_deer_range_layer_noop_when_no_features(tmp_path):
    """No deer_range_features at all (e.g. every layer fetch failed) must
    not error and must not add a stray empty layer."""
    prob = np.array([[0.2, 0.8], [0.1, 0.5]])
    lats = np.array([38.0, 38.1])
    lons = np.array([-105.0, -104.9])
    prob_uri, prob_bounds = render_prob_png(prob, lats, lons)
    rows, half_lat, half_lon = build_inspection_cells(
        lats, lons, prob, prob, prob, np.ones(prob.shape, dtype=bool), stride=1, thresh=0.0
    )
    units_data = [{
        "gmu": 59, "prob_uri": prob_uri, "prob_bounds": prob_bounds,
        "cells": rows, "half_lat": half_lat, "half_lon": half_lon,
        "harvest": None, "used": ["habitat", "security"],
        "station_name": None, "station_dist_km": None,
    }]
    out_path = tmp_path / "map.html"
    build_map(units_data=units_data, weights={"habitat": 0.55, "security": 0.45}, out_path=str(out_path))
    assert out_path.exists()
