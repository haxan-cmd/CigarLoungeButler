"""Tests for utils.goals — the nearest-target-per-track picker."""
from utils.goals import next_goals

RANKS = [(1, "Bronze"), (5, "Silver"), (12, "Gold"), (25, "Emerald")]
KW = dict(mastery_threshold=100, virtuoso_threshold=250, rank_thresholds=RANKS)


def test_rank_up_picks_the_closest_weapon():
    g = next_goals({"Messer": 4, "Axe": 2}, [], hh_total=46, **KW)
    # Messer 4 -> Silver(5) needs 1; Axe 2 -> Silver needs 3. Messer wins.
    assert g['rank_up']['weapon'] == "Messer" and g['rank_up']['remaining'] == 1
    assert g['rank_up']['target'] == "Silver"


def test_mastery_vs_virtuoso():
    # A weapon between mastery and virtuoso chases Virtuoso.
    g = next_goals({"Messer": 180, "Axe": 40}, [], **KW)
    assert g['mastery']['kind'] == 'virtuoso' and g['mastery']['weapon'] == "Messer"
    assert g['mastery']['remaining'] == 70
    # Without a mastered weapon, chase the closest to Mastery.
    g2 = next_goals({"Axe": 90, "Messer": 40}, [], **KW)
    assert g2['mastery']['kind'] == 'mastery' and g2['mastery']['weapon'] == "Axe"
    assert g2['mastery']['remaining'] == 10


def test_hundred_handed_counts_and_names_closest_subclass():
    missing = [("Crusader", "Messer"), ("Crusader", "Axe"), ("Raider", "Glaive")]
    g = next_goals({"Messer": 3}, missing, hh_total=46, **KW)
    hh = g['hundred_handed']
    assert hh['remaining'] == 3 and hh['done'] == 43 and hh['total'] == 46
    # Raider is closest (1 owed) so it's named as the concrete next step.
    assert hh['closest_subclass'] == "Raider" and hh['closest_weapons'] == ["Glaive"]


def test_nearest_is_the_smallest_remaining_across_tracks():
    g = next_goals({"Messer": 4}, [("Crusader", "Axe")] * 5, hh_total=46, **KW)
    # rank_up remaining 1 beats hundred_handed remaining 5.
    assert g['nearest']['kind'] == 'rank_up' and g['nearest']['remaining'] == 1


def test_all_none_when_no_progress():
    g = next_goals({}, [], **KW)
    assert g['rank_up'] is None and g['mastery'] is None
    assert g['hundred_handed'] is None and g['nearest'] is None


def test_top_rank_weapon_has_no_rank_up():
    g = next_goals({"Messer": 999}, [], **KW)
    assert g['rank_up'] is None
