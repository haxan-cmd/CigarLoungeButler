"""Tests for utils.feats — the shared feat-derivation logic used by both the
submission finalise path and the edit path."""
from utils.feats import (is_pacifist, is_triple_run, derive_stat_feats, tilt_mark,
                         run_marks, is_excluded)


def test_run_marks_base_and_stacks():
    # Base submission mark, then +1 per stacking feat tag.
    assert run_marks("Messer", 40, 120, []) == 1
    assert run_marks("Messer", 120, 210, ["200 Takedowns", "100 Kills"]) == 3
    assert run_marks("Messer", 120, 210, ["Triple", "100 Kills", "200 Takedowns"]) == 4


def test_run_marks_score_and_high_score_distinct():
    # 'Score' is a token, NOT a substring of 'High Score' — both count.
    assert run_marks("Messer", 40, 120, ["High Score"]) == 2
    assert run_marks("Messer", 40, 120, ["Score"]) == 2
    assert run_marks("Messer", 40, 120, ["High Score", "Score"]) == 3


def test_run_marks_hybrid_and_pacifist_earn_nothing():
    assert run_marks("Hybrid", 120, 200, ["Triple"]) == 0     # Hybrid never earns marks
    assert run_marks("Messer", 0, 5, []) == 0                 # pacifist (0 K, <=10 TD)
    assert run_marks("Other", 120, 200, []) == 0


def test_run_marks_valor_added_and_string_feats_ok():
    assert run_marks("Messer", 40, 160, ["Outmatched"], valor_marks=2) == 3   # 1 + valor 2
    # feats may arrive as a comma string too (blurb passes a string sometimes).
    assert run_marks("Messer", 120, 210, "200 Takedowns, 100 Kills") == 3


def test_is_excluded():
    assert is_excluded("Resubmit") is True
    assert is_excluded("Triple, Unlisted") is True
    assert is_excluded(["Resubmit"]) is True
    assert is_excluded("Triple, Flawless") is False
    assert is_excluded("") is False
    assert is_excluded([]) is False

# (low_gap, name, emoji, marks, tag) — hardest first, mirrors config.TILT_BANDS shape
_BANDS = [
    (99, "Brutal", "🔴", 3, "Brutal"),
    (30, "Outmatched", "🟠", 2, "Outmatched"),
    (10, "Slightly Uphill", "🟡", 1, "Uphill"),
    (0, "Even", "🟢", 0, None),
]


def test_tilt_mark_matches_band_by_tag():
    assert tilt_mark(["Brutal"], _BANDS) == (3, "🔴", "Brutal")
    assert tilt_mark(["Outmatched"], _BANDS) == (2, "🟠", "Outmatched")
    assert tilt_mark(["Uphill"], _BANDS) == (1, "🟡", "Slightly Uphill")


def test_tilt_mark_none_when_no_tilt_tag():
    assert tilt_mark(["100 Kills", "Flawless"], _BANDS) == (0, None, None)
    assert tilt_mark([], _BANDS) == (0, None, None)


def test_tilt_mark_first_match_wins():
    # a run should only ever carry one tilt tag, but if two appear the hardest (first) wins
    assert tilt_mark(["Uphill", "Brutal"], _BANDS) == (3, "🔴", "Brutal")

FEAT_WEAPONS = {"Mallet", "Knife"}


def test_pacifist():
    assert is_pacifist(0, 10) is True
    assert is_pacifist(0, 11) is False      # too many takedowns
    assert is_pacifist(1, 5) is False       # has a kill
    assert is_pacifist(0, 0) is True


def test_triple_requires_all_three_gates():
    # thresholds: 150 TD, 100 K, and the 20k bar (confirmed or score>=20000)
    assert is_triple_run(100, 150, 20000) is True          # score meets bar
    assert is_triple_run(100, 150, None, confirmed=True) is True  # confirmed
    assert is_triple_run(100, 150, 19999) is False         # under 20k, unconfirmed
    assert is_triple_run(99, 150, 25000) is False          # kills short
    assert is_triple_run(100, 149, 25000) is False         # takedowns short
    assert is_triple_run(100, 150, None) is False          # no score, no confirm
    # A READ score below the bar can't be overridden by a manual 20k+ confirmation
    # (the Nildain case: confirmed YES but the scorecard read 19,500).
    assert is_triple_run(100, 150, 19500, confirmed=True) is False
    # Confirmation only fills in when the score is unreadable (None).
    assert is_triple_run(100, 150, None, confirmed=True) is True


def test_triple_stacks_100k_200td():
    # Feats STACK: a Triple that also clears 100 kills / 200 takedowns banks a mark
    # for each milestone, not just the Triple. (120 K, 210 TD -> all three.)
    feats = derive_stat_feats(120, 210, 3, "Longsword", FEAT_WEAPONS, triple=True)
    assert "Triple" in feats
    assert "100 Kills" in feats
    assert "200 Takedowns" in feats


def test_triple_under_200td_stacks_only_100k():
    # A Triple needs 150+ TD, not 200 — so a 150-199 TD Triple stacks 100 Kills but
    # not 200 Takedowns.
    feats = derive_stat_feats(110, 160, 3, "Longsword", FEAT_WEAPONS, triple=True)
    assert "Triple" in feats
    assert "100 Kills" in feats
    assert "200 Takedowns" not in feats


def test_non_triple_100k_and_200td():
    feats = derive_stat_feats(120, 210, 3, "Longsword", FEAT_WEAPONS, triple=False)
    assert feats.count("100 Kills") == 1
    assert feats.count("200 Takedowns") == 1
    assert "Triple" not in feats


def test_flawless_needs_zero_deaths_and_not_pacifist():
    assert "Flawless" in derive_stat_feats(50, 80, 0, "Axe", FEAT_WEAPONS, triple=False)
    assert "Flawless" not in derive_stat_feats(50, 80, 1, "Axe", FEAT_WEAPONS, triple=False)
    # a 0-death pacifist run (0 kills, <=10 TD) is NOT flawless
    assert "Flawless" not in derive_stat_feats(0, 8, 0, "Axe", FEAT_WEAPONS, triple=False)


def test_predator_needs_150td_no_deaths():
    assert "Predator" in derive_stat_feats(40, 150, 0, "Axe", FEAT_WEAPONS, triple=False)
    assert "Predator" not in derive_stat_feats(40, 150, 2, "Axe", FEAT_WEAPONS, triple=False)
    assert "Predator" not in derive_stat_feats(40, 149, 0, "Axe", FEAT_WEAPONS, triple=False)


def test_weapon_feat_only_for_feat_weapons_at_100_kills():
    assert "Mallet" in derive_stat_feats(100, 60, 4, "Mallet", FEAT_WEAPONS, triple=False)
    assert "Mallet" not in derive_stat_feats(99, 60, 4, "Mallet", FEAT_WEAPONS, triple=False)
    # a non-feat weapon never gets a weapon feat
    assert "Longsword" not in derive_stat_feats(120, 60, 4, "Longsword", FEAT_WEAPONS, triple=False)


def test_canonical_order_stacked_run():
    # a monster non-triple run: 100k + 200td + flawless + predator + feat weapon
    feats = derive_stat_feats(120, 210, 0, "Knife", FEAT_WEAPONS, triple=False)
    assert feats == ["100 Kills", "200 Takedowns", "Flawless", "Predator", "Knife"]
