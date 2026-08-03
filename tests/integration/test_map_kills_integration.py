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
from cogs.leaderboards import _classify_board
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
