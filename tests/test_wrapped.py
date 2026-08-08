"""Tests for utils.wrapped — Lounge Wrapped + Season Superlatives aggregation.

Rows mimic db.get_all_submissions() shape (lists of strings). Only the indices the
engine reads need to be populated; we build rows with a small helper."""
from utils.wrapped import build_wrapped, compute_superlatives, VALOR_TAGS


def row(ts="2026-07-01 12:00:00", name="Alice", did="1", weapon="Messer",
        subclass="Officer", mp="Falmire", faction="Agatha", td=50, k=40, d=3,
        vip="No", feats="", link="L", score=8000):
    r = [""] * 27
    r[0] = ts; r[1] = name; r[2] = did; r[3] = weapon; r[4] = subclass
    r[5] = mp; r[6] = faction; r[7] = str(td); r[8] = str(k); r[9] = str(d)
    r[10] = vip; r[11] = feats; r[12] = link; r[24] = str(score)
    return r


# ── build_wrapped ────────────────────────────────────────────────────────────

def test_empty():
    w = build_wrapped([])
    assert w['runs'] == 0 and w['signature_weapon'] is None and w['best_game'] is None


def test_totals_and_signatures():
    subs = [
        row(weapon="Messer", mp="Falmire", td=50, k=40, d=2),
        row(weapon="Messer", mp="Rudhelm", td=60, k=30, d=0),
        row(weapon="War Axe", mp="Falmire", td=20, k=10, d=5),
    ]
    w = build_wrapped(subs)
    assert w['runs'] == 3
    assert w['kills'] == 80 and w['takedowns'] == 130 and w['deaths'] == 7
    assert w['signature_weapon'] == "Messer" and w['signature_weapon_runs'] == 2
    assert w['signature_map'] == "Falmire" and w['signature_map_runs'] == 2
    assert w['weapons_used'] == 2 and w['maps_played'] == 2
    assert w['kd'] == round(80 / 7, 2)


def test_best_game_is_highest_score():
    subs = [row(score=5000, k=20), row(score=21000, k=110, td=205), row(score=9000)]
    w = build_wrapped(subs)
    assert w['best_game']['score'] == 21000 and w['best_game']['kills'] == 110


def test_flawless_streak_is_longest_consecutive_zero_death():
    subs = [
        row(ts="2026-07-01 10:00:00", d=0, td=30),
        row(ts="2026-07-01 11:00:00", d=0, td=40),
        row(ts="2026-07-01 12:00:00", d=2, td=50),   # breaks the streak
        row(ts="2026-07-01 13:00:00", d=0, td=20),
    ]
    assert build_wrapped(subs)['flawless_streak'] == 2


def test_feats_and_carries_and_night():
    subs = [
        row(feats="Triple, Brutal", d=0, td=160, k=105),   # triple + carry + flawless
        row(feats="100 Kills", k=120),
        row(feats="200 Takedowns", td=210),
        row(ts="2026-07-02 02:30:00", feats="Outmatched"),  # night + carry
    ]
    w = build_wrapped(subs)
    assert w['triples'] == 1 and w['hundred_kills'] == 1 and w['two_hundred_td'] == 1
    assert w['carries'] == 2          # Brutal + Outmatched
    assert w['flawless_runs'] == 1
    assert w['night_runs'] == 1


def test_excludes_resubmit_and_unlisted():
    subs = [row(k=40), row(feats="Resubmit", k=999), row(feats="Unlisted", k=999)]
    w = build_wrapped(subs)
    assert w['runs'] == 1 and w['kills'] == 40


def test_faction_split_and_top_faction():
    subs = [row(faction="Agatha"), row(faction="Agatha"), row(faction="Mason")]
    w = build_wrapped(subs)
    assert w['faction_split'] == {"Agatha": 2, "Mason": 1}
    assert w['top_faction'] == "Agatha"


def test_tilt_hardest_lobby_from_banner_totals():
    # cols 25/26 = team_total_kills / enemy_total_kills. Negative gap = uphill.
    a = row(); a[25] = "100"; a[26] = "160"   # your team outkilled by 60% — hard
    b = row(); b[25] = "200"; b[26] = "150"   # comfortable stomp
    w = build_wrapped([a, b])
    assert w['tilt_bands']                       # bands recorded
    assert w['hardest_lobby'] is not None
    assert w['hardest_lobby']['gap'] == -60      # the most-negative run is captured
    # a run with no banner totals contributes nothing to tilt
    assert build_wrapped([row()])['hardest_lobby'] is None


def test_peak_hour():
    subs = [row(ts="2026-07-01 22:00:00"), row(ts="2026-07-01 22:30:00"),
            row(ts="2026-07-02 09:00:00")]
    w = build_wrapped(subs)
    assert w['peak_hour'] == 22 and w['peak_hour_runs'] == 2


# ── compute_superlatives ─────────────────────────────────────────────────────

def test_superlatives_pick_expected_winners():
    subs = [
        # Alice: farmer + tireless (many Falmire runs)
        row(name="Alice", did="1", mp="Falmire", k=30, d=2),
        row(name="Alice", did="1", mp="Falmire", k=25, d=1),
        row(name="Alice", did="1", mp="Falmire", k=20, d=1),
        # Bob: bloodbath + glass cannon (huge kills, huge deaths)
        row(name="Bob", did="2", mp="Rudhelm", k=150, d=20),
        row(name="Bob", did="2", mp="Rudhelm", k=140, d=18),
        row(name="Bob", did="2", mp="Rudhelm", k=130, d=22),
        # Cara: comeback king (carries) + night shift
        row(name="Cara", did="3", ts="2026-07-01 03:00:00", feats="Brutal", k=40, d=5),
        row(name="Cara", did="3", ts="2026-07-01 04:00:00", feats="Outmatched", k=35, d=4),
        row(name="Cara", did="3", ts="2026-07-01 02:00:00", feats="Uphill", k=30, d=6),
    ]
    s = compute_superlatives(subs, farm_maps=("Falmire", "Darkforest"), min_games=3)
    assert s['bloodbath']['name'] == "Bob" and s['bloodbath']['value'] == 150
    assert s['martyr']['name'] == "Bob"          # 60 deaths
    assert s['glass_cannon']['name'] == "Bob"
    assert s['farmer']['name'] == "Alice" and s['farmer']['value'] == 3
    assert s['comeback_king']['name'] == "Cara" and s['comeback_king']['value'] == 3
    assert s['night_shift']['name'] == "Cara" and s['night_shift']['value'] == 3


def test_superlatives_min_games_gate_and_empty():
    assert compute_superlatives([]) == {}
    # a single-run player can't win glass_cannon / one_trick (min_games=3) but can win counts
    s = compute_superlatives([row(name="Solo", did="9", k=200, d=1)], min_games=3)
    assert 'glass_cannon' not in s and 'one_trick' not in s
    assert s['bloodbath']['name'] == "Solo"
