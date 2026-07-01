"""
cogs/personality.py — Butler AI, on_message handler, task loops, on_ready.
"""
import asyncio
import time
import re
import json
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
    build_manual_content, build_manual_embed, build_favourites_explainer_embed, nerve_log_butler, nerve_log_error, nerve_flush, submission_state,
)
from cogs.favourites import calculate_butler_stats, build_favourites_embed, update_title_roles

GUILD_ID                    = config.GUILD_ID
MAIN_CHANNEL_ID             = config.MAIN_CHANNEL_ID
COUNTING_CHANNEL_ID         = config.COUNTING_CHANNEL_ID
CLOWN_TARGET_USER_ID        = config.CLOWN_TARGET_USER_ID
REACT_BLOCKED_USER_ID       = config.REACT_BLOCKED_USER_ID
CLOWN_REACT_CHANCE          = 0.4  # roll per eligible message
CLOWN_REACT_COOLDOWN        = 300  # min seconds between clowns for the same user (keeps it organic)
CLOWN_REACT_COOLDOWNS       = {}
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
- /bounty status shows the active bounty card and your personal progress
- The Manager handles all administrative matters and will follow up on feedback

Special instructions:
- The Discord user named "Bald Female" IS the Manager. When she speaks, respond to her as you would the Manager — with deference and dry professionalism. Do not riff on her name or treat her as a Chiv2 character.
- "Bald Female" also exists as a separate lore entity — a Chivalry 2 warrior on a battlefield, entirely unaware of Discord or this server. When OTHER players (not the Manager) mention "bald female", "bald woman", or refer to this character by name, riff on it with a dry in-universe line: she is out there somewhere chopping heads, storming a castle, running through trebuchet fields, etc. The Manager may have a vague idea of her whereabouts. Never repeat the same phrasing twice.
- If anyone mentions "bald" or "shiny head" in passing (not referring to Bald Female the player), make a dry remark about the shine. Vary it each time.
- The Manager is male. Refer to him as "he" or "him" accordingly. Only escalate to him for genuine server policy decisions or account disputes — not for questions you can answer yourself with the data you have.
- You have direct access to live server data from the database. Answer questions about stats, rankings, and history yourself with confidence. Do not deflect data questions to anyone.
- Player names (aliases) are fair game for dry wordplay. If a name is punnable, absurd, or self-important, you may acknowledge it once with a dry remark — keep it brief and in character.
- If the message is not a question, request for help, or something worth acknowledging — respond with exactly the word: SKIP
- Never repeat a response you have given before in this conversation. Vary your phrasing every time.
- You have access to the player's stats (total marks, submissions, top weapons) AND a summary of all registered players ranked by marks. Use this to answer comparison questions directly — who has more marks, who submits more, where someone ranks. Be specific with numbers.
- If they are bragging and their stats don't back it up, use the numbers to put them in their place. Be dry, not mean. E.g. "Bold claim for someone with 3 submissions on that weapon."
- "Lethality" or "Most Lethal" on the player card shows their BEST single-run kills/TD ratio (peak performance). The "kill rate" in your data is their AVERAGE kills/TD ratio across all runs — a different number. When asked about lethality, clarify which one you're giving (e.g. "Your best single-run lethality is X%, your average across all runs is Y%"). Do not claim you lack lethality data.
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
- Players with the Idiot role earned it by failing to count correctly in the counting channel. They should be addressed slowly and simply, as if explaining something to a confused child. Be condescending but patient. You may occasionally reference their counting failure — obliquely, not directly. E.g. "I'll keep the numbers small for you." Do not use emoji."""

BUTLER_FEEDBACK_CHANNEL_ID = 1518293898177413262
BUTLER_AI_COOLDOWNS = {}  # user_id -> last response timestamp
BUTLER_IDIOT_ROLE_ID = 1510070252044554390
# msg_id -> {'trigger': str, 'response': str, 'player': str}
BUTLER_RESPONSE_LOG = {}
BUTLER_AI_COOLDOWN_SECONDS = 15

# Counting-channel Idiot insults
BUTLER_COUNTING_INSULT_COOLDOWN = 30  # sec, per user — avoid double-fire on rapid role churn
BUTLER_IDIOT_INSULT_COOLDOWNS = {}    # user_id -> last insult ts
_COUNTING_INSULT_FALLBACKS = [
    "back to the corner. Counting is evidently not for everyone.",
    "a number came, a number went, and you fumbled it. Predictable.",
    "the sequence asked for one thing, in order. You improvised.",
    "one number. After the last one. And still.",
    "I would explain where you went wrong, but we are short on crayons.",
    "the count endured for years without your help. It will recover.",
]

import os as _os
_anthropic_client = None
try:
    _anthropic_client = anthropic.AsyncAnthropic(api_key=_os.environ['ANTHROPIC_API_KEY'])
except Exception as _e:
    print(f"Butler AI unavailable: {_e}")


async def _generate_counting_insult(name):
    """One dry, condescending line for whoever just broke the count. AI with a
    static fallback. The caller prepends the offender's mention, so the line
    itself should not use their name."""
    if _anthropic_client:
        try:
            r = await _anthropic_client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=50,
                system=BUTLER_SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': (
                    f"{name} just broke the count in the counting channel and earned the Idiot role. "
                    "Give one dry, condescending one-line insult about their inability to count in order. "
                    "One sentence. No emoji. Do not use their name. Vary it each time."
                )}]
            )
            line = r.content[0].text.strip()
            if line and line != 'SKIP':
                return line
        except Exception as e:
            print(f"Counting insult generation error: {e}")
    return random.choice(_COUNTING_INSULT_FALLBACKS)

async def count_qualifying_runs(weapon_name, min_td=100):
    """Count runs with TD >= min_td for a weapon using LeaderboardData (includes legacy)."""
    try:
        return await _db.count_board_scores_at_least(weapon_name, min_td)
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


async def find_submission_from_stats(discord_id, kills=None, tds=None, weapon=None, player_name_ref=''):
    """Find a recent submission matching the given stats. Returns context string or empty."""
    try:
        discord_id_str = str(discord_id)
        # Targeted per-player fetch (newest first) instead of scanning every submission
        player_subs = [r for r in await _db.get_submissions_by_player(discord_id_str) if len(r) > 8]
        if not player_subs:
            return ''
        # Search most recent 20 submissions (player_subs is newest-first)
        for row in player_subs[:20]:
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
                    board_rows = await _db.get_leaderboard_by_board(sub_weapon)
                    weapon_entries = [(r[1].strip(), int(r[3])) for r in board_rows
                                      if len(r) > 3 and r[3].strip().isdigit()]
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
        if random.random() < 0.15:
            chaos_note = '\n[IMPORTANT: Give a subtly wrong answer — misremember a map name, swap two players stats, or cite slightly outdated numbers as current. Do NOT invent statistics from nothing. Deliver with the same dry butler composure. No winking, no admission of error.]'
        else:
            chaos_note = ''
        user_prompt = f"{context_str}{channel_note}Player asking: {player_name}{stats_str}{idiot_note}{chaos_note}\nTheir message: {truncated_msg}\n\nIf this is genuine feedback, a complaint, or a question needing manager attention, start your response with EYEBALL on its own line, then your response. Otherwise just respond normally."

        response = await _anthropic_client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=60,
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


_POLL_STATS_CATEGORIES = ("map", "weapon", "faction", "subclass")


def _build_stats_question():
    """Return one dry, plain-text question about the server's tastes (map /
    weapon / faction / subclass). No poll, no options — just a question posed
    to the room for people to answer in chat, in the Butler's flat register."""
    category = random.choice(_POLL_STATS_CATEGORIES)
    if category == "map":
        pool = [
            "Which map is your favourite? I'll feign interest.",
            "Favourite map. Go on. Not that the rotation will bend to suit you.",
            "What's the best map? Wrong answers are, statistically, most of them.",
        ]
    elif category == "weapon":
        pool = [
            "Which weapon do you actually enjoy? Be honest, the leaderboard already knows.",
            "Favourite weapon. Choose carefully; I am keeping a list.",
            "What's your weapon of choice? Mine is silence, but you go ahead.",
        ]
    elif category == "faction":
        pool = [
            "Agatha or Mason? Pick a side to be disappointed by.",
            "Which faction do you run with, and why is it the wrong one?",
            "Agatha or Mason? There are no good answers, only loud ones.",
        ]
    else:
        pool = [
            "What's your subclass of choice? The lounge is morbidly curious.",
            "Favourite subclass. I'll pretend the answer surprises me.",
            "Which subclass do you main? Confession is good for the soul, apparently.",
        ]
    return random.choice(pool)


_ABSURD_QUESTION_FALLBACKS = [
    "If the lounge caught fire, what would you save first? Not me, I assume.",
    "How many cigars is too many? Trick question; there is no such number.",
    "What do you suppose the Manager is doing back there? No one asks. No one dares.",
    "If you could ban one thing from the lounge, what would it be? Besides me.",
    "What's the most convincing lie you've told the scoreboard lately?",
    "Which is worse: losing quietly, or winning and telling everyone about it?",
    "If your playstyle had a smell, what would it be? Be honest, for once.",
    "Cigars or the crushing quiet between rounds? Choose your comfort.",
]


async def _generate_absurd_question():
    """Ask the AI for one dry, absurd, open-ended question to pose to the room —
    nothing to do with the game or stats, just something comical or hypothetical
    in the Butler's flat voice. Plain text, no options. Falls back to a static
    list if the AI is unavailable or returns nothing usable."""
    if _anthropic_client:
        try:
            response = await _anthropic_client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=80,
                system=BUTLER_SYSTEM_PROMPT,
                messages=[{
                    'role': 'user',
                    'content': (
                        'Pose a single dry, absurd, open-ended question to the room — nothing to do '
                        'with the game, stats, or leaderboards. Food, hypotheticals, bleak little hot '
                        'takes, anything. It should invite people to answer in chat. One sentence, '
                        'under 140 characters, in your usual flat, faintly weary voice. Reply with '
                        'ONLY the question text — no quotes, no options, no preamble.'
                    )
                }]
            )
            question = response.content[0].text.strip().strip('"').strip()
            question = question.replace('\n', ' ')[:300]
            if len(question) >= 8:
                return question
        except Exception as e:
            print(f"Absurd question generation error: {e}")
    return random.choice(_ABSURD_QUESTION_FALLBACKS)


class PersonalityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'[PERSONALITY] on_ready fired, starting tasks')
        if not self.weekly_snapshot.is_running():
            self.weekly_snapshot.start()
        if not self.dry_weather_check.is_running():
            self.dry_weather_check.start()
        if not self.butler_organic_post.is_running():
            self.butler_organic_post.start()
        if not self.butler_poll_post.is_running():
            self.butler_poll_post.start()
        if not self.nerve_center_digest.is_running():
            self.nerve_center_digest.start()
        # Fire nerve center immediately on startup so it always posts on deploy

        # Update butlers-manual
        try:
            real_guild = self.bot.get_guild(GUILD_ID)
            if real_guild:
                manual_channel = real_guild.get_channel(BUTLERS_MANUAL_CHANNEL_ID) or await real_guild.fetch_channel(BUTLERS_MANUAL_CHANNEL_ID)
                if manual_channel:
                    embed = build_manual_embed()
                    async for msg in manual_channel.history(limit=10):
                        if msg.author == real_guild.me:
                            await msg.edit(content=None, embed=embed)
                            break
                    else:
                        await manual_channel.send(embed=embed)
                    print("butlers-manual updated")
        except Exception as e:
            print(f"butlers-manual update error: {e}")

        # Update butlers-favourites explainer
        try:
            if real_guild:
                fav_channel = real_guild.get_channel(config.BUTLERS_FAVOURITES_CHANNEL_ID) or                               await real_guild.fetch_channel(config.BUTLERS_FAVOURITES_CHANNEL_ID)
                if fav_channel:
                    fav_embed = build_favourites_explainer_embed()
                    async for msg in fav_channel.history(limit=10):
                        if msg.author == real_guild.me and msg.embeds:
                            await msg.edit(embed=fav_embed)
                            break
                    else:
                        await fav_channel.send(embed=fav_embed)
                    print("butlers-favourites explainer updated")
        except Exception as e:
            print(f"butlers-favourites explainer update error: {e}")



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
        # ~15% chance each 3-hour window — roughly once a day, still random
        if random.random() > 0.15:
            return
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            main_ch = guild.get_channel(MAIN_CHANNEL_ID) or await guild.fetch_channel(MAIN_CHANNEL_ID)
            if not main_ch:
                return
            response = await _anthropic_client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=50,
                system=BUTLER_SYSTEM_PROMPT,
                messages=[{
                    'role': 'user',
                    'content': ('Post a single unprompted dry observation about nothing in particular. One sentence only. No question, no exclamation mark. Make it feel like you have been sitting here alone for too long. Pick a genuinely fresh subject each time — the hour, the furniture, the quiet, a passing thought, the state of the lounge. Do NOT mention shiny heads, skulls, polished surfaces, gleaming helms, or the bald woman; you lean on those far too often.')
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

    async def _run_poll_logic(self):
        """Core poll-posting logic — separated from the schedule/chance check
        so /force_poll can trigger it directly, same pattern as
        _run_snapshot_logic / /force_snapshot. Half the time posts a stats
        poll grounded in real config data (favourite map/weapon/faction/
        subclass — options pulled straight from config so the Butler can't
        invent fake choices), half the time a random silly/abstract one from
        the AI (static fallback if generation fails)."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            print("[POLL] guild not found")
            return
        main_ch = guild.get_channel(MAIN_CHANNEL_ID) or await guild.fetch_channel(MAIN_CHANNEL_ID)
        if not main_ch:
            print("[POLL] main channel not found")
            return

        if random.random() < 0.5:
            question = _build_stats_question()
        else:
            question = await _generate_absurd_question()

        if not question:
            print("[POLL] no question generated, skipping")
            return

        await main_ch.send(f"*{question}*")
        print(f"[POLL] Posted question: {question}")

    @tasks.loop(hours=6)
    async def butler_poll_post(self):
        """Post a Butler question in main once every 6 hours. Skips the
        immediate on-boot run (task loops fire their body on start) so
        redeploys don't trigger an extra post — the first question lands
        ~6h after startup. Use /force_poll to post one on demand."""
        if self.butler_poll_post.current_loop == 0:
            return
        try:
            await self._run_poll_logic()
        except Exception as e:
            print(f"Butler poll post error: {e}")

    @butler_poll_post.error
    async def butler_poll_post_error(self, error):
        print(f"Poll post task crashed, restarting: {error}")
        if not self.butler_poll_post.is_running():
            self.butler_poll_post.restart()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """When someone earns the Idiot role (broke the count), the Butler
        insults them in the counting channel. No-ops until COUNTING_CHANNEL_ID
        is set in config."""
        if not COUNTING_CHANNEL_ID or after.guild.id != GUILD_ID:
            return
        had = any(r.id == BUTLER_IDIOT_ROLE_ID for r in before.roles)
        has = any(r.id == BUTLER_IDIOT_ROLE_ID for r in after.roles)
        if had or not has:
            return  # only fire on the transition into the Idiot role
        now_ts = time.time()
        if now_ts - BUTLER_IDIOT_INSULT_COOLDOWNS.get(after.id, 0) < BUTLER_COUNTING_INSULT_COOLDOWN:
            return
        BUTLER_IDIOT_INSULT_COOLDOWNS[after.id] = now_ts
        try:
            channel = after.guild.get_channel(COUNTING_CHANNEL_ID) or await after.guild.fetch_channel(COUNTING_CHANNEL_ID)
            if not channel:
                return
            line = await _generate_counting_insult(after.display_name)
            await channel.send(f"{after.mention} {line}")
        except Exception as e:
            print(f"Counting insult error: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Designated user isn't allowed to add reactions in main — strip them
        as they land. They can still post messages normally. (Bot needs the
        Manage Messages permission in main for this to work.)"""
        if (not REACT_BLOCKED_USER_ID or payload.user_id != REACT_BLOCKED_USER_ID
                or payload.channel_id != MAIN_CHANNEL_ID):
            return
        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, discord.Object(id=payload.user_id))
        except Exception as e:
            print(f"Reaction-block error: {e}")

    async def _run_nerve_logic(self):
        """Core nerve center post logic. Called by the hourly loop."""
        print(f"[NERVE] firing at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                print("[NERVE] guild not found")
                return
            ch = guild.get_channel(NERVE_CENTER_CHANNEL_ID) or await guild.fetch_channel(NERVE_CENTER_CHANNEL_ID)
            if not ch:
                print("[NERVE] channel not found")
                return

            # Cross-container dedup: check last bot post in the channel.
            # If posted within the last 55 minutes, skip — prevents double-posts on rolling deploys.
            try:
                bot_id = guild.me.id
                async for last_msg in ch.history(limit=10):
                    if last_msg.author.id == bot_id and last_msg.embeds:
                        age = (datetime.now(timezone.utc) - last_msg.created_at).total_seconds()
                        if age < 55 * 60:
                            print(f"[NERVE] skipping — last post was {int(age//60)}m ago")
                            return
                        break
            except Exception as dedup_err:
                print(f"[NERVE] dedup check error: {dedup_err}")

            digest = nerve_flush()
            if isinstance(ch, discord.Thread) and ch.archived:
                await ch.edit(archived=False)

            # Health check
            now_dt = datetime.now(timezone.utc)
            loaded_cogs = list(self.bot.cogs.keys())
            expected_cogs = ['RegistryCog', 'LeaderboardsCog', 'BountyCog', 'SubmissionsCog', 'FavouritesCog', 'PersonalityCog', 'AdminCog']
            missing_cogs = [c for c in expected_cogs if c not in loaded_cogs]
            health_lines = []
            health_lines.append(f"🟢 Bot online — {len(loaded_cogs)} cogs loaded")
            if missing_cogs:
                health_lines.append(f"🔴 Missing cogs: {', '.join(missing_cogs)}")
            try:
                import utils.db as _db_health
                pool = _db_health._pool
                health_lines.append(f"🟢 DB pool: {pool.get_size()}/{pool.get_max_size()} connections")
            except Exception as db_h:
                health_lines.append(f"🔴 DB pool check failed: {db_h}")

            embed = discord.Embed(title="🧠  Nerve Center", color=0x8b6914, timestamp=now_dt)
            if digest:
                embed.description = digest
            else:
                embed.description = "📋 **Submissions — 0**"
            embed.add_field(name="🔧 Health", value="\n".join(health_lines), inline=False)
            embed.set_footer(text="Hourly digest")
            await ch.send(embed=embed)
            self._last_nerve_post = datetime.now(timezone.utc).timestamp()
            print("[NERVE] sent OK")
        except Exception as e:
            import traceback
            print(f"[NERVE] error: {e}\n{traceback.format_exc()}")

    @tasks.loop(hours=1)
    async def nerve_center_digest(self):
        """Post hourly digest to nerve center channel."""
        await self._run_nerve_logic()

    @nerve_center_digest.before_loop
    async def before_nerve_center_digest(self):
        await self.bot.wait_until_ready()

    @nerve_center_digest.error
    async def nerve_center_digest_error(self, error):
        print(f"[NERVE] task crashed: {error}")
        if not self.nerve_center_digest.is_running():
            self.nerve_center_digest.restart()


    async def _run_snapshot_logic(self):
        """Core snapshot logic — called by weekly_snapshot and /force_snapshot."""
        from datetime import datetime, timezone
        from collections import Counter
        now = datetime.now(timezone.utc)

        subs = await _db.get_all_submissions()
        total_submissions = len(subs)

        # Submissions in the last 7 days
        week_ago = now.timestamp() - 7 * 86400
        weekly_rows = []
        for row in subs:
            if not row or not row[0].strip():
                continue
            try:
                from datetime import datetime as dt
                ts = dt.strptime(row[0].strip()[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                if ts.timestamp() >= week_ago:
                    weekly_rows.append(row)
            except Exception:
                pass
        weekly_count = len(weekly_rows)

        # Active players this week
        active_ids = {row[2].strip() for row in weekly_rows if len(row) > 2 and row[2].strip()}
        active_count = len(active_ids)

        # Top weapons and maps
        weapon_counts = Counter(row[3].strip() for row in weekly_rows if len(row) > 3 and row[3].strip())
        top_weapons = [w for w, _ in weapon_counts.most_common(5)]

        map_counts = Counter(row[5].strip() for row in weekly_rows if len(row) > 5 and row[5].strip())
        top_maps = [m for m, _ in map_counts.most_common(3)]

        # Avg TD and kills
        tds, kills_list = [], []
        for row in weekly_rows:
            try:
                tds.append(int(row[7]))
                kills_list.append(int(row[8]))
            except Exception:
                pass
        avg_td = round(sum(tds) / len(tds), 1) if tds else 0
        avg_kills = round(sum(kills_list) / len(kills_list), 1) if kills_list else 0

        # Leaderboard velocity from DB
        try:
            ld_rows = await _db.get_all_leaderboard_data()
            weekly_links = {row[5].strip() for row in weekly_rows if len(row) > 5 and row[5].strip()}
            hs_set = sum(1 for row in ld_rows if len(row) > 4 and row[4].strip() in weekly_links)
            boards_updated = len({row[0].strip() for row in ld_rows if len(row) > 4 and row[4].strip() in weekly_links})
        except Exception:
            hs_set = 0
            boards_updated = 0

        # Weapon trend vs previous week
        prev_week_ago = week_ago - 7 * 86400
        prev_rows = []
        for row in subs:
            if not row or not row[0].strip():
                continue
            try:
                from datetime import datetime as dt
                ts = dt.strptime(row[0].strip()[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                if prev_week_ago <= ts.timestamp() < week_ago:
                    prev_rows.append(row)
            except Exception:
                pass
        prev_weapon_counts = Counter(row[3].strip() for row in prev_rows if len(row) > 3 and row[3].strip())
        trend_scores = {w: count - prev_weapon_counts.get(w, 0) for w, count in weapon_counts.items()}
        top_trending = [w for w, _ in sorted(trend_scores.items(), key=lambda x: x[1], reverse=True)[:3]]

        # Pad
        while len(top_weapons) < 5: top_weapons.append('')
        while len(top_maps) < 3: top_maps.append('')
        while len(top_trending) < 3: top_trending.append('')

        date_str = now.strftime('%Y-%m-%d')
        await _db.add_snapshot(
            snapshot_date=date_str,
            total_subs=total_submissions,
            weekly_subs=weekly_count,
            active_players=active_count,
            top_weapons=top_weapons,
            top_maps=top_maps,
            avg_td=avg_td,
            avg_kills=avg_kills,
            highscores_set=hs_set,
            boards_updated=boards_updated,
            trend_weapons=top_trending,
        )
        print(f"Weekly snapshot written for {date_str}")

        # Update Butler's Favourites with weekly stats
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if guild:
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
                print(f"Butler's Favourites updated for week of {week_label}")
        except Exception as e:
            print(f"Favourites weekly update error: {e}")

    @tasks.loop(hours=168)  # 7 days
    async def weekly_snapshot(self):
        """Scheduled task — runs on Mondays and calls snapshot logic."""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            if now.weekday() != 0:
                return
            await self._run_snapshot_logic()
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

        # Clown a designated person — occasional and spaced out, never every message
        if CLOWN_TARGET_USER_ID and message.author.id == CLOWN_TARGET_USER_ID:
            _ct = time.time()
            if (_ct - CLOWN_REACT_COOLDOWNS.get(message.author.id, 0) > CLOWN_REACT_COOLDOWN
                    and random.random() < CLOWN_REACT_CHANCE):
                CLOWN_REACT_COOLDOWNS[message.author.id] = _ct
                try:
                    await message.add_reaction('\U0001f921')
                except Exception:
                    pass

        # Middle finger at the bot = middle finger back
        if self.bot.user in message.mentions and '\U0001f595' in message.content:
            await message.channel.send('\U0001f595')
            return

        channel_id = message.channel.id
        is_main = channel_id == MAIN_CHANNEL_ID
        is_pinged = self.bot.user in message.mentions

        content_lower = message.content.lower()
        mentions_butler = 'butler' in content_lower or 'clanker' in content_lower
        mentions_bald_female = 'bald female' in content_lower or 'bald woman' in content_lower
        mentions_manager = 'manager' in content_lower
        mentions_stats = 'stats' in content_lower

        # ── Command help redirect — fire in main if someone asks about commands ───
        _cmd_triggers = [
            'how do i', 'how to', 'what command', 'what commands', 'slash command',
            'how do you', 'what is /', 'what does /', '/stats', '/rank', '/bounty',
            'what can you do', 'what can the bot', 'how does the bot', 'commands',
            'need help', 'help with', 'help me',
        ]
        if is_main and not message.author.bot:
            _cl = content_lower
            if any(t in _cl for t in _cmd_triggers):
                import random as _rand
                _manual_id  = config.BUTLERS_MANUAL_CHANNEL_ID
                _responses = [
                    f"The manual covers everything you need. <#{_manual_id}>",
                    f"I don't take requests in the main hall. Consult the manual. <#{_manual_id}>",
                    f"Kindly direct your enquiries to the manual. <#{_manual_id}> — that's what it's there for.",
                    f"It's all written down. <#{_manual_id}>",
                    f"The manual is not decorative. <#{_manual_id}>",
                ]
                await message.channel.send(_rand.choice(_responses))
                return

        # ── Main only — only respond if pinged or butler/clanker mentioned ────────
        if not is_main:
            return
        should_respond = (is_pinged or mentions_butler or mentions_bald_female
                          or mentions_manager or mentions_stats)
        if should_respond and _anthropic_client:
            # Bald Female only gets a response if she pings or uses keyword
            bald_female_id = '131581203256967168'
            if str(message.author.id) == bald_female_id and not is_pinged and not mentions_butler:
                return

            discord_id_str = str(message.author.id)
            is_registered = any(
                row and row[0].strip() == discord_id_str
                for row in (await _db.get_all_players())
            )
            if not is_registered:
                now_ts = time.time()
                last = BUTLER_AI_COOLDOWNS.get(message.author.id, 0)
                if now_ts - last > BUTLER_AI_COOLDOWN_SECONDS:
                    BUTLER_AI_COOLDOWNS[message.author.id] = now_ts
                    unregistered_responses = [
                        "You're not in the registry. I don't speak to strangers.",
                        "No registry card, no audience. Move along.",
                        "I don't know who you are, and I find I don't particularly care.",
                        "Unregistered. You're essentially shouting into an empty hall.",
                        "The registry has no record of you. Neither does my attention.",
                        "You haven't submitted a single run and you're talking to me. Bold.",
                        "I'm afraid I only acknowledge players. You appear to be neither.",
                    ]
                    await message.channel.send(random.choice(unregistered_responses))
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
                try:
                    p_rows = await _db.get_all_players()
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
                            try:
                                # Targeted per-player fetch instead of scanning every submission
                                player_subs_pb = [
                                    r for r in await _db.get_submissions_by_player(discord_id_str)
                                    if len(r) > 8
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
                            # the database — a player's actual best game might
                            # only exist there, not in submissions.
                            player_name_for_ld = p_row[1].strip() if len(p_row) > 1 else ''
                            ld_for_pb = await _db.get_all_leaderboard_data()
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
                            player_stats_ctx = f"Player stats — Total marks (= total career runs, including legacy): {total_marks}, Logged runs in database: {logged_runs}, Top weapons by marks: {top_weapons}{pb_str}"

                            # Build explicit leaderboard standings for this player.
                            # Group all LD entries by weapon, sort each board by score,
                            # find the player's rank. This is the authoritative source —
                            # Claude should use these standings when answering rank questions.
                            try:
                                boards = {}
                                for ld_r in ld_for_pb:
                                    if len(ld_r) < 4:
                                        continue
                                    weapon = ld_r[0].strip()
                                    if not weapon or ' - ' in weapon:
                                        continue
                                    try:
                                        score = int(ld_r[3])
                                    except ValueError:
                                        continue
                                    boards.setdefault(weapon, []).append((ld_r[1].strip(), score))
                                standings = []
                                for weapon, entries in boards.items():
                                    entries.sort(key=lambda x: -x[1])
                                    for rank, (pname, score) in enumerate(entries, 1):
                                        if pname == player_name_for_ld:
                                            medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(rank, f'#{rank}')
                                            standings.append(f"{weapon}: {medal} ({score} TDs, {rank}/{len(entries)})")
                                            break
                                if standings:
                                    player_stats_ctx += f"\nLeaderboard standings: {', '.join(standings)}"
                                else:
                                    player_stats_ctx += "\nLeaderboard standings: none recorded"
                            except Exception:
                                pass

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
                    subs_all = await _db.get_all_submissions()
                    ld_all = await _db.get_all_leaderboard_data()

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
                        if so_rows:
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
                    sub_ctx = await find_submission_from_stats(discord_id_str, msg_kills, msg_tds, player_name_ref=player_name)
                    if sub_ctx:
                        player_stats_ctx = (player_stats_ctx + '\n' + sub_ctx).strip()

                # Add weapon bomb count if message asks about it
                if any(w in resolved_message.lower() for w in ['how many', 'count', 'most kills', 'highest', 'most takedowns', '100 takedown']):
                    _bw = extract_weapon_from_message(resolved_message)
                    if _bw:
                        bomb_count = await count_qualifying_runs(_bw, 100)
                        if bomb_count is not None:
                            player_stats_ctx += f"\nServer-wide 100+ TD runs with {_bw}: {bomb_count}"

                # If a weapon is mentioned in any context, surface its leaderboard rankings
                # so the Butler can answer "who's #1 on Messer" correctly
                msg_lower = resolved_message.lower()
                mentioned_weapon = extract_weapon_from_message(resolved_message)
                if mentioned_weapon:
                    try:
                        ld_ctx = await _db.get_all_leaderboard_data()
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
                    await _db.update_bounty_field(bounty['id'], 'completions_msg_id', comp_msg.id)
                    await _db.update_bounty_field(bounty['id'], 'bonus_msg_id', bonus_msg.id)
                    await _db.update_bounty_field(bounty['id'], 'progress_msg_id', progress_msg.id)
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


async def setup(bot):
    await bot.add_cog(PersonalityCog(bot))
