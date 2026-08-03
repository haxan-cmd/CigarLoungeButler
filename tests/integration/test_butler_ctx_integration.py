"""Integration tests for the Butler context builder
(cogs/personality.py `_build_player_stats_ctx`), extracted from on_message so it
can be exercised in isolation against the FakeDB.

The bug this guards: the per-player context has no natural size limit — a heavy
player (77 boards, 40 weapons) once ballooned the prompt to ~8k chars and the
no-reasoning model deflected ("I don't have your data") even though everything
was present. The fix caps the standings list at 20. These tests lock that cap and
the overall bound, so a future edit can't silently reintroduce the balloon.

The method takes no `self` state, only `message.author.id` and the resolved
question, so we can call it unbound with a tiny fake message. Skipped where
discord/asyncpg aren't installed (see conftest).
"""
import asyncio
import pytest

pytest.importorskip("discord")
pytest.importorskip("asyncpg")

from cogs.personality import PersonalityCog


def run(coro):
    return asyncio.run(coro)


class _Author:
    def __init__(self, uid):
        self.id = uid
        self.bot = False
        self.display_name = "Alice"
        self.roles = []


class _Msg:
    def __init__(self, uid):
        self.author = _Author(uid)


def build_ctx(fake_db, did="1", content="butler how am i doing", is_data=False):
    msg = _Msg(int(did))
    # signature: (self, message, discord_id_str, player_name, resolved_message, content_lower, _is_data_q)
    return run(PersonalityCog._build_player_stats_ctx(
        None, msg, did, "Alice", content, content, is_data))


def _player_row(did="1", name="Alice", marks="100", count="40"):
    # players row: 0 did · 1 name · 2 thread · 3 marks · 4 count · 5 last · 6 wmarks · 7 cmarks
    return [did, name, "", marks, count, "", "", ""]


def _weapon_boards(n, player="Alice", did="1"):
    # one leaderboard_data row per distinct weapon board, player ranked #1 on each.
    return [[f"Weapon{i}", player, did, "500", "l", ""] for i in range(n)]


def test_player_core_stats_present(fake_db, make_sub):
    fake_db.players = [_player_row()]
    fake_db.submissions = [make_sub(did="1", name="Alice", weapon="Messer", td=200, kills=90)]
    ctx = build_ctx(fake_db)
    assert "Player stats" in ctx and "Logged runs" in ctx


def _listed_boards(ctx):
    # Every listed standing ends in "…, rank/entries)"; our synthetic boards all
    # have exactly one entry, so each rendered entry ends with "/1)". Counting them
    # is the real test of the cap — the label text is emitted regardless.
    return ctx.count("/1)")


def test_standings_capped_at_twenty_for_heavy_player(fake_db, make_sub):
    # 40 boards -> only 20 actually listed, with an explicit "+20 more boards" tail.
    fake_db.players = [_player_row()]
    fake_db.submissions = [make_sub(did="1", name="Alice")]
    fake_db.leaderboard_data = _weapon_boards(40)
    ctx = build_ctx(fake_db)
    assert "on 40 boards" in ctx          # knows the true total
    assert _listed_boards(ctx) == 20      # but lists only 20 (this is the cap)


def test_context_stays_bounded_regardless_of_board_count(fake_db, make_sub):
    # The balloon was ~8129 chars at 77 boards. However many boards a player holds,
    # the standings list must stay pinned at 20 entries so the prompt can't balloon.
    fake_db.players = [_player_row(count="60")]
    fake_db.submissions = [make_sub(did="1", name="Alice")]
    fake_db.leaderboard_data = _weapon_boards(60)
    ctx = build_ctx(fake_db)
    assert "+40 more boards" in ctx        # 60 - 20
    assert _listed_boards(ctx) == 20       # still only 20 listed at 60 boards
    assert len(ctx) < 8000                 # never re-approaches the balloon size


def test_no_boards_reports_none(fake_db, make_sub):
    fake_db.players = [_player_row(count="0")]
    fake_db.submissions = [make_sub(did="1", name="Alice")]
    fake_db.leaderboard_data = []
    ctx = build_ctx(fake_db)
    assert "Leaderboard standings: none recorded" in ctx
