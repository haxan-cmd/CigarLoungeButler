"""Regression evals — each test pins a bug that actually shipped, so a future
refactor can't silently bring it back. Pure (utils + config only); runs in the
standard `pytest -q`. Cog-level / behavioural cases live in
tests/integration/test_butler_regressions.py, and the methodology (incl. the
optional LLM behavioural layer) is documented in docs/EVALS.md.

Each test names the incident it guards in a comment.
"""
from utils.boards import board_unit, is_kills_board, is_feat_board, is_archer_weapon


# INCIDENT: the Score board (match POINTS) rendered on the card/dossier as "27799 TD".
def test_score_board_is_points_not_takedowns():
    assert board_unit("Score") == "points"
    assert board_unit("Score") != "TDs"


# INCIDENT: personal-best "best takedowns" must only pull from real TD boards.
def test_weapon_and_map_boards_are_takedowns():
    assert board_unit("Messer") == "TDs"
    assert board_unit("Falmire - Agatha") == "TDs"


# INCIDENT: a "{weapon} Kills" companion stores KILLS but board_unit() reports 'TDs';
# consumers MUST gate on is_kills_board first, or a kills score is counted as a TD PB.
def test_kills_companion_must_be_flagged_as_kills_board():
    assert is_kills_board("Messer Kills") is True
    assert is_kills_board("Messer") is False
    # board_unit alone is NOT sufficient to exclude it — this is the trap the fix guards.
    assert board_unit("Messer Kills") == "TDs"
    assert board_unit("100 Kills") == "kills"


# INCIDENT: TUFF is a kill-margin board, never takedowns.
def test_tuff_is_kill_margin():
    assert board_unit("TUFF") != "TDs"


# INCIDENT: Healing boards store a HEALING total, but defaulted to 'TDs', so a player's
# healing-banner score showed up as their "highest takedowns" on the profile.
def test_healing_boards_are_not_takedowns():
    assert board_unit("Healing Banner") != "TDs"
    assert board_unit("Healing Horn") != "TDs"
    # Mallet / Knife ARE takedown-ranked boards, so those must stay 'TDs'.
    assert board_unit("Mallet") == "TDs"
    assert board_unit("Knife") == "TDs"


# INCIDENT: kill-record vs king (feat classification feeds titles + routing).
def test_feat_board_classification():
    assert is_feat_board("100 Kills")
    assert is_feat_board("200 Takedowns")
    assert not is_feat_board("Messer")


# INCIDENT: archer weapons are excluded BY POLICY from the melee titles.
def test_archer_weapons_flagged():
    assert is_archer_weapon("Bow")
    assert not is_archer_weapon("Messer")
