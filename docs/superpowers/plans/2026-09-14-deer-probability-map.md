# Deer Probability Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone sister app to `elk-probability-map` that renders an interactive HTML map estimating where a mule deer buck is likely to be found in Colorado GMU 59 during 2nd rifle season, deployed as a static GitHub Pages site.

**Architecture:** Copy `elk-probability-map`'s generic infrastructure modules verbatim (they have no species dependency), rewrite the species-specific modules (habitat/land-cover scoring, seasonal-range data source, harvest data, map text) for mule deer, and reuse the exact same GitHub Actions Pages-deploy pattern.

**Tech Stack:** Python 3, requests, numpy, scipy, matplotlib, folium, Pillow, pytest. No API keys anywhere.

**Spec:** `docs/superpowers/specs/2026-09-14-deer-probability-map-design.md`

## Global Constraints

- Mule deer only, GMU 59 only, 2nd rifle season only, for this iteration (spec Non-goals).
- No shared code library with `elk-probability-map` — deliberate duplication of the generic modules, copied from the sibling repo at `~/repos/elk-probability-map` (spec Architecture).
- Harvest data is vendored into this repo from day one (`data/deer_harvest.csv` + `harvest.py`) — no `co-hunt-data` runtime dependency, ever (spec Data sources).
- Error handling: GMU-boundary fetch failure is fatal; roads, land cover, snow, and deer-range fetch failures each degrade gracefully (log + renormalize remaining weights) (spec Error handling).
- Testing: fixture-based, no live network calls in the automated test suite; the true network boundary is exercised via one manual end-to-end smoke test before shipping (spec Testing strategy).
- Every retuned constant (elevation band, aspect, land-cover scoring) is a documented best-effort domain assumption, not asserted biology — same "Honest scope" framing as the elk app (spec Known limitations).
- Source repo for all copies: `~/repos/elk-probability-map` (already public on GitHub as `bmills23/elk-probability-map`). Target repo: `~/repos/deer-probability-map` (git already initialized, spec already committed).

---

## File Structure

```
deer-probability-map/
├── deer_map.py              # CLI entry point (from elk_map.py)
├── net.py                   # copied verbatim
├── geo_utils.py              # copied verbatim
├── gmu_boundary.py           # copied verbatim
├── terrain.py                 # copied + retuned (elevation band, aspect)
├── roads.py                   # copied verbatim
├── snow.py                    # copied verbatim (comment reword only)
├── public_land.py             # copied verbatim
├── hunting_access.py          # copied verbatim
├── landcover.py                # copied + retuned (tree/shrub cover scoring)
├── deer_range.py               # new, adapted from elk_range.py
├── probability.py              # copied (comment reword only)
├── harvest.py                  # new, adapted from elk app's harvest.py
├── render.py                   # copied + ~20 targeted text/identifier edits
├── requirements.txt            # copied verbatim
├── README.md                   # new content, adapted from elk's
├── .gitignore                  # copied verbatim
├── .github/workflows/deploy.yml  # copied verbatim
├── data/
│   └── deer_harvest.csv        # vendored from co-hunt-data/data/harvest.csv
└── tests/
    ├── fixtures/
    │   ├── gmu_boundary_38_59.geojson   # copied verbatim (already has GMU 59)
    │   ├── terrarium_tile_11_427_785.png  # copied verbatim
    │   ├── overpass_roads_sample.json     # copied verbatim
    │   ├── padus_public_access_sample.json  # copied verbatim
    │   ├── snotel_stations_co.json         # copied verbatim
    │   ├── deer_range_59.geojson            # NEW real fixture, already fetched
    │   └── README.md                        # copied + one new entry added
    ├── test_geo_utils.py         # copied verbatim
    ├── test_gmu_boundary.py       # copied verbatim
    ├── test_public_land.py        # copied verbatim
    ├── test_hunting_access.py      # copied verbatim
    ├── test_roads.py                # copied verbatim
    ├── test_snow.py                  # copied verbatim
    ├── test_terrain.py                # copied + 4 functions edited
    ├── test_landcover.py               # copied + 1 function edited, 1 added
    ├── test_deer_range.py               # new, adapted from test_elk_range.py
    ├── test_probability.py               # copied (comment reword only)
    ├── test_harvest.py                     # new (no elk-app equivalent existed)
    ├── test_render.py                       # copied + ~15 targeted string edits
    └── test_deer_map.py                      # adapted from test_elk_map.py (module-name only)
```

---

## Task 1: Repo scaffolding

**Files:**
- Create: `requirements.txt`, `.gitignore`, `.github/workflows/deploy.yml`

**Interfaces:** None yet — this task produces no importable code, just the environment other tasks build on.

- [ ] **Step 1: Copy the dependency and CI files verbatim**

```bash
cd ~/repos/deer-probability-map
cp ~/repos/elk-probability-map/requirements.txt .
cp ~/repos/elk-probability-map/.gitignore .
mkdir -p .github/workflows
cp ~/repos/elk-probability-map/.github/workflows/deploy.yml .github/workflows/deploy.yml
```

- [ ] **Step 2: Update the CI build command for the renamed CLI**

The elk workflow runs `python3 elk_map.py --out dist/index.html`. Edit
`.github/workflows/deploy.yml`, changing that one line to:

```yaml
          python3 deer_map.py --out dist/index.html
```

- [ ] **Step 3: Create and populate a virtualenv**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Expected: installs cleanly, no errors (identical `requirements.txt` to the
already-working elk app).

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .gitignore .github/
git commit -m "Add scaffolding: requirements.txt, .gitignore, GitHub Pages deploy workflow"
```

---

## Task 2: Copy generic, unmodified modules

These six modules have no species dependency at all — they fetch/process
GMU boundaries, terrain elevation tiles' pixel math (not the habitat
scoring built on top, that's Task 4), roads, PAD-US land ownership, and
CPW's three-tier access classification. Copied byte-for-byte, verified by
running their existing (also byte-for-byte-copied) test suites, which
require no live network access (fixture-based).

**Files:**
- Create: `net.py`, `geo_utils.py`, `gmu_boundary.py`, `public_land.py`, `hunting_access.py`, `roads.py`
- Create: `tests/test_geo_utils.py`, `tests/test_gmu_boundary.py`, `tests/test_public_land.py`, `tests/test_hunting_access.py`, `tests/test_roads.py`
- Create: `tests/fixtures/gmu_boundary_38_59.geojson`, `tests/fixtures/overpass_roads_sample.json`, `tests/fixtures/padus_public_access_sample.json`, `tests/fixtures/README.md`

**Interfaces:**
- Produces: `geo_utils.polygon_mask(lats, lons, geometries)`, `geo_utils.clip_geometry_to_bbox`, `geo_utils.KM_PER_DEG`; `gmu_boundary.fetch_gmu_geometry(gmu)`, `gmu_boundary.unit_bbox(geometry)`; `net.SESSION`; `public_land.fetch_land_ownership_features`, `.clip_features_to_bbox`, `.filter_min_acres`, `.parse_open_access_polygons`, `.parse_restricted_access_polygons`; `hunting_access.ARCGIS_BASE`, `.access_geometries`, `.classify_access`, `.fetch_cpw_access_features`; `roads.fetch_road_segments`, `.distance_to_roads_km`, `.road_distance_score`.

- [ ] **Step 1: Copy the six modules and their tests**

```bash
cd ~/repos/deer-probability-map
SRC=~/repos/elk-probability-map
cp $SRC/net.py $SRC/geo_utils.py $SRC/gmu_boundary.py $SRC/public_land.py $SRC/hunting_access.py $SRC/roads.py .
mkdir -p tests/fixtures
cp $SRC/tests/test_geo_utils.py $SRC/tests/test_gmu_boundary.py $SRC/tests/test_public_land.py \
   $SRC/tests/test_hunting_access.py $SRC/tests/test_roads.py tests/
cp $SRC/tests/fixtures/gmu_boundary_38_59.geojson $SRC/tests/fixtures/overpass_roads_sample.json \
   $SRC/tests/fixtures/padus_public_access_sample.json $SRC/tests/fixtures/README.md tests/fixtures/
```

- [ ] **Step 2: Run the copied tests**

```bash
source .venv/bin/activate
pytest tests/test_geo_utils.py tests/test_gmu_boundary.py tests/test_public_land.py \
       tests/test_hunting_access.py tests/test_roads.py -v
```

Expected: all pass, unmodified (these tests never referenced elk/species
at all — they're testing generic geometry/access mechanics).

- [ ] **Step 3: Commit**

```bash
git add net.py geo_utils.py gmu_boundary.py public_land.py hunting_access.py roads.py tests/
git commit -m "Copy generic geometry/access/roads modules from elk-probability-map"
```

---

## Task 3: Copy snow.py

`snow.py`'s SNOTEL fetch and elevation-shift mechanics are unchanged for
deer (spec: "flagged as tunable" — not retuned in this iteration). Only
one comment references `elk_map` by name.

**Files:**
- Create: `snow.py`
- Create: `tests/test_snow.py`, `tests/fixtures/snotel_stations_co.json`

**Interfaces:**
- Produces: `snow.SIMULATED_SNOW_LEVELS_IN`, `snow.fetch_co_snotel_stations()`, `snow.nearest_station(lat, lon, stations)`, `snow.current_snow_depth_in(triplet)`, `snow.nearest_simulated_level_in(depth_in, levels=...)`, `snow.snow_elevation_shift_m(depth_in, max_shift_m=610.0, max_depth_in=40.0)`.

- [ ] **Step 1: Copy the module, test, and fixture**

```bash
cd ~/repos/deer-probability-map
SRC=~/repos/elk-probability-map
cp $SRC/snow.py .
cp $SRC/tests/test_snow.py tests/
cp $SRC/tests/fixtures/snotel_stations_co.json tests/fixtures/
```

- [ ] **Step 2: Reword the one elk-specific comment**

In `snow.py`, find:

```python
# see elk_map.process_unit and render.build_snow_level_cells. Picked to
```

Replace with:

```python
# see deer_map.process_unit and render.build_snow_level_cells. Picked to
```

- [ ] **Step 3: Run the tests**

```bash
pytest tests/test_snow.py -v
```

Expected: all pass (test_snow.py has no species-specific assertions).

- [ ] **Step 4: Commit**

```bash
git add snow.py tests/test_snow.py tests/fixtures/snotel_stations_co.json
git commit -m "Copy snow.py (SNOTEL fetch, elevation-shift mechanics unchanged for deer)"
```

---

## Task 4: terrain.py — copy and retune habitat scoring for mule deer

Elevation/slope/aspect *fetch and decode* mechanics are unchanged. Two
scoring defaults change: the elevation band shifts down from elk's
~9,500 ft (2895 m ± 610 m) to mule deer's lower mountain-shrub/browse
zone, ~8,000 ft (2440 m ± 460 m); and the aspect preference flips from
north-facing (elk's security-cover heuristic) to south-facing (mule
deer's solar-exposure/forage heuristic — south slopes melt out first and
retain browse longer as snow accumulates). Both are documented as tunable
domain assumptions, not settled biology, matching the elk app's own
caveat for its own constants.

**Files:**
- Create: `terrain.py`
- Modify: `tests/test_terrain.py` (4 of 13 test functions)

**Interfaces:**
- Consumes: `geo_utils.KM_PER_DEG`, `net.SESSION` (Task 2).
- Produces: `terrain.fetch_elevation_grid`, `.compute_slope_aspect`, `.elevation_band_score(elev_m, center_m=2440.0, half_width_m=460.0, shift_m=0.0)`, `.aspect_score(aspect_deg, favor_deg=180.0)`, `.slope_score`, `.habitat_components(elev_m, aspect_deg, snow_shift_m=0.0, favor_aspect_deg=180.0, slope_deg=None, cover_score=None, ...)`, `.habitat_score`. Same signatures as elk's `terrain.py`, only the default values of `center_m`, `half_width_m`, and `favor_aspect_deg` change.

- [ ] **Step 1: Copy the module and its test file**

```bash
cd ~/repos/deer-probability-map
SRC=~/repos/elk-probability-map
cp $SRC/terrain.py .
cp $SRC/tests/test_terrain.py tests/
```

- [ ] **Step 2: Run the copied tests to see which fail against the new constants (they haven't changed yet, so all should still pass at this point)**

```bash
source .venv/bin/activate
pytest tests/test_terrain.py -v
```

Expected: all 13 pass (nothing changed yet).

- [ ] **Step 3: Edit the 4 tests that depend on elk's specific elevation/aspect constants**

In `tests/test_terrain.py`, replace:

```python
def test_elevation_band_score_peaks_at_center_and_falls_off():
    elev = np.array([2895.0, 2895.0 + 610.0, 2895.0 + 1220.0])
    scores = elevation_band_score(elev)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0, abs=1e-6)
    assert scores[2] == 0.0
```

with:

```python
def test_elevation_band_score_peaks_at_center_and_falls_off():
    elev = np.array([2440.0, 2440.0 + 460.0, 2440.0 + 920.0])
    scores = elevation_band_score(elev)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0, abs=1e-6)
    assert scores[2] == 0.0
```

Replace:

```python
def test_elevation_band_score_shifts_down_with_snow():
    # A 610m downward shift moves the ideal elevation to center - shift.
    elev = np.array([2895.0 - 610.0])
    scores = elevation_band_score(elev, shift_m=610.0)
    assert scores[0] == pytest.approx(1.0)
```

with:

```python
def test_elevation_band_score_shifts_down_with_snow():
    # A 460m downward shift moves the ideal elevation to center - shift.
    elev = np.array([2440.0 - 460.0])
    scores = elevation_band_score(elev, shift_m=460.0)
    assert scores[0] == pytest.approx(1.0)
```

Replace:

```python
def test_aspect_score_favors_north_by_default():
    aspect = np.array([0.0, 90.0, 180.0])
    scores = aspect_score(aspect)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.5)
    assert scores[2] == pytest.approx(0.0)
```

with:

```python
def test_aspect_score_favors_south_by_default():
    aspect = np.array([0.0, 90.0, 180.0])
    scores = aspect_score(aspect)
    assert scores[0] == pytest.approx(0.0)
    assert scores[1] == pytest.approx(0.5)
    assert scores[2] == pytest.approx(1.0)
```

Replace:

```python
def test_habitat_score_blends_elevation_and_aspect():
    elev = np.array([2895.0])  # perfect elevation
    aspect = np.array([0.0])  # perfect (north) aspect
    score = habitat_score(elev, aspect, elev_weight=0.6, aspect_weight=0.4)
    assert score[0] == pytest.approx(1.0)
```

with:

```python
def test_habitat_score_blends_elevation_and_aspect():
    elev = np.array([2440.0])  # perfect elevation
    aspect = np.array([180.0])  # perfect (south) aspect
    score = habitat_score(elev, aspect, elev_weight=0.6, aspect_weight=0.4)
    assert score[0] == pytest.approx(1.0)
```

Replace:

```python
def test_habitat_components_renormalizes_when_cover_is_missing():
    """Graceful degradation: if a LANDFIRE fetch fails at run time and
    cover_score is None, the remaining sub-weights (elevation, aspect,
    slope) must renormalize to sum to 1, not just silently drop cover's
    share of the blend."""
    elev = np.array([2895.0])
    aspect = np.array([0.0])
    slope = np.array([15.0])
    blended, components, wnorm = habitat_components(elev, aspect, slope_deg=slope, cover_score=None)
    assert "cover" not in components
    assert set(wnorm) == {"elevation", "aspect", "slope"}
    assert pytest.approx(sum(wnorm.values())) == 1.0
    # Perfect elevation, perfect (north) aspect, and slope at its own peak
    # -- with all three sub-factors at 1.0, the renormalized blend must
    # also be 1.0 regardless of how the three weights were split.
    assert blended[0] == pytest.approx(1.0)
```

with:

```python
def test_habitat_components_renormalizes_when_cover_is_missing():
    """Graceful degradation: if a LANDFIRE fetch fails at run time and
    cover_score is None, the remaining sub-weights (elevation, aspect,
    slope) must renormalize to sum to 1, not just silently drop cover's
    share of the blend."""
    elev = np.array([2440.0])
    aspect = np.array([180.0])
    slope = np.array([15.0])
    blended, components, wnorm = habitat_components(elev, aspect, slope_deg=slope, cover_score=None)
    assert "cover" not in components
    assert set(wnorm) == {"elevation", "aspect", "slope"}
    assert pytest.approx(sum(wnorm.values())) == 1.0
    # Perfect elevation, perfect (south) aspect, and slope at its own peak
    # -- with all three sub-factors at 1.0, the renormalized blend must
    # also be 1.0 regardless of how the three weights were split.
    assert blended[0] == pytest.approx(1.0)
```

Leave `test_habitat_components_matches_habitat_score_when_slope_and_cover_given`
and `test_habitat_components_renormalizes_when_slope_is_also_missing`
unchanged — they check internal self-consistency and dict-key structure,
not the specific peak/favor values, so they pass regardless of which
constants terrain.py uses.

- [ ] **Step 4: Run the edited tests to confirm they now FAIL against terrain.py's still-elk-tuned defaults**

```bash
pytest tests/test_terrain.py -v
```

Expected: the 4 edited tests FAIL (terrain.py still has `center_m=2895.0`,
`favor_deg=0.0`); the other 9 still PASS.

- [ ] **Step 5: Retune terrain.py's module docstring and defaults**

Replace the module docstring:

```python
"""Elevation (AWS public Terrarium tiles), slope/aspect, and the elk
habitat-suitability factor: an elevation-band preference (peaks ~8,500-
10,500 ft, shifted down by current snow depth) blended with an aspect
preference (default: north-facing, a security-cover heuristic), a slope
preference (moderate ground favored, cliff-steep avoided), and a land-cover
suitability score (landcover.py, LANDFIRE EVC) -- see README for why every
one of these is tunable, not asserted biology."""
```

with:

```python
"""Elevation (AWS public Terrarium tiles), slope/aspect, and the mule
deer habitat-suitability factor: an elevation-band preference (peaks
~6,500-9,500 ft, shifted down by current snow depth) blended with an
aspect preference (default: south-facing, a solar-exposure/forage
heuristic -- south slopes melt out first and retain browse longer as
snow accumulates), a slope preference (moderate ground favored,
cliff-steep avoided), and a land-cover suitability score (landcover.py,
LANDFIRE EVC) -- see README for why every one of these is tunable, not
asserted biology."""
```

Replace:

```python
def elevation_band_score(elev_m, center_m=2895.0, half_width_m=610.0, shift_m=0.0):
```

with:

```python
def elevation_band_score(elev_m, center_m=2440.0, half_width_m=460.0, shift_m=0.0):
```

Replace:

```python
def aspect_score(aspect_deg, favor_deg=0.0):
```

with:

```python
def aspect_score(aspect_deg, favor_deg=180.0):
```

Replace:

```python
# Slope preference: elk favor moderate ground (enough relief for
# forest/opening edges and thermal cover without exhausting energy) and
```

with:

```python
# Slope preference: mule deer favor moderate ground (enough relief for
# forest/opening edges and thermal cover without exhausting energy) and
```

And in `habitat_components`/`habitat_score`'s shared signature, update the
default keyword argument (both functions declare it):

```python
def habitat_components(elev_m, aspect_deg, snow_shift_m=0.0, favor_aspect_deg=0.0,
```

with:

```python
def habitat_components(elev_m, aspect_deg, snow_shift_m=0.0, favor_aspect_deg=180.0,
```

(and the identical parameter in `habitat_score`'s signature just below it).

- [ ] **Step 6: Run the tests again to confirm they now pass**

```bash
pytest tests/test_terrain.py -v
```

Expected: all 13 pass.

- [ ] **Step 7: Commit**

```bash
git add terrain.py tests/test_terrain.py
git commit -m "Retune terrain.py habitat scoring for mule deer (lower elevation band, south-facing aspect)"
```

---

## Task 5: landcover.py — copy and retune cover scoring for mule deer

The LANDFIRE EVC fetch/decode mechanics are unchanged. Two scoring
constants change: `TREE_SECURITY_FULL_PCT` rises from 50% to 65% (mule
deer rely less on big timber than elk, so it takes denser canopy before
tree cover counts as full security value), and `SHRUB_FORAGE_FULL_PCT`
falls from 40% to 25% (mule deer are primarily browsers — even moderate
mountain-shrub canopy is prime habitat, so shrub cover saturates faster).

**Files:**
- Create: `landcover.py`
- Modify: `tests/test_landcover.py` (1 function edited, 1 added)

**Interfaces:**
- Produces: `landcover.fetch_landcover_grid`, `.decode_evc_tiff`, `.cover_suitability_score(evc_values)`, `.fetch_cover_score(lats, lons)`, `.known_evc_coverage_frac`, constants `TREE_SECURITY_FULL_PCT=65.0`, `SHRUB_FORAGE_FULL_PCT=25.0`, `HERB_MODERATE_CAP`, `NONHABITAT_SCORE`, `SPARSE_VEG_SCORE`, `UNKNOWN_SCORE` (last four unchanged).

- [ ] **Step 1: Copy the module and its test file**

```bash
cd ~/repos/deer-probability-map
SRC=~/repos/elk-probability-map
cp $SRC/landcover.py .
cp $SRC/tests/test_landcover.py tests/
```

- [ ] **Step 2: Write the new failing test for mule deer's shrub-forage retune**

In `tests/test_landcover.py`, add this test right after
`test_cover_suitability_score_dense_timber_scores_high`:

```python
def test_cover_suitability_score_moderate_shrub_cover_scores_high_for_deer():
    # 225 = shrub cover 25%, at SHRUB_FORAGE_FULL_PCT -- mule deer are
    # primarily browsers, so even moderate (not dense) shrub cover should
    # already read as prime habitat, unlike elk's higher timber threshold.
    v = np.full((5, 5), 225)
    scores = cover_suitability_score(v)
    assert scores[2, 2] == pytest.approx(1.0)
```

- [ ] **Step 3: Update the existing dense-timber test's value and comment to stay accurate under the new (higher) tree threshold**

Replace:

```python
def test_cover_suitability_score_dense_timber_scores_high():
    # 160 = tree cover 60%, at/above TREE_SECURITY_FULL_PCT -- deep in a
    # uniform stand (no edge effect from neighbors), should score high.
    v = np.full((5, 5), 160)
    scores = cover_suitability_score(v)
    assert scores[2, 2] > 0.8
```

with:

```python
def test_cover_suitability_score_dense_timber_scores_high():
    # 170 = tree cover 70%, at/above TREE_SECURITY_FULL_PCT -- deep in a
    # uniform stand (no edge effect from neighbors), should score high.
    v = np.full((5, 5), 170)
    scores = cover_suitability_score(v)
    assert scores[2, 2] > 0.8
```

- [ ] **Step 4: Run the tests to confirm the new/edited ones fail against landcover.py's still-elk-tuned constants**

```bash
source .venv/bin/activate
pytest tests/test_landcover.py -v
```

Expected: `test_cover_suitability_score_moderate_shrub_cover_scores_high_for_deer`
FAILS (225/40 = 0.625, not 1.0 under elk's `SHRUB_FORAGE_FULL_PCT=40.0`);
`test_cover_suitability_score_dense_timber_scores_high` still PASSES
(170 tree cover still saturates under elk's 50% threshold too — this one
is about to be re-verified against the new 65% threshold in the next step).

- [ ] **Step 5: Retune landcover.py's constants and reword its elk-specific comments**

Replace:

```python
HUNTING HEURISTIC, NOT SETTLED BIOLOGY: every constant below is a tunable
guess about what an elk prefers, not a sourced wildlife-biology parameter
-- same spirit as terrain.py's aspect-preference note. Tune freely if your
own scouting says otherwise."""
```

with:

```python
HUNTING HEURISTIC, NOT SETTLED BIOLOGY: every constant below is a tunable
guess about what a mule deer prefers, not a sourced wildlife-biology
parameter -- same spirit as terrain.py's aspect-preference note. Tune
freely if your own scouting says otherwise."""
```

Replace:

```python
# --- Cover -> elk score tunables ---
```

with:

```python
# --- Cover -> mule deer score tunables ---
```

Replace:

```python
TREE_SECURITY_FULL_PCT = 50.0    # tree canopy % at which the security-cover score saturates at 1.0
SHRUB_FORAGE_FULL_PCT = 40.0     # shrub canopy % at which the forage score saturates at 1.0
```

with:

```python
TREE_SECURITY_FULL_PCT = 65.0    # tree canopy % at which the security-cover score saturates at 1.0 --
                                  # higher than elk's 50%: mule deer rely less on big timber
SHRUB_FORAGE_FULL_PCT = 25.0     # shrub canopy % at which the forage score saturates at 1.0 --
                                  # lower than elk's 40%: mule deer are primarily browsers, so even
                                  # moderate mountain-shrub cover is prime habitat
```

Replace:

```python
    the transition zone elk favor for feeding near cover."""
```

with:

```python
    the transition zone mule deer favor for feeding near cover."""
```

Replace:

```python
def cover_suitability_score(evc_values):
    """EVC raster values -> elk cover-suitability score, 0..1. See module
    docstring for the verified value bands and the mapping rationale."""
```

with:

```python
def cover_suitability_score(evc_values):
    """EVC raster values -> mule deer cover-suitability score, 0..1. See
    module docstring for the verified value bands and the mapping
    rationale."""
```

Replace:

```python
    "habitat inputs" line, elk_map.process_unit's habitat_used) as if
```

with:

```python
    "habitat inputs" line, deer_map.process_unit's habitat_used) as if
```

- [ ] **Step 6: Run the tests again to confirm all pass**

```bash
pytest tests/test_landcover.py -v
```

Expected: all pass, including the new shrub test and the re-verified
dense-timber test (170/65 = 1.0, clipped).

- [ ] **Step 7: Reword the remaining elk references in test_landcover.py's docstrings (no assertions affected)**

Replace `elk_map.process_unit's existing try/except` (in
`test_fetch_cover_score_raises_when_raster_is_effectively_all_nodata`'s
docstring) with `deer_map.process_unit's existing try/except`.

Replace `elk_map.process_unit is responsible for` (in
`test_fetch_cover_score_propagates_http_errors`'s docstring) with
`deer_map.process_unit is responsible for`.

- [ ] **Step 8: Commit**

```bash
git add landcover.py tests/test_landcover.py
git commit -m "Retune landcover.py cover scoring for mule deer (higher tree threshold, lower shrub threshold)"
```

---

## Task 6: deer_range.py — CPW mule deer seasonal range (new module)

Adapted from `elk_range.py`: same CPW ArcGIS host and service
(`CPWHPHTerrestrialData/FeatureServer`), different layer IDs (29/30/31
instead of 20/21/22/23), and **no Production Area layer at all** for mule
deer in this service — unlike elk, there's nothing to fetch-but-exclude.
Per-range-type scores and `NEUTRAL_BASELINE` are unchanged (spec:
"carried over unchanged in relative ordering"). A real fixture
(`tests/fixtures/deer_range_59.geojson`, 17 features: 1 migration
corridor, 3 severe winter range, 13 winter concentration) has already
been fetched live from the CPW service for GMU 59's bbox and committed to
this repo.

**Files:**
- Create: `deer_range.py`
- Create: `tests/test_deer_range.py`

**Interfaces:**
- Consumes: `geo_utils.clip_geometry_to_bbox`, `geo_utils.polygon_mask` (Task 2); `hunting_access.ARCGIS_BASE` (Task 2); `net.SESSION` (Task 2).
- Produces: `deer_range.RANGE_TYPE_URLS` (3 keys: `migration_corridor`, `severe_winter_range`, `winter_concentration`), `deer_range.RANGE_TYPE_LABELS`, `deer_range.NEUTRAL_BASELINE = 0.5`, `deer_range.RANGE_TYPE_SCORES` (`winter_concentration: 1.0`, `severe_winter_range: 0.85`, `migration_corridor: 0.7`), `deer_range.fetch_deer_range_features(bbox)`, `.range_geometries(features, range_type)`, `.seasonal_range_score(lats, lons, features, baseline=NEUTRAL_BASELINE)`, `.clip_deer_range_features_to_bbox(features, bbox)`, `.DEFAULT_MAX_ALLOWABLE_OFFSET`, `.DEFAULT_GEOMETRY_PRECISION`.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_deer_range.py`:

```python
import numpy as np
import pytest

import deer_range
from deer_range import (
    NEUTRAL_BASELINE,
    RANGE_TYPE_SCORES,
    clip_deer_range_features_to_bbox,
    fetch_deer_range_features,
    range_geometries,
    seasonal_range_score,
)

BBOX = (38.3, 39.05, -105.2, -104.6)  # GMU 59's bbox


def _feature(coords, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [coords]}}


WINTER_CONC_PARCEL = _feature(
    [[-105.05, 38.60], [-105.05, 38.65], [-105.00, 38.65], [-105.00, 38.60], [-105.05, 38.60]],
    Activity_C="Winter Concentration",
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_deer_range_features_sends_where_1_equals_1_and_bbox_geometry(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeResponse({"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": False})

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = fetch_deer_range_features(BBOX)

    # Three layers fetched (no Production Area layer exists for mule deer
    # in this service), each contributing the one fixture feature.
    assert len(features) == 3
    for url, params in calls:
        assert params["where"] == "1=1"
        assert params["geometry"] == "-105.2,38.3,-104.6,39.05"
        assert params["geometryType"] == "esriGeometryEnvelope"
        assert params["outFields"] == "*"
        assert params["f"] == "geojson"
        assert params["maxAllowableOffset"] == deer_range.DEFAULT_MAX_ALLOWABLE_OFFSET
        assert params["geometryPrecision"] == deer_range.DEFAULT_GEOMETRY_PRECISION
    urls = sorted(url for url, _ in calls)
    assert urls == sorted(deer_range.RANGE_TYPE_URLS.values())


def test_fetch_deer_range_features_tags_each_range_type(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": False})

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = fetch_deer_range_features(BBOX)
    tags = sorted(f["properties"]["_range_type"] for f in features)
    assert tags == sorted(deer_range.RANGE_TYPE_URLS.keys())


def test_fetch_deer_range_features_handles_a_layer_with_no_features(monkeypatch):
    """A unit with no delineated Migration Corridor (or any one layer) at
    all is expected, not an error."""

    def fake_get(url, params=None, timeout=None):
        if url == deer_range.RANGE_TYPE_URLS["migration_corridor"]:
            return _FakeResponse({"features": []})
        return _FakeResponse({"features": [WINTER_CONC_PARCEL]})

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = fetch_deer_range_features(BBOX)
    assert len(features) == 2
    assert "migration_corridor" not in {f["properties"]["_range_type"] for f in features}


def test_fetch_paged_pages_past_the_transfer_limit(monkeypatch):
    page1 = {"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": True}
    page2 = {"features": [WINTER_CONC_PARCEL], "exceededTransferLimit": False}
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["resultOffset"])
        return _FakeResponse(page1 if params["resultOffset"] == 0 else page2)

    monkeypatch.setattr(deer_range.SESSION, "get", fake_get)

    features = deer_range._fetch_paged(deer_range.RANGE_TYPE_URLS["winter_concentration"], BBOX, page_size=1)

    assert len(features) == 2
    assert calls == [0, 1]


def test_range_geometries_filters_to_one_type():
    features = [
        {"type": "Feature", "properties": {"_range_type": "winter_concentration"}, "geometry": {"a": 1}},
        {"type": "Feature", "properties": {"_range_type": "severe_winter_range"}, "geometry": {"b": 2}},
    ]
    assert range_geometries(features, "winter_concentration") == [{"a": 1}]


# --- seasonal_range_score ---

LATS = np.array([0.5, 1.5])
LONS = np.array([0.5, 1.5])


def test_seasonal_range_score_uses_neutral_baseline_outside_all_polygons():
    """Core requirement: absence of a polygon must NOT score as 0 (these
    layers are incomplete HPH subsets), so a cell outside everything gets
    the named neutral baseline, not zero."""
    score = seasonal_range_score(LATS, LONS, [])
    assert np.all(score == NEUTRAL_BASELINE)
    assert NEUTRAL_BASELINE > 0


def test_seasonal_range_score_scores_winter_concentration_at_full_confidence():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    features = [{"type": "Feature", "properties": {"_range_type": "winter_concentration"}, "geometry": poly}]
    score = seasonal_range_score(LATS, LONS, features)
    assert score[0, 0] == pytest.approx(RANGE_TYPE_SCORES["winter_concentration"])
    assert score[1, 1] == pytest.approx(NEUTRAL_BASELINE)  # outside the polygon


def test_seasonal_range_score_overlapping_types_take_the_max_not_the_sum():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    features = [
        {"type": "Feature", "properties": {"_range_type": "migration_corridor"}, "geometry": poly},
        {"type": "Feature", "properties": {"_range_type": "winter_concentration"}, "geometry": poly},
    ]
    score = seasonal_range_score(LATS, LONS, features)
    assert score[0, 0] == pytest.approx(RANGE_TYPE_SCORES["winter_concentration"])
    assert score[0, 0] <= 1.0


def test_seasonal_range_score_severe_winter_range_between_baseline_and_concentration():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    features = [{"type": "Feature", "properties": {"_range_type": "severe_winter_range"}, "geometry": poly}]
    score = seasonal_range_score(LATS, LONS, features)
    assert NEUTRAL_BASELINE < score[0, 0] < RANGE_TYPE_SCORES["winter_concentration"]


def test_clip_deer_range_features_to_bbox_trims_and_drops():
    big = _feature([[-106.0, 37.0], [-106.0, 40.0], [-104.0, 40.0], [-104.0, 37.0], [-106.0, 37.0]],
                    _range_type="winter_concentration")
    far_away = _feature([[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]],
                         _range_type="winter_concentration")
    clipped = clip_deer_range_features_to_bbox([big, far_away], BBOX)
    assert len(clipped) == 1
    lons = [c[0] for c in clipped[0]["geometry"]["coordinates"][0]]
    lats = [c[1] for c in clipped[0]["geometry"]["coordinates"][0]]
    assert min(lons) == pytest.approx(-105.2)
    assert max(lons) == pytest.approx(-104.6)
    assert min(lats) == pytest.approx(38.3)
    assert max(lats) == pytest.approx(39.05)
```

Note: unlike `test_elk_range.py`, there is **no**
`test_seasonal_range_score_production_area_never_contributes` equivalent
— mule deer has no Production Area layer in this service, so there is
nothing to test never contributing.

- [ ] **Step 2: Run the test to verify it fails (module doesn't exist yet)**

```bash
pytest tests/test_deer_range.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'deer_range'`.

- [ ] **Step 3: Create deer_range.py**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_deer_range.py -v
```

Expected: all 10 pass.

- [ ] **Step 5: Verify the module against the real committed fixture (sanity check, not part of the automated suite)**

```bash
python3 -c "
import json
import deer_range

with open('tests/fixtures/deer_range_59.geojson') as f:
    fc = json.load(f)

by_type = {}
for f in fc['features']:
    by_type.setdefault(f['properties']['_range_type'], 0)
    by_type[f['properties']['_range_type']] += 1
print(by_type)
assert by_type == {'migration_corridor': 1, 'severe_winter_range': 3, 'winter_concentration': 13}
print('OK')
"
```

Expected: `{'migration_corridor': 1, 'severe_winter_range': 3, 'winter_concentration': 13}` then `OK`.

- [ ] **Step 6: Commit**

```bash
git add deer_range.py tests/test_deer_range.py
git commit -m "Add deer_range.py: CPW mule deer seasonal range (layers 29-31)"
```

---

## Task 7: probability.py — copy, comment reword only

The weighted-blend framework, `DEFAULT_WEIGHTS`
(`{"habitat": 0.45, "security": 0.35, "seasonal_range": 0.20}`), and the
snow-driven weight-coupling constants are **unchanged** — spec keeps
these as the deer app's starting point too. Only comments referencing
`elk_range.py`/elk by name are reworded.

**Files:**
- Create: `probability.py`
- Create: `tests/test_probability.py`

**Interfaces:**
- Produces: `probability.DEFAULT_WEIGHTS`, `.SEASONAL_RANGE_WEIGHT`, `.compute_probability(...)`, `.normalize_stack(raw_probs)`, `.weights_for_snow(depth_in, base_weights=None, enabled=True)`, `.seasonal_range_weight_for_snow(...)`, `.sigma_cells(...)`. Identical signatures and values to elk's `probability.py`.

- [ ] **Step 1: Copy the module and its test file**

```bash
cd ~/repos/deer-probability-map
SRC=~/repos/elk-probability-map
cp $SRC/probability.py .
cp $SRC/tests/test_probability.py tests/
```

- [ ] **Step 2: Reword the elk-specific comments**

In `probability.py`, replace:

```python
weight, since snow pushes elk toward the CPW-delineated winter range
(elk_range.py) that factor is built from. A caller that wants that
```

with:

```python
weight, since snow pushes deer toward the CPW-delineated winter range
(deer_range.py) that factor is built from. A caller that wants that
```

Replace:

```python
# Seasonal range is deliberately the smallest of the three -- elk_range.py's
# CPW polygons are High Priority Habitat *subsets* (no Elk Overall Range or
# Summer Range layer exists in that service), so a cell outside every
# polygon is scored at a neutral baseline, not zero (see elk_range.
```

with:

```python
# Seasonal range is deliberately the smallest of the three -- deer_range.py's
# CPW polygons are High Priority Habitat *subsets* (no Mule Deer Overall
# Range or Summer Range layer exists in that service), so a cell outside
# every polygon is scored at a neutral baseline, not zero (see deer_range.
```

Replace:

```python
# Deeper snow pushes elk toward CPW-delineated winter range (elk_range.py,
```

with:

```python
# Deeper snow pushes deer toward CPW-delineated winter range (deer_range.py,
```

In `tests/test_probability.py`, replace:

```python
    """A failed elk_range fetch must degrade gracefully -- habitat and
```

with:

```python
    """A failed deer_range fetch must degrade gracefully -- habitat and
```

- [ ] **Step 3: Run the tests**

```bash
source .venv/bin/activate
pytest tests/test_probability.py -v
```

Expected: all pass, unmodified behavior.

- [ ] **Step 4: Commit**

```bash
git add probability.py tests/test_probability.py
git commit -m "Copy probability.py (weights unchanged for deer, comments reworded)"
```

---

## Task 8: harvest.py + data/deer_harvest.csv (new — no elk-app test to copy)

Vendors GMU harvest stats the same way the elk app's `harvest.py` does
(added there specifically to remove a `co-hunt-data` runtime dependency
in CI) — this app starts with that pattern from day one instead of
introducing the dependency and removing it later. No test for this
existed in `elk-probability-map` (a gap there, out of scope to fix in
that repo), so this is a genuine from-scratch TDD task.

**Files:**
- Create: `harvest.py`, `data/deer_harvest.csv`
- Create: `tests/test_harvest.py`

**Interfaces:**
- Produces: `harvest.get_deer_harvest_stats(gmu, season="rifle_2nd", year=None)` returning `{"bucks": int, "does": int, "fawns": int, "total_harvest": int, "total_hunters": int, "pct_success": int, "rec_days": int}` or `None`.

- [ ] **Step 1: Vendor the harvest data**

```bash
mkdir -p ~/repos/deer-probability-map/data
cp ~/repos/co-hunt-data/data/harvest.csv ~/repos/deer-probability-map/data/deer_harvest.csv
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_harvest.py`:

```python
from harvest import get_deer_harvest_stats


def test_get_deer_harvest_stats_returns_most_recent_year_for_gmu_59_2nd_rifle():
    stats = get_deer_harvest_stats(59)
    assert stats is not None
    assert stats["bucks"] == 19
    assert stats["does"] == 0
    assert stats["fawns"] == 0
    assert stats["total_harvest"] == 19
    assert stats["total_hunters"] == 32
    assert stats["pct_success"] == 60
    assert stats["rec_days"] == 109


def test_get_deer_harvest_stats_specific_year():
    stats = get_deer_harvest_stats(59, year=2021)
    assert stats is not None
    assert stats["bucks"] == 9
    assert stats["total_hunters"] == 40
    assert stats["pct_success"] == 23
    assert stats["rec_days"] == 174


def test_get_deer_harvest_stats_returns_none_for_unknown_gmu():
    assert get_deer_harvest_stats(99999) is None


def test_get_deer_harvest_stats_respects_season_argument():
    archery = get_deer_harvest_stats(59, season="archery")
    rifle = get_deer_harvest_stats(59, season="rifle_2nd")
    assert archery != rifle
```

These expected values are the real rows from
`~/repos/co-hunt-data/data/harvest.csv` (confirmed directly, not the
sqlite snapshot):

```
2023,59,rifle_2nd,19,0,0,19,32,60,109
2021,59,rifle_2nd,9,0,0,9,40,23,174
```

2021 (not 2022) is used for the specific-year test deliberately: GMU 59's
2022 `rifle_2nd` section has two rows in the source data (an apparent
early/late split, `21,0,0,21,50,43,233` and `0,8,0,8,11,73,14`), and
`get_deer_harvest_stats`'s tie-break on duplicate years (same `max()`
pattern as elk-probability-map's `get_elk_harvest_stats`) depends on CSV
row order — a fragile thing to assert a specific value against. 2021 has
only one row for GMU 59 `rifle_2nd`, so it's unambiguous.

- [ ] **Step 3: Verify the vendored CSV has the same rows (sanity check on the `cp` from Step 1)**

```bash
grep '^2023,59,rifle_2nd\|^2021,59,rifle_2nd' ~/repos/deer-probability-map/data/deer_harvest.csv
```

Expected: exactly the two lines shown above, byte-identical to the
source (a straight `cp`, so this should never differ — this step just
catches a wrong source path or a corrupted copy).

- [ ] **Step 4: Run the test to verify it fails (module doesn't exist yet)**

```bash
cd ~/repos/deer-probability-map && source .venv/bin/activate
pytest tests/test_harvest.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harvest'`.

- [ ] **Step 5: Create harvest.py**

```python
"""GMU mule deer harvest stats, vendored from co-hunt-data's harvest.csv
(see data/deer_harvest.csv) so this repo has no dependency on the sibling
co-hunt-data project -- required for it to build standalone in CI/GitHub
Actions, which can't see a local, un-pushed sibling directory. Same
vendoring pattern as elk-probability-map's harvest.py."""

import csv
import os

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "deer_harvest.csv")


def get_deer_harvest_stats(gmu, season="rifle_2nd", year=None):
    """Look up mule deer harvest stats for a GMU/season.

    year defaults to the most recent year available for that GMU/section.
    Returns None if no matching row exists. Same shape and semantics as
    co-hunt-data's harvest table (bucks/does/fawns), and the same lookup
    pattern as elk-probability-map's get_elk_harvest_stats (bulls/cows/calves).
    """
    rows = []
    with open(DATA_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if int(row["unit"]) == gmu and row["section"] == season:
                if year is None or int(row["year"]) == year:
                    rows.append(row)
    if not rows:
        return None

    row = max(rows, key=lambda r: int(r["year"]))
    return {
        "bucks": int(row["bucks"]),
        "does": int(row["does"]),
        "fawns": int(row["fawns"]),
        "total_harvest": int(row["total_harvest"]),
        "total_hunters": int(row["total_hunters"]),
        "pct_success": int(row["pct_success"]),
        "rec_days": int(row["rec_days"]),
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/test_harvest.py -v
```

Expected: all 4 pass.

- [ ] **Step 7: Commit**

```bash
git add harvest.py data/deer_harvest.csv tests/test_harvest.py
git commit -m "Vendor GMU deer harvest data (data/deer_harvest.csv) and add harvest.py lookup"
```

---

## Task 9: render.py — copy and adapt for deer

The PNG-overlay rendering, folium map assembly, mobile CSS, and the bulk
of the inspect/snow-slider JS templates are generic plumbing with no
species dependency and are copied verbatim. ~20 places reference elk by
name (module import, function/constant names, and user-facing text) and
need updating; this task lists every one.

**Files:**
- Create: `render.py`
- Create: `tests/test_render.py`

**Interfaces:**
- Consumes: `deer_range.RANGE_TYPE_LABELS` (Task 6, replaces `elk_range.RANGE_TYPE_LABELS`).
- Produces: same public surface as elk's `render.py` (`build_map`, `build_snow_level_cells`, `render_prob_png`, `build_inspection_cells`), with these renames: `_elk_range_feature_collection`→`_deer_range_feature_collection`, `_elk_range_style_function`→`_deer_range_style_function`, `_add_elk_range_layer`→`_add_deer_range_layer`, `_elk_range_legend_html`→`_deer_range_legend_html`, `ELK_RANGE_STYLES`→`DEER_RANGE_STYLES`, `ELK_RANGE_ORDER`→`DEER_RANGE_ORDER`, `ELK_RANGE_OUTLINE_COLOR`→`DEER_RANGE_OUTLINE_COLOR`, `ELK_RANGE_FILL_OPACITY`→`DEER_RANGE_FILL_OPACITY`, `ELK_RANGE_LINE_WEIGHT`→`DEER_RANGE_LINE_WEIGHT`. `build_map`'s `units_data` dicts now carry `deer_range_features` instead of `elk_range_features`.

- [ ] **Step 1: Copy the module and its test file**

```bash
cd ~/repos/deer-probability-map
SRC=~/repos/elk-probability-map
cp $SRC/render.py .
cp $SRC/tests/test_render.py tests/
```

- [ ] **Step 2: Run the copied tests (should all pass unmodified before any edits)**

```bash
source .venv/bin/activate
pytest tests/test_render.py -v
```

Expected: all pass (nothing changed yet).

- [ ] **Step 3: Edit render.py — import and constant/function renames**

Replace:

```python
from elk_range import RANGE_TYPE_LABELS
```

with:

```python
from deer_range import RANGE_TYPE_LABELS
```

Replace the whole "Elk seasonal range" display-layer block (comment +
styles + order + functions), from:

```python
# 'Elk seasonal range' display layer (elk_range.py): CPW's own elk
# migration corridor / severe winter range / winter concentration area /
# production area polygons, distinct from the land ownership layer above
# both in color palette (purple family, not the greens/blues/oranges
# LAND_OWNERSHIP_STYLES uses) and in what they mean -- these are CPW
# biologists' delineations of where elk actually are, not ownership.
# Production Area is included here for display even though
# elk_range.seasonal_range_score never scores it (spring calving, not
# relevant to a November hunt) -- its label says so directly in the
# tooltip.
ELK_RANGE_STYLES = {
    "winter_concentration": {"label": RANGE_TYPE_LABELS["winter_concentration"], "color": "#4a148c"},
    "severe_winter_range": {"label": RANGE_TYPE_LABELS["severe_winter_range"], "color": "#7b1fa2"},
    "migration_corridor": {"label": RANGE_TYPE_LABELS["migration_corridor"], "color": "#ab47bc"},
    "production_area": {"label": RANGE_TYPE_LABELS["production_area"], "color": "#e1bee7"},
}
ELK_RANGE_ORDER = ["winter_concentration", "severe_winter_range", "migration_corridor", "production_area"]


def _elk_range_feature_collection(features):
    out = []
    for f in features:
        props = f.get("properties") or {}
        range_type = props.get("_range_type")
        label = ELK_RANGE_STYLES.get(range_type, {}).get("label", "Elk range (unspecified)")
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


ELK_RANGE_OUTLINE_COLOR = "#1a0033"  # near-black purple, deliberately distinct from
                                     # both the fill palette above and land ownership's
                                     # magenta "cpw_access" dashed outline, so an elk-range
                                     # polygon's boundary stays legible when it overlaps
                                     # either the heatmap or a land-ownership parcel.


# Legibility fix (visual regression from the previous stage): this layer
# used to fill at 0.4 opacity, which at the scale a single range polygon
# usually covers (often most of a unit) washed out both the basemap and
# the probability heatmap underneath it -- see elkrange_inspect.png. Elk
# seasonal range is now a light outline with only a faint fill (0.08) so
# it reads as "this area is delineated" without competing with the
# heatmap for attention, and it defaults OFF (show=False) given how much
# area it typically covers -- a user who wants it can turn it on in the
# layer control.
ELK_RANGE_FILL_OPACITY = 0.08
ELK_RANGE_LINE_WEIGHT = 1.2


def _elk_range_style_function(feature):
    range_type = feature.get("properties", {}).get("_range_type")
    color = ELK_RANGE_STYLES.get(range_type, {}).get("color", "#9c27b0")
    return {
        "fillColor": color, "fillOpacity": ELK_RANGE_FILL_OPACITY,
        "color": ELK_RANGE_OUTLINE_COLOR, "weight": ELK_RANGE_LINE_WEIGHT, "opacity": 0.7,
        "dashArray": "3,3",
    }


def _add_elk_range_layer(m, features):
    """'Elk seasonal range' toggle: CPW's own elk seasonal-range polygons
    (elk_range.py), separate from the 'Land ownership' layer above -- this
    shows CPW biologists' delineation of where elk actually are, not who
    owns the ground. Off by default (show=False) -- see the legibility
    note on _elk_range_style_function above; a user can turn it on in the
    layer control."""
    import folium

    if not features:
        return
    fc = _elk_range_feature_collection(features)
    if not fc["features"]:
        return
    folium.GeoJson(
        fc,
        name="Elk seasonal range",
        style_function=_elk_range_style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=["RangeType", "Activity"],
            aliases=["Range type:", "Activity:"],
            sticky=True,
        ),
        show=False,
    ).add_to(m)
```

with:

```python
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
# in the layer control.
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
```

Replace:

```python
    seasonal_range_score (elk_range.seasonal_range_score) is appended last,
    after the habitat sub-factors, so their fixed column indices
    (HABITAT_SUBFACTOR_KEYS) don't shift; None if seasonal_range wasn't
    given (e.g. a failed elk_range fetch this run).
```

with:

```python
    seasonal_range_score (deer_range.seasonal_range_score) is appended last,
    after the habitat sub-factors, so their fixed column indices
    (HABITAT_SUBFACTOR_KEYS) don't shift; None if seasonal_range wasn't
    given (e.g. a failed deer_range fetch this run).
```

Replace:

```python
    snow slider (see snow.SIMULATED_SNOW_LEVELS_IN and elk_map.process_unit).
```

with:

```python
    snow slider (see snow.SIMULATED_SNOW_LEVELS_IN and deer_map.process_unit).
```

- [ ] **Step 4: Edit render.py — the two JS legend-label dicts and two popup titles**

Both `INSPECT_JS_TMPL` and `SNOW_JS_TMPL` contain this line (appears
twice, identical) — replace **each occurrence**:

```python
  var LBL = {"habitat":"Habitat suitability","security":"Distance from roads",
    "seasonal_range":"Elk seasonal range (CPW)"};
```

with:

```python
  var LBL = {"habitat":"Habitat suitability","security":"Distance from roads",
    "seasonal_range":"Deer seasonal range (CPW)"};
```

Replace (in `INSPECT_JS_TMPL`):

```python
      +'<b>Elk probability: '+best[2]+'%</b>'
```

with:

```python
      +'<b>Deer probability: '+best[2]+'%</b>'
```

Replace (in `SNOW_JS_TMPL`):

```python
      + '<b>Elk probability: '+probPct+'%</b>'
```

with:

```python
      + '<b>Deer probability: '+probPct+'%</b>'
```

- [ ] **Step 5: Edit render.py — `_elk_range_legend_html` → `_deer_range_legend_html`**

Replace:

```python
def _elk_range_legend_html():
    """'Elk seasonal range' legend: a second, independent collapsible
    sub-section (epm-legend2-*), same pattern as _legend_html above but
    for elk_range.py's polygons rather than land ownership."""

    def _swatch(key):
        style = ELK_RANGE_STYLES[key]
        return f"""<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;
          background:{style['color']};opacity:.75;flex:none;"></span>
          <span>{style['label']}</span>
        </div>"""

    swatches = "".join(_swatch(key) for key in ELK_RANGE_ORDER)
    return f"""
    <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;">
      <div id="epm-legend2-hd" onclick="epmLegend2Toggle()"
           style="display:flex;justify-content:space-between;align-items:center;
           gap:8px;cursor:pointer;">
        <span style="font-size:11px;font-weight:600;">Elk seasonal range</span>
        <button id="epm-legend2-toggle" onclick="event.stopPropagation();epmLegend2Toggle()"
          style="border:none;background:#eef2f8;border-radius:6px;padding:1px 8px;
          cursor:pointer;font-size:13px;line-height:1.2;color:#333;">&#8211;</button>
      </div>
      <div id="epm-legend2-body" style="margin-top:3px;">
        {swatches}
        <div style="font-size:9.5px;color:#888;margin-top:4px;">CPW's own delineation of
        where elk actually are (`elk_range.py`), a stronger signal than anything the
        habitat factor infers from terrain alone. These are High Priority Habitat
        <i>subsets</i>, not a complete elk-range product: there is no Elk Overall Range
        or Elk Summer Range layer, so ground with no polygon here is not evidence elk
        are absent, it may simply be un-delineated. Elk Production Area (spring calving)
        is shown for reference only and never affects the probability score in this
        November-season map. Off by default and drawn as a light outline with a faint
        fill (these polygons often cover most of a unit, and a heavy fill washed out
        the basemap and heatmap underneath it) -- turn it on in the layer control.</div>
      </div>
    </div>"""
```

with:

```python
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
```

- [ ] **Step 6: Edit render.py — the snow-slider weight-sentence text**

Replace:

```python
    explains, in plain text, where the initial position came from -- the
    live SNOTEL reading(s) for the units actually built this run.

    seasonal_range_gmus/total_units: which of this run's units actually
    have the elk seasonal range factor in their blend (probability.
    weights_for_snow only has a weight to raise if seasonal_range is
    actually one of the factors -- when a unit's CPW fetch failed and
    that factor was dropped, probability.compute_probability renormalizes
    to a level-invariant split instead, and asserting a weight shift for
    that unit would be false; see README's elk-seasonal-range section)."""
    anchor_depth = levels_in[anchor_idx]
    seasonal_range_gmus = seasonal_range_gmus or []
    if not seasonal_range_gmus:
        weight_sentence = (
            " The elk seasonal range factor is unavailable this run (its CPW fetch "
            "failed) for every unit built, so simulated snow depth here only shifts "
            "the elevation-band sweet spot -- it does not change any factor's weight."
        )
    elif len(seasonal_range_gmus) == total_units:
        weight_sentence = (
            " Deeper simulated snow also raises the elk seasonal range factor's weight in the "
            "blend (an uncalibrated heuristic, see the README), with the other weights scaled "
            "down to keep the total at 100%."
        )
    else:
        gmu_list = ", ".join(f"GMU {g}" for g in seasonal_range_gmus)
        weight_sentence = (
            f" Deeper simulated snow also raises the elk seasonal range factor's weight in the "
            f"blend (an uncalibrated heuristic, see the README) for {gmu_list}, where that factor "
            f"is available this run, with the other weights scaled down to keep the total at 100%; "
            f"its CPW fetch failed for the rest, so snow only shifts their elevation-band sweet spot."
        )
```

with:

```python
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
```

- [ ] **Step 7: Edit render.py — panel title, harvest line, season label, and build_map's remaining renames**

Replace:

```python
        harvest_html = (
            f"Bulls: {h['bulls']} &middot; Hunters: {h['total_hunters']} &middot; "
            f"Success: {h['pct_success']}%"
            if h else "No 2023 harvest data for this GMU/season."
        )
```

with:

```python
        harvest_html = (
            f"Bucks: {h['bucks']} &middot; Hunters: {h['total_hunters']} &middot; "
            f"Success: {h['pct_success']}%"
            if h else "No 2023 harvest data for this GMU/season."
        )
```

Replace:

```python
          <span style="font-size:11px;color:#666;">3rd rifle 2023: {harvest_html}</span><br>
```

with:

```python
          <span style="font-size:11px;color:#666;">2nd rifle 2023: {harvest_html}</span><br>
```

Replace:

```python
        <span style="font-weight:700;font-size:14.5px;">Bull Elk Probability</span>
```

with:

```python
        <span style="font-weight:700;font-size:14.5px;">Mule Deer Probability</span>
```

Replace:

```python
        {_elk_range_legend_html()}
```

with:

```python
        {_deer_range_legend_html()}
```

Replace:

```python
    """units_data: list of dicts, one per unit:
    {gmu, prob_uri, prob_bounds, cells, half_lat, half_lon, harvest, used,
     station_name, station_dist_km, land_features, cpw_features,
     elk_range_features, gmu_geometry}.
    land_features, cpw_features, elk_range_features, and gmu_geometry are
    optional (a unit missing any of them just contributes nothing to that
    layer).

    snow (optional; see elk_map.process_unit/main): enables the simulated
    snow depth slider. A dict {levels_in, weights_by_level, anchor_idx,
    anchor_note} (levels_in: snow.SIMULATED_SNOW_LEVELS_IN; weights_by_level:
    one probability.weights_for_snow() dict per level, shared by every
    unit, since the simulated depth is one slider for the whole map, not
    per unit; anchor_idx/anchor_note: elk_map.snow_anchor's initial slider
    position and the plain-text explanation of how it was chosen from the
```

with:

```python
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
```

Replace:

```python
        overlay = ImageOverlay(image=u["prob_uri"], bounds=u["prob_bounds"], opacity=0.7,
                                name=f"GMU {u['gmu']} elk probability", show=True)
```

with:

```python
        overlay = ImageOverlay(image=u["prob_uri"], bounds=u["prob_bounds"], opacity=0.7,
                                name=f"GMU {u['gmu']} deer probability", show=True)
```

Replace:

```python
    all_elk_range_features = [f for u in units_data for f in (u.get("elk_range_features") or [])]
    _add_land_ownership_layer(m, all_land_features, all_cpw_features)
    _add_elk_range_layer(m, all_elk_range_features)
```

with:

```python
    all_deer_range_features = [f for u in units_data for f in (u.get("deer_range_features") or [])]
    _add_land_ownership_layer(m, all_land_features, all_cpw_features)
    _add_deer_range_layer(m, all_deer_range_features)
```

- [ ] **Step 8: Run the tests — expect failures matching the renames just made**

```bash
pytest tests/test_render.py -v
```

Expected: several FAIL (the test file still imports `_elk_range_style_function`
and asserts elk-specific strings). Note exactly which tests fail before
proceeding to Step 9 — they should be the ones touching seasonal-range
display, the panel title, and the harvest line.

- [ ] **Step 9: Edit tests/test_render.py to match**

Replace the import:

```python
    _elk_range_style_function,
```

with:

```python
    _deer_range_style_function,
```

Replace every occurrence of `"elk_range_features"` (dict key, appears at
minimum in `test_build_map_includes_elk_seasonal_range_layer_and_legend_and_popup_factor`
and `test_elk_range_style_is_light_not_a_heavy_wash`'s setup, and in
`test_add_elk_range_layer_noop_when_no_features`) with `"deer_range_features"`.

Rename the test functions themselves:
- `test_build_map_includes_elk_seasonal_range_layer_and_legend_and_popup_factor` → `test_build_map_includes_deer_seasonal_range_layer_and_legend_and_popup_factor`
- `test_elk_range_style_is_light_not_a_heavy_wash` → `test_deer_range_style_is_light_not_a_heavy_wash`
- `test_add_elk_range_layer_noop_when_no_features` → `test_add_deer_range_layer_noop_when_no_features`

Within those functions, replace the call `_elk_range_style_function(...)`
with `_deer_range_style_function(...)`, and any local variable named
`elk_range_features` with `deer_range_features`.

Replace assertion strings:
- `assert "Elk seasonal range" in html` → `assert "Deer seasonal range" in html`
- `assert "Elk Winter Concentration Area" in html` → `assert "Mule Deer Winter Concentration Area" in html`
- `assert "Elk seasonal range (CPW)" in html` → `assert "Deer seasonal range (CPW)" in html`
- `assert "raises the elk seasonal range factor's weight" in used_html` → `assert "raises the deer seasonal range factor's weight" in used_html`
- `assert "raises the elk seasonal range factor's weight" not in unused_html` → `assert "raises the deer seasonal range factor's weight" not in unused_html`
- `assert "raises the elk seasonal range factor's weight" in html_with` → `assert "raises the deer seasonal range factor's weight" in html_with`
- `assert "raises the elk seasonal range factor's weight" not in html_without` → `assert "raises the deer seasonal range factor's weight" not in html_without`

Replace the two remaining docstring/comment mentions:
- `"""seasonal_range_score (elk_range.py) must be appended after the four` → `"""seasonal_range_score (deer_range.py) must be appended after the three`
- `a network failure can also reach it (elk_map.fetch_snow_conditions` → `a network failure can also reach it (deer_map.fetch_snow_conditions`

- [ ] **Step 10: Run the tests again to verify they pass**

```bash
pytest tests/test_render.py -v
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add render.py tests/test_render.py
git commit -m "Adapt render.py for mule deer (seasonal-range layer, panel/legend/popup text)"
```

---

## Task 10: deer_map.py — CLI entry point

Adapted from `elk_map.py`: single default unit (59), `deer_range`/`harvest`
imports, 2nd rifle season, updated print/description text. The
per-simulated-snow-level loop, `build_snow_stack`, `snow_anchor`, and
`combined_access_mask` mechanics are all unchanged — they were already
GMU-count-agnostic (they loop over however many units are passed).

**Files:**
- Create: `deer_map.py`
- Create: `tests/test_deer_map.py`

**Interfaces:**
- Consumes: everything from Tasks 2-9 (`geo_utils.polygon_mask`, `gmu_boundary.fetch_gmu_geometry`/`.unit_bbox`, `hunting_access.*`, `probability.*`, `public_land.*`, `render.build_map`/`.build_snow_level_cells`/`.render_prob_png`, `roads.*`, `snow.*`, `terrain.*`, `deer_range.*`, `harvest.get_deer_harvest_stats`).
- Produces: `deer_map.process_unit(gmu, cell_mi=..., inspect_mi=...)`, `.snow_anchor(units_depth_in, levels=...)`, `.build_snow_stack(units_data, inspect_mi=...)`, `.combined_access_mask`, `.fetch_security_score`, `.fetch_snow_conditions`, `.main(argv=None)`. Same names/signatures as `elk_map.py`.

- [ ] **Step 1: Copy the test file first (drives the module's required interface)**

```bash
cd ~/repos/deer-probability-map
cp ~/repos/elk-probability-map/tests/test_elk_map.py tests/test_deer_map.py
```

- [ ] **Step 2: Edit tests/test_deer_map.py — module-name substitution only**

Replace:

```python
import elk_map
from elk_map import (
```

with:

```python
import deer_map
from deer_map import (
```

Replace every `monkeypatch.setattr(elk_map, ...)` call (there are four:
in `test_fetch_security_score_degrades_to_none_when_roads_fetch_fails`,
`test_fetch_security_score_returns_scores_on_success`,
`test_fetch_snow_conditions_degrades_to_zero_shift_when_snotel_fetch_fails`,
`test_fetch_snow_conditions_returns_reading_on_success`) with
`monkeypatch.setattr(deer_map, ...)`.

Replace the two remaining docstring mentions:
- `already does: security omitted (None), so compute_probability drops it from\n    the blend and renormalizes the remaining weights, and the failure is\n    printed so it isn't silent."""` — no change needed here, this text doesn't name `elk_map`.
- `"""THE CRITICAL CORRECTNESS TEST, at the elk_map integration level` → `"""THE CRITICAL CORRECTNESS TEST, at the deer_map integration level`

Leave every other line unchanged — including the GMU numbers 38/59 used
inside `test_snow_anchor_averages_and_discloses_differing_readings` and
`test_build_snow_stack_renders_genuinely_worse_unit_dimmer_not_renormalized`.
Those are arbitrary example unit numbers exercising `snow_anchor` and
`build_snow_stack`'s general multi-unit averaging/normalization behavior
(functions that don't know or care which real GMUs they're called with)
— not a claim about which units this app actually targets.

- [ ] **Step 3: Run the test to verify it fails (module doesn't exist yet)**

```bash
source .venv/bin/activate
pytest tests/test_deer_map.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'deer_map'`.

- [ ] **Step 4: Create deer_map.py**

```python
#!/usr/bin/env python3
"""CLI: build the mule deer probability map for GMU 59, 2nd rifle season.
See README.md for usage and docs/superpowers/specs/ for the design this
implements. Sister app to elk-probability-map."""

import argparse
import math

import numpy as np

import deer_range
import landcover
from geo_utils import polygon_mask
from gmu_boundary import fetch_gmu_geometry, unit_bbox
from harvest import get_deer_harvest_stats
from hunting_access import access_geometries, classify_access, fetch_cpw_access_features
from probability import DEFAULT_WEIGHTS, compute_probability, normalize_stack, weights_for_snow
from public_land import (
    clip_features_to_bbox,
    fetch_land_ownership_features,
    filter_min_acres,
    parse_open_access_polygons,
    parse_restricted_access_polygons,
)
from render import build_map, build_snow_level_cells, render_prob_png
from roads import distance_to_roads_km, fetch_road_segments, road_distance_score
from snow import (
    SIMULATED_SNOW_LEVELS_IN,
    current_snow_depth_in,
    fetch_co_snotel_stations,
    nearest_simulated_level_in,
    nearest_station,
    snow_elevation_shift_m,
)
from terrain import compute_slope_aspect, fetch_elevation_grid, habitat_components

DEFAULT_UNITS = [59]
DEFAULT_CELL_MI = 0.25
DEFAULT_INSPECT_MI = 0.5
MI_PER_DEG_LAT = 69.0


def combined_access_mask(lats, lons, open_polygons, gmu_geometry):
    """Public-land mask ANDed with the GMU boundary itself.

    Without this, open-access polygons that fall inside the 2 mi buffered
    analysis bbox but outside the actual GMU boundary would be shaded as
    if they were huntable land in this unit. Kept as a small, independently
    tested utility; process_unit now gets the same GMU-boundary
    intersection (for all three access tiers, not just "open") from
    hunting_access.classify_access."""
    return polygon_mask(lats, lons, open_polygons) & polygon_mask(lats, lons, [gmu_geometry])


def cell_mi_to_strides(cell_mi, mean_lat_deg):
    """Degree strides for a square-ish ground cell of cell_mi miles."""
    lat_stride = cell_mi / MI_PER_DEG_LAT
    lon_stride = cell_mi / (MI_PER_DEG_LAT * math.cos(math.radians(mean_lat_deg)))
    return lat_stride, lon_stride


def fetch_security_score(bbox, lats, lons):
    """Roads (Overpass) -> the security-cover distance score, degrading to
    None -- security omitted, compute_probability's remaining weights
    renormalize -- if the fetch fails, same graceful-degradation pattern
    already used below for LANDFIRE land cover and CPW deer seasonal range."""
    try:
        road_segments = fetch_road_segments(bbox)
        road_dist_km = distance_to_roads_km(lats, lons, road_segments)
        return road_distance_score(road_dist_km) if road_dist_km is not None else None
    except Exception as exc:
        print(f"  roads fetch failed ({exc}); security will be omitted, remaining weights renormalize")
        return None


def fetch_snow_conditions(center_lat, center_lon):
    """Nearest CO SNOTEL station + its current depth, degrading to
    (None, None, None, note) -- no station, no live reading, snow.
    snow_elevation_shift_m(None) already falls back to a zero elevation-
    band shift -- if the stations list or depth lookup fetch fails, same
    graceful-degradation pattern already used below for LANDFIRE land
    cover and CPW deer seasonal range.

    Returns (station, station_dist_km, depth_in, snow_error): snow_error
    is None on success (including the ordinary, expected case of no
    reading), or a short human-readable reason the fetch failed."""
    try:
        stations = fetch_co_snotel_stations()
        station, station_dist_km = nearest_station(center_lat, center_lon, stations)
        depth_in = current_snow_depth_in(station["triplet"]) if station else None
        return station, station_dist_km, depth_in, None
    except Exception as exc:
        print(f"  SNOTEL fetch failed ({exc}); snow depth unavailable, elevation-band shift assumed 0 in")
        return None, None, None, str(exc)


def process_unit(gmu, cell_mi=DEFAULT_CELL_MI, inspect_mi=DEFAULT_INSPECT_MI):
    geometry = fetch_gmu_geometry(gmu)
    if geometry is None:
        raise RuntimeError(f"No CPW boundary found for GMU {gmu}")
    bbox = unit_bbox(geometry)
    lat_min, lat_max, lon_min, lon_max = bbox
    mean_lat = (lat_min + lat_max) / 2
    lat_stride_deg, lon_stride_deg = cell_mi_to_strides(cell_mi, mean_lat)

    print(f"  fetching elevation... (target cell {cell_mi} mi)")
    elev, lats, lons = fetch_elevation_grid(bbox, lat_stride_deg=lat_stride_deg, lon_stride_deg=lon_stride_deg)
    slope, aspect = compute_slope_aspect(elev, lats, lons)

    print("  fetching nearest SNOTEL station...")
    center_lat, center_lon = (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
    station, station_dist_km, depth_in, snow_error = fetch_snow_conditions(center_lat, center_lon)

    print("  fetching land cover (LANDFIRE EVC)...")
    try:
        cover_score = landcover.fetch_cover_score(lats, lons)
    except Exception as exc:
        print(f"  land cover fetch failed ({exc}); habitat will renormalize without it")
        cover_score = None

    # Habitat is recomputed once per simulated snow level (elevation, roads,
    # land cover, and range polygons are each fetched exactly once above --
    # only the cheap numpy recompute below happens per level): snow only
    # ever enters habitat_components through snow_shift_m, which only moves
    # elevation_band_score's effective center, so aspect/slope/cover come
    # back byte-identical at every level and only "elevation" (and the
    # blended habitat score built from it) actually varies. See
    # deer_map.build_snow_stack for what happens with these per-level grids
    # once every unit in the run has been processed (the global
    # normalization step -- see probability.normalize_stack).
    level_habitat = []
    level_habitat_parts = []
    for depth in SIMULATED_SNOW_LEVELS_IN:
        shift = snow_elevation_shift_m(depth)
        hab, hab_parts, _ = habitat_components(
            elev, aspect, snow_shift_m=shift, slope_deg=slope, cover_score=cover_score
        )
        level_habitat.append(hab)
        level_habitat_parts.append(hab_parts)
    habitat_used = list(level_habitat_parts[0].keys())

    print("  fetching roads...")
    security = fetch_security_score(bbox, lats, lons)

    print("  fetching public land boundaries...")
    land_features = fetch_land_ownership_features(bbox)
    oa_polygons = parse_open_access_polygons({"features": land_features})
    ra_polygons = parse_restricted_access_polygons({"features": land_features})

    print("  fetching CPW hunting-access sources (managed properties, "
          "walk-in access, state trust land public access program)...")
    cpw_features = fetch_cpw_access_features(bbox)
    cpw_polygons = access_geometries(cpw_features)

    print("  fetching CPW mule deer seasonal range polygons (migration corridor, "
          "severe winter range, winter concentration area)...")
    try:
        deer_range_features = deer_range.fetch_deer_range_features(bbox)
        seasonal_range = deer_range.seasonal_range_score(lats, lons, deer_range_features)
    except Exception as exc:
        print(f"  deer seasonal range fetch failed ({exc}); seasonal range will be "
              "omitted, remaining weights renormalize")
        deer_range_features = []
        seasonal_range = None

    range_type_counts = {
        rt: len(deer_range.range_geometries(deer_range_features, rt)) for rt in deer_range.RANGE_TYPE_URLS
    }
    print(f"  deer seasonal range polygons in bbox: {range_type_counts}")

    open_mask, conditional_mask, closed_mask = classify_access(
        lats, lons, oa_polygons, ra_polygons, cpw_polygons, geometry
    )
    public_mask = open_mask

    old_oa_only_mask = combined_access_mask(lats, lons, oa_polygons, geometry)
    cell_acres = cell_mi * cell_mi * 640.0  # approx acres/sq mi; cells are square-ish (cell_mi_to_strides)
    newly_open_acres = float(np.sum(open_mask & ~old_oa_only_mask)) * cell_acres
    conditional_acres = float(np.sum(conditional_mask)) * cell_acres
    print(f"  access tiers vs. old OA-only mask: open +{newly_open_acres:,.0f} ac "
          f"from CPW sources, conditional (shown, not shaded) ~{conditional_acres:,.0f} ac")

    display_features = filter_min_acres(clip_features_to_bbox(land_features, bbox))
    cpw_display_features = clip_features_to_bbox(cpw_features, bbox)
    deer_range_display_features = deer_range.clip_deer_range_features_to_bbox(deer_range_features, bbox)
    print(f"  land ownership: {len(land_features)} PAD-US features fetched, "
          f"{len(display_features)} kept for the map display layer; "
          f"{len(cpw_features)} CPW/SLB access features")

    level_raw_prob = []
    used = []
    for depth, hab in zip(SIMULATED_SNOW_LEVELS_IN, level_habitat):
        weights_lvl = weights_for_snow(depth, base_weights=DEFAULT_WEIGHTS)
        raw_prob, used = compute_probability(
            hab, security, public_mask, seasonal_range=seasonal_range,
            weights=weights_lvl, lats=lats, lons=lons, normalize=False,
        )
        level_raw_prob.append(raw_prob)

    if seasonal_range is not None and np.any(public_mask):
        in_scoring_range = seasonal_range > deer_range.NEUTRAL_BASELINE
        coverage_frac = float(np.sum(public_mask & in_scoring_range)) / float(np.sum(public_mask))
        print(f"  fraction of huntable (open-tier) cells inside a scoring deer "
              f"seasonal range polygon (winter concentration/severe winter range/"
              f"migration corridor): {coverage_frac:.1%}")

    harvest = get_deer_harvest_stats(gmu, season="rifle_2nd")

    return {
        "gmu": gmu,
        "lats": lats,
        "lons": lons,
        "level_raw_prob": level_raw_prob,
        "level_habitat": level_habitat,
        "level_habitat_parts": level_habitat_parts,
        "security": security,
        "seasonal_range": seasonal_range,
        "public_mask": public_mask,
        "depth_in": depth_in,
        "snow_error": snow_error,
        "harvest": harvest,
        "used": used,
        "habitat_used": habitat_used,
        "station_name": station["name"] if station else None,
        "station_dist_km": station_dist_km,
        "land_features": display_features,
        "cpw_features": cpw_display_features,
        "deer_range_features": deer_range_display_features,
        "gmu_geometry": geometry,
    }


def snow_anchor(units_depth_in, levels=SIMULATED_SNOW_LEVELS_IN):
    """The simulated snow slider's initial position, anchored to the
    live SNOTEL reading(s) of the unit(s) actually built this run.

    units_depth_in: [(gmu, depth_in_or_None), ...], one entry per unit.
    Returns (anchor_depth_in, anchor_level_in, anchor_idx, note)."""
    readings = [(gmu, d) for gmu, d in units_depth_in if d is not None]
    if not readings:
        anchor_depth = 0.0
        note = ("No live SNOTEL reading was available for any unit built this run; "
                "the simulated snow slider starts at 0 in.")
    else:
        anchor_depth = sum(d for _, d in readings) / len(readings)
        if len({round(d, 1) for _, d in readings}) > 1:
            detail = "; ".join(f"GMU {gmu}: {d:.0f} in" for gmu, d in readings)
            note = (f"Units report different live readings ({detail}); the simulated "
                    f"snow slider starts at their average ({anchor_depth:.0f} in), "
                    "snapped to the nearest precomputed level.")
        else:
            note = (f"The simulated snow slider starts at the live SNOTEL reading "
                    f"({anchor_depth:.0f} in), snapped to the nearest precomputed level.")
    anchor_level = nearest_simulated_level_in(anchor_depth, levels=levels)
    anchor_idx = levels.index(anchor_level)
    return anchor_depth, anchor_level, anchor_idx, note


def build_snow_stack(units_data, inspect_mi=DEFAULT_INSPECT_MI):
    """Turn each unit's per-level RAW probability grids (process_unit's
    level_raw_prob, normalize=False) into the slider's actual payload.
    See probability.normalize_stack's docstring for why the whole stack
    shares one global maximum instead of each level normalizing to its
    own peak."""
    all_raw = [raw for u in units_data for raw in u["level_raw_prob"]]
    normalized_all, global_max = normalize_stack(all_raw)

    n_levels = len(SIMULATED_SNOW_LEVELS_IN)
    weights_by_level = [weights_for_snow(d, base_weights=DEFAULT_WEIGHTS) for d in SIMULATED_SNOW_LEVELS_IN]
    anchor_depth, anchor_level, anchor_idx, anchor_note = snow_anchor(
        [(u["gmu"], u.get("depth_in")) for u in units_data]
    )

    offset = 0
    for u in units_data:
        level_probs = normalized_all[offset:offset + n_levels]
        offset += n_levels

        snow_prob_uris = []
        prob_bounds = None
        for prob in level_probs:
            uri, prob_bounds = render_prob_png(prob, u["lats"], u["lons"])
            snow_prob_uris.append(uri)
        u["prob_uri"] = snow_prob_uris[anchor_idx]
        u["prob_bounds"] = prob_bounds
        u["snow_prob_uris"] = snow_prob_uris

        elevation_levels = [parts["elevation"] for parts in u["level_habitat_parts"]]
        static_parts = u["level_habitat_parts"][0]
        snow_cells, snow_half_lat, snow_half_lon = build_snow_level_cells(
            u["lats"], u["lons"], level_probs, u["level_habitat"], elevation_levels,
            u["public_mask"], security=u["security"], seasonal_range=u["seasonal_range"],
            aspect=static_parts.get("aspect"), slope=static_parts.get("slope"),
            cover=static_parts.get("cover"), inspect_mi=inspect_mi,
        )
        u["snow_cells"] = snow_cells
        u["snow_half_lat"] = snow_half_lat
        u["snow_half_lon"] = snow_half_lon

    snow_info = {
        "levels_in": SIMULATED_SNOW_LEVELS_IN,
        "weights_by_level": weights_by_level,
        "anchor_idx": anchor_idx,
        "anchor_depth_in": anchor_depth,
        "anchor_level_in": anchor_level,
        "anchor_note": anchor_note,
        "global_max": global_max,
    }
    return units_data, snow_info


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mule deer probability map for 2nd rifle season")
    parser.add_argument("--units", default="59", help="Comma-separated GMU numbers")
    parser.add_argument("--out", default="deer_map.html")
    parser.add_argument(
        "--cell-mi", type=float, default=DEFAULT_CELL_MI,
        help=f"Analysis grid cell size, in miles, square-ish on the ground (default: {DEFAULT_CELL_MI})",
    )
    parser.add_argument(
        "--inspect-mi", type=float, default=DEFAULT_INSPECT_MI,
        help=f"Target spacing, in miles, between click-to-inspect cells (default: {DEFAULT_INSPECT_MI})",
    )
    args = parser.parse_args(argv)

    units = [int(u) for u in args.units.split(",")]

    units_data = []
    for gmu in units:
        print(f"Processing GMU {gmu}...")
        units_data.append(process_unit(gmu, cell_mi=args.cell_mi, inspect_mi=args.inspect_mi))

    print(f"Building simulated snow stack ({SIMULATED_SNOW_LEVELS_IN} in, globally normalized "
          "across every level and unit)...")
    units_data, snow_info = build_snow_stack(units_data, inspect_mi=args.inspect_mi)
    print(f"  global normalization max (raw blended score before any level's/unit's scaling): "
          f"{snow_info['global_max']:.4f}")
    print(f"  {snow_info['anchor_note']}")

    build_map(units_data=units_data, weights=DEFAULT_WEIGHTS, out_path=args.out, snow=snow_info)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_deer_map.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add deer_map.py tests/test_deer_map.py
git commit -m "Add deer_map.py CLI entry point (GMU 59, 2nd rifle season)"
```

---

## Task 11: README.md

**Files:**
- Create: `README.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Write README.md**

```markdown
# Deer Probability Map

Estimate where a mule deer buck is likely to be in Colorado GMU 59
during 2nd rifle season, from free public data, rendered as an
interactive map. Sister app to
[`elk-probability-map`](../elk-probability-map), reusing its
architecture and rendering approach. GMU harvest stats are vendored from
[`co-hunt-data`](../co-hunt-data) into `data/deer_harvest.csv` (see
`harvest.py`).

## Honest scope

This is a **habitat/access-suitability index, not a calibrated
probability** of encountering a deer, and it models aggregate habitat,
not individual animals -- no public live deer-telemetry feed exists.
Every tunable constant (elevation band, aspect preference, land-cover
scoring) is a best-effort domain assumption about mule deer, not
sourced wildlife biology -- tune freely if your own scouting says
otherwise.

## Usage

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 deer_map.py                    # GMU 59, current conditions
open deer_map.html
```

### Options

```
--units 59                 comma-separated GMU numbers (default: 59)
--out deer_map.html         output HTML path
--cell-mi 0.25               analysis grid cell size, in miles, square-ish on the ground (default: 0.25)
--inspect-mi 0.5              target spacing, in miles, between click-to-inspect cells (default: 0.5)
```

## The probability model

Three weighted, renormalizable factors, plus a hard legal-access mask
(same model as elk-probability-map's current shipped version):

- **Habitat suitability (0.45)** -- elevation-band fit (peaks ~6,500-
  9,500 ft, shifted down by current snow depth), aspect (south-facing
  favored -- a solar-exposure/forage heuristic, since south slopes melt
  out first and retain browse longer as snow accumulates), slope
  (moderate ground favored), and land cover (LANDFIRE EVC, mountain-shrub
  cover favored over dense timber -- mule deer are primarily browsers).
- **Security cover / distance from roads (0.35)** -- same mechanism as
  elk-probability-map.
- **CPW mule deer seasonal range (0.20)** -- migration corridor, severe
  winter range, and winter concentration area polygons
  (`CPWHPHTerrestrialData/FeatureServer`, layers 29-31, `deer_range.py`).
  Unlike elk, there is no Production Area layer for mule deer in this
  service. A cell outside every polygon is scored at a neutral baseline
  (0.5), not zero -- these are High Priority Habitat *subsets*, not a
  complete range product, so absence of a polygon is not evidence deer
  are absent.
- **Public/CPW access (hard mask)** -- three-tier open/conditional/closed
  model: PAD-US Open Access, plus land opened by a CPW access program
  (State Wildlife Areas, Walk-In Access, State Trust Land Public Access
  Program).

If a factor's data source is unavailable at run time, that factor drops
out and the remaining weight(s) renormalize to sum to 1, with a note in
the status panel listing which factors were actually used.

## Map / UI

Same interaction model as elk-probability-map: a probability heatmap
(viridis, masked to legally open land), click any cell to inspect its
score breakdown, a status panel with harvest context (bucks/does/fawns,
hunters, % success for 2nd rifle, most recent year -- 2023) and the
SNOTEL station used, a simulated snow-depth slider (8 precomputed levels,
globally normalized so a genuinely worse unit renders dimmer rather than
renormalizing back to full brightness), and a live NOAA NOHRSC snow-depth
map overlay toggle (a display overlay only, not a model input -- fetched
directly by your browser when you check the box, not baked in at build
time, so it always reflects current conditions regardless of when the
site was last built).

## Data sources

- GMU boundary: CPW ArcGIS, `CPWAdminData/FeatureServer/6`, `GMUID=59`
- Elevation / slope / aspect: AWS public Terrarium terrain tiles, no key
- Roads: Overpass API (via `curl`, see `roads.py`)
- Public land ownership: USGS PAD-US, no key
- CPW hunting access (three-tier model): CPW `CPWAdminData/FeatureServer`
  managed properties, walk-in access, State Trust Land public access
- Land cover: LANDFIRE Existing Vegetation Cover (EVC), no key
- Snow depth (model input): NRCS SNOTEL station network (AWDB REST API)
- Snow depth (live display overlay only, not a model input): NOAA NOHRSC
  Snow Analysis (`raster/rest/services/snow/NOHRSC_Snow_Analysis/MapServer`,
  no API key)
- Mule deer seasonal range: `CPWHPHTerrestrialData/FeatureServer`, layers
  29 (Migration Corridor), 30 (Severe Winter Range), 31 (Winter
  Concentration Area)
- GMU harvest context: `harvest.get_deer_harvest_stats`, reading
  `data/deer_harvest.csv` (vendored from `co-hunt-data`; 2023 data)

See `docs/superpowers/specs/2026-09-14-deer-probability-map-design.md`
for full design rationale.

## Known limitations

- Elevation-band, aspect, and land-cover constants are a best-effort
  domain assumption, not field-calibrated data.
- No Production Area (fawning habitat) layer exists in CPW's mule deer
  High Priority Habitat dataset, unlike elk's -- nothing is being
  silently dropped, the layer simply doesn't exist in this service.
- SNOTEL station coverage near GMU 59 may be sparse; the status panel
  states the station used and its distance from the unit.
- GMU harvest context is 2023 data only (see `co-hunt-data`'s README for
  why 2024/2025 aren't loaded yet).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Add README"
```

---

## Task 12: End-to-end smoke test, push, and deploy

Mirrors exactly what was done for `elk-probability-map`'s own launch:
run the full pipeline against live APIs once, verify the output, then
create the GitHub repo, push, enable Pages, and verify the live site.

**Files:** None (verification and deployment only).

- [ ] **Step 1: Sweep for any missed elk/bull references**

Tasks 4-10 involved manually transcribing dozens of targeted edits into
copied files (especially `render.py`, `test_render.py`, and
`deer_map.py`). Before trusting that coverage, grep the whole repo for
anything that should have been caught but wasn't:

```bash
cd ~/repos/deer-probability-map
grep -rn "[Ee]lk\|[Bb]ull" --include="*.py" .
```

Expected: the only remaining hits are legitimate cross-references to the
sister repo, not missed renames — e.g. `deer_range.py`'s module docstring
("The same elk-probability-map repo's elk_range.py queries layers
20-23..."), `harvest.py`'s docstring ("...same lookup pattern as
elk-probability-map's get_elk_harvest_stats"), and `README.md`'s opening
line ("Sister app to elk-probability-map"). Any hit inside `render.py`,
`terrain.py`, `landcover.py`, `probability.py`, `deer_map.py`, or any
`tests/test_*.py` file that is NOT one of those deliberate
cross-references is a missed edit — fix it, matching the style of the
surrounding already-completed renames in that file, then re-run that
file's test module before continuing.

- [ ] **Step 2: Run the full test suite**

```bash
cd ~/repos/deer-probability-map && source .venv/bin/activate
pytest -q
```

Expected: all tests across every task above pass together (no
cross-task interference).

- [ ] **Step 3: Run the CLI against live APIs**

```bash
mkdir -p dist
python3 deer_map.py --out dist/index.html
```

Expected: completes without an unhandled exception (roads/Overpass may
degrade gracefully with a printed warning, same as the elk app's own
production runs — that is expected, not a failure). Note the printed
deer seasonal range polygon counts and harvest line for GMU 59.

- [ ] **Step 4: Verify the output file**

```bash
ls -la dist/index.html
grep -c "epm-noaa-snow-toggle" dist/index.html
grep -o "Mule Deer Probability" dist/index.html
grep -o "GMU 59</b>" dist/index.html
rm -rf dist
```

Expected: file exists (a few MB), the NOAA toggle element is present,
"Mule Deer Probability" and "GMU 59" both appear in the output.

- [ ] **Step 5: Create the public GitHub repo and push**

```bash
cd ~/repos/deer-probability-map
gh repo create deer-probability-map --public --source=. --remote=origin \
  --description "Mule deer habitat/access probability map for Colorado GMU 59, 2nd rifle season"
git push -u origin main
```

If the push fails with an HTTP 400 / RPC error (seen once during the elk
app's own push, resolved by a larger buffer), run:

```bash
git config --global http.postBuffer 524288000
git push -u origin main
```

- [ ] **Step 6: Enable GitHub Pages via Actions**

```bash
gh api -X POST repos/bmills23/deer-probability-map/pages -f build_type=workflow
```

- [ ] **Step 7: Trigger the deploy workflow and watch it**

```bash
gh workflow run deploy.yml --repo bmills23/deer-probability-map
gh run list --repo bmills23/deer-probability-map --limit 3
# then, using the run ID printed above:
gh run watch <run-id> --repo bmills23/deer-probability-map --interval 20
```

Expected: both the `build` and `deploy` jobs complete successfully.

- [ ] **Step 8: Verify the live site**

```bash
curl -sS -o /tmp/deer_live_check.html -w "HTTP %{http_code}, %{size_download} bytes\n" \
  https://bmills23.github.io/deer-probability-map/
grep -c "epm-noaa-snow-toggle" /tmp/deer_live_check.html
grep -o "Mule Deer Probability" /tmp/deer_live_check.html
rm -f /tmp/deer_live_check.html
```

Expected: `HTTP 200`, the NOAA toggle present, "Mule Deer Probability"
present.
