"""Integration tests for the title / board-count math
(cogs/favourites.py `_calculate_butler_stats_uncached`) against the FakeDB.

Policy (updated): a weapon's Highest-Kills companion board ("Messer Kills") DOES
count as its own board toward the titles now — each weapon can contribute both its
takedown board and its Kills board. Archer/ranged weapons (and their Kills boards),
non-weapon feat boards (Score/TUFF/…), and the 100 Kills / 200 Takedowns boards are
still excluded. These tests lock which board lands in (or out of) the right bucket.

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


def test_kills_companion_counts_as_weapon_board(fake_db):
    # "Messer" and its "Messer Kills" companion each count as a board now.
    fake_db.leaderboard_data = [lb("Messer", "Alice"), lb("Messer Kills", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 2


def test_kills_companions_each_count(fake_db):
    # 3 weapons + their 3 Kills companions = 6 weapon boards under the new policy.
    fake_db.leaderboard_data = [
        lb("Messer", "Alice"),      lb("Messer Kills", "Alice"),
        lb("Maul", "Alice"),        lb("Maul Kills", "Alice"),
        lb("Longsword", "Alice"),   lb("Longsword Kills", "Alice"),
    ]
    assert stats(fake_db)["_weapon_board_total"] == 6


def test_archer_kills_board_still_excluded(fake_db):
    # Archer weapons and their Kills companions stay out of the melee titles.
    from utils.boards import archer_weapons
    aw = sorted(archer_weapons())[0]
    fake_db.leaderboard_data = [lb(aw, "Alice"), lb(aw + " Kills", "Alice")]
    assert stats(fake_db)["_weapon_board_total"] == 0


def test_map_board_counted_separately_from_weapons(fake_db):
    fake_db.leaderboard_data = [lb("Messer", "Alice"), lb("Falmire - Agatha", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 1
    assert s["_map_board_total"] == 1


def test_feat_board_excluded_from_weapon_count(fake_db):
    # Score / TUFF / Pacifist etc. are non-weapon feat boards: they count toward
    # NEITHER Weapons Master nor Grand Marshal, and must not inflate any board total.
    fake_db.leaderboard_data = [lb("Score", "Alice"), lb("TUFF", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 0
    assert s["_map_board_total"] == 0


def test_grand_marshal_count_is_weapons_plus_maps_only(fake_db):
    # Regression: Grand Marshal's per-player count must equal weapon + map placements,
    # never inflated by feat boards (the 62/64-vs-59 mismatch). Alice sits on 2 weapon
    # boards + 1 map board + 2 feat boards; her combined placement list must be length 3.
    fake_db.leaderboard_data = [
        lb("Messer", "Alice"), lb("Maul", "Alice"),
        lb("Falmire - Agatha", "Alice"),
        lb("Score", "Alice"), lb("TUFF", "Alice"),
    ]
    s = stats(fake_db)
    assert len(s["_combined_placements"]["Alice"]) == 3
    assert len(s["_weapon_placements"]["Alice"]) == 2
    assert len(s["_map_placements"]["Alice"]) == 1
    # And the count never exceeds the denominator.
    assert len(s["_combined_placements"]["Alice"]) <= s["_combined_board_total"]


def test_hundred_kills_and_takedowns_boards_excluded(fake_db):
    # 100 Kills / 200 Takedowns are their own thing — excluded from board totals.
    fake_db.leaderboard_data = [lb("100 Kills", "Alice"), lb("200 Takedowns", "Alice")]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 0 and s["_map_board_total"] == 0


def test_combined_total_is_weapons_plus_maps(fake_db):
    fake_db.leaderboard_data = [
        lb("Messer", "Alice"), lb("Maul", "Alice"),      # 2 weapon TD boards
        lb("Messer Kills", "Alice"),                     # companion, now counts (3rd weapon board)
        lb("Falmire - Agatha", "Alice"),                 # 1 map
        lb("Score", "Alice"),                            # feat, ignored
    ]
    s = stats(fake_db)
    assert s["_weapon_board_total"] == 3
    assert s["_map_board_total"] == 1
    assert s["_combined_board_total"] == 4


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
