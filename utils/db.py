"""
utils/db.py — Async Postgres layer replacing utils/sheets.py.

Drop-in replacement: same data shapes returned, no SheetCache needed.
Connection pool is initialised once on bot startup via db_init().
"""

import os
import json
import asyncpg
import time as _time
from datetime import datetime

_pool: asyncpg.Pool | None = None


async def db_init():
    """Call once at bot startup to create the connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        os.environ['DATABASE_URL'],
        min_size=2,
        max_size=10,
    )
    print("[DB] Postgres pool ready.")


async def db_close():
    """Call on bot shutdown."""
    if _pool:
        await _pool.close()


def _pool_check():
    if not _pool:
        raise RuntimeError("DB pool not initialised — call db_init() first.")
    return _pool


# ── In-memory read cache ────────────────────────────────────────────────────
# The full-table getters below (submissions / players / leaderboard_data) get
# hit repeatedly within a single event handler — a Butler chat reply alone can
# fetch the same table several times. Cache each briefly so those bursts collapse
# into one query. Writers invalidate the affected table immediately; the short
# TTL is a backstop so any missed invalidation self-heals within seconds.
# NOTE: returned lists are shared references — callers must treat them read-only,
# same contract as the old SheetCache this replaces.
_CACHE_TTL = 5.0  # seconds
_cache: dict = {}

def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (_time.monotonic() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None

def _cache_set(key: str, data: list):
    _cache[key] = (_time.monotonic(), data)

def _cache_invalidate(*keys: str):
    for k in keys:
        _cache.pop(k, None)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_submission(r) -> list:
    """Convert asyncpg Record to the same list format the cogs expect from Sheets."""
    return [
        r['submitted_at'].strftime('%Y-%m-%d %H:%M:%S') if r['submitted_at'] else '',
        r['player_name'] or '',
        r['discord_id'] or '',
        r['weapon'] or '',
        r['subclass'] or '',
        r['map'] or '',
        r['faction'] or '',
        str(r['takedowns']) if r['takedowns'] is not None else '',
        str(r['kills']) if r['kills'] is not None else '',
        str(r['deaths']) if r['deaths'] is not None else '',
        'Yes' if r['vip'] else 'No',
        r['feats'] or '',
        r['message_link'] or '',
        str(r['lobby_rank']) if r['lobby_rank'] is not None else '',
        str(r['lobby_size']) if r['lobby_size'] is not None else '',
        str(r['kills_rank']) if r['kills_rank'] is not None else '',
        str(r['team_rank']) if r['team_rank'] is not None else '',
        str(r['team_size']) if r['team_size'] is not None else '',
        str(r['total_lobby_kills']) if r['total_lobby_kills'] is not None else '',
        str(r['team_td_ratio']) if r['team_td_ratio'] is not None else '',
        str(r['team_kill_share']) if r['team_kill_share'] is not None else '',
        str(r['team_td_share']) if r['team_td_share'] is not None else '',
        str(r['second_place_td']) if r['second_place_td'] is not None else '',
        str(r['id']),  # row index equivalent
    ]


def _row_to_player(r) -> list:
    return [
        r['discord_id'] or '',
        r['player_name'] or '',
        r['forum_thread_id'] or '',
        str(r['total_marks']) if r['total_marks'] is not None else '0',
        str(r['submission_count']) if r['submission_count'] is not None else '0',
        str(r['last_submission']) if r['last_submission'] else '',
        r['weapon_marks'] or '',
        r['class_marks'] or '',
        # indices 8, 9, 10 — manual feat count overrides (None = not set, use auto)
        r['kills_100_count'] if 'kills_100_count' in r.keys() and r['kills_100_count'] is not None else None,
        r['takedowns_200_count'] if 'takedowns_200_count' in r.keys() and r['takedowns_200_count'] is not None else None,
        r['triple_count'] if 'triple_count' in r.keys() and r['triple_count'] is not None else None,
    ]


# ── Submissions ───────────────────────────────────────────────────────────────

async def get_all_submissions() -> list[list]:
    cached = _cache_get('submissions')
    if cached is not None:
        return cached
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM submissions ORDER BY id")
    data = [_row_to_submission(r) for r in rows]
    _cache_set('submissions', data)
    return data


async def get_submissions_by_player(discord_id, limit: int | None = None) -> list[list]:
    """Targeted fetch: one player's submissions, newest first — uses the
    submissions(discord_id) index instead of scanning the whole table.
    Pass a limit to cap the rows returned."""
    pool = _pool_check()
    q = "SELECT * FROM submissions WHERE discord_id=$1 ORDER BY id DESC"
    async with pool.acquire() as conn:
        if limit is not None:
            rows = await conn.fetch(q + " LIMIT $2", str(discord_id), limit)
        else:
            rows = await conn.fetch(q, str(discord_id))
    return [_row_to_submission(r) for r in rows]


async def add_submission(
    timestamp, discord_name, discord_id, weapon, cls, map_name, faction,
    takedowns, kills, deaths, vip, feats, message_link,
    lobby_rank=None, lobby_size=None, kills_rank=None,
    team_rank=None, team_size=None, total_lobby_kills=None,
    team_td_ratio=None, team_kill_share=None, team_td_share=None, second_place_td=None
) -> int:
    """Insert a submission and return its id (replaces sheet row index)."""
    _cache_invalidate('submissions')
    pool = _pool_check()
    vip_bool = vip if isinstance(vip, bool) else str(vip).upper() in ('YES', 'TRUE', '1')
    if isinstance(timestamp, str):
        try: timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        except: timestamp = None
    async with pool.acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO submissions
            (submitted_at, player_name, discord_id, weapon, subclass, map, faction,
             takedowns, kills, deaths, vip, feats, message_link,
             lobby_rank, lobby_size, kills_rank, team_rank, team_size,
             total_lobby_kills, team_td_ratio, team_kill_share, team_td_share, second_place_td)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
            RETURNING id
        """,
            timestamp, discord_name, str(discord_id), weapon, cls, map_name, faction,
            takedowns, kills, deaths, vip_bool, feats, message_link,
            lobby_rank, lobby_size, kills_rank, team_rank, team_size,
            total_lobby_kills, team_td_ratio, team_kill_share, team_td_share, second_place_td
        )
    return row_id


async def get_submission_feats(submission_id: int) -> str:
    """Return the feats string for a submission by id (empty string if not found)."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT feats FROM submissions WHERE id=$1", submission_id)
    return val or ''


async def update_submission_feats(submission_id: int, feats: str):
    _cache_invalidate('submissions')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE submissions SET feats=$1 WHERE id=$2", feats, submission_id
        )


async def update_submission_fields(submission_id: int, weapon: str, cls: str,
                                   map_name: str, faction: str, takedowns: int,
                                   kills: int, deaths: int, vip: bool, feats: str):
    """Update all editable fields on a submission row (used by edit flow)."""
    _cache_invalidate('submissions')
    pool = _pool_check()
    vip_bool = vip if isinstance(vip, bool) else str(vip).upper() in ('YES', 'TRUE', '1')
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE submissions
            SET weapon=$1, subclass=$2, map=$3, faction=$4,
                takedowns=$5, kills=$6, deaths=$7, vip=$8, feats=$9
            WHERE id=$10
        """, weapon, cls, map_name, faction, takedowns, kills, deaths, vip_bool, feats, submission_id)


async def check_duplicate_submission(discord_id: str, takedowns: int, kills: int,
                                     deaths: int, map_name: str, faction: str,
                                     cutoff_minutes: int = 5):
    """Return the weapon of a matching duplicate submission within the last N
    minutes, or None if no duplicate exists. (Used to return a plain bool — now
    returns the original weapon too, since callers need it to tell a genuine
    re-submission-with-corrected-weapon apart from an exact accidental repeat;
    see log_submission()/finalise_submission's dedup branch.)
    """
    pool = _pool_check()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT weapon FROM submissions
            WHERE discord_id=$1
              AND takedowns=$2 AND kills=$3 AND deaths=$4
              AND LOWER(map)=$5 AND LOWER(faction)=$6
              AND submitted_at > NOW() - ($7 || ' minutes')::INTERVAL
            LIMIT 1
        """, str(discord_id), takedowns, kills, deaths,
             (map_name or '').lower(), (faction or '').lower(),
             str(cutoff_minutes))
    return row['weapon'] if row else None


async def delete_submission_by_link(message_link: str):
    _cache_invalidate('submissions')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM submissions WHERE message_link=$1", message_link
        )


# ── Players ───────────────────────────────────────────────────────────────────

async def get_all_players() -> list[list]:
    cached = _cache_get('players')
    if cached is not None:
        return cached
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM players ORDER BY player_name")
    data = [_row_to_player(r) for r in rows]
    _cache_set('players', data)
    return data


async def get_player(discord_id: str) -> list | None:
    pool = _pool_check()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM players WHERE discord_id=$1", str(discord_id))
    return _row_to_player(r) if r else None


async def upsert_player(discord_id, player_name, forum_thread_id=None,
                         total_marks=0, submission_count=0, last_submission=None,
                         weapon_marks=None, class_marks=None):
    _cache_invalidate('players')
    pool = _pool_check()
    if isinstance(last_submission, str):
        try: last_submission = datetime.strptime(last_submission, '%Y-%m-%d %H:%M:%S')
        except: last_submission = None
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO players
            (discord_id, player_name, forum_thread_id, total_marks, submission_count,
             last_submission, weapon_marks, class_marks)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (discord_id) DO UPDATE SET
                player_name=EXCLUDED.player_name,
                forum_thread_id=COALESCE(EXCLUDED.forum_thread_id, players.forum_thread_id),
                total_marks=EXCLUDED.total_marks,
                submission_count=EXCLUDED.submission_count,
                last_submission=EXCLUDED.last_submission,
                weapon_marks=EXCLUDED.weapon_marks,
                class_marks=EXCLUDED.class_marks
        """,
            str(discord_id), player_name, forum_thread_id, total_marks,
            submission_count, last_submission, weapon_marks, class_marks
        )


async def get_player_igns(discord_id: str) -> list[str]:
    """Return all known in-game names for this player."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "ALTER TABLE players ADD COLUMN IF NOT EXISTS igns TEXT[] DEFAULT '{}'"
            )
            val = await conn.fetchval(
                "SELECT igns FROM players WHERE discord_id=$1", str(discord_id)
            )
            return list(val) if val else []
        except Exception:
            return []


async def save_player_ign(discord_id: str, ign: str):
    """Append a new in-game name alias if not already stored."""
    _cache_invalidate('players')
    pool = _pool_check()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "ALTER TABLE players ADD COLUMN IF NOT EXISTS igns TEXT[] DEFAULT '{}'"
            )
            # Append only if not already in the array
            await conn.execute(
                """UPDATE players SET igns = array_append(igns, $1)
                   WHERE discord_id=$2 AND NOT ($1 = ANY(COALESCE(igns, '{}')))""",
                ign, str(discord_id)
            )
            print(f"[IGN] Appended alias '{ign}' for discord_id={discord_id}")
        except Exception as e:
            print(f"[IGN] save failed: {e}")


async def increment_manual_feat_count(discord_id: str, feat: str):
    """Increment a manual feat count by 1 — only if the column is already set (not NULL).
    If NULL, does nothing so auto-detection continues to work for untracked players."""
    _cache_invalidate('players')
    col_map = {
        '100 kills':      'kills_100_count',
        '200 takedowns':  'takedowns_200_count',
        'triple':         'triple_count',
    }
    col = col_map.get(feat.lower().strip())
    if not col:
        return
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE players SET {col}={col}+1 WHERE discord_id=$1 AND {col} IS NOT NULL",
            str(discord_id)
        )


async def set_manual_feat_count(discord_id: str, feat: str, count: int):
    """Set a manual override count for 100 Kills, 200 Takedowns, or Triple on a player row."""
    _cache_invalidate('players')
    col_map = {
        '100 kills':      'kills_100_count',
        '200 takedowns':  'takedowns_200_count',
        'triple':         'triple_count',
    }
    col = col_map.get(feat.lower().strip())
    if not col:
        raise ValueError(f"Unknown feat '{feat}'. Use: 100 Kills, 200 Takedowns, Triple")
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            f"ALTER TABLE players ADD COLUMN IF NOT EXISTS kills_100_count INTEGER"
        )
        await conn.execute(
            f"ALTER TABLE players ADD COLUMN IF NOT EXISTS takedowns_200_count INTEGER"
        )
        await conn.execute(
            f"ALTER TABLE players ADD COLUMN IF NOT EXISTS triple_count INTEGER"
        )
        await conn.execute(
            f"UPDATE players SET {col}=$1 WHERE discord_id=$2",
            count, str(discord_id)
        )


async def update_player_thread(discord_id: str, thread_id: str):
    _cache_invalidate('players')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE players SET forum_thread_id=$1 WHERE discord_id=$2",
            thread_id, str(discord_id)
        )


# ── Leaderboards ──────────────────────────────────────────────────────────────

async def get_all_leaderboards() -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM leaderboards ORDER BY id")
    return [[r['board_name'], r['thread_id'] or '', r['message_ids'] or '', r['board_type'] or ''] for r in rows]


async def upsert_leaderboard(board_name, thread_id, message_ids, board_type):
    pool = _pool_check()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM leaderboards WHERE board_name=$1", board_name
        )
        if existing:
            await conn.execute(
                "UPDATE leaderboards SET thread_id=$1, message_ids=$2, board_type=$3 WHERE board_name=$4",
                thread_id, message_ids, board_type, board_name
            )
        else:
            await conn.execute(
                "INSERT INTO leaderboards (board_name, thread_id, message_ids, board_type) VALUES ($1,$2,$3,$4)",
                board_name, thread_id, message_ids, board_type
            )


async def update_leaderboard_messages(board_name: str, message_ids: str):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE leaderboards SET message_ids=$1 WHERE board_name=$2",
            message_ids, board_name
        )


# ── LeaderboardData ───────────────────────────────────────────────────────────

async def get_all_leaderboard_data() -> list[list]:
    cached = _cache_get('leaderboard_data')
    if cached is not None:
        return cached
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM leaderboard_data ORDER BY id")
    data = [
        [r['board_name'], r['player_name'], r['discord_id'] or '',
         str(r['score']) if r['score'] is not None else '', r['message_link'] or '', r['weapon'] or '']
        for r in rows
    ]
    _cache_set('leaderboard_data', data)
    return data


async def get_leaderboard_by_board(board_name: str) -> list[list]:
    """Targeted fetch: a single board's entries, highest score first — uses the
    leaderboard_data(board_name) index instead of scanning every board.
    Same row shape as get_all_leaderboard_data()."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM leaderboard_data WHERE board_name=$1 ORDER BY score DESC NULLS LAST",
            board_name)
    return [
        [r['board_name'], r['player_name'], r['discord_id'] or '',
         str(r['score']) if r['score'] is not None else '', r['message_link'] or '', r['weapon'] or '']
        for r in rows
    ]


async def count_board_scores_at_least(board_name: str, min_score: int) -> int:
    """Count entries on a board with score >= min_score (case-insensitive,
    whitespace-tolerant board match). One COUNT instead of fetching + filtering
    the entire leaderboard_data table in Python."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM leaderboard_data "
            "WHERE LOWER(TRIM(board_name)) = LOWER(TRIM($1)) AND score >= $2",
            board_name, min_score)
    return n or 0


async def get_leaderboard_position(board_name: str, score: int) -> int:
    """1-based rank a given score holds on a board = (entries strictly higher) + 1.
    One indexed COUNT instead of fetching the board and sorting in Python."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        higher = await conn.fetchval(
            "SELECT COUNT(*) FROM leaderboard_data WHERE board_name=$1 AND score > $2",
            board_name, score)
    return (higher or 0) + 1


async def upsert_leaderboard_entry(board_name, player_name, discord_id, score, message_link, weapon):
    _cache_invalidate('leaderboard_data')
    pool = _pool_check()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM leaderboard_data WHERE board_name=$1 AND discord_id=$2",
            board_name, str(discord_id)
        )
        if existing:
            await conn.execute("""
                UPDATE leaderboard_data
                SET player_name=$1, score=$2, message_link=$3, weapon=$4
                WHERE board_name=$5 AND discord_id=$6
            """, player_name, score, message_link, weapon, board_name, str(discord_id))
        else:
            await conn.execute("""
                INSERT INTO leaderboard_data (board_name, player_name, discord_id, score, message_link, weapon)
                VALUES ($1,$2,$3,$4,$5,$6)
            """, board_name, player_name, str(discord_id), score, message_link, weapon)


async def delete_leaderboard_entry(entry_id: int):
    _cache_invalidate('leaderboard_data')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM leaderboard_data WHERE id=$1", entry_id)


# ── Bounties ──────────────────────────────────────────────────────────────────

async def get_all_bounties() -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS bonus_completions TEXT DEFAULT '[]'"
        )
        rows = await conn.fetch("SELECT * FROM bounties ORDER BY id")
    return [
        [r['title'], r['channel_id'] or '', r['message_id'] or '', r['theme_emoji'] or '',
         r['weapons'] or '', r['special_challenge'] or '', '1' if r['special_done'] else '0',
         r['completions'] or '', 'TRUE' if r['active'] else 'FALSE', r['role_id'] or '',
         r['forum_channel_id'] or '', r['completions_msg_id'] or '', r['bonus_msg_id'] or '',
         r['progress_msg_id'] or '', str(r['start_date']) if r['start_date'] else '',
         str(r['id']), r['bonus_completions'] or '[]']
        for r in rows
    ]


async def update_bounty_field(bounty_id: int, field: str, value):
    pool = _pool_check()
    allowed = {'weapons', 'special_done', 'completions', 'bonus_completions', 'active', 'message_id',
               'completions_msg_id', 'bonus_msg_id', 'progress_msg_id', 'channel_id'}
    if field not in allowed:
        raise ValueError(f"Field {field} not allowed")
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE bounties SET {field}=$1 WHERE id=$2", value, bounty_id)


async def add_bounty(title, channel_id, message_id, theme_emoji, weapons,
                     special_challenge, active, role_id, forum_channel_id, start_date) -> int:
    pool = _pool_check()
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO bounties
            (title, channel_id, message_id, theme_emoji, weapons, special_challenge,
             active, role_id, forum_channel_id, start_date)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            RETURNING id
        """, title, channel_id, message_id, theme_emoji, weapons, special_challenge,
             active, role_id, forum_channel_id, start_date)


# ── BountyPlayers ─────────────────────────────────────────────────────────────

async def get_all_bounty_players() -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM bounty_players ORDER BY id")
    return [[r['bounty_title'] or '', r['discord_id'] or '', r['player_name'] or '',
             r['forum_post_id'] or '', r['progress'] or ''] for r in rows]


async def get_all_bounty_progress(bounty_title: str) -> list:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT player_name, progress FROM bounty_players WHERE bounty_title=$1",
            bounty_title
        )
    return [{'player_name': r['player_name'], 'progress': r['progress']} for r in rows]


async def upsert_bounty_player(bounty_title, discord_id, player_name, forum_post_id, progress):
    pool = _pool_check()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM bounty_players WHERE bounty_title=$1 AND discord_id=$2",
            bounty_title, str(discord_id)
        )
        if existing:
            await conn.execute("""
                UPDATE bounty_players SET player_name=$1, forum_post_id=$2, progress=$3
                WHERE bounty_title=$4 AND discord_id=$5
            """, player_name, forum_post_id, progress, bounty_title, str(discord_id))
        else:
            await conn.execute("""
                INSERT INTO bounty_players (bounty_title, discord_id, player_name, forum_post_id, progress)
                VALUES ($1,$2,$3,$4,$5)
            """, bounty_title, str(discord_id), player_name, forum_post_id, progress)


# ── RegistryCards ─────────────────────────────────────────────────────────────

async def get_all_registry_cards() -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM registry_cards ORDER BY player_name")
    return [[r['discord_id'], r['player_name'] or '', r['forum_thread_id'] or ''] for r in rows]


async def upsert_registry_card(discord_id, player_name, forum_thread_id):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO registry_cards (discord_id, player_name, forum_thread_id)
            VALUES ($1,$2,$3)
            ON CONFLICT (discord_id) DO UPDATE SET
                player_name=EXCLUDED.player_name,
                forum_thread_id=COALESCE(EXCLUDED.forum_thread_id, registry_cards.forum_thread_id)
        """, str(discord_id), player_name, forum_thread_id)


# ── SpecialOps ────────────────────────────────────────────────────────────────

async def get_all_special_ops() -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM special_ops ORDER BY id")
    return [[r['discord_id'], r['player_name'] or '', r['achievement'] or ''] for r in rows]


# ── IndexPosts ────────────────────────────────────────────────────────────────

async def get_all_index_posts() -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM index_posts")
    return [[r['forum_name'], r['channel_id'] or '', r['message_id'] or ''] for r in rows]


async def upsert_index_post(forum_name, channel_id, message_id):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO index_posts (forum_name, channel_id, message_id)
            VALUES ($1,$2,$3)
            ON CONFLICT (forum_name) DO UPDATE SET
                channel_id=EXCLUDED.channel_id,
                message_id=EXCLUDED.message_id
        """, forum_name, channel_id, message_id)


# ── Snapshots ─────────────────────────────────────────────────────────────────

async def add_leaderboard_entry(board_name, player_name, discord_id, score, message_link, weapon):
    """Always insert a new row (used for unlimited boards like 100 Kills / 200 Takedowns)."""
    _cache_invalidate('leaderboard_data')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO leaderboard_data (board_name, player_name, discord_id, score, message_link, weapon)
            VALUES ($1,$2,$3,$4,$5,$6)
        """, board_name, player_name, str(discord_id), score, message_link, weapon)


async def delete_leaderboard_entry_by_board_and_player(board_name: str, discord_id: str):
    """Delete the oldest entry for a player on a board (top-10 pruning)."""
    _cache_invalidate('leaderboard_data')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("""
            DELETE FROM leaderboard_data
            WHERE id = (
                SELECT id FROM leaderboard_data
                WHERE board_name=$1 AND discord_id=$2
                ORDER BY id ASC LIMIT 1
            )
        """, board_name, str(discord_id))


async def delete_leaderboard_entry_by_link(board_name: str, message_link: str):
    """Delete one entry on a specific board by message link (for deduplication)."""
    _cache_invalidate('leaderboard_data')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM leaderboard_data WHERE board_name=$1 AND message_link=$2 AND id = "
            "(SELECT id FROM leaderboard_data WHERE board_name=$1 AND message_link=$2 ORDER BY id ASC LIMIT 1)",
            board_name, message_link
        )


async def delete_leaderboard_entries_by_link(message_link: str) -> list[str]:
    """Delete all leaderboard_data rows matching a message_link; return affected board names."""
    _cache_invalidate('leaderboard_data')
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT board_name FROM leaderboard_data WHERE message_link=$1", message_link
        )
        board_names = [r['board_name'] for r in rows]
        await conn.execute("DELETE FROM leaderboard_data WHERE message_link=$1", message_link)
    return board_names


async def update_submission_feats_by_link(message_link: str, feats: str):
    """Update feats string for a submission identified by message_link."""
    _cache_invalidate('submissions')
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE submissions SET feats=$1 WHERE message_link=$2", feats, message_link
        )


# ── Players extras ────────────────────────────────────────────────────────────

async def update_player_stats(discord_id, total_marks, submission_count, last_submission_str,
                               weapon_marks_str, class_marks_str, forum_thread_id=None):
    """Update stats columns on the players table."""
    _cache_invalidate('players')
    pool = _pool_check()
    last_sub = None
    if last_submission_str:
        try:
            last_sub = datetime.strptime(str(last_submission_str).strip(), '%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    async with pool.acquire() as conn:
        if forum_thread_id:
            await conn.execute("""
                UPDATE players
                SET total_marks=$1, submission_count=$2, last_submission=$3,
                    weapon_marks=$4, class_marks=$5,
                    forum_thread_id=COALESCE($6, forum_thread_id)
                WHERE discord_id=$7
            """, total_marks, submission_count, last_sub,
                 weapon_marks_str, class_marks_str,
                 str(forum_thread_id), str(discord_id))
        else:
            await conn.execute("""
                UPDATE players
                SET total_marks=$1, submission_count=$2, last_submission=$3,
                    weapon_marks=$4, class_marks=$5
                WHERE discord_id=$6
            """, total_marks, submission_count, last_sub,
                 weapon_marks_str, class_marks_str, str(discord_id))


async def get_registry_card(discord_id: str) -> list | None:
    """Get [discord_id, player_name, forum_thread_id] for one player, or None."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM registry_cards WHERE discord_id=$1", str(discord_id)
        )
    return [r['discord_id'], r['player_name'] or '', r['forum_thread_id'] or ''] if r else None


# ── Legacy tables ─────────────────────────────────────────────────────────────

async def get_legacy_marks_for_player(player_name: str) -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM legacy_marks WHERE LOWER(player_name)=LOWER($1)", player_name
        )
    return [[r['player_name'], r['weapon'] or '', r['subclass'] or '',
             str(r['marks']) if r['marks'] is not None else '0'] for r in rows]


async def add_legacy_mark(player_name: str, weapon: str, subclass: str, marks: int):
    """Add (or accumulate onto) a legacy mark for player+weapon+subclass.

    Previously this only checked player_name+weapon for an existing row, ignoring
    subclass — so a second award on the same weapon under a *different* subclass
    silently did nothing (no insert, no error). It also never accumulated: a repeat
    award on the exact same (player, weapon, subclass) was just dropped instead of
    adding to the existing total. Both fixed here by keying on the full triple and
    incrementing on conflict. (OctoLemon Sword/Man-at-Arms, 2026-06-30.)
    """
    pool = _pool_check()
    subclass = subclass or ''
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM legacy_marks WHERE LOWER(player_name)=LOWER($1) AND weapon=$2 AND subclass=$3 LIMIT 1",
            player_name, weapon, subclass
        )
        if existing:
            await conn.execute(
                "UPDATE legacy_marks SET marks = marks + $1 WHERE id = $2",
                marks, existing['id']
            )
        else:
            await conn.execute(
                "INSERT INTO legacy_marks (player_name, weapon, subclass, marks) VALUES ($1,$2,$3,$4)",
                player_name, weapon, subclass, marks
            )


async def get_legacy_feats_for_player(player_name: str) -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM legacy_feats WHERE LOWER(player_name)=LOWER($1)", player_name
        )
    return [[r['player_name'], r['emojis'] or '', r['message_link'] or ''] for r in rows]


async def add_legacy_feat(player_name: str, emojis: str, link: str):
    pool = _pool_check()
    async with pool.acquire() as conn:
        exists = await conn.fetchrow(
            "SELECT id FROM legacy_feats WHERE LOWER(player_name)=LOWER($1) AND message_link=$2 LIMIT 1",
            player_name, link or ''
        )
        if not exists:
            await conn.execute(
                "INSERT INTO legacy_feats (player_name, emojis, message_link) VALUES ($1,$2,$3)",
                player_name, emojis, link or ''
            )


async def get_legacy_bounties_for_player(player_name: str) -> list[list]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM legacy_bounties WHERE LOWER(player_name)=LOWER($1)", player_name
        )
    return [[r['player_name'], r['bounty_title'] or '',
             str(r['completed']) if r['completed'] is not None else ''] for r in rows]


async def add_legacy_bounty(player_name: str, bounty_title: str, placement):
    pool = _pool_check()
    placement_int = None
    if placement:
        try:
            placement_int = int(placement)
        except (ValueError, TypeError):
            pass
    async with pool.acquire() as conn:
        exists = await conn.fetchrow(
            "SELECT id FROM legacy_bounties WHERE LOWER(player_name)=LOWER($1) AND LOWER(bounty_title)=LOWER($2) LIMIT 1",
            player_name, bounty_title
        )
        if not exists:
            await conn.execute(
                "INSERT INTO legacy_bounties (player_name, bounty_title, completed) VALUES ($1,$2,$3)",
                player_name, bounty_title, placement_int
            )


# ── ChallengeRules ────────────────────────────────────────────────────────────

async def get_challenge_rule_msg_ids() -> list[int]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT message_id FROM challenge_rules ORDER BY id")
    result = []
    for r in rows:
        try:
            result.append(int(r['message_id']))
        except (ValueError, TypeError):
            pass
    return result


async def save_challenge_rules(msg_ids: list, labels: list):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM challenge_rules")
        for msg_id, label in zip(msg_ids, labels):
            await conn.execute(
                "INSERT INTO challenge_rules (message_id, section) VALUES ($1,$2)",
                str(msg_id), label
            )


# ── Hundred Handed ────────────────────────────────────────────────────────────

async def add_hundred_handed(discord_id: str, player_name: str, subclass: str, weapon: str) -> bool:
    """Insert a subclass+weapon completion. Returns True if it was new."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS hundred_handed ("
            "id SERIAL PRIMARY KEY, discord_id TEXT NOT NULL, player_name TEXT, "
            "subclass TEXT NOT NULL, weapon TEXT NOT NULL, achieved_at TIMESTAMP DEFAULT NOW(), "
            "UNIQUE(discord_id, subclass, weapon))"
        )
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM hundred_handed WHERE discord_id=$1 AND subclass=$2 AND weapon=$3",
            str(discord_id), subclass, weapon
        )
        if existing:
            return False
        await conn.execute(
            "INSERT INTO hundred_handed (discord_id, player_name, subclass, weapon) VALUES ($1,$2,$3,$4)",
            str(discord_id), player_name, subclass, weapon
        )
        return True


async def get_hundred_handed_progress(discord_id: str) -> list:
    """Return list of (subclass, weapon) tuples completed by this player."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT subclass, weapon FROM hundred_handed WHERE discord_id=$1 ORDER BY achieved_at",
            str(discord_id)
        )
    return [(r['subclass'], r['weapon']) for r in rows]


async def get_hundred_handed_leaderboard() -> list:
    """Return [(discord_id, player_name, count)]. Completers first (earliest
    completion), then in-progress by count desc.

    Collapses duplicate identities — the same person split across id/name
    spellings (a rename, or a legacy-backfill id vs their live id) — so nobody
    shows twice, e.g. in both the completed and in-progress lists. Keeps their
    highest count. Purely a display fix; the underlying rows are untouched."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT discord_id, player_name, COUNT(*) as cnt, MAX(achieved_at) as last_entry "
            "FROM hundred_handed GROUP BY discord_id, player_name"
        )

    recs = [((r['discord_id'] or '').strip(), (r['player_name'] or '').strip(),
             int(r['cnt']), r['last_entry']) for r in rows]

    def _collapse(records, keyfn):
        best = {}
        for did, name, cnt, last in records:
            k = keyfn(did, name)
            cur = best.get(k)
            if cur is None or cnt > cur[2] or (cnt == cur[2] and name and not cur[1]):
                best[k] = (did, name, cnt, last)
        return list(best.values())

    recs = _collapse(recs, lambda did, name: did or name.lower())   # merge name variants under one id
    recs = _collapse(recs, lambda did, name: name.lower() or did)   # merge one name across ids
    recs.sort(key=lambda x: (-x[2], x[3] or datetime.min))
    return [(did, name, cnt) for did, name, cnt, last in recs]


async def consolidate_hundred_handed(dry_run: bool = False) -> dict:
    """Merge duplicate Hundred Handed identities — the same player split across
    different discord_id / player_name spellings — into a single canonical
    id+name, deduping (subclass, weapon) combos and keeping the earliest
    achieved_at per combo. Canonical id/name come from the players table when the
    name matches, else the most common id / non-empty name in the group.
    Returns {'players', 'removed', 'details'}. dry_run computes but writes nothing."""
    from collections import Counter
    pool = _pool_check()
    async with pool.acquire() as conn:
        prows = await conn.fetch("SELECT discord_id, player_name FROM players")
        canon = {}
        for r in prows:
            nm = (r['player_name'] or '').strip()
            if nm:
                canon[nm.lower()] = (str(r['discord_id']), nm)
        hh = await conn.fetch("SELECT discord_id, player_name, subclass, weapon, achieved_at FROM hundred_handed")

        groups = {}
        for r in hh:
            nm = (r['player_name'] or '').strip()
            did = (r['discord_id'] or '').strip()
            groups.setdefault(nm.lower() or did, []).append(r)

        details, merged_players, removed = [], 0, 0
        for key, rows in groups.items():
            ids = {(r['discord_id'] or '').strip() for r in rows}
            names = {(r['player_name'] or '').strip() for r in rows}
            if len(ids) <= 1 and len(names) <= 1:
                continue  # single clean identity — nothing to merge
            if key in canon:
                canon_id, canon_name = canon[key]
            else:
                id_counts = Counter(i for i in ((r['discord_id'] or '').strip() for r in rows) if i)
                canon_id = id_counts.most_common(1)[0][0] if id_counts else ''
                nonempty = [(r['player_name'] or '').strip() for r in rows if (r['player_name'] or '').strip()]
                canon_name = Counter(nonempty).most_common(1)[0][0] if nonempty else ''
            if not canon_id:
                continue  # can't consolidate without a real id
            combo = {}
            for r in rows:
                ck = (r['subclass'], r['weapon'])
                at = r['achieved_at']
                if ck not in combo:
                    combo[ck] = at
                elif at is not None and (combo[ck] is None or at < combo[ck]):
                    combo[ck] = at
            removed += len(rows) - len(combo)
            merged_players += 1
            details.append(f"{canon_name or canon_id}: {len(rows)} rows / {len(ids)} id(s) -> {len(combo)} combos")
            if not dry_run:
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM hundred_handed WHERE LOWER(TRIM(player_name)) = $1 OR discord_id = ANY($2::text[])",
                        key, list(ids)
                    )
                    for (sub, wpn), at in combo.items():
                        await conn.execute(
                            "INSERT INTO hundred_handed (discord_id, player_name, subclass, weapon, achieved_at) "
                            "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (discord_id, subclass, weapon) DO NOTHING",
                            canon_id, canon_name, sub, wpn, at
                        )
    return {"players": merged_players, "removed": removed, "details": details}


# ── Snapshots ─────────────────────────────────────────────────────────────────

async def add_snapshot(snapshot_date, total_subs, weekly_subs, active_players,
                        top_weapons, top_maps, avg_td, avg_kills,
                        highscores_set, boards_updated, trend_direction, previous_subs):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO snapshots
            (snapshot_date, total_subs, weekly_subs, active_players,
             top_weapons, top_maps, avg_td, avg_kills,
             highscores_set, boards_updated, trend_direction, previous_subs)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                total_subs=EXCLUDED.total_subs,
                weekly_subs=EXCLUDED.weekly_subs,
                active_players=EXCLUDED.active_players,
                top_weapons=EXCLUDED.top_weapons,
                top_maps=EXCLUDED.top_maps,
                avg_td=EXCLUDED.avg_td,
                avg_kills=EXCLUDED.avg_kills,
                highscores_set=EXCLUDED.highscores_set,
                boards_updated=EXCLUDED.boards_updated,
                trend_direction=EXCLUDED.trend_direction,
                previous_subs=EXCLUDED.previous_subs
        """,
            snapshot_date, total_subs, weekly_subs, active_players,
            top_weapons, top_maps, avg_td, avg_kills,
            highscores_set, boards_updated, trend_direction, previous_subs
        )


async def get_snapshots(limit: int = 52) -> list[dict]:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM snapshots ORDER BY snapshot_date DESC LIMIT $1", limit
        )
    return [dict(r) for r in rows]


# -- Ko-fi --------------------------------------------------------------------

async def kofi_init():
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kofi_donations (
                id SERIAL PRIMARY KEY,
                kofi_transaction_id TEXT UNIQUE,
                donor_name TEXT,
                amount NUMERIC(10,2),
                currency TEXT,
                received_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kofi_dashboard (
                id INT PRIMARY KEY DEFAULT 1,
                channel_id BIGINT,
                message_id BIGINT
            )
        """)


async def add_kofi_donation(transaction_id: str, donor_name: str, amount: float, currency: str) -> bool:
    pool = _pool_check()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM kofi_donations WHERE kofi_transaction_id=$1", transaction_id
        )
        if existing:
            return False
        await conn.execute(
            "INSERT INTO kofi_donations (kofi_transaction_id, donor_name, amount, currency) VALUES ($1,$2,$3,$4)",
            transaction_id, donor_name, amount, currency
        )
        return True


async def get_kofi_total() -> float:
    pool = _pool_check()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM kofi_donations")
        return float(val)


async def get_kofi_dashboard_message():
    pool = _pool_check()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT channel_id, message_id FROM kofi_dashboard WHERE id=1")
        if row:
            return row['channel_id'], row['message_id']
        return None


async def set_kofi_dashboard_message(channel_id: int, message_id: int):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO kofi_dashboard (id, channel_id, message_id) VALUES (1,$1,$2)
            ON CONFLICT (id) DO UPDATE SET channel_id=EXCLUDED.channel_id, message_id=EXCLUDED.message_id""",
            channel_id, message_id
        )


# -- Season / Hall of Fame: one season per bounty cycle --------------------------
async def season_init():
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seasons (
                id SERIAL PRIMARY KEY,
                label TEXT,
                started_at TIMESTAMPTZ DEFAULT NOW(),
                ended_at TIMESTAMPTZ,
                thread_id TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS season_bonus (
                id SERIAL PRIMARY KEY,
                season_id INT NOT NULL,
                player_name TEXT NOT NULL,
                reason TEXT NOT NULL,
                points INT NOT NULL,
                awarded_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(season_id, player_name, reason)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS season_features (
                season_id INT NOT NULL,
                slot TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (season_id, slot)
            )
        """)


async def start_season(label: str) -> int:
    """Open a new season (defensively closing any still-open one). Returns its id."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE seasons SET ended_at = NOW() WHERE ended_at IS NULL")
        return await conn.fetchval("INSERT INTO seasons (label) VALUES ($1) RETURNING id", label)


async def get_current_season():
    pool = _pool_check()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, label, started_at, ended_at, thread_id FROM seasons "
            "WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
    return dict(r) if r else None


async def get_season(season_id: int):
    pool = _pool_check()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, label, started_at, ended_at, thread_id FROM seasons WHERE id = $1", season_id)
    return dict(r) if r else None


async def end_current_season():
    pool = _pool_check()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "UPDATE seasons SET ended_at = NOW() WHERE ended_at IS NULL "
            "RETURNING id, label, started_at, ended_at, thread_id")
    return dict(r) if r else None


async def get_all_seasons():
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, label, started_at, ended_at, thread_id FROM seasons ORDER BY id DESC")
    return [dict(r) for r in rows]


async def get_finished_seasons():
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, label, started_at, ended_at, thread_id FROM seasons "
            "WHERE ended_at IS NOT NULL ORDER BY id DESC")
    return [dict(r) for r in rows]


async def set_season_thread(season_id: int, thread_id: str):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE seasons SET thread_id = $1 WHERE id = $2", str(thread_id), season_id)


async def set_season_start(season_id: int, started_at):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE seasons SET started_at = $1 WHERE id = $2", started_at, season_id)


async def award_season_bonus(season_id: int, player_name: str, points: int, reason: str) -> bool:
    """Idempotent per (season, player, reason) so a resubmission can't farm it."""
    pool = _pool_check()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "INSERT INTO season_bonus (season_id, player_name, reason, points) VALUES ($1,$2,$3,$4) "
            "ON CONFLICT (season_id, player_name, reason) DO NOTHING", season_id, player_name, points, reason)
    return res.split()[-1] == '1'


async def get_season_bonuses(season_id: int) -> dict:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT player_name, SUM(points) AS pts FROM season_bonus WHERE season_id = $1 GROUP BY player_name",
            season_id)
    return {r['player_name']: int(r['pts']) for r in rows}


async def set_season_feature(season_id: int, slot: str, value: str):
    pool = _pool_check()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO season_features (season_id, slot, value) VALUES ($1,$2,$3) "
            "ON CONFLICT (season_id, slot) DO UPDATE SET value = EXCLUDED.value", season_id, slot, value)


async def get_season_features(season_id: int) -> dict:
    pool = _pool_check()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT slot, value FROM season_features WHERE season_id = $1", season_id)
    return {r['slot']: r['value'] for r in rows}
