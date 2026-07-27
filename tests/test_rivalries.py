"""Tests for utils.rivalries — shared-lobby aggregation (meetings + comparative
averages, no per-game win/loss)."""
from utils.rivalries import compute_rivalries, rivalry_context, compute_pair_awards


def row(ts, name, did, mp="Falmire", kills=40, td=50, team_total=300, enemy_total=280, feats=""):
    """Submission-shaped row. Banner totals (25/26) drive same-lobby + confirmed side;
    td/kills (7/8) feed the comparative averages."""
    r = [""] * 27
    r[0] = ts; r[1] = name; r[2] = did; r[3] = "Messer"; r[5] = mp
    r[7] = str(td); r[8] = str(kills); r[11] = feats
    r[18] = str(team_total + enemy_total)
    r[25] = str(team_total); r[26] = str(enemy_total)
    return r


def test_no_history_is_empty():
    d = compute_rivalries("1", [])
    assert d['nemesis'] is None and d['ally'] is None
    assert rivalry_context("A", d) == ""


def test_foe_and_ally_from_shared_lobby():
    # A vs B (banner swapped = opponent), C on A's team (same orientation = ally).
    subs = [
        row("2026-07-27 12:00:00", "A", "1", td=60, kills=50, team_total=300, enemy_total=280),
        row("2026-07-27 12:03:00", "B", "2", td=40, kills=30, team_total=280, enemy_total=300),  # foe
        row("2026-07-27 12:02:00", "C", "3", td=20, kills=15, team_total=300, enemy_total=280),  # ally
    ]
    d = compute_rivalries("1", subs)
    assert d['nemesis']['name'] == "B" and d['nemesis']['meetings'] == 1
    # comparative averages over the shared game
    assert d['nemesis']['my_td'] == 60 and d['nemesis']['their_td'] == 40
    assert d['ally']['name'] == "C" and d['ally']['matches'] == 1
    # NO win/loss keys anymore
    assert 'wins' not in d['nemesis'] and 'losses' not in d['nemesis']


def test_nemesis_is_most_met_and_averages_span_all_meetings():
    subs = []
    # A meets B three times (different banners/times), with varying takedowns.
    for i, (tt, et, atd, btd) in enumerate([(300, 280, 40, 30), (410, 400, 80, 20), (250, 240, 60, 40)]):
        ts = f"2026-07-2{i+1} 12:00:00"
        subs.append(row(ts, "A", "1", td=atd, team_total=tt, enemy_total=et))
        subs.append(row(ts, "B", "2", td=btd, team_total=et, enemy_total=tt))  # swapped = foe
    # A meets D once
    subs.append(row("2026-07-28 12:00:00", "A", "1", td=50, team_total=200, enemy_total=190))
    subs.append(row("2026-07-28 12:01:00", "D", "4", td=45, team_total=190, enemy_total=200))
    d = compute_rivalries("1", subs)
    assert d['nemesis']['name'] == "B" and d['nemesis']['meetings'] == 3
    assert d['nemesis']['my_td'] == 60.0        # (40+80+60)/3
    assert d['nemesis']['their_td'] == 30.0     # (30+20+40)/3


def test_different_map_or_far_time_is_not_a_lobby():
    subs = [
        row("2026-07-27 12:00:00", "A", "1", mp="Falmire", team_total=300, enemy_total=280),
        row("2026-07-27 12:01:00", "B", "2", mp="Rudhelm", team_total=280, enemy_total=300),
        row("2026-07-27 20:00:00", "C", "3", mp="Falmire", team_total=280, enemy_total=300),
    ]
    d = compute_rivalries("1", subs)
    assert d['nemesis'] is None and d['ally'] is None


def test_excludes_resubmit():
    subs = [
        row("2026-07-27 12:00:00", "A", "1", team_total=300, enemy_total=280),
        row("2026-07-27 12:02:00", "B", "2", team_total=280, enemy_total=300, feats="Resubmit"),
    ]
    assert compute_rivalries("1", subs)['nemesis'] is None


def test_no_banner_totals_names_no_false_ally_but_keeps_foe():
    # Without banner totals side can't be confirmed -> NO ally claimed, but the shared
    # lobby (matched by total_lobby_kills) still surfaces B as a frequent foe.
    a = row("2026-07-27 12:00:00", "A", "1"); a[25] = ""; a[26] = ""; a[18] = "600"
    b = row("2026-07-27 12:02:00", "B", "2"); b[25] = ""; b[26] = ""; b[18] = "600"
    d = compute_rivalries("1", [a, b])
    assert d['ally'] is None
    assert d['nemesis'] and d['nemesis']['name'] == "B" and d['nemesis']['meetings'] == 1


def test_pair_awards_bitter_rivals_and_inseparable():
    subs = []
    # A & B clash as opponents 3 times (swapped banners) -> Bitter Rivals
    for i, (tt, et) in enumerate([(300, 280), (410, 400), (250, 240)]):
        ts = f"2026-07-1{i+1} 12:00:00"
        subs.append(row(ts, "A", "1", team_total=tt, enemy_total=et))
        subs.append(row(ts, "B", "2", team_total=et, enemy_total=tt))
    # C & D on the SAME team 3 times (same orientation) -> Inseparable
    for i, (tt, et) in enumerate([(320, 300), (200, 180), (500, 480)]):
        ts = f"2026-07-2{i+1} 15:00:00"
        subs.append(row(ts, "C", "3", team_total=tt, enemy_total=et))
        subs.append(row(ts, "D", "4", team_total=tt, enemy_total=et))
    p = compute_pair_awards(subs, min_meetings=2)
    assert p['bitter_rivals'] and {p['bitter_rivals']['a'], p['bitter_rivals']['b']} == {"A", "B"}
    assert p['bitter_rivals']['clashes'] == 3
    assert p['inseparable'] and {p['inseparable']['a'], p['inseparable']['b']} == {"C", "D"}
    assert p['inseparable']['matches'] == 3


def test_pair_awards_ignore_one_offs():
    # a single shared lobby shouldn't win (min_meetings=2)
    subs = [row("2026-07-27 12:00:00", "A", "1", team_total=300, enemy_total=280),
            row("2026-07-27 12:02:00", "B", "2", team_total=280, enemy_total=300)]
    p = compute_pair_awards(subs, min_meetings=2)
    assert p['bitter_rivals'] is None and p['inseparable'] is None


def test_context_uses_averages_not_winloss():
    subs = [
        row("2026-07-27 12:00:00", "A", "1", td=60, kills=50, team_total=300, enemy_total=280),
        row("2026-07-27 12:03:00", "B", "2", td=40, kills=30, team_total=280, enemy_total=300),
    ]
    ctx = rivalry_context("A", compute_rivalries("1", subs))
    assert "Nemesis" in ctx and "B" in ctx
    assert "60" in ctx and "40" in ctx           # comparative averages present
    assert "meeting" in ctx and "average" in ctx  # framed as meetings + averages
    # the nemesis LINE never claims a beaten opponent (header may mention "no win/loss")
    nem_line = next(l for l in ctx.splitlines() if l.startswith("- Nemesis"))
    assert "beat" not in nem_line.lower() and "-" not in nem_line.split(":", 1)[1]
