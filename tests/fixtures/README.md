# Fixtures

Real, saved API responses used by the test suite (no live network calls in
tests). Captured 2026-09-10 during design/planning.

- `gmu_boundary_38_59.geojson` — CPW `CPWAdminData/FeatureServer/6`, GMU 38 + 59 polygons (`where=GMUID IN (38,59)&returnGeometry=true&f=geojson`).
- `terrarium_tile_11_427_785.png` — AWS Terrarium elevation tile covering GMU 59's centroid at zoom 11 (`elevation-tiles-prod/terrarium/11/427/785.png`). Decoded center-pixel elevation hand-verified at ~1943 m (~6374 ft), plausible for the Wet Mountains foothills.
- `overpass_roads_sample.json` — Overpass `way["highway"~"..."]` query over a small (~5x5 mi) bbox near GMU 59 (38.58,-105.00 to 38.68,-104.88), 84 ways.
- `padus_public_access_sample.json` — USGS PAD-US Public Access `FeatureServer/0` query over the same small bbox, 15 features (includes both `Pub_Access: 'OA'` and non-OA features, needed to test the mask filter).
- `snotel_stations_co.json` — NRCS AWDB REST station list for all Colorado SNTL stations, 118 stations.
