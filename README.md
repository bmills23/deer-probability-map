# Deer Probability Map

Estimate where a mule deer buck is likely to be in Colorado GMU 59
during 2nd rifle season, from free public data, rendered as an
interactive map. Sister app to
[`elk-probability-map`](https://github.com/bmills23/elk-probability-map),
reusing its architecture and rendering approach. GMU harvest stats are
vendored from `co-hunt-data` into `data/deer_harvest.csv` (see
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
score breakdown, a status panel with harvest context (bucks, hunters,
% success for 2nd rifle, most recent year -- 2023) and the
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

- Elevation-band, aspect, land-cover, and snow-elevation-shift constants
  are a best-effort domain assumption, not field-calibrated data.
- No Production Area (fawning habitat) layer exists in CPW's mule deer
  High Priority Habitat dataset, unlike elk's -- nothing is being
  silently dropped, the layer simply doesn't exist in this service.
- SNOTEL station coverage near GMU 59 may be sparse; the status panel
  states the station used and its distance from the unit.
- GMU harvest context is 2023 data only (see `co-hunt-data`'s README for
  why 2024/2025 aren't loaded yet).
