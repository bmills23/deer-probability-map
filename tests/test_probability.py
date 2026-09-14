import numpy as np
import pytest

from probability import (
    DEFAULT_WEIGHTS,
    SEASONAL_RANGE_WEIGHT,
    SEASONAL_RANGE_WEIGHT_MAX,
    compute_probability,
    normalize_stack,
    seasonal_range_weight_for_snow,
    sigma_cells,
    weights_for_snow,
)


def test_sigma_cells_doubles_when_cell_size_halves():
    """sigma_mi is a physical smoothing radius; halving the grid's degree
    stride (finer cells) must double the equivalent sigma in cells, on
    both axes."""
    coarse = sigma_cells(sigma_mi=0.5, dlat_deg=0.02, dlon_deg=0.02, mean_lat_deg=39.0)
    fine = sigma_cells(sigma_mi=0.5, dlat_deg=0.01, dlon_deg=0.01, mean_lat_deg=39.0)
    assert fine[0] == pytest.approx(2 * coarse[0])
    assert fine[1] == pytest.approx(2 * coarse[1])


def test_sigma_cells_accounts_for_longitude_convergence():
    """At non-zero latitude a degree of longitude covers fewer miles than a
    degree of latitude, so for the same stride in degrees the lon-axis
    sigma in cells should be larger."""
    lat_sigma, lon_sigma = sigma_cells(sigma_mi=0.5, dlat_deg=0.01, dlon_deg=0.01, mean_lat_deg=45.0)
    assert lon_sigma > lat_sigma


def test_compute_probability_blends_both_factors_and_peak_normalizes():
    habitat = np.array([[1.0, 0.0], [0.5, 0.5]])
    security = np.array([[1.0, 1.0], [0.0, 1.0]])
    mask = np.array([[True, True], [True, True]])
    prob, used = compute_probability(habitat, security, mask, weights={"habitat": 0.5, "security": 0.5})
    assert set(used) == {"habitat", "security"}
    assert prob[0, 0] == pytest.approx(1.0)  # the max cell normalizes to itself


def test_compute_probability_masks_out_non_public_cells():
    habitat = np.array([[1.0, 1.0]])
    security = np.array([[1.0, 1.0]])
    mask = np.array([[True, False]])
    prob, used = compute_probability(habitat, security, mask)
    assert np.isnan(prob[0, 1])
    assert not np.isnan(prob[0, 0])


def test_compute_probability_renormalizes_when_security_is_missing():
    habitat = np.array([[1.0]])
    mask = np.array([[True]])
    prob, used = compute_probability(habitat, None, mask)
    assert used == ["habitat"]
    assert prob[0, 0] == pytest.approx(1.0)


def test_compute_probability_raises_if_no_factors_available():
    mask = np.array([[True]])
    with pytest.raises(ValueError):
        compute_probability(None, None, mask)


def test_default_weights_include_seasonal_range_and_sum_to_one():
    assert DEFAULT_WEIGHTS["seasonal_range"] == SEASONAL_RANGE_WEIGHT
    assert set(DEFAULT_WEIGHTS) == {"habitat", "security", "seasonal_range"}
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_compute_probability_blends_all_three_factors():
    habitat = np.array([[1.0, 0.0], [0.5, 0.5]])
    security = np.array([[1.0, 1.0], [0.0, 1.0]])
    seasonal_range = np.array([[1.0, 1.0], [1.0, 0.0]])
    mask = np.array([[True, True], [True, True]])
    prob, used = compute_probability(
        habitat, security, mask, seasonal_range=seasonal_range,
        weights={"habitat": 0.45, "security": 0.35, "seasonal_range": 0.20},
    )
    assert set(used) == {"habitat", "security", "seasonal_range"}
    assert prob[0, 0] == pytest.approx(1.0)  # the max cell normalizes to itself
    assert prob[1, 1] < prob[0, 0]  # weakest cell on all three factors scores lower


def test_compute_probability_renormalizes_when_seasonal_range_is_missing():
    """A failed deer_range fetch must degrade gracefully -- habitat and
    security's weights renormalize to sum to 1, and 'seasonal_range' must
    not appear in `used` (this is what the status panel's factor list
    reads to show which factors were actually used)."""
    habitat = np.array([[1.0]])
    security = np.array([[1.0]])
    mask = np.array([[True]])
    prob, used = compute_probability(habitat, security, mask, seasonal_range=None)
    assert used == ["habitat", "security"]
    assert "seasonal_range" not in used
    assert prob[0, 0] == pytest.approx(1.0)


def test_compute_probability_seasonal_range_alone_still_works():
    seasonal_range = np.array([[1.0]])
    mask = np.array([[True]])
    prob, used = compute_probability(None, None, mask, seasonal_range=seasonal_range)
    assert used == ["seasonal_range"]
    assert prob[0, 0] == pytest.approx(1.0)


def test_compute_probability_uses_physical_sigma_when_lats_lons_given():
    habitat = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    mask = np.ones((3, 3), dtype=bool)
    lats = np.array([39.0, 39.01, 39.02])
    lons = np.array([-105.0, -104.99, -104.98])
    prob, used = compute_probability(habitat, None, mask, lats=lats, lons=lons, sigma_mi=0.5)
    assert used == ["habitat"]
    assert prob[0, 0] == pytest.approx(1.0)  # peak still normalizes to itself
    assert prob[1, 1] > 0  # smoothing spread the peak to neighboring cells


def test_compute_probability_normalize_false_skips_self_normalization():
    """normalize=False must return the raw blended/smoothed/masked grid
    without dividing by its own max -- this is what lets a stack of
    multiple calls (snow levels, units) be normalized together afterward
    instead of each call independently maxing out at 1.0."""
    habitat = np.array([[0.4, 0.0], [0.2, 0.2]])
    mask = np.array([[True, True], [True, True]])
    raw, used = compute_probability(habitat, None, mask, normalize=False)
    normalized, _ = compute_probability(habitat, None, mask, normalize=True)
    assert used == ["habitat"]
    assert np.nanmax(raw) < 1.0  # not rescaled to 1.0
    # normalize=True is exactly raw divided by raw's own max -- confirms
    # normalize=False really is the pre-division grid, not something else.
    np.testing.assert_allclose(normalized, raw / np.nanmax(raw))


def test_normalize_stack_shows_genuine_intensity_difference_not_reset_to_one():
    """THE CRITICAL CORRECTNESS TEST for the snow slider: two raw grids
    (standing in for two snow levels) where one is genuinely, absolutely
    less suitable than the other overall. Naive per-array normalization
    (each divided by its own max) would map BOTH to a peak of 1.0, hiding
    that the second one is worse. normalize_stack must instead divide both
    by one shared global max, so the weaker level's peak renders dimmer,
    not renormalized back to full brightness."""
    strong_level = np.array([[0.9, 0.1], [0.3, 0.05]])   # peak 0.9
    weak_level = np.array([[0.3, 0.05], [0.1, 0.02]])    # peak 0.3 -- genuinely worse overall

    naive_strong = strong_level / np.nanmax(strong_level)
    naive_weak = weak_level / np.nanmax(weak_level)
    assert naive_strong[0, 0] == pytest.approx(1.0)
    assert naive_weak[0, 0] == pytest.approx(1.0)  # the trap: naive normalization hides the difference

    (norm_strong, norm_weak), global_max = normalize_stack([strong_level, weak_level])
    assert global_max == pytest.approx(0.9)
    assert norm_strong[0, 0] == pytest.approx(1.0)   # the true global peak still normalizes to itself
    assert norm_weak[0, 0] == pytest.approx(0.3 / 0.9)  # weak level's peak renders well below 1.0
    assert norm_weak[0, 0] < norm_strong[0, 0]           # dimmer, not reset to full brightness
    assert norm_weak[0, 0] == pytest.approx(1 / 3)


def test_normalize_stack_ignores_nan_cells_when_finding_max():
    a = np.array([[np.nan, 0.5]])
    b = np.array([[0.8, np.nan]])
    (norm_a, norm_b), global_max = normalize_stack([a, b])
    assert global_max == pytest.approx(0.8)
    assert np.isnan(norm_a[0, 0])
    assert norm_a[0, 1] == pytest.approx(0.5 / 0.8)
    assert norm_b[0, 0] == pytest.approx(1.0)


def test_normalize_stack_all_nan_or_zero_returns_unchanged_with_zero_max():
    arrays = [np.full((2, 2), np.nan), np.zeros((2, 2))]
    out, global_max = normalize_stack(arrays)
    assert global_max == 0.0
    assert out[1][0, 0] == 0.0


def test_seasonal_range_weight_for_snow_ramps_linearly_from_base_to_max():
    assert seasonal_range_weight_for_snow(0) == pytest.approx(SEASONAL_RANGE_WEIGHT)
    assert seasonal_range_weight_for_snow(40) == pytest.approx(SEASONAL_RANGE_WEIGHT_MAX)
    midpoint = SEASONAL_RANGE_WEIGHT + 0.5 * (SEASONAL_RANGE_WEIGHT_MAX - SEASONAL_RANGE_WEIGHT)
    assert seasonal_range_weight_for_snow(20) == pytest.approx(midpoint)


def test_seasonal_range_weight_for_snow_caps_beyond_max_depth():
    assert seasonal_range_weight_for_snow(100) == pytest.approx(SEASONAL_RANGE_WEIGHT_MAX)


def test_seasonal_range_weight_for_snow_disabled_stays_at_base_regardless_of_depth():
    assert seasonal_range_weight_for_snow(40, enabled=False) == pytest.approx(SEASONAL_RANGE_WEIGHT)
    assert seasonal_range_weight_for_snow(None) == pytest.approx(SEASONAL_RANGE_WEIGHT)


def test_weights_for_snow_sums_to_one_and_raises_seasonal_range_with_depth():
    w0 = weights_for_snow(0)
    w40 = weights_for_snow(40)
    assert sum(w0.values()) == pytest.approx(1.0)
    assert sum(w40.values()) == pytest.approx(1.0)
    assert w40["seasonal_range"] > w0["seasonal_range"]
    assert w0["seasonal_range"] == pytest.approx(SEASONAL_RANGE_WEIGHT)


def test_weights_for_snow_preserves_ratio_between_other_weights():
    """habitat and security must shrink proportionally as seasonal_range
    grows, keeping their ratio to each other constant."""
    base_ratio = DEFAULT_WEIGHTS["habitat"] / DEFAULT_WEIGHTS["security"]
    w40 = weights_for_snow(40)
    assert w40["habitat"] / w40["security"] == pytest.approx(base_ratio)


def test_weights_for_snow_disabled_matches_base_weights():
    w = weights_for_snow(40, enabled=False)
    assert w == pytest.approx(DEFAULT_WEIGHTS)
