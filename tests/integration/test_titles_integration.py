"""Integration tests for the title / board-count math
(cogs/favourites.py `_calculate_butler_stats_uncached`) against the FakeDB.

This is the code that produced the "81 boards" Weapons Master inflation: a
weapon's Highest-Kills companion board ("Messer Kills") was being counted as a
separate weapon board, roughly doubling everyone's weapon-board tally and handing
the title to the wrong player. These tests lock the fix — Kills boards, map
boards, feat boards, and the 100 Kills / 200 Takedowns boards must each land in
(or out of) the right bucket — so a future edit can't silently re-inflate it.

We call the uncached builder directly to bypass the memo + data_version cache.
Skipped where discord/asyncpg aren't installed (see conftest).
"""
import asyncio
import pytest

pytest.importorskip("discord")
pytest.importorskip("asyncpg")

from cogs.favourites import _calculate_butler_stats_uncached


def run(coro):
    return asyncio.run(coro)


def lb(board, player, score=100, did="1"):
    """leaderboard_data row: [board, player, discord_id, score, link, weapon]."""
    return [board, player, did, str(score), "l", ""]


def stats(fake_db):
    return run(_calculate_butler_stats_uncached())


def test_kills_companion_not_counted_as_weapon_board(fake_db):
    # "Messer" is a weapon board; "Messer Kills" is its companion, NOT a 2nd board.
    fake_db.leaderboard_data = [lb("Messer", "Alice"), lb("Messer Kills", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 1


def test_kills_companions_dont_double_the_tally(fake_db):
    # The exact "81 boards" regression: 3 weapons + their 3 Kills companions must
    # count as 3 weapon boards, not 6.
    fake_db.leaderboard_data = [
        lb("Messer", "Alice"),      lb("Messer Kills", "Alice"),
        lb("Maul", "Alice"),        lb("Maul Kills", "Alice"),
        lb("Longsword", "Alice"),   lb("Longsword Kills", "Alice"),
    ]
    assert stats(fake_db)["_weapon_board_total"] == 3


def test_map_board_counted_separately_from_weapons(fake_db):
    fake_db.leaderboard_data = [lb("Messer", "Alice"), lb("Falmire - Agatha", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 1
    assert s["_map_board_total"] == 1


def test_feat_board_excluded_from_weapon_count(fake_db):
    # Score / TUFF / Pacifist etc. are non-weapon feat boards: they count toward
    # Grand Marshal placement but must NOT inflate the weapon-board total.
    fake_db.leaderboard_data = [lb("Score", "Alice"), lb("TUFF", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 0
    assert s["_map_board_total"] == 0


def test_hundred_kills_and_takedowns_boards_excluded(fake_db):
    # 100 Kills / 200 Takedowns are their own thing — excluded from board totals.
    fake_db.leaderboard_data = [lb("100 Kills", "Alice"), lb("200 Takedowns", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 0 and s["_map_board_total"] == 0


def test_combined_total_is_weapons_plus_maps(fake_db):
    fake_db.leaderboard_data = [
        lb("Messer", "Alice"), lb("Maul", "Alice"),      # 2 weapons
        lb("Messer Kills", "Alice"),                     # companion, ignored
        lb("Falmire - Agatha", "Alice"),                 # 1 map
        lb("Score", "Alice"),                            # feat, ignored
    ]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 2
    assert s["_map_board_total"] == 1
    assert s["_combined_board_total"] == 3


def _many_weapon_boards(n, player="Alice"):
    weapons = ["Messer", "Maul", "Longsword", "Greatsword", "Poleaxe", "Warhammer",
               "Axe", "Mace", "Spear", "Halberd", "Falchion", "Dagger"]
    return [lb(weapons[i], player) for i in range(n)]


def test_weapons_master_needs_nine_boards(fake_db):
    # min_boards=9 for the Weapons Master title.
    fake_db.leaderboard_data = _many_weapon_boards(8)
    assert stats(fake_db)["weapons_master"] == "N/A"

    fake_db.leaderboard_data = _many_weapon_boards(9)
    assert stats(fake_db)["weapons_master"] == "Alice"
