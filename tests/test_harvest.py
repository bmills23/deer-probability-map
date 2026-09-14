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
