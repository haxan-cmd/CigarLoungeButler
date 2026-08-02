"""Tests for utils.boards — the single source of truth for board classification.

These lock the exact bugs we just fixed: the Score board must NOT count as a
weapon board (Weapons Master inflation), and board score-units must not report
Score points as takedowns. If a future board is added and mis-categorised, these
fail loudly instead of silently corrupting titles.
"""
import config
from utils import boards as b


def test_feat_set_contains_the_new_boards():
    for name in ("Score", "Hybrid", "Mallet", "Knife", "TUFF", "Pacifist",
                 "100 Kills", "200 Takedowns", "Triple", "Flawless"):
        assert b.is_feat_board(name), f"{name} should be a feat board"


def test_non_weapon_feat_boards_excludes_score_and_the_carriers():
    nw = b.non_weapon_feat_boards()
    # The bug: these were counting as WEAPON boards -> Weapons Master inflated.
    for name in ("Score", "TUFF", "Pacifist", "Triple", "Hybrid",
                 "Flawless", "Healing Horn", "Healing Banner"):
        assert name in nw, f"{name} must be a NON-weapon feat board"
    # Weapon-specific feats and the counted-elsewhere boards stay OUT.
    for name in ("Mallet", "Knife", "100 Kills", "200 Takedowns", "The Hundred Handed"):
        assert name not in nw, f"{name} must NOT be in non_weapon_feat_boards"


def test_a_real_weapon_board_is_not_feat_map_or_kills():
    for w in ("Messer", "Longsword", "Two-Handed Hammer"):
        assert not b.is_feat_board(w)
        assert not b.is_map_board(w)
        assert not b.is_kills_board(w)


def test_kills_board_detection():
    assert b.is_kills_board("Messer Kills")
    assert not b.is_kills_board("100 Kills")     # feat board, not a per-weapon kills board
    assert not b.is_kills_board("Messer")


def test_map_board_detection_uses_real_maps():
    # Every real map/faction pair is a map board.
    for mp in config.MAP_ATTACK_DEFENSE:
        assert b.is_map_board(f"{mp} - Agatha")
    assert not b.is_map_board("Messer")
    assert not b.is_map_board("Nonexistent Keep - Agatha")


def test_board_unit_never_calls_points_takedowns():
    assert b.board_unit("Score") == "points"
    assert b.board_unit("Top Score") == "points"      # pre-rename alias
    assert b.board_unit("Pacifist") == "points"
    assert b.board_unit("100 Kills") == "kills"
    assert b.board_unit("TUFF") == "kill margin"
    # Real weapon/map boards are takedown boards.
    assert b.board_unit("Messer") == "TDs"
    assert b.board_unit("Coxwell - Agatha") == "TDs"
