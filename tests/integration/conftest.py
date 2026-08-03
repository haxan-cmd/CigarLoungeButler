"""Integration-test harness.

Runs cog-level logic (mark calculation, board placement) end-to-end against an
in-memory FakeDB instead of a real Postgres, and against plain stubs instead of
Discord. This is where the bugs actually lived this year (double-counting,
score-as-takedowns, kills-boards-in-titles, id-vs-name matching) — none of which
the pure-`utils` tests could reach, because the logic sits in cogs that import
discord + asyncpg.

The whole package is SKIPPED where discord/asyncpg aren't installed (the pure-unit
CI that installs only pytest+dotenv), so it never breaks the green `pytest -q`.
Locally / in a full env it runs.

Tests are plain sync functions that drive the async code with `run(coro)` — no
pytest-asyncio dependency.
"""
import asyncio
import pytest

# Skip the entire integration package unless the real runtime deps are present.
pytest.importorskip("discord")
pytest.importorskip("asyncpg")

import utils.db as _db


def run(coro):
    """Drive an async call synchronously (no pytest-asyncio needed)."""
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class FakeDB:
    """In-memory stand-in for the Postgres layer. Holds the legacy row-shaped
    tables the mark/board code reads, with async shims matching utils/db.py."""

    def __init__(self):
        self.submissions = []       # submission row shape (list[str], 27 cols)
        self.leaderboard_data = []  # [board, name, did, score, link, weapon]
        self.players = []           # [did, name, thread, marks, count, last, wmarks, cmarks, ...]
        self.legacy_marks = []      # [name, weapon, subclass, marks, did]

    async def get_all_submissions(self):
        return [list(r) for r in self.submissions]

    async def get_all_leaderboard_data(self):
        return [list(r) for r in self.leaderboard_data]

    async def get_all_players(self):
        return [list(r) for r in self.players]

    async def get_submissions_by_player(self, discord_id, limit=None):
        rows = [list(r) for r in self.submissions if len(r) > 2 and r[2] == str(discord_id)]
        return rows[:limit] if limit else rows

    async def get_legacy_marks_for_player(self, player_name, discord_id=None):
        return [list(r) for r in self.legacy_marks
                if ((r[0] or '').strip().lower() == (player_name or '').strip().lower())
                or (len(r) > 4 and str(r[4] or '') == str(discord_id or '') and discord_id)]

    async def get_leaderboard_by_board(self, board):
        return [list(r) for r in self.leaderboard_data if r and r[0] == board]


@pytest.fixture
def fake_db(monkeypatch):
    """Monkeypatch utils.db's read functions onto an in-memory FakeDB. Cogs do
    `import utils.db as _db`, so patching the module attribute reaches them."""
    fdb = FakeDB()
    for name in ("get_all_submissions", "get_all_leaderboard_data", "get_all_players",
                 "get_submissions_by_player", "get_legacy_marks_for_player",
                 "get_leaderboard_by_board"):
        monkeypatch.setattr(_db, name, getattr(fdb, name))
    return fdb


@pytest.fixture
def make_sub():
    """Factory for a submission row (legacy list-of-strings shape). Indices:
    0 ts · 1 name · 2 did · 3 weapon · 4 subclass · 5 map · 6 faction · 7 td ·
    8 kills · 9 deaths · 10 vip · 11 feats · 12 link · 24 score."""
    def _sub(did="1", name="A", weapon="Messer", subclass="Crusader", td=120,
             kills=50, deaths=10, vip="No", feats="", link="l1", score=None,
             map_="Falmire", faction="Agatha", ts="2026-08-01 12:00:00"):
        r = [""] * 27
        r[0] = ts; r[1] = name; r[2] = str(did); r[3] = weapon; r[4] = subclass
        r[5] = map_; r[6] = faction; r[7] = str(td); r[8] = str(kills); r[9] = str(deaths)
        r[10] = vip; r[11] = feats; r[12] = link
        if score is not None:
            r[24] = str(score)
        return r
    return _sub
