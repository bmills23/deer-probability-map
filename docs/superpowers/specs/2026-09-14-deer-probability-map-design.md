# Mule Deer Probability Map — Design Spec

**Date:** 2026-09-14
**Status:** Draft, pending user review

## Goal

A sister app to `elk-probability-map`: an interactive HTML map estimating
where a mule deer buck is likely to be found in Colorado GMU 59 during 2nd
rifle season, published as a static GitHub Pages site. Built as a
standalone repo, copying and adapting `elk-probability-map`'s current
shipped architecture (not its original day-one spec — the app has grown
since: three-tier access, CPW seasonal range, land cover, live NOAA snow
overlay, GitHub Pages hosting).

## Non-goals

- **Not a calibrated probability**, same honest-scope framing as the elk
  app: a habitat/access-suitability index, not a statistical chance of
  encountering a deer.
- **No individual-animal tracking / live telemetry.**
- **GMU 59 only, 2nd rifle season only**, for this iteration. Additional
  units or seasons are a possible follow-up, not part of this spec.
- **Mule deer only.** Whitetail habitat (low-elevation river corridors,
  agricultural edges) is a materially different model and out of scope —
  GMU 59 is a mule deer unit.
- **No shared library with `elk-probability-map`.** Deliberate code
  duplication of the generic modules, for the same reason
  `elk-probability-map` vendors `co-hunt-data`'s harvest CSV instead of
  depending on it at runtime: no cross-repo dependency for a from-scratch
  CI build to trip over.

## Data sources

All free, no API key — the same sources `elk-probability-map` already
uses live in production, minus the ones being replaced:

| Factor | Source | Notes |
|---|---|---|
| GMU boundary | CPW ArcGIS, `CPWAdminData/FeatureServer/6`, `where=GMUID=59` | Single unit this time — no ~85 mi multi-unit bbox concern, but `gmu_boundary.py`'s per-unit bbox derivation is unchanged/reused as-is. |
| Elevation / slope / aspect | AWS Terrarium tiles (unchanged) | `terrain.py` fetch/decode copied verbatim; only `habitat_components()`'s elevation-band and aspect *scoring* is retuned for mule deer (see Probability model). |
| Roads | Overpass via `curl` subprocess (unchanged, including the existing 406-with-`requests` workaround) | `roads.py` copied verbatim. Overpass's public instance is already flaky in the elk app's own production runs (406s intermittently even via `curl`) — same graceful-degradation behavior applies here, not a new risk. |
| Public land ownership | PAD-US (unchanged) | `public_land.py` copied verbatim. |
| CPW hunting access (three-tier open/conditional/closed) | CPW `CPWAdminData/FeatureServer` managed properties, walk-in access, SLB access (unchanged) | `hunting_access.py` copied verbatim — access tiering is about land, not species. |
| Land cover | LANDFIRE EVC (unchanged fetch) | `landcover.py`'s fetch copied verbatim; the cover-type → score mapping is retuned for mule deer (mountain shrub/browse favored over elk's aspen/conifer preference). |
| Snow depth (model input) | NRCS SNOTEL (unchanged) | `snow.py` copied verbatim; the elevation-shift constants (`max_shift_m`, `max_depth_in`) are a mule-deer-specific tuning question, documented as tunable rather than asserted (see Known limitations). |
| Snow depth (live display overlay) | NOAA NOHRSC, client-side (unchanged) | `render.py`'s `NoaaSnowLayer` tile logic and toggle copied verbatim — no species dependency at all. |
| Mule deer seasonal range | Same CPW host as elk's, `CPWHPHTerrestrialData/FeatureServer`: layer 29 (Migration Corridor), 30 (Severe Winter Range), 31 (Winter Concentration Area) | Confirmed present on the live service (same host `elk_range.py` already queries via `hunting_access.ARCGIS_BASE`). **No Production Area layer exists for mule deer in this service** — unlike elk (layer 21), there's nothing to fetch-but-exclude-from-scoring; all three deer layers are scorable. |
| GMU harvest context | Vendored `data/deer_harvest.csv` (subset of `co-hunt-data`'s `harvest` table: `bucks`/`does`/`fawns`/`total_harvest`/`total_hunters`/`pct_success`/`rec_days`, section `rifle_2nd`) | Same vendoring pattern as the elk app's `harvest.py` (added 2026-09-14 specifically to remove the cross-repo CI dependency) — copy that pattern from day one instead of introducing the dependency and removing it later. |

## Architecture

New standalone repo, `deer-probability-map`, structured like the *current*
`elk-probability-map`:

```
deer-probability-map/
├── deer_map.py             # CLI entry point (adapted from elk_map.py); default --units 59
├── net.py                  # copied verbatim
├── geo_utils.py            # copied verbatim
├── gmu_boundary.py         # copied verbatim
├── terrain.py              # fetch/decode/slope-aspect copied; habitat_components()
│                           #   elevation-band + aspect scoring retuned for mule deer
├── roads.py                # copied verbatim
├── snow.py                 # copied verbatim (fetch + anchor mechanics);
│                           #   elevation-shift constants flagged as tunable
├── public_land.py          # copied verbatim
├── hunting_access.py       # copied verbatim (three-tier access model)
├── landcover.py            # fetch copied verbatim; cover-type scoring retuned
├── deer_range.py           # adapted from elk_range.py: layers 29/30/31,
│                           #   no production_area exclusion needed
├── probability.py          # blend/renormalize framework copied;
│                           #   DEFAULT_WEIGHTS and weights_for_snow retuned
├── harvest.py              # adapted: bucks/does/fawns, section='rifle_2nd'
├── render.py               # map/panel/slider/NOAA-toggle plumbing copied;
│                           #   labels/title/legend text updated for deer
├── requirements.txt        # identical
├── README.md               # adapted from elk's, same "Honest scope" framing
├── .github/workflows/deploy.yml   # identical pattern, own Pages site
├── data/
│   └── deer_harvest.csv    # vendored subset of co-hunt-data's harvest table
└── tests/
    ├── fixtures/           # copied as-is from elk-probability-map: the
    │                       #   existing GMU boundary fixture already
    │                       #   contains GMU 59's real geometry (bundled
    │                       #   with 38), so no new fetch is needed there;
    │                       #   Terrarium tile, Overpass sample, PAD-US
    │                       #   sample, SNOTEL stations are also reused
    │                       #   as-is (not species-specific); one new
    │                       #   fixture needed for the deer_range query
    │                       #   (layers 29-31)
    └── test_*.py           # copied and adapted per module, one per module
```

**Data flow:** unchanged from `elk_map.py`'s per-unit loop, just a single
default unit (59). The simulated-snow-slider global-normalization
machinery (`build_snow_stack`) is kept as-is even for one unit — it costs
nothing extra and avoids a rewrite if a second deer unit is added later.

## Probability model

Matches the elk app's *current* shipped model (three weighted,
renormalizable factors, plus the three-tier access mask) — not the
original 2-factor elk spec:

| Factor | Elk's current weight | Deer starting weight | Basis |
|---|---:|---:|---|
| Habitat suitability | 0.45 | 0.45 (starting point, tunable) | Elevation-band fit retuned for mule deer's lower, browse/mountain-shrub habitat (vs. elk's higher subalpine preference), shifted downward by snow depth same as elk. Aspect/land-cover sub-scores retuned similarly. |
| Security cover (distance from roads) | 0.35 | 0.35 (starting point) | Mechanism unchanged; deer and elk both benefit from distance-from-roads as an escape-cover proxy, no species-specific change identified. |
| Seasonal range (CPW delineation) | 0.20 | 0.20 (starting point) | Same `NEUTRAL_BASELINE = 0.5` "unknown ≠ absent" handling as elk's `elk_range.py`; per-type scores (winter concentration highest confidence, then severe winter range, then migration corridor) carried over unchanged in relative ordering — 2nd rifle (early-mid November) has the same "moving onto winter range as season progresses" seasonal logic elk's 3rd rifle (also November) uses, so the elk app's own `SEASON RELEVANCE` reasoning transfers directly. |
| Public/CPW access | mask (0/1) | mask (0/1), unchanged | Three-tier open/conditional/closed model, identical mechanism — legal access doesn't depend on species. |

Habitat/land-cover/snow-shift constants are a **best-effort domain
assumption**, not calibrated data — flagged explicitly in code comments
and the README, same "Honest scope" caveat the elk app already carries for
its own aspect-preference constant.

## CLI / usage

```bash
python3 deer_map.py                       # GMU 59, latest data
python3 deer_map.py --units 59            # explicit (same as default)
python3 deer_map.py --out deer_map.html   # output path
```

Same `--cell-mi` / `--inspect-mi` flags as `elk_map.py`, unchanged
defaults. No `--co-hunt-data-path` flag (harvest data is vendored, per
`elk-probability-map`'s own 2026-09-14 change — see Data sources).

## Map / UI

Same interaction model as the current elk app: probability heatmap
(viridis, masked to the three-tier access model), click-to-inspect cells,
a status panel with harvest context (bucks/does/fawns, hunters, % success
for 2nd rifle, most recent year — 2023) and the SNOTEL station used, the
simulated snow-depth slider (same precomputed levels, same global
normalization), and the live NOAA NOHRSC snow-depth overlay toggle
(client-side, unchanged). Legend/panel text and the map title updated to
read "Mule Deer Probability" instead of "Bull Elk Probability."

## Error handling

Identical policy to the current `elk_map.py`:

- GMU boundary fetch failure is fatal (no trustworthy fallback bbox).
- Roads, land cover, snow, and deer seasonal range fetch failures each
  degrade gracefully: log a warning, drop that factor, and let
  `compute_probability` renormalize the remaining weights — never abort
  the whole run.

## Testing strategy (TDD, real fixtures over mocks)

Same philosophy as the elk app: fixture-based unit tests, no live network
calls in the test suite, no mocking of application logic — the true
network boundary is exercised via one manual end-to-end smoke-test run
before shipping (exactly as was done for `elk-probability-map` before its
GitHub Pages launch).

- Fixtures copied as-is from `elk-probability-map` (its GMU boundary
  fixture already contains GMU 59's real geometry, no new fetch needed;
  Terrarium tile, Overpass sample, PAD-US sample, and SNOTEL stations are
  likewise not species-specific).
- One new fixture: a real response from the mule deer range query (layers
  29/30/31) for GMU 59's bbox.
- Each copied module's existing test file is copied and adapted to the
  new module name; each retuned module's tests are rewritten against the
  new deer-specific constants/behavior.

## Known limitations

- Mule-deer elevation-band, aspect, land-cover, and snow-elevation-shift
  constants are a best-effort domain assumption carried over from general
  hunting knowledge, not field-calibrated data — documented as tunable in
  both this spec and the shipped README, same honesty standard as the
  elk app's own aspect-preference caveat.
- No Production Area (fawning habitat) layer exists in CPW's mule deer
  HPH dataset, unlike elk's — nothing to note in the UI beyond "not
  available," since there's no display-only layer being silently dropped.
- SNOTEL station coverage near GMU 59 is whatever the elk app already
  found (same unit) — same "station used and its distance" transparency
  note in the status panel.
- GMU harvest context is 2023 data only, same as the elk app (see
  `co-hunt-data`'s README for why later years aren't yet
  scriptable-downloadable).

## Deferred (explicitly out of scope for this spec)

- Additional GMUs beyond 59.
- Additional deer seasons beyond 2nd rifle (archery, muzzleloader, 3rd/4th
  rifle all have real harvest data available in `co-hunt-data` already,
  per this session's exploration — a plausible follow-up).
- Whitetail deer modeling.
- A shared code library between `elk-probability-map` and
  `deer-probability-map` (deliberately rejected — see Architecture).
