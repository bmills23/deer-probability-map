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
