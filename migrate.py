"""
migrate.py — One-time migration from Google Sheets to Postgres.

Usage:
    DATABASE_URL=<your_railway_url> python migrate.py

Reads all data from Google Sheets and inserts into Postgres.
Safe to re-run — uses INSERT ... ON CONFLICT DO NOTHING where possible.
"""

import os
import json
import asyncio
import asyncpg
from datetime import datetime

# ── Reuse existing Sheets setup ───────────────────────────────────────────────
from utils.sheets import (
    submissions_ws, players_ws, leaderboards_ws, leaderboard_data_ws,
    bounty_ws, bounty_players_ws, registry_ws, special_ops_ws,
    snapshots_ws, index_posts_ws,
)

try:
    from utils.sheets import sheet
    legacy_ws        = sheet.worksheet('LegacyMarks')
    legacy_feats_ws  = sheet.worksheet('LegacyFeats')
    legacy_bounty_ws = sheet.worksheet('LegacyBounties')
    challenge_ws     = sheet.worksheet('ChallengeRules')
except Exception as e:
    print(f"Warning: could not load legacy sheets: {e}")
    legacy_ws = legacy_feats_ws = legacy_bounty_ws = challenge_ws = None


def _int(v):
    try: return int(float(v)) if v not in (None, '') else None
    except: return None

def _float(v):
    try: return float(v) if v not in (None, '') else None
    except: return None

def _bool(v):
    if isinstance(v, bool): return v
    if str(v).upper() in ('YES', 'TRUE', '1'): return True
    return False

def _ts(v):
    if not v: return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try: return datetime.strptime(str(v).strip(), fmt)
        except: pass
    return None


async def migrate():
    db_url = os.environ['DATABASE_URL']
    conn = await asyncpg.connect(db_url)
    print("Connected to Postgres.")

    # ── Apply schema ──────────────────────────────────────────────────────────
    with open('schema.sql') as f:
        await conn.execute(f.read())
    print("Schema applied.")

    # ── Submissions ───────────────────────────────────────────────────────────
    rows = submissions_ws.get_all_values()[1:]
    count = 0
    for r in rows:
        r += [''] * (23 - len(r))
        try:
            await conn.execute("""
                INSERT INTO submissions
                (submitted_at, player_name, discord_id, weapon, subclass, map, faction,
                 takedowns, kills, deaths, vip, feats, message_link,
                 lobby_rank, lobby_size, kills_rank, team_rank, team_size,
                 total_lobby_kills, team_td_ratio, team_kill_share, team_td_share)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
            """,
                _ts(r[0]), r[1], r[2], r[3], r[4], r[5], r[6],
                _int(r[7]), _int(r[8]), _int(r[9]), _bool(r[10]), r[11], r[12],
                _int(r[13]), _int(r[14]), _int(r[15]), _int(r[16]), _int(r[17]),
                _int(r[18]), _float(r[19]), _float(r[20]), _float(r[21])
            )
            count += 1
        except Exception as e:
            print(f"  Submission row error: {e} | {r[:4]}")
    print(f"Submissions: {count}/{len(rows)}")

    # ── Players ───────────────────────────────────────────────────────────────
    rows = players_ws.get_all_values()[1:]
    count = 0
    for r in rows:
        r += [''] * (8 - len(r))
        try:
            await conn.execute("""
                INSERT INTO players
                (discord_id, player_name, forum_thread_id, total_marks, submission_count,
                 last_submission, weapon_marks, class_marks)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (discord_id) DO UPDATE SET
                    player_name=EXCLUDED.player_name,
                    forum_thread_id=EXCLUDED.forum_thread_id,
                    total_marks=EXCLUDED.total_marks,
                    submission_count=EXCLUDED.submission_count,
                    last_submission=EXCLUDED.last_submission,
                    weapon_marks=EXCLUDED.weapon_marks,
                    class_marks=EXCLUDED.class_marks
            """,
                r[0], r[1], r[2] or None, _int(r[3]), _int(r[4]),
                _ts(r[5]), r[6] or None, r[7] or None
            )
            count += 1
        except Exception as e:
            print(f"  Player row error: {e} | {r[:3]}")
    print(f"Players: {count}/{len(rows)}")

    # ── Leaderboards ──────────────────────────────────────────────────────────
    rows = leaderboards_ws.get_all_values()[1:]
    count = 0
    for r in rows:
        r += [''] * (4 - len(r))
        try:
            await conn.execute("""
                INSERT INTO leaderboards (board_name, thread_id, message_ids, board_type)
                VALUES ($1,$2,$3,$4)
            """, r[0], r[1] or None, r[2] or None, r[3] or None)
            count += 1
        except Exception as e:
            print(f"  Leaderboard row error: {e} | {r[:2]}")
    print(f"Leaderboards: {count}/{len(rows)}")

    # ── LeaderboardData ───────────────────────────────────────────────────────
    rows = leaderboard_data_ws.get_all_values()[1:]
    count = 0
    for r in rows:
        r += [''] * (6 - len(r))
        try:
            await conn.execute("""
                INSERT INTO leaderboard_data
                (board_name, player_name, discord_id, score, message_link, weapon)
                VALUES ($1,$2,$3,$4,$5,$6)
            """, r[0], r[1], r[2] or None, _int(r[3]), r[4] or None, r[5] or None)
            count += 1
        except Exception as e:
            print(f"  LeaderboardData row error: {e} | {r[:3]}")
    print(f"LeaderboardData: {count}/{len(rows)}")

    # ── Bounties ──────────────────────────────────────────────────────────────
    if bounty_ws:
        rows = bounty_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (15 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO bounties
                    (title, channel_id, message_id, theme_emoji, weapons, special_challenge,
                     special_done, completions, active, role_id, forum_channel_id,
                     completions_msg_id, bonus_msg_id, progress_msg_id, start_date)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                """,
                    r[0], r[1] or None, r[2] or None, r[3] or None, r[4] or None,
                    r[5] or None, _bool(r[6]), r[7] or None, _bool(r[8]),
                    r[9] or None, r[10] or None, r[11] or None, r[12] or None,
                    r[13] or None, _ts(r[14])
                )
                count += 1
            except Exception as e:
                print(f"  Bounty row error: {e} | {r[:2]}")
        print(f"Bounties: {count}/{len(rows)}")

    # ── BountyPlayers ─────────────────────────────────────────────────────────
    if bounty_players_ws:
        rows = bounty_players_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (5 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO bounty_players
                    (bounty_title, discord_id, player_name, forum_post_id, progress)
                    VALUES ($1,$2,$3,$4,$5)
                """, r[0], r[1], r[2], r[3] or None, r[4] or None)
                count += 1
            except Exception as e:
                print(f"  BountyPlayers row error: {e} | {r[:3]}")
        print(f"BountyPlayers: {count}/{len(rows)}")

    # ── RegistryCards ─────────────────────────────────────────────────────────
    if registry_ws:
        rows = registry_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (3 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO registry_cards (discord_id, player_name, forum_thread_id)
                    VALUES ($1,$2,$3)
                    ON CONFLICT (discord_id) DO UPDATE SET
                        player_name=EXCLUDED.player_name,
                        forum_thread_id=EXCLUDED.forum_thread_id
                """, r[0], r[1], r[2] or None)
                count += 1
            except Exception as e:
                print(f"  RegistryCards row error: {e} | {r[:2]}")
        print(f"RegistryCards: {count}/{len(rows)}")

    # ── SpecialOps ────────────────────────────────────────────────────────────
    if special_ops_ws:
        rows = special_ops_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (3 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO special_ops (discord_id, player_name, achievement)
                    VALUES ($1,$2,$3)
                """, r[0], r[1], r[2])
                count += 1
            except Exception as e:
                print(f"  SpecialOps row error: {e} | {r[:2]}")
        print(f"SpecialOps: {count}/{len(rows)}")

    # ── LegacyMarks ───────────────────────────────────────────────────────────
    if legacy_ws:
        rows = legacy_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (4 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO legacy_marks (player_name, weapon, subclass, marks)
                    VALUES ($1,$2,$3,$4)
                """, r[0], r[1], r[2], _int(r[3]))
                count += 1
            except Exception as e:
                print(f"  LegacyMarks row error: {e} | {r[:3]}")
        print(f"LegacyMarks: {count}/{len(rows)}")

    # ── LegacyFeats ───────────────────────────────────────────────────────────
    if legacy_feats_ws:
        rows = legacy_feats_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (3 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO legacy_feats (player_name, emojis, message_link)
                    VALUES ($1,$2,$3)
                """, r[0], r[1], r[2] or None)
                count += 1
            except Exception as e:
                print(f"  LegacyFeats row error: {e} | {r[:2]}")
        print(f"LegacyFeats: {count}/{len(rows)}")

    # ── LegacyBounties ────────────────────────────────────────────────────────
    if legacy_bounty_ws:
        rows = legacy_bounty_ws.get_all_values()
        # No header row on this sheet based on the export
        count = 0
        for r in rows:
            r += [''] * (3 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO legacy_bounties (player_name, bounty_title, completed)
                    VALUES ($1,$2,$3)
                """, r[0], r[1], _int(r[2]))
                count += 1
            except Exception as e:
                print(f"  LegacyBounties row error: {e} | {r[:2]}")
        print(f"LegacyBounties: {count}/{len(rows)}")

    # ── ChallengeRules ────────────────────────────────────────────────────────
    if challenge_ws:
        rows = challenge_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (2 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO challenge_rules (message_id, section)
                    VALUES ($1,$2)
                """, r[0], r[1])
                count += 1
            except Exception as e:
                print(f"  ChallengeRules row error: {e} | {r[:2]}")
        print(f"ChallengeRules: {count}/{len(rows)}")

    # ── Snapshots ─────────────────────────────────────────────────────────────
    if snapshots_ws:
        rows = snapshots_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (19 - len(r))
            if not r[0]:
                continue
            try:
                await conn.execute("""
                    INSERT INTO snapshots
                    (snapshot_date, total_subs, weekly_subs, active_players,
                     top_weapon_1, top_weapon_2, top_weapon_3, top_weapon_4, top_weapon_5,
                     top_map_1, top_map_2, top_map_3,
                     avg_td, avg_kills, highscores_set, boards_updated,
                     trend_weapon_1, trend_weapon_2, trend_weapon_3)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                """,
                    _ts(r[0]), _int(r[1]), _int(r[2]), _int(r[3]),
                    r[4] or None, r[5] or None, r[6] or None, r[7] or None, r[8] or None,
                    r[9] or None, r[10] or None, r[11] or None,
                    _float(r[12]), _float(r[13]), _int(r[14]), _int(r[15]),
                    r[16] or None, r[17] or None, r[18] or None
                )
                count += 1
            except Exception as e:
                print(f"  Snapshots row error: {e} | {r[:2]}")
        print(f"Snapshots: {count}/{len(rows)}")

    # ── IndexPosts ────────────────────────────────────────────────────────────
    if index_posts_ws:
        rows = index_posts_ws.get_all_values()[1:]
        count = 0
        for r in rows:
            r += [''] * (3 - len(r))
            try:
                await conn.execute("""
                    INSERT INTO index_posts (forum_name, channel_id, message_id)
                    VALUES ($1,$2,$3)
                    ON CONFLICT (forum_name) DO UPDATE SET
                        channel_id=EXCLUDED.channel_id,
                        message_id=EXCLUDED.message_id
                """, r[0], r[1] or None, r[2] or None)
                count += 1
            except Exception as e:
                print(f"  IndexPosts row error: {e} | {r[:2]}")
        print(f"IndexPosts: {count}/{len(rows)}")

    await conn.close()
    print("\nMigration complete.")


if __name__ == '__main__':
    asyncio.run(migrate())
