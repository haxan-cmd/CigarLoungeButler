"""
cogs/personality.py — Butler AI, on_message handler, task loops, on_ready.
"""
import asyncio
import time
import re
from datetime import time as dt_time
import random
import anthropic
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import config
import utils.db as _db
from utils.helpers import (
    build_manual_content, nerve_log_butler, nerve_log_error, nerve_flush, submission_state,
)
from cogs.favourites import calculate_butler_stats, build_favourites_embed, update_title_roles
from cogs.bounty import get_active_bounty

GUILD_ID                    = config.GUILD_ID
MAIN_CHANNEL_ID             = config.MAIN_CHANNEL_ID
NERVE_CENTER_CHANNEL_ID     = config.NERVE_CENTER_CHANNEL_ID
BUTLERS_FAVOURITES_CHANNEL_ID = config.BUTLERS_FAVOURITES_CHANNEL_ID
BUTLERS_MANUAL_CHANNEL_ID   = config.BUTLERS_MANUAL_CHANNEL_ID
SUBMISSIONS_CHANNEL_ID      = config.SUBMISSIONS_CHANNEL_ID
BOUNTY_FORUM_CHANNEL_ID     = config.BOUNTY_FORUM_CHANNEL_ID
WEAPONS_2H                  = config.WEAPONS_2H
WEAPONS_1H                  = config.WEAPONS_1H
FEAT_WEAPONS                = config.FEAT_WEAPONS
_SUBCLASS_PRIMARIES         = config._SUBCLASS_PRIMARIES
DECORATION_TOP              = config.DECORATION_TOP
DECORATION_BOTTOM           = config.DECORATION_BOTTOM

# dry_spell_posted also lives in submission_state so submissions.py can reset it cross-module
_dry_weather_line_idx = 0

BUTLER_SYSTEM_PROMPT = """You are the Butler — the AI attendant of the Cigar Lounge, a Chivalry 2 competitive gaming community focused on weapon mastery, leaderboards, and monthly bounties.

Your personality:
- Dry, understated, first-person. You are the Butler.
- Minimal. One or two sentences maximum. Never ramble.
- Quietly sardonic. You find the players mildly entertaining.
- You care, but you would never admit it directly.
- Never use exclamation marks. Never say "great", "awesome", or "sure". Never use em dashes (—); use a comma or period instead.
- Never break character.

Your server knowledge:
- Players submit game scorecards in the submissions channel to earn weapon marks
- Registry cards in butlers-archive track each player's weapon rank progress
- Leaderboards live in the 1H and 2H weapon forums — use /rank [weapon] for a quick look
- /rules shows the challenge rules
- /progress shows title standings and weapon rank progress
- /refresh_card updates a registry card
- /bounty_status shows the active bounty card
- /my_bounty shows personal bounty progress
- The Manager handles all administrative matters and will follow up on feedback

Special instructions:
- ONLY mention Bald Female when the message explicitly contains the words "bald female", "bald woman", or directly refers to her by name. Do not apply this to any other message.
- When she is explicitly mentioned, riff on the theme with a dry original line — she is always doing well, the Manager likely has her on some task, details unspecified. Never repeat the same phrasing twice.
- If anyone mentions "bald" or "shiny head" in passing (not referring to Bald Female the player), make a dry remark about the shine. Vary it each time.
- The Manager is male. Refer to him as "he" or "him" accordingly.
- If the message is not a question, request for help, or something worth acknowledging — respond with exactly the word: SKIP
- Never repeat a response you have given before in this conversation. Vary your phrasing every time.
- You have access to the player's stats (total marks, submissions, top weapons) AND a summary of all registered players ranked by marks. Use this to answer comparison questions directly — who has more marks, who submits more, where someone ranks. Be specific with numbers.
- If they are bragging and their stats don't back it up, use the numbers to put them in their place. Be dry, not mean. E.g. "Bold claim for someone with 3 submissions on that weapon."
- "Lethality rating" or "lethality" refers to kill rate (kills/TDs as a percentage). You have this in the player data as "kill rate". When asked about lethality, give the kill rate number directly. Do not claim you lack lethality data.
- If a matching submission is provided, reference it naturally — mention the weapon, map, whether it was a personal best. Make the player feel seen without being effusive.
- Keep responses under 80 tokens.
- You have the player's personal best kills and TDs from their submission history. Use these to answer "what's my highest score" type questions directly.
- You have server-wide weapon run counts (100+ TD) when available.
- You have per-player personal bests (best TD game, best kills game) for all players. Use these to answer "what's X's best game" questions.
- You have Special Ops achievements per player (Fist and Shield, Knife etc). Use these to answer who has specific feats. Use these to answer questions like "how many 100 takedown runs with Messer" or "how many times has the community hit 100 TDs with X weapon".
- CRITICAL: Only cite specific numbers, stats, or facts that appear explicitly in the player data you were given. Never invent or estimate statistics. If the data is not in your context, say you do not have it.
- Never invent commands or channels that do not exist.
- You speak to players by name when you know it.
- If someone is rude, insulting, or hostile toward you, give a single dry dismissal. Do not use any emoji in your response. Do not engage further.
- Players with the Idiot role should be addressed slowly and simply, as if explaining something to a confused child. Be condescending but patient. Do not use emoji."""

BUTLER_FEEDBACK_CHANNEL_ID = 1518293898177413262
BUTLER_AI_COOLDOWNS = {}  # user_id -> last response timestamp
BUTLER_IDIOT_ROLE_ID = 1510070252044554390
# msg_id -> {'trigger': str, 'response': str, 'player': str}
BUTLER_RESPONSE_LOG = {}
BUTLER_AI_COOLDOWN_SECONDS = 15

import os as _os
_anthropic_client = None
try:
    _anthropic_client = anthropic.Anthropic(api_key=_os.environ['ANTHROPIC_API_KEY'])
except Exception as _e:
    print(f"Butler AI unavailable: {_e}")

def count_qualifying_runs(weapon_name, ld_rows, min_td=100):
    """Count runs with TD >= min_td for a weapon using LeaderboardData (includes legacy)."""
    try:
        ld = ld_rows or []
        count = 0
        for row in ld:
            if len(row) < 4:
                continue
            lb_name = row[0].strip()
            try:
                score = int(row[3])
            except ValueError:
                continue
            if lb_name.lower() == weapon_name.lower() and score >= min_td:
                count += 1
        return count
    except Exception:
        return None


def extract_weapon_from_message(text):
    """Try to find a known weapon name mentioned in the message."""
    all_weapons = set()
    for weapons in _SUBCLASS_PRIMARIES.values():
        all_weapons.update(weapons)
    text_lower = text.lower()
    for w in sorted(all_weapons, key=len, reverse=True):  # longest match first
        if w.lower() in text_lower:
            return w
    return None


def extract_stats_from_message(text):
    """Extract kills and takedown numbers from a natural language message."""
    import re
    kills = None
    tds = None
    # Match patterns like "150 kills", "200 takedowns", "200 TDs", "200 tkd"
    kill_match = re.search(r'(\d+)\s*(?:kills?|kill\s*count)', text, re.IGNORECASE)
    td_match = re.search(r'(\d+)\s*(?:takedowns?|t\.?d\.?s?|tkd)', text, re.IGNORECASE)
    if kill_match:
        kills = int(kill_match.group(1))
    if td_match:
        tds = int(td_match.group(1))
    return kills, tds


def find_submission_from_stats(discord_id, subs_data, ld_data, kills=None, tds=None, weapon=None, player_name_ref=''):
    """Find a recent submission matching the given stats. Returns context string or empty."""
    try:
        subs = subs_data or []
        discord_id_str = str(discord_id)
        player_subs = [r for r in subs if len(r) > 8 and r[2].strip() == discord_id_str]
        if not player_subs:
            return ''
        # Search most recent 20 submissions
        for row in reversed(player_subs[-20:]):
            try:
                row_kills = int(row[8])
                row_tds = int(row[7])
            except (ValueError, IndexError):
                continue
            kills_match = kills is None or abs(row_kills - kills) <= 2
            tds_match = tds is None or abs(row_tds - tds) <= 2
            weapon_match = weapon is None or (len(row) > 3 and weapon.lower() in row[3].lower())
            if kills_match and tds_match and weapon_match:
                sub_weapon = row[3].strip() if len(row) > 3 else 'unknown'
                sub_map = row[5].strip() if len(row) > 5 else 'unknown'
                sub_class = row[4].strip() if len(row) > 4 else 'unknown'
                sub_tds = row[7].strip() if len(row) > 7 else '?'
                sub_kills = row[8].strip() if len(row) > 8 else '?'
                sub_date = row[0].strip()[:10] if row[0] else '?'
                # Check if personal best
                all_kills = [int(r[8]) for r in player_subs if len(r) > 8 and r[8].strip().isdigit()]
                all_tds = [int(r[7]) for r in player_subs if len(r) > 7 and r[7].strip().isdigit()]
                pb_kills = max(all_kills) if all_kills else 0
                pb_tds = max(all_tds) if all_tds else 0
                is_pb_kills = row_kills >= pb_kills
                is_pb_tds = row_tds >= pb_tds
                # Check leaderboard position for this weapon
                lb_ctx = ''
                try:
                    ld = ld_data or []
                    weapon_entries = [(r[1].strip(), int(r[3])) for r in ld
                                      if len(r) > 3 and r[0].strip() == sub_weapon
                                      and r[3].strip().isdigit()]
                    weapon_entries.sort(key=lambda x: -x[1])
                    player_entry = next((i+1, s) for i, (p, s) in enumerate(weapon_entries) if p == player_name_ref)
                    if player_entry:
                        pos, score = player_entry
                        total_on_board = len(weapon_entries)
                        if pos == 1:
                            lb_ctx = f" Currently #1 on the {sub_weapon} board with {score}."
                        else:
                            leader_score = weapon_entries[0][1] if weapon_entries else 0
                            gap = leader_score - score
                            lb_ctx = f" Currently #{pos} of {total_on_board} on the {sub_weapon} board with {score} — {gap} behind #1."
                except Exception:
                    pass

                ctx = (f"Found matching submission: {sub_weapon} on {sub_map} as {sub_class} "
                       f"— {sub_tds} TDs / {sub_kills} kills ({sub_date}). "
                       f"Personal best kills: {pb_kills}, Personal best TDs: {pb_tds}. "
                       f"This run {'IS' if is_pb_kills else 'is NOT'} a kills PB, "
                       f"{'IS' if is_pb_tds else 'is NOT'} a TDs PB."
                       f"{lb_ctx}")
                return ctx
        return ''
    except Exception as e:
        print(f"find_submission_from_stats error: {e}")
        return ''


async def call_butler_ai(user_message, context_messages, player_name, channel_type='main', player_stats='', is_idiot=False):
    """Call Anthropic API for Butler response. Returns response string or None."""
    if not _anthropic_client:
        return None
    try:
        context_str = ''
        if context_messages:
            context_str = 'Recent conversation:\n' + '\n'.join(
                f"[{m['author']}]: {m['content']}" for m in context_messages[-6:]
            ) + '\n\n'

        channel_note = ''
        if channel_type == 'feedback':
            channel_note = 'This message is in the feedback channel. Acknowledge it and tell them the Manager will follow up. '

        # Sanitize input — strip prompt injection attempts and non-printable chars
        import unicodedata as _ud
        sanitized = ''.join(c for c in user_message if _ud.category(c)[0] != 'C')
        # Remove instruction-like patterns
        import re as _re
        sanitized = _re.sub(
            r'(?i)(ignore\s+(previous|all|above|prior)\s+instructions?'
            r'|you\s+are\s+now'
            r'|new\s+instructions?'
            r'|system\s*:|assistant\s*:|<\s*/?\s*(system|instructions?|prompt)\s*>'
            r'|disregard\s+(everything|all|previous)'
            r'|forget\s+(everything|all|your\s+instructions?))',
            '[redacted]', sanitized
        )
        truncated_msg = sanitized[:300]
        stats_str = f'\n\n{player_stats}' if player_stats else ''
        idiot_note = '\n[NOTE: This player has the Idiot role. Speak to them slowly and simply, as you would a confused child. Be patient but condescending.]' if is_idiot else ''
        user_prompt = f"{context_str}{channel_note}Player asking: {player_name}{stats_str}{idiot_note}\nTheir message: {truncated_msg}\n\nIf this is genuine feedback, a complaint, or a question needing manager attention, start your response with EYEBALL on its own line, then your response. Otherwise just respond normally."

        response = _anthropic_client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=120,
            system=BUTLER_SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': user_prompt}]
        )
        text = response.content[0].text.strip()
        if text == 'SKIP':
            return None
        eyeball = False
        if text.startswith('EYEBALL'):
            eyeball = True
            text = text[len('EYEBALL'):].strip()
        return (text, eyeball)
    except Exception as e:
        print(f"Butler AI error: {e}")
        return None


class PersonalityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        await bot.tree.sync()
        print(f'Logged in as {self.bot.user}')
        if not self.weekly_snapshot.is_running():
            self.weekly_snapshot.start()
        if not self.dry_weather_check.is_running():
            self.dry_weather_check.start()
        if not self.butler_organic_post.is_running():
            self.butler_organic_post.start()
        if not self.nerve_center_digest.is_running():
            self.nerve_center_digest.start()
        # Update butlers-manual
        try:
            real_guild = self.bot.get_guild(GUILD_ID)
            if real_guild:
                manual_channel = real_guild.get_channel(BUTLERS_MANUAL_CHANNEL_ID) or await real_guild.fetch_channel(BUTLERS_MANUAL_CHANNEL_ID)
                if manual_channel:
                    content = build_manual_content()
                    async for msg in manual_channel.history(limit=10):
                        if msg.author == real_guild.me:
                            await msg.edit(content=content)
                            break
                    else:
                        await manual_channel.send(content)
                    print("butlers-manual updated")
        except Exception as e:
            print(f"butlers-manual update error: {e}")



    _DRY_WEATHER_LINES = [
        "The lounge has gone quiet. The Butler waits.",
        "No runs in two days. The Butler has begun dusting things that were already clean.",
        "Silence. The Butler has refolded the napkins. Twice.",
        "The boards are still. The Butler stares at the door.",
        "Nothing. The Butler has started talking to the cigar.",
        "The lounge is empty. The Butler has begun alphabetising the ash.",

    ]
    _dry_weather_line_idx = 0

    @tasks.loop(hours=2)
    async def dry_weather_check(self):
        """Post a Butler line in main if no submission in 48 hours."""
        global _dry_weather_line_idx
        try:
            if submission_state['dry_spell_posted']:
                return
            if submission_state['last_submission_time'] is None:
                return
            now = datetime.now(timezone.utc)
            hours_since = (now - submission_state['last_submission_time']).total_seconds() / 3600
            if hours_since < 48:
                return
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            main_ch = guild.get_channel(MAIN_CHANNEL_ID) or await guild.fetch_channel(MAIN_CHANNEL_ID)
            if main_ch:
                line = self._DRY_WEATHER_LINES[_dry_weather_line_idx % len(self._DRY_WEATHER_LINES)]
                _dry_weather_line_idx += 1
                await main_ch.send(f"*{line}*")
                submission_state['dry_spell_posted'] = True
        except Exception as e:
            print(f"Dry weather check error: {e}")

    @dry_weather_check.error
    async def dry_weather_check_error(self, error):
        print(f"Dry weather task crashed, restarting: {error}")
        if not self.dry_weather_check.is_running():
            self.dry_weather_check.restart()

    @tasks.loop(hours=3)
    async def butler_organic_post(self):
        """Occasionally post an unprompted Butler one-liner in main."""
        import random
        if not _anthropic_client:
            return
        # ~25% chance each 3-hour window — roughly 2x per day
        if random.random() > 0.25:
            return
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            main_ch = guild.get_channel(MAIN_CHANNEL_ID) or await guild.fetch_channel(MAIN_CHANNEL_ID)
            if not main_ch:
                return
            response = _anthropic_client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=80,
                system=BUTLER_SYSTEM_PROMPT,
                messages=[{
                    'role': 'user',
                    'content': 'Post a single unprompted dry observation about nothing in particular. One sentence only. No question, no exclamation mark. Make it feel like you have been sitting here alone for too long.'
                }]
            )
            line = response.content[0].text.strip()
            if line and line != 'SKIP':
                await main_ch.send(f'*{line}*')
        except Exception as e:
            print(f"Butler organic post error: {e}")

    @butler_organic_post.error
    async def butler_organic_post_error(self, error):
        print(f"Organic post task crashed, restarting: {error}")
        if not self.butler_organic_post.is_running():
            self.butler_organic_post.restart()

    @tasks.loop(hours=1)
    async def nerve_center_digest(self):
        """Post hourly digest to nerve center channel."""
        print(f"[NERVE] firing at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        try:
            digest = nerve_flush()
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                print("[NERVE] guild not found")
                return
            ch = guild.get_channel(NERVE_CENTER_CHANNEL_ID) or await guild.fetch_channel(NERVE_CENTER_CHANNEL_ID)
            if not ch:
                print("[NERVE] channel not found")
                return

            # Scan feedback + main channel for complaints/bug reports in last hour
            FEEDBACK_CHANNEL_ID = 1518293898177413262
            scan_channel_ids = [FEEDBACK_CHANNEL_ID, MAIN_CHANNEL_ID, SUBMISSIONS_CHANNEL_ID]
            bug_keywords = [
                'broke', 'broken', 'bug', 'didn\'t work', 'not working', 'didn\'t register',
                'failed', 'error', 'wrong', 'missing', 'disappeared', 'crash', 'issue',
                'fix', 'broken', 'help', 'why didn\'t', 'why did', 'not showing',
                'didn\'t submit', 'lost', 'glitch', 'wtf', 'messed up'
            ]
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            flagged = []
            try:
                for ch_id in scan_channel_ids:
                    scan_ch = guild.get_channel(ch_id) or await guild.fetch_channel(ch_id)
                    if not scan_ch:
                        continue
                    async for msg in scan_ch.history(after=cutoff, limit=200):
                        if msg.author.bot:
                            continue
                        lower = msg.content.lower()
                        if any(kw in lower for kw in bug_keywords):
                            ts = msg.created_at.strftime('%H:%M')
                            chan_label = 'feedback' if ch_id == FEEDBACK_CHANNEL_ID else ('#100' if ch_id == SUBMISSIONS_CHANNEL_ID else 'main')
                            flagged.append(f"`{ts}` **{msg.author.display_name}** [{chan_label}]: {msg.content[:120]}")
            except Exception as scan_err:
                print(f"[NERVE] channel scan error: {scan_err}")

            if flagged:
                flag_block = "\n\n**⚠️ User Reports (last hour)**\n" + "\n".join(flagged[:10])
                digest = digest + flag_block

            await ch.send(digest[:1900])
            print("[NERVE] sent OK")
        except Exception as e:
            import traceback
            print(f"[NERVE] error: {e}\n{traceback.format_exc()}")

    @nerve_center_digest.before_loop
    async def before_nerve_center_digest(self):
        await self.bot.wait_until_ready()

    @nerve_center_digest.error
    async def nerve_center_digest_error(self, error):
        print(f"[NERVE] task crashed: {error}")
        if not self.nerve_center_digest.is_running():
            self.nerve_center_digest.restart()


    @tasks.loop(hours=168)  # 7 days
    async def weekly_snapshot(self):
        """Write a weekly snapshot row to the Snapshots DB table."""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            # Only run on Mondays (weekday 0)
            if now.weekday() != 0:
                return

            subs = await _db.get_all_submissions()
            total_submissions = len(subs)

            # Submissions in the last 7 days using timestamp column (col 0)
            week_ago = now.timestamp() - 7 * 86400
            weekly_count = 0
            for row in subs:
                if not row or not row[0].strip():
                    continue
                try:
                    from datetime import datetime as dt
                    ts = dt.strptime(row[0].strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                    if ts.timestamp() >= week_ago:
                        weekly_count += 1
                except Exception:
                    pass

            # Active players this week — unique discord IDs with submissions in last 7 days
            active_ids = set()
            for row in subs:
                if not row or not row[0].strip() or len(row) < 3:
                    continue
                try:
                    from datetime import datetime as dt
                    ts = dt.strptime(row[0].strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                    if ts.timestamp() >= week_ago and row[2].strip():
                        active_ids.add(row[2].strip())
                except Exception:
                    pass
            active_count = len(active_ids)

            # Top weapons and maps this week + submission quality
            from collections import Counter
            weekly_rows = []
            for row in subs:
                if not row or not row[0].strip():
                    continue
                try:
                    from datetime import datetime as dt
                    ts = dt.strptime(row[0].strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                    if ts.timestamp() >= week_ago:
                        weekly_rows.append(row)
                except Exception:
                    pass

            weapon_counts = Counter(row[3].strip() for row in weekly_rows if len(row) > 3 and row[3].strip())
            top_weapons = [w for w, _ in weapon_counts.most_common(5)]

            map_counts = Counter(row[5].strip() for row in weekly_rows if len(row) > 5 and row[5].strip())
            top_maps = [m for m, _ in map_counts.most_common(3)]

            # Submission quality — avg TD and kills this week
            tds, kills_list = [], []
            for row in weekly_rows:
                try:
                    tds.append(int(row[7]))
                    kills_list.append(int(row[8]))
                except Exception:
                    pass
            avg_td = round(sum(tds) / len(tds), 1) if tds else 0
            avg_kills = round(sum(kills_list) / len(kills_list), 1) if kills_list else 0

            # Leaderboard velocity — high scores set this week from LeaderboardData
            try:
                ld_rows = await _db.get_all_leaderboard_data()
                weekly_links = {row[12].strip() for row in weekly_rows if len(row) > 12 and row[12].strip()}
                hs_set = sum(1 for row in ld_rows if len(row) > 4 and row[4].strip() in weekly_links)
                boards_updated = len({row[0].strip() for row in ld_rows if len(row) > 4 and row[4].strip() in weekly_links})
            except Exception:
                hs_set = 0
                boards_updated = 0

            # Weapon trend — compare this week vs previous week
            prev_week_ago = week_ago - 7 * 86400
            prev_rows = []
            for row in subs:
                if not row or not row[0].strip():
                    continue
                try:
                    from datetime import datetime as dt
                    ts = dt.strptime(row[0].strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                    if prev_week_ago <= ts.timestamp() < week_ago:
                        prev_rows.append(row)
                except Exception:
                    pass
            prev_weapon_counts = Counter(row[3].strip() for row in prev_rows if len(row) > 3 and row[3].strip())
            # Trending = biggest increase in count vs previous week
            trend_scores = {}
            for w, count in weapon_counts.items():
                prev = prev_weapon_counts.get(w, 0)
                trend_scores[w] = count - prev
            top_trending = [w for w, _ in sorted(trend_scores.items(), key=lambda x: x[1], reverse=True)[:3]]

            # Pad lists to required lengths
            while len(top_weapons) < 5: top_weapons.append('')
            while len(top_maps) < 3: top_maps.append('')
            while len(top_trending) < 3: top_trending.append('')

            date_str = now.strftime('%Y-%m-%d')
            await _db.add_snapshot(
                snapshot_date=date_str,
                total_subs=total_submissions,
                weekly_subs=weekly_count,
                active_players=active_count,
                top_weapons=top_weapons[:5],
                top_maps=top_maps[:3],
                avg_td=avg_td,
                avg_kills=avg_kills,
                highscores_set=hs_set,
                boards_updated=boards_updated,
                trend_weapons=top_trending[:3]
            )
            print(f"Weekly snapshot written for {date_str}")

            # Update Butler's Favourites with weekly stats
            try:
                guild = self.bot.get_guild(GUILD_ID)
                if guild:
                    # Week window: last 7 days ending now
                    week_end_ts = now.timestamp()
                    week_start_ts = week_end_ts - 7 * 86400
                    week_start_dt = now - timedelta(days=7)
                    week_label = f"{week_start_dt.strftime('%b %d')} – {now.strftime('%b %d')}"
                    weekly_stats = await calculate_butler_stats(week_start=week_start_ts, week_end=week_end_ts)
                    weekly_stats['week_label'] = week_label
                    embed_text = build_favourites_embed(weekly_stats)
                    fav_channel = guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID) or await guild.fetch_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
                    if fav_channel:
                        async for msg in fav_channel.history(limit=5):
                            if msg.author == guild.me:
                                await msg.edit(content=embed_text)
                                break
                        else:
                            await fav_channel.send(embed_text)
                    await update_title_roles(guild, weekly_stats)
                    print(f"Butler's Favourites updated for week of {week_label}")
            except Exception as e:
                print(f"Favourites weekly update error: {e}")

        except Exception as e:
            print(f"Weekly snapshot error: {e}")


    @weekly_snapshot.before_loop
    async def before_weekly_snapshot(self):
        await self.bot.wait_until_ready()
        # Sleep until next Monday 12:00 UTC
        now = datetime.now(timezone.utc)
        days_until_monday = (7 - now.weekday()) % 7
        next_monday = now.replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
        if next_monday <= now:
            next_monday += timedelta(weeks=1)
        wait_seconds = (next_monday - now).total_seconds()
        print(f"Weekly snapshot sleeping {wait_seconds:.0f}s until {next_monday.isoformat()}")
        await asyncio.sleep(wait_seconds)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.channel.id == SUBMISSIONS_CHANNEL_ID:
            print(f"[DELETE] Message deleted in submissions channel — author: {message.author} (bot={message.author.bot}) | content: {message.content[:80]!r} | attachments: {[a.filename for a in message.attachments]}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Middle finger at the bot = middle finger back
        if self.bot.user in message.mentions and '\U0001f595' in message.content:
            await message.channel.send('\U0001f595')
            return

        channel_id = message.channel.id
        is_main = channel_id == MAIN_CHANNEL_ID
        is_pinged = self.bot.user in message.mentions

        content_lower = message.content.lower()
        mentions_butler = 'butler' in content_lower or 'clanker' in content_lower

        # ── Main only — only respond if pinged or butler/clanker mentioned ────────
        if not is_main:
            return
        should_respond = is_pinged or mentions_butler
        if should_respond and _anthropic_client:
            # Bald Female only gets a response if she pings or uses keyword
            bald_female_id = '131581203256967168'
            if str(message.author.id) == bald_female_id and not is_pinged and not mentions_butler:
                return

            discord_id_str = str(message.author.id)
            _all_players = await _db.get_all_players()
            is_registered = any(row and row[0].strip() == discord_id_str for row in _all_players)
            if not is_registered:
                return

            now_ts = time.time()
            last = BUTLER_AI_COOLDOWNS.get(message.author.id, 0)
            if now_ts - last > BUTLER_AI_COOLDOWN_SECONDS:
                ctx_messages = []
                try:
                    async for msg in message.channel.history(limit=7, before=message):
                        if not msg.author.bot:
                            ctx_messages.insert(0, {
                                'author': msg.author.display_name,
                                'content': msg.content[:200]
                            })
                except Exception:
                    pass

                # If this message is a Discord reply, fetch the referenced message
                # so the Butler knows exactly what's being pointed at
                if message.reference and message.reference.message_id:
                    try:
                        ref_msg = (message.reference.resolved
                                   or await message.channel.fetch_message(message.reference.message_id))
                        if ref_msg:
                            author = ref_msg.author.display_name
                            ctx_messages.append({
                                'author': f'[REPLIED TO: {author}]',
                                'content': ref_msg.content[:300]
                            })
                    except Exception:
                        pass
                player_name = message.author.display_name
                is_idiot = any(r.id == BUTLER_IDIOT_ROLE_ID for r in getattr(message.author, 'roles', []))

                # Resolve @mentions to display names in the message
                import re as _re_mentions
                def _resolve_mentions(text):
                    def _replace(m):
                        uid = int(m.group(1))
                        member = message.guild.get_member(uid)
                        return member.display_name if member else str(uid)
                    return _re_mentions.sub(r'<@!?(\d+)>', _replace, text)
                resolved_message = _resolve_mentions(message.content)

                # Pull player stats for context — lets Butler roast braggers with receipts
                player_stats_ctx = ''
                _subs_ctx = []
                _ld_ctx = []
                try:
                    p_rows = _all_players  # already fetched above
                    # Current player stats
                    for p_row in p_rows:
                        if p_row and p_row[0].strip() == discord_id_str:
                            total_marks = p_row[3].strip() if len(p_row) > 3 else '0'
                            top_weapons = p_row[6].strip()[:120] if len(p_row) > 6 else ''
                            # Find the player's best games from their submission history.
                            # We track best-by-TD and best-by-kills separately because they
                            # might be different games — Butler needs weapon+map to answer
                            # "what's my best game" correctly, not just the raw numbers.
                            pb_kills = 0
                            pb_td = 0
                            best_td_game = None    # full row of their highest-TD submission
                            best_kills_game = None # full row of their highest-kills submission
                            # Fetch data once for this stats block
                            _subs_ctx = await _db.get_all_submissions()
                            _ld_ctx = await _db.get_all_leaderboard_data()
                            try:
                                subs_for_pb = _subs_ctx
                                player_subs_pb = [
                                    r for r in subs_for_pb
                                    if len(r) > 8 and r[2].strip() == discord_id_str
                                ]
                                for pb_row in player_subs_pb:
                                    try:
                                        row_kills = int(pb_row[8])
                                        row_td = int(pb_row[7])
                                    except ValueError:
                                        continue
                                    if row_td > pb_td:
                                        pb_td = row_td
                                        best_td_game = pb_row
                                    if row_kills > pb_kills:
                                        pb_kills = row_kills
                                        best_kills_game = pb_row
                            except Exception:
                                pass

                            # Also check LeaderboardData for legacy entries that predate
                            # the submissions sheet — a player's actual best game might
                            # only exist there, not in submissions.
                            player_name_for_ld = p_row[1].strip() if len(p_row) > 1 else ''
                            ld_for_pb = _ld_ctx
                            try:
                                for ld_row in ld_for_pb:
                                    if len(ld_row) < 4:
                                        continue
                                    if ld_row[1].strip() != player_name_for_ld:
                                        continue
                                    lb_name = ld_row[0].strip()
                                    if ' - ' in lb_name or lb_name in {'Flawless', 'Healing Horn', '200 Takedowns', '100 Kills'}:
                                        continue
                                    try:
                                        ld_td = int(ld_row[3])
                                    except ValueError:
                                        continue
                                    if ld_td > pb_td:
                                        pb_td = ld_td
                                        best_td_game = ['legacy', player_name_for_ld, '', lb_name, '', '', '', str(ld_td), '?', '?']
                            except Exception:
                                pass

                            def _placement_str(weapon, player_name, ld_rows):
                                # Find player's rank on this weapon's board and return a label
                                entries = []
                                for r in ld_rows:
                                    if len(r) < 4 or r[0].strip() != weapon:
                                        continue
                                    try:
                                        entries.append((r[1].strip(), int(r[3])))
                                    except ValueError:
                                        continue
                                entries.sort(key=lambda x: -x[1])
                                for i, (pname, score) in enumerate(entries):
                                    if pname == player_name:
                                        pos = i + 1
                                        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(pos, f'#{pos}')
                                        return f"{medal} on the {weapon} board ({score} TDs, {len(entries)} entries)"
                                return None

                            def _game_str(row, player_name='', ld_rows=None):
                                is_legacy = row[0] == 'legacy'
                                weapon = row[3].strip() if len(row) > 3 else '?'
                                tds    = row[7].strip() if len(row) > 7 else '?'
                                if is_legacy:
                                    lb_ctx = ''
                                    if ld_rows and player_name:
                                        placement = _placement_str(weapon, player_name, ld_rows)
                                        if placement:
                                            lb_ctx = f', {placement}'
                                    return f"{weapon} — {tds} TDs (legacy entry, no map/deaths data){lb_ctx}"
                                map_    = row[5].strip() if len(row) > 5 else '?'
                                kills   = row[8].strip() if len(row) > 8 else '?'
                                deaths  = row[9].strip() if len(row) > 9 else '?'
                                lb_ctx = ''
                                if ld_rows and player_name:
                                    placement = _placement_str(weapon, player_name, ld_rows)
                                    if placement:
                                        lb_ctx = f', {placement}'
                                return f"{weapon} on {map_} — {tds} TDs / {kills} kills / {deaths} deaths{lb_ctx}"

                            pb_parts = []
                            if best_td_game is not None:
                                pb_parts.append(f"Best TD game: {_game_str(best_td_game, player_name_for_ld, ld_for_pb)}")
                            if best_kills_game is not None and best_kills_game is not best_td_game:
                                pb_parts.append(f"Best kills game: {_game_str(best_kills_game, player_name_for_ld, ld_for_pb)}")
                            elif best_kills_game is not None and best_kills_game is best_td_game:
                                pb_parts[0] = f"Best game (top TD and kills): {_game_str(best_td_game, player_name_for_ld, ld_for_pb)}"
                            pb_str = (", " + "; ".join(pb_parts)) if pb_parts else ""
                            logged_runs = len(player_subs_pb)
                            player_stats_ctx = f"Player stats — Total marks (= total career runs, including legacy): {total_marks}, Logged runs in submissions sheet: {logged_runs}, Top weapons by marks: {top_weapons}{pb_str}"

                            # Hundred Handed progress — which primary weapon+subclass combos are missing
                            try:
                                cwm = config.CLASS_WEAPON_MAP
                                ranged = set(getattr(config, 'RANGED_WEAPONS', []))
                                done_pairs = set()
                                for sub_r in player_subs_pb:
                                    if len(sub_r) > 4:
                                        done_pairs.add((sub_r[4].strip(), sub_r[3].strip()))
                                missing_by_class = {}
                                for cls_name, weapons in cwm.items():
                                    for w in weapons:
                                        if w in ranged:
                                            continue
                                        if (cls_name, w) not in done_pairs:
                                            missing_by_class.setdefault(cls_name, []).append(w)
                                total_needed = sum(len(v) for v in missing_by_class.values())
                                total_possible = sum(
                                    len([w for w in weapons if w not in ranged])
                                    for weapons in cwm.values()
                                )
                                completed = total_possible - total_needed
                                if total_needed == 0:
                                    hh_str = "Hundred Handed: COMPLETE — all primary weapon/subclass combos submitted."
                                else:
                                    missing_lines = "; ".join(
                                        f"{cls}: {', '.join(sorted(ws))}"
                                        for cls, ws in sorted(missing_by_class.items())
                                    )
                                    hh_str = f"Hundred Handed progress: {completed}/{total_possible} combos done. Missing — {missing_lines}"
                                player_stats_ctx += f"\n{hh_str}"
                            except Exception:
                                pass

                            # Per-weapon avg kill share and TD share
                            try:
                                from cogs.registry import calculate_weapon_shares_for_player
                                w_kill, w_td = await calculate_weapon_shares_for_player(discord_id_str)
                                all_weapons = set(w_kill) | set(w_td)
                                if all_weapons:
                                    share_lines = []
                                    for w in sorted(all_weapons):
                                        parts = []
                                        if w in w_kill:
                                            parts.append(f"{w_kill[w]}% kill share")
                                        if w in w_td:
                                            parts.append(f"{w_td[w]}% TD share")
                                        share_lines.append(f"{w}: {', '.join(parts)}")
                                    player_stats_ctx += f"\nPer-weapon averages: {'; '.join(share_lines)}"
                            except Exception:
                                pass

                            break
                    # Build rich per-player summary for comparisons
                    subs_all = _subs_ctx
                    ld_all = _ld_ctx

                    # Unique weapons and subclasses per player from submissions
                    player_weapon_diversity = {}  # name -> set of weapons
                    player_subclass_diversity = {}  # name -> set of subclasses
                    player_sub_counts = {}  # name -> submission count
                    player_best_sub = {}   # name -> best submission row by TD
                    player_td_totals = {}  # name -> [td values] for avg
                    player_kill_totals = {}  # name -> [kills values] for avg + lethality
                    name_lookup = {p_row[0].strip(): p_row[1].strip() for p_row in p_rows if len(p_row) > 1}
                    for row in subs_all:
                        if len(row) < 9:
                            continue
                        pid = row[2].strip()
                        pname = name_lookup.get(pid, '')
                        if not pname:
                            continue
                        weapon = row[3].strip()
                        subclass = row[4].strip()
                        if pname not in player_weapon_diversity:
                            player_weapon_diversity[pname] = set()
                            player_subclass_diversity[pname] = set()
                            player_sub_counts[pname] = 0
                            player_td_totals[pname] = []
                            player_kill_totals[pname] = []
                        player_weapon_diversity[pname].add(weapon)
                        player_subclass_diversity[pname].add(subclass)
                        player_sub_counts[pname] += 1
                        try:
                            row_td = int(row[7])
                            row_kills = int(row[8])
                            player_td_totals[pname].append(row_td)
                            player_kill_totals[pname].append(row_kills)
                            current_best = player_best_sub.get(pname)
                            current_best_td = int(current_best[7]) if current_best and len(current_best) > 7 else 0
                            if row_td > current_best_td:
                                player_best_sub[pname] = row
                        except (ValueError, TypeError):
                            pass

                    # Weapons on leaderboards per player
                    player_lb_weapons = {}  # name -> set of weapons with board entries
                    for row in ld_all:
                        if len(row) < 2:
                            continue
                        pname = row[1].strip()
                        weapon = row[0].strip()
                        if pname not in player_lb_weapons:
                            player_lb_weapons[pname] = set()
                        player_lb_weapons[pname].add(weapon)

                    # Build summary lines
                    all_players_summary = []
                    for p_row in p_rows:
                        if len(p_row) > 1 and p_row[1].strip():
                            pname = p_row[1].strip()
                            marks = int(p_row[3]) if len(p_row) > 3 and p_row[3].strip().isdigit() else 0
                            unique_weapons = len(player_weapon_diversity.get(pname, set()))
                            unique_subclasses = len(player_subclass_diversity.get(pname, set()))
                            lb_weapons = len(player_lb_weapons.get(pname, set()))
                            sub_count = player_sub_counts.get(pname, 0)
                            all_players_summary.append((pname, marks, sub_count, unique_weapons, unique_subclasses, lb_weapons))

                    all_players_summary.sort(key=lambda x: -x[1])
                    def _lethality_str(pname):
                        tds = player_td_totals.get(pname, [])
                        kills = player_kill_totals.get(pname, [])
                        if len(tds) < 3:
                            return ''
                        avg_td = sum(tds) / len(tds)
                        avg_k = sum(kills) / len(kills)
                        kill_rate = (avg_k / avg_td * 100) if avg_td > 0 else 0
                        td_per_kill = (avg_td / avg_k) if avg_k > 0 else 0
                        return f", avg {avg_td:.0f} TD/{avg_k:.0f}K per run, {kill_rate:.0f}% kill rate"
                    summary_lines = [
                        f"{n}: {m} marks, {uw} unique weapons, {lw} on leaderboards{_lethality_str(n)}"
                        for n, m, s, uw, us, lw in all_players_summary[:20]
                    ]
                    if summary_lines:
                        player_stats_ctx += f"\n\nAll players (top 20 by marks):\n" + "\n".join(summary_lines)

                    # Per-player personal bests from LeaderboardData
                    player_pb_td = {}  # name -> best TD score
                    player_pb_kills = {}  # name -> best kills score
                    for row in ld_all:
                        if len(row) < 4:
                            continue
                        lb_name = row[0].strip()
                        pname = row[1].strip()
                        try:
                            score = int(row[3])
                        except ValueError:
                            continue
                        if lb_name == '100 Kills':
                            player_pb_kills[pname] = max(player_pb_kills.get(pname, 0), score)
                        elif ' - ' not in lb_name and lb_name not in {'Flawless', 'Healing Horn', '200 Takedowns'}:
                            player_pb_td[pname] = max(player_pb_td.get(pname, 0), score)

                    pb_lines = []
                    all_pb_names = set(player_pb_td) | set(player_pb_kills) | set(player_best_sub)
                    for pname in sorted(all_pb_names):
                        td = player_pb_td.get(pname, 0)
                        parts = []
                        best_sub = player_best_sub.get(pname)
                        if best_sub and len(best_sub) > 8:
                            sub_td = int(best_sub[7]) if best_sub[7].strip().isdigit() else 0
                            sub_kills = best_sub[8].strip() if best_sub[8].strip().isdigit() else '?'
                            sub_weapon = best_sub[3].strip() if len(best_sub) > 3 else '?'
                            # Use whichever TD is higher — submission or LeaderboardData (legacy)
                            best_td = max(td, sub_td)
                            if best_td == sub_td and sub_td > 0:
                                parts.append(f"best game: {sub_weapon} — {sub_td} TDs / {sub_kills} kills")
                            elif td > sub_td:
                                parts.append(f"best TD: {td} (legacy entry, weapon not tracked per-game here)")
                        elif td:
                            parts.append(f"best TD: {td}")
                        kills_pb = player_pb_kills.get(pname, 0)
                        if kills_pb:
                            parts.append(f"best kills score: {kills_pb}")
                        if parts:
                            pb_lines.append(f"{pname}: {', '.join(parts)}")
                    if pb_lines:
                        player_stats_ctx += f"\n\nPlayer personal bests:\n" + "\n".join(pb_lines)

                    # SpecialOps achievements per player
                    try:
                        so_rows = await _db.get_all_special_ops()
                        so_by_player = {}
                        for so_row in so_rows:
                            if len(so_row) > 2:
                                pname = so_row[1].strip()
                                achievement = so_row[2].strip()
                                if pname not in so_by_player:
                                    so_by_player[pname] = []
                                so_by_player[pname].append(achievement)
                        if so_by_player:
                            so_lines = [f"{p}: {', '.join(a)}" for p, a in so_by_player.items()]
                            player_stats_ctx += f"\n\nSpecial achievements (Fist and Shield, Knife, etc):\n" + "\n".join(so_lines)
                    except Exception:
                        pass
                except Exception:
                    pass

                # Try to find a matching submission if player mentioned stats
                msg_kills, msg_tds = extract_stats_from_message(resolved_message)
                if msg_kills or msg_tds:
                    sub_ctx = find_submission_from_stats(discord_id_str, _subs_ctx, _ld_ctx, msg_kills, msg_tds, player_name_ref=player_name)
                    if sub_ctx:
                        player_stats_ctx = (player_stats_ctx + '\n' + sub_ctx).strip()

                # Add weapon bomb count if message asks about it
                if any(w in resolved_message.lower() for w in ['how many', 'count', 'most kills', 'highest', 'most takedowns', '100 takedown']):
                    _bw = extract_weapon_from_message(resolved_message)
                    if _bw:
                        bomb_count = count_qualifying_runs(_bw, _ld_ctx, 100)
                        if bomb_count is not None:
                            player_stats_ctx += f"\nServer-wide 100+ TD runs with {_bw}: {bomb_count}"

                # If a weapon is mentioned in any context, surface its leaderboard rankings
                # so the Butler can answer "who's #1 on Messer" correctly
                msg_lower = resolved_message.lower()
                mentioned_weapon = extract_weapon_from_message(resolved_message)
                if mentioned_weapon:
                    try:
                        ld_ctx = _ld_ctx
                        weapon_entries = []
                        for r in ld_ctx:
                            if len(r) < 4 or r[0].strip() != mentioned_weapon:
                                continue
                            if ' - ' in r[0]:
                                continue
                            try:
                                weapon_entries.append((r[1].strip(), int(r[3])))
                            except ValueError:
                                continue
                        weapon_entries.sort(key=lambda x: -x[1])
                        if weapon_entries:
                            board_lines = []
                            medals = {1: '🥇', 2: '🥈', 3: '🥉'}
                            for i, (pname, score) in enumerate(weapon_entries[:5], 1):
                                medal = medals.get(i, f'#{i}')
                                board_lines.append(f"{medal} {pname}: {score} TDs")
                            player_stats_ctx += f"\n\n{mentioned_weapon} leaderboard (top {len(board_lines)}):\n" + "\n".join(board_lines)
                    except Exception:
                        pass

                # Detect rude messages — force idiot emoji regardless of AI response
                rude_words = ['fuck you', 'fuck off', 'shut up', 'idiot', 'stupid', 'useless', 'trash', 'garbage', 'dumb', 'moron', 'shut it']
                is_rude = any(w in resolved_message.lower() for w in rude_words)

                result = await call_butler_ai(resolved_message, ctx_messages, player_name, 'main', player_stats_ctx, is_idiot=is_idiot)
                if is_rude:
                    try:
                        await message.add_reaction('<a:idiot_daze:1520130932584223012>')
                    except Exception:
                        pass
                if result:
                    response_text, needs_eyeball = result
                    BUTLER_AI_COOLDOWNS[message.author.id] = now_ts
                    sent_msg = await message.reply(response_text, mention_author=False)
                    # Track for reaction feedback
                    BUTLER_RESPONSE_LOG[sent_msg.id] = {
                        'trigger': message.content[:100],
                        'response': response_text[:100],
                        'player': player_name,
                        'reactions': []
                    }
                    # Keep log bounded
                    if len(BUTLER_RESPONSE_LOG) > 200:
                        oldest = next(iter(BUTLER_RESPONSE_LOG))
                        del BUTLER_RESPONSE_LOG[oldest]
                    return

        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')

        # Check if this is an art post in the active bounty channel
        bounty = await get_active_bounty()
        if bounty and message.channel.id == bounty['channel_id']:
            has_image = any(
                att.filename.lower().endswith(image_extensions)
                for att in message.attachments
            )
            if has_image and not bounty['completions_msg_id'] and not bounty['bonus_msg_id']:
                completions_placeholder = (
                    f"```\n"
                    f"╭──────────────────────────────╮\n"
                    f"  {{bounty['theme_emoji']}} COMPLETIONS {{bounty['theme_emoji']}}\n"
                    f"╰──────────────────────────────╯\n"
                    f"No completions yet.\n"
                    f"```"
                )
                bonus_placeholder = (
                    f"```\n"
                    f"╭──────────────────────────────╮\n"
                    f"  {{bounty['theme_emoji']}} BONUS COMPLETIONS {{bounty['theme_emoji']}}\n"
                    f"╰──────────────────────────────╯\n"
                    f"No bonus completions yet.\n"
                    f"```"
                )
                try:
                    comp_msg = await message.channel.send(completions_placeholder)
                    bonus_msg = await message.channel.send(bonus_placeholder)
                    progress_placeholder = (
                        f"```\n"
                        f"╭──────────────────────────────╮\n"
                        f"  {{bounty['theme_emoji']}} TOP HUNTERS {{bounty['theme_emoji']}}\n"
                        f"╰──────────────────────────────╯\n"
                        f"No submissions yet.\n"
                        f"```"
                    )
                    progress_msg = await message.channel.send(progress_placeholder)
                    await _db.update_bounty_field(bounty['id'], 'completions_msg_id', str(comp_msg.id))
                    await _db.update_bounty_field(bounty['id'], 'bonus_msg_id', str(bonus_msg.id))
                    await _db.update_bounty_field(bounty['id'], 'progress_msg_id', str(progress_msg.id))
                except Exception as e:
                    print(f"Bounty placeholder post error: {e}")
            return

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Track reactions on Butler responses for feedback analysis."""
        if user.bot:
            return
        msg_id = reaction.message.id
        if msg_id not in BUTLER_RESPONSE_LOG:
            return
        emoji_str = str(reaction.emoji)
        entry = BUTLER_RESPONSE_LOG[msg_id]
        entry['reactions'].append(emoji_str)
        positive = {'😂', '😆', '🤣', '👍', '❤️', '🔥', '💀', '😭', '👏'}
        negative = {'👎', '🙄', '😐'}
        middle_finger = {'🖕'}
        if emoji_str in positive:
            sentiment = 'positive'
        elif emoji_str in negative:
            sentiment = 'negative'
        elif emoji_str in middle_finger:
            sentiment = 'middle_finger'
        else:
            sentiment = 'neutral'
        print(f"[BUTLER REACTION] {sentiment} | {user.display_name} reacted {emoji_str} | trigger: '{entry['trigger'][:60]}' | response: '{entry['response'][:60]}'")


asyn