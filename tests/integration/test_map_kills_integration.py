"""Locks the map Kills-companion board: the "{Map} - {Faction} Kills" name
collides with both the map detector (' - ') and the kills detector (' Kills'),
so classification order matters. Also guards that a map-kills board does NOT
inflate the Campaign Master map count (mirrors the weapon "81 boards" fix).

Skipped where discord/asyncpg aren't installed (see conftest).
"""
import asyncio
import pytest

pytest.importorskip("discord")
pytest.importorskip("asyncpg")

import config
from cogs.leaderboards import _classify_board, _map_kills_ranking
from cogs.favourites import _calculate_butler_stats_uncached

_MAP = next(iter(config.MAP_ATTACK_DEFENSE))


def run(coro):
    return asyncio.run(coro)


def lb(board, player="Alice", score=100, did="1"):
    return [board, player, did, str(score), "l", ""]


def test_map_kills_classifies_before_plain_map():
    assert _classify_board(f"{_MAP} - Agatha", "") == "map"
    assert _classify_board(f"{_MAP} - Agatha Kills", "") == "map_kills"
    assert _classify_board(f"{_MAP} - Agatha Kills", "map_kills") == "map_kills"
    # weapon kills unaffected
    assert _classify_board("Messer Kills", "") == "weapon_kills"
    assert _classify_board("100 Kills", "") == "feat"


def test_map_kills_not_counted_in_campaign_master_total(fake_db):
    fake_db.leaderboard_data = [lb(f"{_MAP} - Agatha"), lb(f"{_MAP} - Agatha Kills")]
    s = run(_calculate_butler_stats_uncached())
    assert s["_map_board_total"] == 1   # the kills companion is not a second map board


def test_archer_weapons_excluded_from_melee_titles(fake_db):
    # Two melee weapon boards + two Archer/ranged boards. Only the melee ones count
    # toward Weapons Master / Grand Marshal.
    fake_db.leaderboard_data = [
        lb("Messer"), lb("Maul"),          # melee -> count
        lb("Bow"), lb("Crossbow"),         # archer -> excluded
    ]
    s = run(_calculate_butler_stats_uncached())
    assert s["_weapon_board_total"] == 2
    assert s["_combined_board_total"] == 2   # combined = weapon + map, archer not in either


def test_inline_map_kills_ranking(make_sub):
    # The Kills section rendered inside the map embed: best kills per player on
    # that map/faction, VIP included, unlisted excluded, other factions ignored.
    subs = [
        make_sub(did="1", name="Alice", kills=90, map_=_MAP, faction="Agatha", link="a90"),
        make_sub(did="1", name="Alice", kills=70, map_=_MAP, faction="Agatha", link="a70"),  # lower, dropped
        make_sub(did="2", name="Bob", kills=110, map_=_MAP, faction="Agatha", vip="Yes", link="b110"),
        make_sub(did="3", name="Cara", kills=200, map_=_MAP, faction="Mason", link="c"),   # other faction
        make_sub(did="4", name="Dan", kills=95, map_=_MAP, faction="Agatha", feats="Unlisted", link="d"),
    ]
    ranking = _map_kills_ranking(f"{_MAP} - Agatha", subs)
    # (name, best_kills, link-of-that-run) — Alice's link is her 90 run, not the 70.
    assert ranking == [("Bob", 110, "b110"), ("Alice", 90, "a90")]
