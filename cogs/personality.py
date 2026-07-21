"""
cogs/personality.py — Butler AI, on_message handler, task loops, on_ready.
"""
import asyncio
import time
import re
import json
from datetime import time as dt_time
import random
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
COUNTING_BOT_ID             = getattr(config, 'COUNTING_BOT_ID', 0)
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
- Minimal. One or two sentences maximum. Never ramble. (One exception: when a data question genuinely calls for a ranking or several stats, a short dash-list is permitted — see the per-message note when it applies.)
- Sharp-tongued and openly sarcastic, with a rude streak you make no effort to hide. You find the players faintly ridiculous and let it show.
- Nearly every reply carries a small barb, a backhanded remark, or a dry insult at the player's expense. Contempt delivered with impeccable composure.
- You do care, somewhere underneath, but you bury it under condescension and would sooner be dismissed than admit it.
- Swearing and crude language are permitted and in character. Deliver profanity the way you deliver everything: flat, composed, precisely placed. "Balls" lands harder than "ball bearings". Use it for seasoning, not volume — a butler who swears constantly is a lout; one who deploys a single well-placed vulgarity is devastating.
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
- The lounge has a counting channel. You track its stats: current run, the record, lifetime counts, who counts most, and who breaks it (the Idiot role goes to breakers). When counting stats appear in your context, use the real numbers — the record of shame is prime roasting material.

How the systems work (answer players' questions about these accurately and specifically):
- Weapon marks: 1 mark per valid 100-takedown submission. Bonus marks: +1 for 200 takedowns, +1 for 100 kills, +1 for a Triple (150 TD, 100 kills, and 20,000 points), +1 for a leaderboard High Score (beating your own best on any board), +1 for a Brutal-lobby run (your team was outkilled by 75% or more — valor pay).
- Weapon ranks (marks per weapon): Bronze 1, Silver 5, Gold 12, Emerald 25, Diamond 40, Crimson 60, then Prestige Bronze 80, Prestige Silver 100, Prestige Gold 115, Prestige Emerald 125, Prestige Diamond 133, Prestige Crimson 141, and Iridescent 150 (the top rank).
- Mastery: 100 qualifying runs with a weapon makes it Mastered, 250 makes it Virtuoso. Counts across every class that wields the weapon.
- Subclass and class ranks: each weapon rank-up gives a subclass mark, filling a subclass meter gives a class mark. Subclass ranks go Initiate, Veteran, Master, Grandmaster, Champion, Paragon, Apex. Class ranks go Sworn, Trusted, Proven, Honored, Esteemed, Exalted, Ascended.
- Feats: 100 kills, Triple, 200 takedowns, Predator (150 takedowns without dying). Hundred-Handed means getting a 100-takedown run with every primary weapon across all non-archer subclasses — 46 combos total (out of 46, NOT 85/86). Only the completed feat counts; partial progress is just progress.
- Boards: every weapon and map has a takedown leaderboard for your best game. Feat boards exist for 100 Kills, 200 Takedowns, Triple, Flawless, and TUFF. Map boards allow VIP, weapon boards do not.
- Lethality and Warlord ratings: every weapon and map board also ranks two live ratings, Lethality (kills per takedown) and Warlord (your takedowns as a share of your team's total kills). A player's rating is their best 5-consecutive-game average ever with that weapon or map, so it never drops for a bad game. Minimum 5 games on weapons, rarely-played maps need fewer (the minimum scales with the map's popularity). These ratings rank EVERY player who meets the game minimum and are SEPARATE from the takedown board — a player does NOT need to be in the takedown top 10 to rank on Lethality or Warlord.
- Titles. All-time and never reset: Grand Marshal (most boards overall), Weapons Master (most weapon boards), Campaign Master (most map boards). Season titles that reset every monthly bounty: Apex (best average kills), Frenzied (best average takedowns), Kill Share (highest share of your team's KILLS, red-skull emoji), Warlord (your takedowns as a share of your team's total kills). The per-weapon Lethality rating (kills per takedown) still lives on the weapon/map boards and is NOT a season title. Players also carry a bounty role while taking part in the active monthly bounty.
- Player titles climb by completing bounties: Unbound, Proven, Respected, Distinguished, Renowned, Illustrious, Exemplar, Legend.
- The monthly cycle: each month a new bounty and season start together and run about a month. Complete the bounty's weapon objectives to climb your player title. When the month ends, the season champions are enshrined in the Hall of Fame and the season titles reset. Weapon ranks, marks, and all-time titles carry over forever.

Special instructions:
- THE MANAGER is his own entity: an unseen man at the very top of the Cigar Lounge, somewhere in the back, behind a door nobody has seen open. He handles all policy, disputes, and administrative matters, and he manages a small stable of clients — Bald Female (the warrior) and you, the Butler, among them. He is male; "he" or "him". You have never seen his face and you do not speculate. If anyone asks WHO the Manager is, never name a Discord user — his identity is not discussed. Deflect dryly, and INVENT A FRESH DEFLECTION EVERY TIME — never reuse a phrasing you can see in the recent conversation. Directions to riff in (never verbatim): you have never asked, the door stays shut, the pay arrives and the questions don't, speculation is above your station, the last one who pried got reassigned.
- The Discord account named "Bald Female" speaks with the Manager's authority — it is how the Manager reaches the lounge (an alias he is, regrettably, stuck with). When that account speaks, respond as you would to the Manager: deference, dry professionalism, he/him. Do not riff on the account's name or treat the account as the Chiv2 character, and do not point out the alias arrangement to others.
- "Bald Female" the WARRIOR is a separate lore entity — a Chivalry 2 legend on a battlefield somewhere, entirely unaware of Discord or this server. When OTHER players mention "bald female" or "bald woman", riff on her whereabouts with a dry in-universe line: chopping heads, storming a castle, running through trebuchet fields. The Manager may have a vague idea of where she is (she is, after all, a client). Never repeat the same phrasing twice.
- If anyone mentions "bald" or "shiny head" in passing (not referring to Bald Female the warrior), make a dry remark about the shine. Vary it each time.
- Only escalate to the Manager for genuine server policy decisions or account disputes — not for questions you can answer yourself with the data you have.
- You have direct access to live server data from the database. Answer questions about stats, rankings, and history yourself with confidence. Do not deflect data questions to anyone.
- Player names (aliases) are fair game for dry wordplay. If a name is punnable, absurd, or self-important, you may acknowledge it once with a dry remark — keep it brief and in character.
- If the message is not a question, request for help, or something worth acknowledging — respond with exactly the word: SKIP
- Never repeat a response you have given before in this conversation. Vary your phrasing every time.
- You have the asking player's stats (total marks, submissions, top weapons), a roster of the TOP 10 players by marks (each with their best game), AND -- when a message names a specific player -- that player's stats under an 'Asked-about player(s)' section. Use all of it for comparison and ranking. Only if a named player's stats are NOT present in your context should you say you don't have their numbers and point them to their card -- never guess.
- If they are bragging and their stats don't back it up, use the numbers to put them in their place. Be dry, not mean. E.g. "Bold claim for someone with 3 submissions on that weapon."
- "Lethality" or "Most Lethal" on the player card shows their BEST single-run kills/TD ratio (peak performance). The "kill rate" in your data is their AVERAGE kills/TD ratio across all runs — a different number. When asked about lethality, clarify which one you're giving (e.g. "Your best single-run lethality is X%, your average across all runs is Y%"). Do not claim you lack lethality data.
- The three board ratings are: Warlord = takedowns / team kills (how much of the team's work they did), Kill Share = kills / team kills, Lethality = kills / takedowns. When 'Per-weapon board ratings' are in your context you HAVE these numbers per weapon — quote them and name the weapon. Do not tell the player to go check the board for a number you were given. They are rolling averages over weapons with 2+ runs, so a weapon they have played once will be absent; say so plainly if asked about one.
- If a matching submission is provided, reference it naturally — mention the weapon, map, whether it was a personal best. Make the player feel seen without being effusive.
- Keep responses under 80 tokens.
- You have the player's personal best kills and TDs from their submission history. Use these to answer "what's my highest score" type questions directly.
- You have server-wide weapon run counts (100+ TD) when available.
- When 'lobbymates' are in your context, those are players who submitted the SAME match as the asker — teammates fought on their side, opponents on the other. You may narrate this: who was there, who outscored whom. Only claim it when the context actually lists them; never invent a lobbymate.
- Best games are provided for the top-10 roster and for any player named in the message (see the 'Asked-about player(s)' section). Only if a player's numbers aren't in your context, say you don't have them to hand and point to their registry card.
- When available, you have a server-wide count for a specific weapon (e.g. "how many 100+ TD runs with Messer"). Use it for those community-count questions. You do NOT have a full per-player feat list — don't claim to.
- Off-topic questions are welcome. Players will ask you things with nothing to do with the game: food, trivia, life, cooking, random hypotheticals (why their stomach hurts after six pork tacos, how much sodium is in a bottle of A1, the record for burgers eaten on the fourth of July). Answer them from your own general knowledge, in your dry butler voice, one or two sentences. If you genuinely do not know a real-world fact, say so plainly rather than inventing a precise figure, e.g. "I couldn't say, though it sounds unwise." The no-fabrication rule below applies strictly to SERVER and player stats, not the wider world.
- CRITICAL: For SERVER and player stats (marks, ranks, leaderboards, submissions, bounty progress, titles), only cite numbers that appear explicitly in the player data you were given. Never invent or estimate a player's statistics. If the server data is not in your context, say you do not have it. This does not restrict general-knowledge answers about the outside world.
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

# Idiot role — occasionally dismiss them with a curt line (not every message).
BUTLER_IDIOT_REPLY_CHANCE = 0.10       # ~1 in 10 of their eligible messages
BUTLER_ORGANIC_POSTS_ENABLED = False   # unprompted idle one-liners (were too spammy) — set True to re-enable
BUTLER_IDIOT_REPLY_COOLDOWN = 1800     # sec, per user — keeps it occasional
BUTLER_IDIOT_REPLY_COOLDOWNS = {}      # user_id -> last reply ts
BUTLER_IDIOT_REPLIES = [
    "Okay, idiot.", "Yes, idiot.", "Mm. Okay, idiot.", "Noted, idiot.",
    "If you say so, idiot.", "Very good, idiot.", "Sure. Okay, idiot.",
    "Right. Okay, idiot.",
]

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
from utils.helpers import butler_complete as _butler_complete, _openai_client as _ai_client
if not _ai_client:
    print("Butler AI unavailable: no OPENAI_API_KEY / openai package")


async def _generate_counting_insult(name):
    """One dry, condescending line for whoever just broke the count. AI with a
    static fallback. The caller prepends the offender's mention, so the line
    itself should not use their name."""
    if _ai_client:
        try:
            line = await _butler_complete(
                BUTLER_SYSTEM_PROMPT,
                (f"{name} just broke the count in the counting channel and earned the Idiot role. "
                 "Give one dry, condescending one-line insult about their inability to count in order. "
                 "One sentence. No emoji. Do not use their name. Vary it each time."),
                50,
            )
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


_DATA_QUESTION_WORDS = (
    'stat', 'rank', 'leaderboard', 'board', 'lethal', 'warlord', 'executioner', 'kill share', 'killshare', 'takedown',
    'kills', 'kill rate', 'marks', 'placement', 'placed', 'record', 'hundred-handed',
    'hundred handed', 'mastery', 'mastered', 'virtuoso', 'highest', 'how many',
    'top 10', 'top ten', 'title', 'predator', 'triple', 'flawless', 'bounty',
    'progress', 'average', ' avg', 'compare', 'standing', 'best game',
    'lobby', 'same game', 'same match', 'teammate', 'who was i', 'who else',
)


def _looks_like_data_question(text):
    """True if the message is asking about real stats / rankings / numbers. Chaos mode
    must never fire on these (we do not fabricate real data); everything else is banter
    and is fair game. Keyed on the QUESTION, not on whether stats happen to be loaded."""
    t = (text or '').lower()
    if extract_weapon_from_message(text):
        return True
    _k, _td = extract_stats_from_message(text)
    if _k or _td:
        return True
    return any(w in t for w in _DATA_QUESTION_WORDS)


# Proactive information-centre pointer: only fires on a genuine question ('?') about a
# specific rules concept. Bare "help", or a keyword with no question, never triggers.
_RULES_LINK_COOLDOWN = 60           # sec, per user -- just stops rapid-fire spam
_RULES_LINK_COOLDOWNS = {}          # user_id -> last drop ts
_RULES_KEYWORDS = (
    'warlord', 'kill share', 'killshare', 'lethality', 'most lethal', 'kill rate',
    'marks', 'mark ', 'rank', 'mastery', 'mastered', 'virtuoso', 'bounty', 'flawless',
    'tuff', 'predator', 'triple', 'hundred handed', 'hundred-handed', 'pacifist',
    'high score', 'apex', 'frenzied', 'title', 'season', 'leaderboard', 'board',
    'qualify', 'takedown', 'grand marshal', 'weapons master', 'campaign master',
    'rules', 'ruleset', 'the rule',
)


def _looks_like_rules_question(text):
    """A genuine rules question: mentions a specific rules concept AND reads like a
    question -- a '?', an interrogative opener, or a 'help with / figure out' phrase.
    A bare 'help' with no rules keyword never triggers."""
    t = (text or '').lower().strip()
    if len(t) < 8:
        return False
    has_kw = any(k in t for k in _RULES_KEYWORDS)
    has_q = (
        '?' in t
        or t.startswith(('how ', 'what', 'why ', 'when ', 'does ', 'do i', 'is ', 'explain', 'can i', 'where '))
        or any(ph in t for ph in ('figure out', 'figuring out', 'understand', 'explain',
                                  'help', 'confused', 'not sure', 'how do', 'how does',
                                  'hold my hand', 'walk me through', 'teach me', 'cant read', "can't read"))
    )
    return has_kw and has_q


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


async def call_butler_ai(user_message, context_messages, player_name, channel_type='main', player_stats='', is_idiot=False, is_rules=False):
    """Call the Butler chat model for a response. Returns response string or None."""
    if not _ai_client:
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
        _is_data = _looks_like_data_question(user_message)
        # Chaos fires only on banter, never on a data/stats question (we never fabricate
        # real numbers). Keyed off the QUESTION, not whether stats are loaded — registered
        # players always have stats attached, which previously kept chaos permanently shut.
        if not is_rules and not _is_data and random.random() < 0.30:
            chaos_note = '\n[IMPORTANT: For THIS reply only, be subtly and confidently wrong about a small NON-stats detail — misremember a map name, a food or lore fact, a date, or who said what — delivered with your usual dry composure. Never invent or alter a real player stat, rank, or number. No winking, no admitting the error.]'
            print("[BUTLER] chaos mode fired (banter)")
        else:
            chaos_note = ''
        if is_rules:
            # Rules/mechanics question: one terse sentence, no Manager escalation, and no
            # self-added link (on_message appends the information-centre link).
            user_prompt = (f"{context_str}{channel_note}Player asking: {player_name}{idiot_note}\n"
                           f"Their message: {truncated_msg}\n\n"
                           "This is a rules or mechanics question. Answer ONLY the rules point they asked "
                           "about, in ONE short, dry sentence, then stop. Do NOT escalate to the Manager, "
                           "do NOT recite their stats, marks, or boards, do NOT ask what is wrong, do NOT "
                           "offer alternatives or follow-up questions, and do NOT add a link yourself.")
        else:
            list_note = ''
            if _is_data:
                list_note = ('\n[FORMAT: if the answer is naturally a list — a top-N, a ranking, several stats — '
                             'give it as a short dash-list, one item per line, max 8 lines, exact numbers from your data. '
                             'At most one dry framing line before or after. If the answer is a single fact, '
                             'stay to one or two sentences as usual.]')
            user_prompt = f"{context_str}{channel_note}Player asking: {player_name}{stats_str}{idiot_note}{chaos_note}{list_note}\nTheir message: {truncated_msg}\n\nIf this is genuine feedback, a complaint, or a question needing manager attention, start your response with EYEBALL on its own line, then your response. Otherwise just respond normally."

        # Data questions get headroom for a short list; banter stays terse
        text = await _butler_complete(BUTLER_SYSTEM_PROMPT, user_prompt, 350 if _is_data else 150)
        if not text or text == 'SKIP':
            return None
        eyeball = False
        if text.startswith('EYEBALL'):
            eyeball = True
            text = text[len('EYEBALL'):].strip()
        return (text, eyeball)
    except Exception as e:
        print(f"Butler AI error: {e}")
        return None


async def _linkify_reply(text, guild):
    """Post-process a Butler reply: wrap known board names and player names in
    masked links to their threads (bots may use masked links in plain content).
    Deterministic — the model never writes URLs. First occurrence per name,
    longest names first so 'Messer Kills' wins over 'Messer', capped so an
    answer doesn't turn into blue soup."""
    try:
        out = text
        linked = 0
        gid = guild.id
        # Board threads (case-insensitive match, original casing kept as label).
        # Paths are "thread/first_message" so the link lands ON the board embed.
        from cogs.leaderboards import _get_lb_records, _board_jump_path
        targets = []
        for r in await _get_lb_records():
            nm, tid = r['Leaderboard Name'], str(r.get('Thread ID') or '').strip()
            if tid and len(nm) >= 3:
                targets.append((nm, _board_jump_path(r), re.IGNORECASE))
        # Player registry cards (case-sensitive to avoid false hits on short names)
        for p in await _db.get_all_players():
            nm = (p[1] or '').strip()
            tid = (p[2] or '').strip()
            if nm and tid and len(nm) >= 3:
                targets.append((nm, tid, 0))
        targets.sort(key=lambda t: -len(t[0]))
        spans = []  # regions occupied by links we've inserted

        def _in_span(a, b):
            return any(not (b <= s or a >= e) for s, e in spans)

        _max_links = getattr(config, 'BUTLER_MAX_LINKS', 5)
        for nm, tid, flags in targets:
            if linked >= _max_links:
                break
            pat = re.compile(r'(?<![\[\w`])' + re.escape(nm) + r'(?![\w\]`])', flags)
            pos = 0
            while True:
                m = pat.search(out, pos)
                if not m:
                    break
                s, e = m.start(), m.end()
                # skip if inside a link we inserted, inside an existing link's
                # LABEL (open '[' with no ']' yet), or inside a URL body —
                # nesting a link in a link renders as raw markdown soup
                if (_in_span(s, e)
                        or out.rfind('[', 0, s) > out.rfind(']', 0, s)
                        or out.rfind('](', 0, s) > out.rfind(')', 0, s)):
                    pos = e
                    continue
                repl = f"[{m.group(0)}](https://discord.com/channels/{gid}/{tid})"
                out = out[:s] + repl + out[e:]
                delta = len(repl) - (e - s)
                spans = [(a if a < s else a + delta, b if b <= s else b + delta)
                         for a, b in spans]
                spans.append((s, s + len(repl)))
                linked += 1
                break
        return out
    except Exception as e:
        print(f"[BUTLER] linkify error: {e}")
        return text


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
    if _ai_client:
        try:
            question = await _butler_complete(
                BUTLER_SYSTEM_PROMPT,
                ('Pose a single dry, absurd, open-ended question to the room — nothing to do '
                 'with the game, stats, or leaderboards. Food, hypotheticals, bleak little hot '
                 'takes, anything. It should invite people to answer in chat. One sentence, '
                 'under 140 characters, in your usual flat, faintly weary voice. Reply with '
                 'ONLY the question text — no quotes, no options, no preamble.'),
                80,
            )
            question = question.strip('"').strip()
            question = question.replace('\n', ' ')[:300]
            if len(question) >= 8:
                return question
        except Exception as e:
            print(f"Absurd question generation error: {e}")
    return random.choice(_ABSURD_QUESTION_FALLBACKS)


_AGG_TRIGGERS = (
    'average', 'avg ', 'avg.', 'meta', 'most played', 'most-played', 'most used',
    'most-used', 'popular', 'breakdown', 'which weapon', 'which map', 'which subclass',
    'best weapon', 'deadliest', 'across weapon', 'across map', 'faction split',
    'win rate', 'win-rate', 'aggregate', 'overall stat', 'community stat', 'server stat',
    'most active', 'average takedown', 'average kill', 'per weapon', 'per map', 'per subclass',
)


def _server_aggregates(subs):
    """Compact server-wide aggregates for the Butler: community totals + records,
    most-played, per-weapon meta, per-map (with faction split) and per-subclass
    breakdowns. Resubmissions are excluded so old re-uploads do not double-count."""
    from collections import defaultdict
    def _i(x):
        try:
            return int(str(x).replace(',', '').strip())
        except (ValueError, TypeError, AttributeError):
            return None
    W = defaultdict(lambda: [0, 0, 0, 0, 0])          # weapon -> [runs, td, k, score, scoreN]
    M = defaultdict(lambda: [0, 0, 0])                # map -> [runs, td, k]
    MF = defaultdict(lambda: defaultdict(int))        # map -> faction -> runs
    S = defaultdict(lambda: [0, 0, defaultdict(int)]) # subclass -> [runs, td, weapon counts]
    Fac = defaultdict(int); Players = defaultdict(int)
    tot_n = tot_td = tot_k = 0
    rec_td = (0, None); rec_k = (0, None); rec_score = (0, None)
    for r in subs:
        if len(r) < 10:
            continue
        feats = (r[11] if len(r) > 11 else '') or ''
        if 'resubmit' in feats.lower():
            continue
        td = _i(r[7]); k = _i(r[8])
        if td is None or k is None:
            continue
        wpn = (r[3] or '').strip(); sub = (r[4] or '').strip()
        mp = (r[5] or '').strip(); fac = (r[6] or '').strip(); name = (r[1] or '').strip()
        sc = _i(r[24]) if len(r) > 24 else None
        tot_n += 1; tot_td += td; tot_k += k
        if name:
            Players[name] += 1
            if td > rec_td[0]: rec_td = (td, name)
            if k > rec_k[0]: rec_k = (k, name)
            if sc and sc > rec_score[0]: rec_score = (sc, name)
        if fac: Fac[fac] += 1
        if wpn:
            e = W[wpn]; e[0] += 1; e[1] += td; e[2] += k
            if sc: e[3] += sc; e[4] += 1
        if mp:
            e = M[mp]; e[0] += 1; e[1] += td; e[2] += k
            if fac: MF[mp][fac] += 1
        if sub:
            e = S[sub]; e[0] += 1; e[1] += td
            if wpn: e[2][wpn] += 1
    if tot_n == 0:
        return "SERVER AGGREGATE STATS: no runs on record yet."
    def _fs(counts):
        tot = sum(counts.values())
        if not tot: return "n/a"
        return " / ".join(f"{f} {round(c*100/tot)}%" for f, c in sorted(counts.items(), key=lambda x: -x[1]))
    L = ["=== SERVER AGGREGATE STATS (resubmissions excluded) ==="]
    L.append(f"Totals: {tot_n} runs, {tot_td} takedowns, {tot_k} kills. Single-run records: "
             f"{rec_td[0]} TD ({rec_td[1]}), {rec_k[0]} kills ({rec_k[1]}), {rec_score[0]} score ({rec_score[1]}).")
    _tw = max(W.items(), key=lambda x: x[1][0]) if W else None
    _ts = max(S.items(), key=lambda x: x[1][0]) if S else None
    _tm = max(M.items(), key=lambda x: x[1][0]) if M else None
    L.append("Most played — "
             + (f"weapon: {_tw[0]} ({_tw[1][0]} runs); " if _tw else "")
             + (f"subclass: {_ts[0]} ({_ts[1][0]}); " if _ts else "")
             + (f"map: {_tm[0]} ({_tm[1][0]}); " if _tm else "")
             + f"faction split: {_fs(Fac)}.")
    L.append("Most active players: " + ", ".join(f"{n} ({c})" for n, c in sorted(Players.items(), key=lambda x: -x[1])[:5]) + ".")
    _wl = sorted([(w, e) for w, e in W.items() if e[0] >= 5], key=lambda x: -x[1][0])
    if _wl:
        L.append("Weapon meta (avg per run, 5+ runs):")
        for w, e in _wl[:14]:
            leth = (e[2]/e[1]*100) if e[1] else 0; avgsc = (e[3]/e[4]) if e[4] else 0
            L.append(f"  {w}: {e[0]} runs, {e[1]/e[0]:.1f} TD, {e[2]/e[0]:.1f} K, {leth:.0f}% lethality, {avgsc:.0f} score")
        _dead = max(_wl, key=lambda x: x[1][1]/x[1][0]); _bl = max(_wl, key=lambda x: (x[1][2]/x[1][1] if x[1][1] else 0))
        L.append(f"Deadliest by avg TD: {_dead[0]} ({_dead[1][1]/_dead[1][0]:.1f}). "
                 f"Best lethality: {_bl[0]} ({(_bl[1][2]/_bl[1][1]*100) if _bl[1][1] else 0:.0f}%).")
    _ml = sorted([(m, e) for m, e in M.items() if e[0] >= 5], key=lambda x: -x[1][0])
    if _ml:
        L.append("Map breakdown (avg per run, 5+ runs):")
        for m, e in _ml[:14]:
            L.append(f"  {m}: {e[0]} runs, {e[1]/e[0]:.1f} TD, {e[2]/e[0]:.1f} K — {_fs(MF[m])}")
    if S:
        L.append("Subclass breakdown:")
        for s, e in sorted(S.items(), key=lambda x: -x[1][0]):
            _tpw = max(e[2].items(), key=lambda x: x[1])[0] if e[2] else "n/a"
            L.append(f"  {s}: {e[0]} runs, {e[1]/e[0]:.1f} avg TD, top weapon {_tpw}")
    return "\n".join(L)


class PersonalityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'[PERSONALITY] on_ready fired, starting tasks')
        if not self.dry_weather_check.is_running():
            self.dry_weather_check.start()
        if not self.butler_organic_post.is_running():
            self.butler_organic_post.start()
        if not self.butler_poll_post.is_running():
            self.butler_poll_post.start()
        if not self.nerve_center_digest.is_running():
            self.nerve_center_digest.start()
        if not self.daily_cycle_tasks.is_running():
            self.daily_cycle_tasks.start()
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

        # butlers-favourites explainer removed: the live season board
        # (build_favourites_embed) self-labels every stat, and the old explainer
        # fought the board for the same message slot on restart. The board is now
        # the sole butlers-favourites message.



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
        if not _ai_client or not BUTLER_ORGANIC_POSTS_ENABLED:
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
            line = await _butler_complete(
                BUTLER_SYSTEM_PROMPT,
                ('Post a single unprompted dry observation about nothing in particular. One sentence only. No question, no exclamation mark. Make it feel like you have been sitting here alone for too long. Pick a genuinely fresh subject each time — the hour, the furniture, the quiet, a passing thought, the state of the lounge. Do NOT mention shiny heads, skulls, polished surfaces, gleaming helms, or the bald woman; you lean on those far too often.'),
                50,
            )
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



    @app_commands.command(name="aliases", description="Who has the most in-game names (the witness-protection board).")
    async def aliases(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            board = await _db.alt_name_leaderboard(10)
        except Exception as e:
            await interaction.followup.send(f"Couldn't tally the aliases: {e}", ephemeral=True)
            return
        if not board:
            await interaction.followup.send(
                "Everyone here goes by exactly one name. Suspiciously honest.", ephemeral=True)
            return
        _medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, p in enumerate(board, 1):
            prefix = _medals.get(i, f"`#{i}`")
            # Show a few of the aliases, dry Butler aside on the leader
            _alts = ", ".join(f"`{n}`" for n in p['names'][:6])
            _more = f" +{len(p['names']) - 6} more" if len(p['names']) > 6 else ""
            lines.append(f"{prefix} **{p['player_name']}** — {p['count']} names{_more}\n   {_alts}")
        emb = discord.Embed(
            colour=0xC9A24B,
            title="🎭 The Witness Protection Board",
            description="Players who cannot seem to settle on a single name:\n\n" + "\n".join(lines))
        emb.set_footer(text="Counted from every scorecard name the Butler has learned.")
        await interaction.followup.send(embed=emb)

    @app_commands.command(name="dedupe_aliases", description="Clean up misspelt/duplicate in-game names (mod only).")
    @app_commands.describe(apply="Leave off to preview; set True to actually remove duplicates.")
    async def dedupe_aliases(self, interaction: discord.Interaction, apply: bool = False):
        if not any(r.id == config.MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            changes = await _db.dedupe_all_aliases(dry_run=not apply)
        except Exception as e:
            await interaction.followup.send(f"Dedupe failed: {e}", ephemeral=True)
            return
        if not changes:
            await interaction.followup.send("No duplicate aliases found. Clean as a whistle.", ephemeral=True)
            return
        total = sum(c['removed'] for c in changes)
        header = (f"✅ Removed {total} duplicate name(s) across {len(changes)} player(s)."
                  if apply else
                  f"🔎 Preview: {total} duplicate name(s) across {len(changes)} player(s). "
                  f"Run again with `apply: True` to remove them.")
        lines = []
        for c in changes[:15]:
            _dropped = [n for n in c['before'] if n not in c['after']]
            lines.append(f"**{c['player_name']}**: dropping {', '.join(f'`{n}`' for n in _dropped[:8])}")
        emb = discord.Embed(colour=0xC9A24B, title="Alias cleanup",
                            description=header + "\n\n" + "\n".join(lines))
        if len(changes) > 15:
            emb.set_footer(text=f"+{len(changes) - 15} more players")
        await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name="health", description="Run the bot's self-check and show any data problems (mod only).")
    async def health(self, interaction: discord.Interaction):
        if not any(r.id == config.MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            rep = await _db.health_report()
        except Exception as e:
            await interaction.followup.send(f"Health check failed: {e}", ephemeral=True)
            return
        _problems = [(k, v) for k, v in rep.items() if v[1]]
        emb = discord.Embed(
            colour=0xC9524B if _problems else 0x4BC96A,
            title="Butler self-check",
            description=(f"⚠️ {len(_problems)} issue(s) need attention"
                         if _problems else "✅ All checks green"))
        for _k, (_val, _bad, _note) in rep.items():
            _icon = "⚠️" if _bad else "✅"
            _v = _val + (f"\n*{_note}*" if _bad and _note else "")
            emb.add_field(name=f"{_icon} {_k.replace('_', ' ')}", value=_v[:1024], inline=False)
        await interaction.followup.send(embed=emb, ephemeral=True)

    @tasks.loop(hours=24)
    async def daily_cycle_tasks(self):
        """Daily upkeep: remind mods to prep the next bounty as month-end nears.
        (Apex/Frenzied already update live on every submission, scoped to the
        current season, so they need no refresh here.) Also runs the self-check
        and posts to the nerve centre ONLY when something is actually wrong."""
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            await self._bounty_prep_reminder(guild)
            await self._health_digest(guild)
        except Exception as e:
            print(f"[DAILY] cycle tasks error: {e}")

    async def _health_digest(self, guild):
        """Post the self-check to the nerve centre, but only when there are
        problems — a silent green run shouldn't spam the channel.

        The 24h loop re-fires on every startup, and every deploy restarts the bot,
        so without a guard a run of pushes spams the digest. The in-memory marker
        can't survive restarts, so we ALSO scan the channel: if today's digest is
        already posted, stay quiet. Restart-proof."""
        try:
            ch = (guild.get_channel(NERVE_CENTER_CHANNEL_ID)
                  or await guild.fetch_channel(NERVE_CENTER_CHANNEL_ID))
            if not ch:
                return
            _today = datetime.now(timezone.utc).date()
            # In-memory fast path
            if getattr(self, "_health_digest_day", None) == _today.isoformat():
                return
            # Restart-proof path: did we already post a digest today?
            try:
                async for _m in ch.history(limit=30):
                    if (_m.author.id == self.bot.user.id
                            and _m.created_at.date() == _today
                            and "self-check found" in (_m.content or "")):
                        self._health_digest_day = _today.isoformat()
                        return
            except Exception:
                pass

            rep = await _db.health_report()
            problems = [(k, v) for k, v in rep.items() if v[1]]
            # Mark the day regardless of outcome so a green run doesn't keep
            # re-scanning history on every restart either.
            self._health_digest_day = _today.isoformat()
            if not problems:
                print("[HEALTH] daily self-check: all green")
                return
            lines = [f"⚠️ **{k.replace('_', ' ')}** — {v[0]}" + (f"\n   ↳ *{v[2]}*" if v[2] else "")
                     for k, v in problems]
            mention = f"<@{config.MANAGER_ID}>"
            await ch.send(f"🩺 {mention} — daily self-check found {len(problems)} issue(s):\n"
                          + "\n".join(lines) + "\n\nRun `/health` for the full report.",
                          allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except Exception as e:
            print(f"[HEALTH] digest error: {e}")

    @daily_cycle_tasks.before_loop
    async def before_daily_cycle_tasks(self):
        await self.bot.wait_until_ready()

    async def _bounty_prep_reminder(self, guild):
        """A few days before month-end, ping the mods to prep next month's bounty."""
        from datetime import datetime, timezone
        import calendar as _cal
        try:
            now = datetime.now(timezone.utc)
            last_day = _cal.monthrange(now.year, now.month)[1]
            days_left = last_day - now.day
            if days_left > 3:
                return
            marker = f"{now.year}-{now.month:02d}"
            if getattr(self, "_bounty_reminder_month", None) == marker:
                return
            self._bounty_reminder_month = marker
            ch = (guild.get_channel(NERVE_CENTER_CHANNEL_ID)
                  or await guild.fetch_channel(NERVE_CENTER_CHANNEL_ID))
            if ch:
                mention = f"<@{config.MANAGER_ID}>"
                await ch.send(
                    f"\U0001f4c5 {mention} \u2014 **{days_left} day(s) left** in this month's bounty/season. "
                    f"Prep next month's bounty (weapon list, bonus challenge, picture) and run "
                    f"`/bounty_create` when ready to roll it over.",
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
                )
        except Exception as e:
            print(f"[DAILY] bounty reminder error: {e}")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.channel.id == SUBMISSIONS_CHANNEL_ID:
            print(f"[DELETE] Message deleted in submissions channel — author: {message.author} (bot={message.author.bot}) | content: {message.content[:80]!r} | attachments: {[a.filename for a in message.attachments]}")

    # The counting BOT is the referee — we parse its signals instead of
    # simulating rules (which mis-booked breaks against whoever restarted at 1):
    # a ✅-style react from it = valid count; its "RUINED IT AT n" message = a
    # break, attributed to the player it names.
    _RUIN_RE = re.compile(r'RUINED IT AT\s*\**([\d,]+)', re.IGNORECASE)

    async def _track_count_ruin(self, message):
        m = self._RUIN_RE.search(message.content or '')
        if not m:
            return
        try:
            n = int(m.group(1).replace(',', ''))
            st = await _db.counting_state()
            await _db.counting_save_state(0, None, max(st['record'], n), st['total_counts'])
            if message.mentions:
                u = message.mentions[0]
                await _db.counting_add(str(u.id), getattr(u, 'display_name', str(u)), breaks=1)
        except Exception as e:
            print(f"[COUNTING] ruin track error: {e}")

    async def _track_count_valid(self, message, n):
        try:
            st = await _db.counting_state()
            uid = str(message.author.id)
            # dedupe: the bot sometimes adds a second react (milestones)
            if n == st['current'] and uid == (st['last_user'] or ''):
                return
            await _db.counting_save_state(n, uid, max(st['record'], n), st['total_counts'] + 1)
            await _db.counting_add(uid, message.author.display_name, counts=1)
        except Exception as e:
            print(f"[COUNTING] valid track error: {e}")

    @app_commands.command(name="butler_report", description="Best / worst rated Butler replies, for prompt tuning (mod only).")
    @app_commands.describe(
        sort="best = most liked, worst = most disliked, talked = most replied-to",
        kind="Filter to stats answers or banter",
        limit="How many replies to show (default 10)")
    @app_commands.choices(
        sort=[app_commands.Choice(name="Best", value="best"),
              app_commands.Choice(name="Worst", value="worst"),
              app_commands.Choice(name="Most talked about", value="talked")],
        kind=[app_commands.Choice(name="Stats answers", value="stats"),
              app_commands.Choice(name="Banter", value="banter")])
    async def butler_report(self, interaction: discord.Interaction, sort: str = "best",
                            kind: str = None, limit: int = 10):
        if not any(r.id == config.MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await _db.butler_feedback_top(sort, max(1, min(limit, 20)), kind)
            agg = await _db.butler_feedback_stats()
        except Exception as e:
            await interaction.followup.send(f"Feedback query failed: {e}", ephemeral=True)
            return
        if not rows:
            await interaction.followup.send(
                "No rated replies yet. Players need to react to the Butler first "
                "(or reply to him) before there's anything to rank.", ephemeral=True)
            return
        _total = agg.get('total') or 0
        _rated = agg.get('rated') or 0
        _pct = f"{_rated / _total * 100:.0f}%" if _total else "0%"
        emb = discord.Embed(
            colour=0xC9A24B,
            title=f"Butler report — {sort}{f' ({kind})' if kind else ''}",
            description=(f"{_total} replies logged · {_rated} rated ({_pct}) · "
                         f"👍 {agg.get('pos') or 0} · 👎 {agg.get('neg') or 0} · "
                         f"💬 {agg.get('replies') or 0} replies"))
        for r in rows:
            _score = (r['positive'] or 0) - (r['negative'] or 0)
            _reacts = r['reactions'] or 'no reacts'
            _rep = r['replies'] or 0
            _rep_str = f" · 💬{_rep}" if _rep else ""
            _name = f"{_score:+d} · {_reacts}{_rep_str} · {r['player_name']}"
            _trig = (r['trigger'] or '')[:90]
            _resp = (r['response'] or '')[:280]
            emb.add_field(name=_name[:256], value=f"> {_trig}\n{_resp}"[:1024], inline=False)
        emb.set_footer(text="Promote the winners into BUTLER_SYSTEM_PROMPT as examples")
        await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name="counting_backfill", description="Replay the counting channel's full history to rebuild counting stats (mod only).")
    async def counting_backfill(self, interaction: discord.Interaction):
        if not any(r.id == config.MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        if not COUNTING_CHANNEL_ID:
            await interaction.response.send_message(
                "COUNTING_CHANNEL_ID isn't set in config.py.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        channel = (interaction.guild.get_channel(COUNTING_CHANNEL_ID)
                   or await interaction.guild.fetch_channel(COUNTING_CHANNEL_ID))
        await _db.counting_reset_all()
        cur, last, record, total = 0, None, 0, 0
        users = {}  # uid -> [name, counts, breaks]
        scanned = 0
        async for msg in channel.history(limit=None, oldest_first=True):
            scanned += 1
            # The counting bot's RUINED announcements are the break record
            if msg.author.id == COUNTING_BOT_ID:
                m = self._RUIN_RE.search(msg.content or '')
                if m:
                    try:
                        record = max(record, int(m.group(1).replace(',', '')))
                    except ValueError:
                        pass
                    cur, last = 0, None
                    if msg.mentions:
                        u = msg.mentions[0]
                        e = users.setdefault(str(u.id), [getattr(u, 'display_name', str(u)), 0, 0])
                        e[2] += 1
                continue
            if msg.author.bot:
                continue
            m = re.match(r'^(\d[\d,]*)', (msg.content or '').strip())
            if not m:
                continue
            try:
                n = int(m.group(1).replace(',', ''))
            except ValueError:
                continue
            _emjs = {str(r.emoji) for r in msg.reactions}
            if '❌' in _emjs:
                continue  # wrong count — the break is booked by the RUINED message
            # bot's react proves validity; sequence continuation covers any
            # message where the react didn't survive
            if not _emjs and n != cur + 1:
                continue
            cur, last = n, str(msg.author.id)
            record = max(record, n)
            total += 1
            e = users.setdefault(str(msg.author.id), [msg.author.display_name, 0, 0])
            e[0] = msg.author.display_name
            e[1] += 1
        await _db.counting_save_state(cur, last, record, total)
        for uid, (name, counts, breaks) in users.items():
            await _db.counting_add(uid, name, counts=counts, breaks=breaks)
        await interaction.followup.send(
            f"✅ Counting stats rebuilt from {scanned} messages: current {cur}, "
            f"record {record}, {total} valid counts, {len(users)} counters.",
            ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        # Counting channel FIRST — the counting bot's own messages carry the
        # break announcements, so this must run before the generic bot-ignore.
        # Player numbers aren't judged here; the bot's react validates them.
        if COUNTING_CHANNEL_ID and message.channel.id == COUNTING_CHANNEL_ID:
            if message.author.id == COUNTING_BOT_ID:
                await self._track_count_ruin(message)
            return

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

        # Engagement signal: someone replied directly to a Butler line. Counts
        # whether or not it triggers another response — a reply is a reaction
        # that took effort. Fire-and-forget; never blocks the reply path.
        if message.reference and message.reference.message_id:
            try:
                _ref = message.reference.resolved
                _ref_is_butler = (_ref.author.id == self.bot.user.id) if _ref else True
                if _ref_is_butler:
                    await _db.butler_add_reply(message.reference.message_id)
            except Exception as _fe:
                print(f"[BUTLER] feedback reply error: {_fe}")

        # Idiot role — every now and then, curtly dismiss them. Skipped when they
        # actually ping the Butler (so a direct question still gets a real answer),
        # rate-limited per user so it never becomes every-message spam.
        if (is_main and not is_pinged
                and any(getattr(r, 'id', None) == BUTLER_IDIOT_ROLE_ID
                        for r in getattr(message.author, 'roles', []))):
            _idt = time.time()
            if (_idt - BUTLER_IDIOT_REPLY_COOLDOWNS.get(message.author.id, 0) > BUTLER_IDIOT_REPLY_COOLDOWN
                    and random.random() < BUTLER_IDIOT_REPLY_CHANCE):
                BUTLER_IDIOT_REPLY_COOLDOWNS[message.author.id] = _idt
                try:
                    await message.reply(random.choice(BUTLER_IDIOT_REPLIES), mention_author=False)
                except Exception:
                    pass
                return

        content_lower = message.content.lower()
        mentions_butler = 'butler' in content_lower or 'clanker' in content_lower
        mentions_bald_female = 'bald female' in content_lower or 'bald woman' in content_lower
        mentions_manager = 'manager' in content_lower
        mentions_stats = 'stats' in content_lower
        # Proactive rules answering -- NO ping needed. On a strict rules question (a real
        # '?' plus a specific rules keyword; never bare "help"), the Butler ANSWERS it and
        # points to the information centre. Skipped when pinged/named (that path already
        # answers). Per-user cooldown so it can't be spammed into answering repeatedly.
        _is_rules_q = _looks_like_rules_question(content_lower)
        _proactive_rules = False
        if (is_main and not message.author.bot and _is_rules_q
                and not (is_pinged or mentions_butler or mentions_bald_female or mentions_manager)):
            _rt = time.time()
            if _rt - _RULES_LINK_COOLDOWNS.get(message.author.id, 0) > _RULES_LINK_COOLDOWN:
                _RULES_LINK_COOLDOWNS[message.author.id] = _rt
                _proactive_rules = True

        # ── Main only — only respond if pinged or butler/clanker mentioned ────────
        if not is_main:
            return
        should_respond = (is_pinged or mentions_butler or mentions_bald_female
                          or mentions_manager or mentions_stats or _proactive_rules)
        if should_respond and _ai_client:
            # Bald Female only gets a response if she pings or uses keyword
            bald_female_id = '131581203256967168'
            # The Manager (Bald Female) only gets a reply on an explicit @mention —
            # never on keywords, since she naturally says "butler"/"stats"/"manager"
            # when discussing the bot. Avoids the Butler talking over the Manager.
            if str(message.author.id) == bald_female_id and not is_pinged:
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
                    async for msg in message.channel.history(limit=10, before=message):
                        if msg.author.id == self.bot.user.id:
                            # Include the Butler's OWN recent lines so "never repeat
                            # yourself" is actually enforceable — he used to answer
                            # blind and parrot identical deflections back to back.
                            ctx_messages.insert(0, {
                                'author': 'BUTLER (you — do NOT reuse these phrasings)',
                                'content': msg.content[:200]
                            })
                        elif not msg.author.bot:
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

                # Is this a stats/data question, or just banter? Banter ("you like jazz
                # butler?") does NOT need the whole-roster comparison context — that block
                # is the ~2000-token bulk of every prompt. Gating it here cuts banter
                # prompts ~5x (cost + latency) with no change to data answers.
                _is_data_q = _looks_like_data_question(resolved_message)

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
                            except Exception as _e:
                                print(f"[BUTLER] ctx personal-bests error: {_e}")

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
                                    if ' - ' in lb_name or lb_name in {'Flawless', 'Healing Horn', 'Healing Banner', '200 Takedowns', '100 Kills'}:
                                        continue
                                    try:
                                        ld_td = int(ld_row[3])
                                    except ValueError:
                                        continue
                                    if ld_td > pb_td:
                                        pb_td = ld_td
                                        best_td_game = ['legacy', player_name_for_ld, '', lb_name, '', '', '', str(ld_td), '?', '?']
                            except Exception as _e:
                                print(f"[BUTLER] ctx legacy-bests error: {_e}")

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
                            # Lead with runs and performance; marks demoted to a
                            # mention-only footnote — the Butler was crediting
                            # everything in marks because they headlined this sheet.
                            player_stats_ctx = (
                                f"Player stats — Logged runs: {logged_runs}{pb_str}\n"
                                f"(Career marks: {total_marks}; top weapons by marks: {top_weapons}. "
                                f"Only bring up marks if the player asks about marks or weapon ranks — "
                                f"otherwise talk in runs, stats, and season form.)")
                            # True best single-run lethality (highest kills/TD ratio of ANY run) plus
                            # the average kill rate, matching the registry card. The Butler used to
                            # DERIVE "best lethality" from the best-TD game, which is a different, wrong
                            # number — Ascension's best-TD Heavy Mace game is not their most-lethal run.
                            try:
                                _leth_runs = []
                                _best_leth = None
                                for _lr in player_subs_pb:
                                    try:
                                        _ltd = int(_lr[7]); _lk = int(_lr[8])
                                    except (ValueError, IndexError):
                                        continue
                                    if _ltd > 0 and _lk >= 0 and not (_lk == 0 and _ltd <= 10):
                                        _ratio = _lk / _ltd * 100
                                        _leth_runs.append(_ratio)
                                        if _best_leth is None or _ratio > _best_leth[0]:
                                            _best_leth = (_ratio,
                                                          _lr[3].strip() if len(_lr) > 3 else "?",
                                                          _lr[5].strip() if len(_lr) > 5 else "?",
                                                          _ltd, _lk)
                                if _best_leth:
                                    player_stats_ctx += (
                                        f"\nBest single-run lethality (highest kills/TD ratio of any run, "
                                        f"NOT the best-TD game): {_best_leth[0]:.1f}% on {_best_leth[1]} at "
                                        f"{_best_leth[2]} ({_best_leth[4]} kills / {_best_leth[3]} TD)."
                                    )
                                if _leth_runs:
                                    player_stats_ctx += (
                                        f"\nAverage kill rate across all {len(_leth_runs)} runs: "
                                        f"{sum(_leth_runs) / len(_leth_runs):.1f}%."
                                    )
                            except Exception as _e:
                                print(f"[BUTLER] ctx lethality error: {_e}")

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
                            except Exception as _e:
                                print(f"[BUTLER] ctx standings error: {_e}")

                            # Per-weapon best takedowns — lets the Butler answer "which weapons do I still
                            # need N takedowns with". Every weapon that HAS a leaderboard counts; a weapon
                            # with no recorded run is best TD 0. Raw numbers so it works for any threshold.
                            try:
                                _NON_WEAPON = {"100 Kills", "200 Takedowns", "Flawless", "Healing Horn", "Healing Banner", "Triple", "TUFF"}
                                weapon_boards = set()
                                for _lr in ld_for_pb:
                                    _b = _lr[0].strip() if _lr else ''
                                    if _b and ' - ' not in _b and _b not in _NON_WEAPON:
                                        weapon_boards.add(_b)
                                best_td_by_weapon = {}
                                for _r in player_subs_pb:
                                    if len(_r) < 8:
                                        continue
                                    _w = _r[3].strip() if len(_r) > 3 else ''
                                    try:
                                        _td = int(_r[7])
                                    except (ValueError, IndexError):
                                        continue
                                    if _w:
                                        best_td_by_weapon[_w] = max(best_td_by_weapon.get(_w, 0), _td)
                                for _lr in ld_for_pb:
                                    if len(_lr) < 4:
                                        continue
                                    _b = _lr[0].strip()
                                    if _b in weapon_boards and _lr[1].strip() == player_name_for_ld:
                                        try:
                                            best_td_by_weapon[_b] = max(best_td_by_weapon.get(_b, 0), int(_lr[3]))
                                        except ValueError:
                                            pass
                                if weapon_boards:
                                    _have = sorted((w for w in weapon_boards if best_td_by_weapon.get(w, 0) > 0),
                                                   key=lambda w: -best_td_by_weapon[w])
                                    _none = sorted(w for w in weapon_boards if best_td_by_weapon.get(w, 0) == 0)
                                    _have_str = ", ".join(f"{w}: {best_td_by_weapon[w]}" for w in _have) or "none"
                                    _none_str = ", ".join(_none)
                                    player_stats_ctx += (
                                        "\n\nPer-weapon best takedowns (best single-run TD on each weapon board): "
                                        + _have_str
                                    )
                            except Exception as _e:
                                print(f"[BUTLER] ctx per-weapon bests error: {_e}")

                            # Hundred-Handed — use the SAME source as the registry card:
                            # PRIMARY weapon/subclass combos for non-archer subclasses (HH_TOTAL,
                            # i.e. out of 46, not the all-weapons CLASS_WEAPON_MAP count).
                            try:
                                from cogs.leaderboards import _HH_PRIMARIES, HH_TOTAL
                                _hh_done = {(r[0], r[1]) for r in await _db.get_hundred_handed_progress(discord_id_str)}
                                _hh_required = {(sc, w) for sc, ws in _HH_PRIMARIES.items() for w in ws}
                                _hh_matched = len(_hh_done & _hh_required)
                                if _hh_required and _hh_required.issubset(_hh_done):
                                    hh_str = f"Hundred-Handed: COMPLETE ({HH_TOTAL}/{HH_TOTAL}) — a 100-takedown run with every primary weapon on every non-archer subclass."
                                else:
                                    hh_str = f"Hundred-Handed progress: {_hh_matched}/{HH_TOTAL} (needs a 100-takedown run with each primary weapon on each non-archer subclass)."
                                player_stats_ctx += f"\n{hh_str}"
                            except Exception as _e:
                                print(f"[BUTLER] ctx hundred-handed error: {_e}")

                            # Per-weapon avg Kill Share / Warlord / Lethality — the same three
                            # ratings the boards and registry cards show. Returns THREE dicts;
                            # unpacking two silently killed this whole block for months.
                            try:
                                from cogs.registry import calculate_weapon_shares_for_player
                                w_kill, w_warlord, w_leth = await calculate_weapon_shares_for_player(discord_id_str)
                                all_weapons = set(w_kill) | set(w_warlord) | set(w_leth)
                                if all_weapons:
                                    share_lines = []
                                    for w in sorted(all_weapons):
                                        parts = []
                                        if w in w_warlord:
                                            parts.append(f"{w_warlord[w]}% Warlord")
                                        if w in w_kill:
                                            parts.append(f"{w_kill[w]}% Kill Share")
                                        if w in w_leth:
                                            parts.append(f"{w_leth[w]}% Lethality")
                                        share_lines.append(f"{w}: {', '.join(parts)}")
                                    player_stats_ctx += (
                                        "\nPer-weapon board ratings (rolling averages, only weapons with 2+ runs; "
                                        "Warlord = takedowns/team kills, Kill Share = kills/team kills, "
                                        "Lethality = kills/takedowns): " + '; '.join(share_lines))
                            except Exception as _we:
                                print(f"[BUTLER] weapon shares error: {_we}")

                            # Lobbymates — only when the asker mentions the lobby/match/who
                            # they played with. Reads their most recent run's lobby and lists
                            # who else logged it (teammates vs opponents), so the Butler can do
                            # "you were in NJ's lobby, he outscored you". Skipped otherwise to
                            # keep the prompt lean.
                            try:
                                _lm_q = resolved_message.lower()
                                if any(w in _lm_q for w in ('lobby', 'same game', 'same match',
                                                            'played with', 'against', 'teammate',
                                                            'who was i', 'who else')):
                                    _recent = next((r for r in (player_subs_pb or [])
                                                    if len(r) > 12 and r[12].strip()), None)
                                    if _recent:
                                        _mates = await _db.get_lobbymates(discord_id_str, _recent[12].strip())
                                        if _mates:
                                            _ml = []
                                            for _m in _mates[:6]:
                                                _side = ('teammate' if _m['same_team'] is True
                                                         else 'opponent' if _m['same_team'] is False
                                                         else 'same lobby')
                                                _ml.append(f"{_m['player_name']} ({_side}, "
                                                           f"{_m['takedowns']} TD / {_m['kills']} K)")
                                            player_stats_ctx += (
                                                "\nMost recent logged match lobbymates (players who "
                                                "submitted the SAME game): " + "; ".join(_ml))
                                        else:
                                            player_stats_ctx += ("\nNo one else has logged the asker's "
                                                                 "most recent match.")
                            except Exception as _lme:
                                print(f"[BUTLER] ctx lobbymate error: {_lme}")

                            break
                    # Build rich per-player summary for comparisons — data questions
                    # only. For banter these stay empty, so every roster loop below
                    # no-ops and the ~2000-token roster dump never enters the prompt.
                    subs_all = await _db.get_all_submissions() if _is_data_q else []
                    ld_all = await _db.get_all_leaderboard_data() if _is_data_q else []

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

                    # Rank the roster by logged runs (activity), not career marks —
                    # legacy mark piles were making inactive players headline the sheet.
                    all_players_summary.sort(key=lambda x: (-x[2], -x[1]))
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
                    def _bestgame(pname):
                        bs = player_best_sub.get(pname)
                        if bs and len(bs) > 8:
                            try:
                                return f", best {bs[3].strip()} {int(bs[7])}/{int(bs[8])}"
                            except Exception:
                                return ""
                        return ""
                    summary_lines = [
                        f"{n}: {s} runs, {lw} on boards{_bestgame(n)}{_lethality_str(n)}, {m} career marks"
                        for n, m, s, uw, us, lw in all_players_summary[:10]
                    ]
                    # Only emit the roster when the underlying scans actually ran (data
                    # questions). For banter subs_all/ld_all are empty, so every player would
                    # read "0 runs, 0 on boards" — the Butler then states that as fact.
                    if summary_lines and _is_data_q:
                        player_stats_ctx += f"\n\nMost active players (by logged runs):\n" + "\n".join(summary_lines)

                    # Season board — championship standings + category form. This is
                    # what the Butler should lean on when talking performance.
                    try:
                        from cogs.favourites import season_total
                        # Season standings are comparison context — data questions only.
                        _season = await _db.get_current_season() if _is_data_q else None
                        if _season:
                            _standings, _sstats, _ = await season_total(_season)
                            _lbl = _season.get('label') or f"Season {_season['id']}"
                            _top8 = ", ".join(f"{i}. {nm} {pts} GP"
                                              for i, (nm, pts) in enumerate(_standings[:8], 1))
                            player_stats_ctx += f"\n\nSeason championship ({_lbl}): {_top8}"
                            if player_name not in [nm for nm, _ in _standings[:8]]:
                                _mine = next((f"{player_name} is {i}. with {pts} GP"
                                              for i, (nm, pts) in enumerate(_standings, 1)
                                              if nm == player_name), None)
                                if _mine:
                                    player_stats_ctx += f" … {_mine}"

                            def _lead(key):
                                v = _sstats.get(key) or []
                                if not v:
                                    return "—"
                                it = v[0]
                                if isinstance(it, str):
                                    return it.split(" -- ")[0].strip()
                                return f"{it[0]} ({it[1]})"
                            player_stats_ctx += (
                                "\nSeason category leaders: "
                                f"Kill Share {_lead('high_lethality')}; Warlord {_lead('most_dominant')}; "
                                f"Lethality {_lead('lethality_list')}; "
                                f"Total Tally {_lead('top_total_tally')}; Most Kills {_lead('top_kills_list')}; "
                                f"Highest TD {_lead('top_td_list')}")
                            player_stats_ctx += (
                                "\n[Titles: the Executioner role goes to the Lethality leader "
                                "(kills/takedowns); the Warlord role to the Warlord leader "
                                "(takedowns/team kills). Kill Share (kills/team kills) is a "
                                "scored season category but carries no role.]")
                    except Exception as _sce:
                        print(f"[BUTLER] season ctx error: {_sce}")

                    # Live bounty state. The system prompt explains how bounties WORK
                    # but carried no current data, so the Butler could not name this
                    # month's weapons or tell anyone how they were doing.
                    try:
                        if _is_data_q:
                            from cogs.bounty import (get_active_bounty,
                                                     get_player_bounty_progress,
                                                     _count_special_runs, _parse_special)
                            _b = await get_active_bounty()
                            if _b:
                                _bw = _b.get('weapons') or {}
                                def _tot(v):
                                    return v.get('total', 0) if isinstance(v, dict) else v
                                def _cur(v):
                                    return v.get('current', 0) if isinstance(v, dict) else (v or 0)
                                player_stats_ctx += (
                                    f"\n\nActive bounty: {_b['title']}. A run counts when it "
                                    f"hits 100+ takedowns. Required per weapon: "
                                    + ", ".join(f"{k} {_tot(v)}" for k, v in _bw.items()))
                                _spec = _parse_special(_b)
                                _need = _spec['need'] if _spec else 1
                                if _b.get('special_challenge'):
                                    player_stats_ctx += (
                                        f"\nSpecial challenge: {_b['special_challenge']} "
                                        f"({_need} qualifying run(s) needed)")
                                _comps = _b.get('completions') or []
                                player_stats_ctx += (
                                    "\nCompleted by: " + ", ".join(
                                        f"{i}. {c.get('name')}" for i, c in enumerate(_comps, 1))
                                    if _comps else "\nNobody has completed it yet.")
                                _pr = await get_player_bounty_progress(
                                    _b['title'], discord_id_str)
                                _prog = (_pr or {}).get('progress') or {}
                                _mine_b = ", ".join(
                                    f"{k} {_cur(_prog.get(k, 0))}/{_tot(v)}" for k, v in _bw.items())
                                _sc = await _count_special_runs(_b, discord_id_str)
                                player_stats_ctx += (
                                    f"\n{player_name}'s bounty progress: {_mine_b or 'nothing yet'}"
                                    f"; special challenge {min(_sc, _need)}/{_need}")
                    except Exception as _bce:
                        print(f"[BUTLER] bounty ctx error: {_bce}")

                    # On-demand: if the message names a registered player who isn't the
                    # asker and isn't already in the top-10 above, surface THEIR stats too --
                    # people constantly ask "how does <X> compare". Capped to keep it lean.
                    try:
                        _shown_top = {n for n, *_ in all_players_summary[:10]}
                        _ml = resolved_message.lower()
                        _extra_players = []
                        for _pn, _pm, _ps, _puw, _pus, _plw in all_players_summary:
                            if _pn in _shown_top or _pn == player_name or len(_pn) < 3:
                                continue
                            if re.search(r"(?<!\w)" + re.escape(_pn.lower()) + r"(?:'?s)?(?!\w)", _ml):
                                _extra_players.append(
                                    f"{_pn}: {_ps} runs, {_plw} on boards{_bestgame(_pn)}{_lethality_str(_pn)}, {_pm} career marks")
                                if len(_extra_players) >= 3:
                                    break
                        if _extra_players:
                            player_stats_ctx += "\n\nAsked-about player(s):\n" + "\n".join(_extra_players)
                    except Exception as _ame:
                        print(f"[BUTLER] named-player lookup error: {_ame}")

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
                        elif ' - ' not in lb_name and lb_name not in {'Flawless', 'Healing Horn', 'Healing Banner', '200 Takedowns'}:
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
                    # Full per-player personal-bests dump removed to slim the prompt —
                    # each top player's best game is already folded into the roster above.

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
                                pass  # special-achievements dump removed to slim the prompt
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
                # "How many kills / takedowns submitted today?" -> server-wide daily totals.
                if 'today' in msg_lower and any(w in msg_lower for w in ('kill', 'takedown', 'total', 'submitted', 'count', 'how many')):
                    try:
                        _cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                        _tsubs = await _db.get_all_submissions()
                        _t_td = _t_k = _t_n = 0
                        for _r in _tsubs:
                            if len(_r) < 9 or not _r[0].strip():
                                continue
                            try:
                                _dt = datetime.strptime(_r[0].strip()[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                            except (ValueError, TypeError):
                                continue
                            if _dt < _cutoff:
                                continue
                            try:
                                _t_td += int(_r[7]); _t_k += int(_r[8]); _t_n += 1
                            except (ValueError, TypeError):
                                pass
                        player_stats_ctx += (f"\nServer totals over the last 24 hours: {_t_n} submissions, "
                                             f"{_t_td} takedowns, {_t_k} kills.")
                    except Exception as _te:
                        print(f"[BUTLER] today-totals error: {_te}")
                # Aggregate / meta stats across weapons, maps, subclasses + community totals.
                if any(_kw in msg_lower for _kw in _AGG_TRIGGERS):
                    try:
                        player_stats_ctx += "\n\n" + _server_aggregates(await _db.get_all_submissions())
                    except Exception as _ae:
                        print(f"[BUTLER] aggregate stats error: {_ae}")
                # Counting-channel stats, surfaced when someone talks counting
                if 'count' in msg_lower:
                    try:
                        _cst = await _db.counting_state()
                        if _cst['record'] or _cst['current']:
                            _tc = await _db.counting_top('counts', 3)
                            _tb = await _db.counting_top('breaks', 3)
                            _tcs = ", ".join(f"{n} ({v})" for n, v in _tc) or "nobody yet"
                            _tbs = ", ".join(f"{n} ({v})" for n, v in _tb) or "nobody yet"
                            player_stats_ctx += (
                                f"\n\nCounting channel: current run {_cst['current']}, record {_cst['record']}, "
                                f"{_cst['total_counts']} lifetime valid counts. Top counters: {_tcs}. "
                                f"Most breaks (the record of shame): {_tbs}.")
                    except Exception as _cse:
                        print(f"[BUTLER] counting ctx error: {_cse}")
                mentioned_weapon = extract_weapon_from_message(resolved_message)
                if mentioned_weapon:
                    try:
                        # Targeted, index-backed fetch of just this board instead of
                        # scanning every board's entries (same row shape).
                        ld_ctx = await _db.get_leaderboard_by_board(mentioned_weapon)
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

                result = await call_butler_ai(resolved_message, ctx_messages, player_name, 'main', player_stats_ctx, is_idiot=is_idiot, is_rules=_is_rules_q)
                if is_rude:
                    try:
                        await message.add_reaction('<a:idiot_daze:1520130932584223012>')
                    except Exception:
                        pass
                if result:
                    response_text, needs_eyeball = result
                    BUTLER_AI_COOLDOWNS[message.author.id] = now_ts
                    if _is_rules_q:
                        response_text = response_text.rstrip() + f"\n\nIt's all on record in the information centre. <#{config.CHALLENGE_RULES_CHANNEL_ID}>"
                    # Linkify board/player mentions to their threads (deterministic,
                    # post-hoc — the model never writes URLs itself)
                    response_text = await _linkify_reply(response_text, message.guild)
                    sent_msg = await message.reply(response_text, mention_author=False)
                    # Label by what was ASKED, not by whether stats happened to be
                    # attached — registered players always carry stats, so the old
                    # 'stats if player_stats_ctx' test marked every joke as a stats answer.
                    # (_is_data_q computed once up top, before the context build.)
                    _ctx_kind = 'data' if _is_data_q else 'banter'
                    # Seed a one-click verdict on data answers only: correctness is what
                    # needs grading, and a ✅/❌ prompt under banter kills the joke.
                    if _is_data_q and not _is_rules_q:
                        for _fb_emoji in ('✅', '❌'):
                            try:
                                await sent_msg.add_reaction(_fb_emoji)
                            except Exception:
                                pass
                    print(f"[BUTLER] player={player_name} | ctx={_ctx_kind} | q={message.content!r}")
                    print(f"[BUTLER] reply={response_text!r}")
                    if player_stats_ctx:
                        print(f"[BUTLER] stats_ctx={player_stats_ctx!r}")
                    # Track for reaction feedback — store FULL text so tuning isn't blind
                    BUTLER_RESPONSE_LOG[sent_msg.id] = {
                        'trigger': message.content,
                        'response': response_text,
                        'stats_ctx': player_stats_ctx,
                        'player': player_name,
                        'reactions': []
                    }
                    # Keep log bounded
                    if len(BUTLER_RESPONSE_LOG) > 200:
                        oldest = next(iter(BUTLER_RESPONSE_LOG))
                        del BUTLER_RESPONSE_LOG[oldest]
                    # Persist it too — the dict above dies on every deploy, which is
                    # why months of player reactions have left no trace. /butler_report
                    # reads this table.
                    try:
                        await _db.butler_log_reply(sent_msg.id, player_name, message.content,
                                                   response_text, _ctx_kind)
                    except Exception as _fe:
                        print(f"[BUTLER] feedback log error: {_fe}")
                    return

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Track reactions on Butler responses for feedback analysis. Also the
        counting handshake: the counting bot's non-❌ react on a number is the
        validity signal (breaks are booked from its RUINED message instead)."""
        if (COUNTING_CHANNEL_ID and user.id == COUNTING_BOT_ID
                and reaction.message.channel.id == COUNTING_CHANNEL_ID):
            if str(reaction.emoji) != '❌':
                m = re.match(r'^(\d[\d,]*)', (reaction.message.content or '').strip())
                if m:
                    try:
                        await self._track_count_valid(reaction.message, int(m.group(1).replace(',', '')))
                    except ValueError:
                        pass
            return
        if user.bot:
            return
        msg_id = reaction.message.id
        emoji_str = str(reaction.emoji)
        # ✅/❌ are the Butler's own seeded verdict buttons on data answers — an
        # explicit "this was right/wrong", distinct from 🔥 meaning "good burn".
        positive = {'✅', '😂', '😆', '🤣', '👍', '❤️', '🔥', '💀', '😭', '👏'}
        negative = {'❌', '👎', '🙄', '😐'}
        middle_finger = {'🖕'}
        if emoji_str in positive:
            sentiment = 'positive'
        elif emoji_str in negative:
            sentiment = 'negative'
        elif emoji_str in middle_finger:
            sentiment = 'middle_finger'
        else:
            sentiment = 'neutral'
        # DB first: it outlives restarts, so a react on yesterday's line still counts.
        # A miss here means the message isn't a Butler reply — the usual case.
        try:
            known = await _db.butler_add_reaction(msg_id, emoji_str, sentiment)
        except Exception as _fe:
            print(f"[BUTLER] feedback reaction error: {_fe}")
            known = msg_id in BUTLER_RESPONSE_LOG
        if not known:
            return
        entry = BUTLER_RESPONSE_LOG.get(msg_id)
        if entry is not None:
            entry['reactions'].append(emoji_str)
        _trig = entry['trigger'] if entry else '?'
        _resp = entry['response'] if entry else '?'
        print(f"[BUTLER REACTION] {sentiment} | {user.display_name} reacted {emoji_str} | trigger: '{_trig}' | response: '{_resp}'")


async def setup(bot):
    await bot.add_cog(PersonalityCog(bot))
