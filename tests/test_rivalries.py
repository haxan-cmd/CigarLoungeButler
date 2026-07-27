"""Tests for utils.rivalries — head-to-head / ally aggregation from lobby fingerprints."""
from utils.rivalries import compute_rivalries, rivalry_context, ident


def row(ts, name, did, mp="Falmire", kills=40, td=50, team_total=300, enemy_total=280, feats=""):
    """Build a submission-shaped row. Banner totals (25/26) drive same-lobby +
    same-team; kills (8) decide head-to-head."""
    r = [""] * 27
    r[0] = ts; r[1] = name; r[2] = did; r[3] = "Messer"; r[5] = mp
    r[7] = str(td); r[8] = str(kills); r[11] = feats
    r[18] = str(team_total + enemy_total)      # total_lobby_kills (fallback)
    r[25] = str(team_total); r[26] = str(enemy_total)
    return r


def test_opponents_and_allies_from_shared_lobby():
    # One match: A (team 300 / enemy 280) vs B (team 280 / enemy 300, swapped = opponent),
    # and C on A's team (300 / 280 = same orientation = ally).
    subs = [
        row("2026-07-27 12:00:00", "A", "1", kills=60, team_total=300, enemy_total=280),
        row("2026-07-27 12:03:00", "B", "2", kills=45, team_total=280, enemy_total=300),  # opponent
        row("2026-07-27 12:02:00", "C", "3", kills=30, team_total=300, enemy_total=280),  # ally
    ]
    d = compute_rivalries("1", subs)
    assert d['nemesis']['name'] == "B" and d['nemesis']['encounters'] == 1
    assert d['nemesis']['wins'] == 1 and d['nemesis']['losses'] == 0   # A(60) > B(45)
    assert d['ally']['name'] == "C" and d['ally']['matches'] == 1


def test_nemesis_is_most_faced_across_matches():
    subs = []
    # A faces B in three separate matches (different times/banner totals), loses 2 of 3
    for i, (tt, et, ak, bk) in enumerate([(300, 280, 50, 55), (410, 400, 40, 60), (250, 240, 70, 30)]):
        ts = f"2026-07-2{i+1} 12:00:00"
        subs.append(row(ts, "A", "1", kills=ak, team_total=tt, enemy_total=et))
        subs.append(row(ts, "B", "2", kills=bk, team_total=et, enemy_total=tt))  # opponent (swapped)
    # A faces D once
    subs.append(row("2026-07-28 12:00:00", "A", "1", kills=50, team_total=200, enemy_total=190))
    subs.append(row("2026-07-28 12:01:00", "D", "4", kills=40, team_total=190, enemy_total=200))
    d = compute_rivalries("1", subs)
    assert d['nemesis']['name'] == "B" and d['nemesis']['encounters'] == 3
    assert d['nemesis']['wins'] == 1 and d['nemesis']['losses'] == 2


def test_different_map_or_far_time_is_not_a_lobby():
    subs = [
        row("2026-07-27 12:00:00", "A", "1", mp="Falmire", team_total=300, enemy_total=280),
        row("2026-07-27 12:01:00", "B", "2", mp="Rudhelm", team_total=280, enemy_total=300),  # diff map
        row("2026-07-27 20:00:00", "C", "3", mp="Falmire", team_total=280, enemy_total=300),  # far time
    ]
    d = compute_rivalries("1", subs)
    assert d['nemesis'] is None and d['ally'] is None


def test_excludes_resubmit_and_empty_output():
    subs = [
        row("2026-07-27 12:00:00", "A", "1", team_total=300, enemy_total=280),
        row("2026-07-27 12:02:00", "B", "2", team_total=280, enemy_total=300, feats="Resubmit"),
    ]
    d = compute_rivalries("1", subs)
    assert d['nemesis'] is None
    assert rivalry_context("A", d) == ""


def test_context_renders_when_present():
    subs = [
        row("2026-07-27 12:00:00", "A", "1", kills=60, team_total=300, enemy_total=280),
        row("2026-07-27 12:03:00", "B", "2", kills=45, team_total=280, enemy_total=300),
    ]
    d = compute_rivalries("1", subs)
    ctx = rivalry_context("A", d)
    assert "Nemesis" in ctx and "B" in ctx and "1-0" in ctx
