"""Tests for utils.roster — name matching + roster-based rivalry aggregation."""
from utils.roster import (
    normalize_name, build_ign_index, resolve_name, has_roster_coverage,
    compute_rivalries, head_to_head, compute_pair_awards,
)


def sub(sid, name, did, ts="2026-07-27 12:00:00", mp="Falmire", td=50, k=40, feats=""):
    r = [""] * 27
    r[0] = ts; r[1] = name; r[2] = did; r[5] = mp
    r[7] = str(td); r[8] = str(k); r[11] = feats; r[23] = str(sid)
    return r


def entry(name, side, td=0, k=0):
    return {'name': name, 'side': side, 'td': td, 'k': k}


IGN = build_ign_index([("1", ["Alice", "AliceGG"]), ("2", ["Bob"]),
                       ("3", ["Carol"]), ("4", ["Dave"])])


# ── normalisation ──────────────────────────────────────────────────────────
def test_normalize_strips_tags_accents_punct_case():
    assert normalize_name("[CLAN] Bob") == "bob"
    assert normalize_name("Àlïce_GG!") == "alicegg"
    assert normalize_name("{xX}Dave") == "dave"
    assert normalize_name("") == "" and normalize_name(None) == ""


# ── matching ────────────────────────────────────────────────────────────────
def test_resolve_exact_and_anonymous():
    assert resolve_name("Alice", IGN) == "1"
    assert resolve_name("[TAG] Bob", IGN) == "2"
    assert resolve_name("RandomPub123", IGN) is None      # unregistered = anonymous


def test_resolve_fuzzy_tolerates_ocr_noise():
    assert resolve_name("A1ice", IGN) == "1"              # l->1 OCR slip
    assert resolve_name("Carol", IGN) == "3"
    # too different -> no false match
    assert resolve_name("Zzzq", IGN) is None


# ── coverage gate ────────────────────────────────────────────────────────────
def test_has_roster_coverage():
    subs = [sub(10, "Alice", "1")]
    assert has_roster_coverage(subs, {}) is False
    assert has_roster_coverage(subs, {"10": [entry("Bob", "enemy")]}) is True


# ── rivalries ────────────────────────────────────────────────────────────────
def test_nemesis_from_enemy_side_ally_from_team_side():
    subs = [sub(10, "Alice", "1", td=60, k=50)]
    rosters = {"10": [entry("Bob", "enemy", td=40, k=30),
                      entry("Carol", "team", td=20, k=15),
                      entry("SomeRandom", "enemy", td=99, k=99)]}  # anonymous, skipped
    d = compute_rivalries("1", ["Alice", "AliceGG"], subs, rosters, IGN)
    assert d['nemesis']['name'] == "Bob" and d['nemesis']['clashes'] == 1
    assert d['nemesis']['my_td'] == 60 and d['nemesis']['their_td'] == 40
    assert d['ally']['name'] == "Carol" and d['ally']['matches'] == 1
    # the anonymous random never becomes a foe
    assert all(f['name'] != "SomeRandom" for f in d['foes'])


def test_player_is_never_their_own_rival():
    # A roster row that is really the target (an IGN of theirs) must be ignored.
    subs = [sub(10, "Alice", "1", td=60, k=50)]
    rosters = {"10": [entry("AliceGG", "enemy", td=1, k=1),   # target's own alt IGN
                      entry("Bob", "enemy", td=40, k=30)]}
    d = compute_rivalries("1", ["Alice", "AliceGG"], subs, rosters, IGN)
    assert d['nemesis']['name'] == "Bob"
    assert all('alice' not in f['name'].lower() for f in d['foes'])


def test_nemesis_averages_span_all_meetings():
    subs = [sub(10, "Alice", "1", ts="2026-07-21 12:00:00", td=40, k=30),
            sub(11, "Alice", "1", ts="2026-07-22 12:00:00", td=80, k=50),
            sub(12, "Alice", "1", ts="2026-07-23 12:00:00", td=60, k=40)]
    rosters = {"10": [entry("Bob", "enemy", td=30, k=20)],
               "11": [entry("Bob", "enemy", td=20, k=10)],
               "12": [entry("Bob", "enemy", td=40, k=30)]}
    d = compute_rivalries("1", ["Alice"], subs, rosters, IGN)
    assert d['nemesis']['meetings'] == 3
    assert d['nemesis']['my_td'] == 60.0        # (40+80+60)/3
    assert d['nemesis']['their_td'] == 30.0     # (30+20+40)/3


def test_one_meeting_per_opponent_per_game_on_dupe_rows():
    subs = [sub(10, "Alice", "1")]
    rosters = {"10": [entry("Bob", "enemy"), entry("Bob", "enemy")]}  # OCR dup
    d = compute_rivalries("1", ["Alice"], subs, rosters, IGN)
    assert d['nemesis']['clashes'] == 1


def test_excluded_rows_ignored():
    subs = [sub(10, "Alice", "1", feats="Resubmit")]
    rosters = {"10": [entry("Bob", "enemy")]}
    d = compute_rivalries("1", ["Alice"], subs, rosters, IGN)
    assert d['nemesis'] is None


# ── head to head ─────────────────────────────────────────────────────────────
def test_head_to_head_dedupes_same_match_from_both_uploads():
    # Same game, uploaded by Alice and by Bob (near-identical time) -> 1 meeting.
    subs = [sub(10, "Alice", "1", ts="2026-07-27 12:00:00", td=60, k=50),
            sub(11, "Bob", "2", ts="2026-07-27 12:05:00", td=40, k=30)]
    rosters = {"10": [entry("Bob", "enemy", td=40, k=30)],
               "11": [entry("Alice", "enemy", td=60, k=50)]}
    h = head_to_head("1", ["Alice"], "2", ["Bob"], subs, rosters, IGN)
    assert h['meetings'] == 1 and h['opponents'] == 1
    assert h['a_td'] == 60 and h['b_td'] == 40


def test_head_to_head_none_when_never_met():
    subs = [sub(10, "Alice", "1")]
    rosters = {"10": [entry("Carol", "team")]}
    assert head_to_head("1", ["Alice"], "2", ["Bob"], subs, rosters, IGN) is None


# ── pair awards ──────────────────────────────────────────────────────────────
def test_pair_awards_bitter_rivals_and_inseparable():
    subs = []
    rosters = {}
    # Alice vs Bob as opponents in 2 different games (bitter rivals)
    for i, sid in enumerate((10, 11)):
        subs.append(sub(sid, "Alice", "1", ts=f"2026-07-2{i+1} 12:00:00"))
        rosters[str(sid)] = [entry("Bob", "enemy")]
    # Carol + Dave on the same team in 2 games (inseparable)
    for i, sid in enumerate((20, 21)):
        subs.append(sub(sid, "Carol", "3", ts=f"2026-07-2{i+1} 15:00:00"))
        rosters[str(sid)] = [entry("Dave", "team")]
    awards = compute_pair_awards(subs, rosters, IGN, min_meetings=2)
    assert awards['bitter_rivals'] and awards['bitter_rivals']['clashes'] == 2
    assert {awards['bitter_rivals']['a'], awards['bitter_rivals']['b']} == {"Alice", "Bob"}
    assert awards['inseparable'] and awards['inseparable']['matches'] == 2
    assert {awards['inseparable']['a'], awards['inseparable']['b']} == {"Carol", "Dave"}


def test_pair_awards_ignore_one_offs():
    subs = [sub(10, "Alice", "1")]
    rosters = {"10": [entry("Bob", "enemy")]}
    awards = compute_pair_awards(subs, rosters, IGN, min_meetings=2)
    assert awards['bitter_rivals'] is None and awards['inseparable'] is None
