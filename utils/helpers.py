import os
import random
from datetime import datetime

import config

# Shared Anthropic client - initialised once, used by any cog that needs a quick Butler line
_anthropic_client = None
try:
    import anthropic as _anthropic
    _anthropic_client = _anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
except Exception:
    pass

# Gemini client for vision (scorecard parsing)
_gemini_client = None
try:
    from google import genai as _genai
    _gemini_client = _genai.Client(api_key=os.environ['GOOGLE_AI_API_KEY'])
except Exception:
    pass


_BUTLER_SYSTEM_BRIEF = (
    "You are the Butler - dry, sardonic, one or two sentences max. "
    "Never say 'great', 'awesome', or use exclamation marks. Never break character."
)

def butler_quip(prompt: str, fallback: str = '') -> str:
    """Call Haiku for a short Butler line. Returns fallback if unavailable."""
    if not _anthropic_client:
        return fallback
    try:
        r = _anthropic_client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=60,
            system=_BUTLER_SYSTEM_BRIEF,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return r.content[0].text.strip()
    except Exception:
        return fallback


_SCORECARD_PROMPT = """You are reading a Chivalry 2 end-of-round scoreboard screenshot.

The scoreboard columns are: RANK | NAME | SCORE | T | K | D | PING
- RANK: leftmost column, a rank number (e.g. 1,000 or 74) - do NOT use this as score or takedowns
- NAME: player name
- SCORE: large point value (often 1,000–20,000) - do NOT use this as takedowns
- T: Takedowns - the number of kills+assists, typically the largest combat stat (50–400 for top players)
- K: Kills - always less than or equal to T
- D: Deaths - typically 0–50
- PING: last column, network latency in ms - ignore this

CRITICAL: The submitting player's row is visually highlighted - it has a noticeably brighter background (often gold/yellow), different colour tint, or a star/crown/icon marker next to their name. The highlighted row can be ANYWHERE - top, middle, or bottom of the scoreboard.

LARGE LOBBIES: The scoreboard may have up to 32 players per team (64 total). In large lobbies the text is small - read carefully. Do not skip rows.

STEAM DECK / CONTROLLER UI: Some screenshots show "PRESS A TO INTERACT", "PRESS B", "PRESS X", or similar controller button prompts at the bottom of the screen. These are UI overlays - ignore them completely, they are not part of the scoreboard.

SCREEN OVERLAYS TO IGNORE - these are NOT scoreboard rows:
- Discord/streaming voice overlays on the left or right edges (small cards showing player names with icons like arrows, diamonds, or letters like "E")
- A "SPECTATORS" panel that may appear on the right side listing players who are spectating
- Any name that appears outside the main two-column scoreboard table
Only read names and stats from inside the RANK | NAME | SCORE | T | K | D | PING table columns.

FINDING THE PLAYER (use BOTH methods, prefer name match if highlight is ambiguous):
Method 1 - Visual highlight: scan every row for the one with a distinctly brighter/gold background or a marker icon.
Method 2 - Name match: if a player name hint is provided, find the row whose NAME column most closely matches it (exact or partial match, case-insensitive, ignoring clan tags or decorators).
If both methods point to the same row, high confidence. If only one method works, use that. If the highlight is subtle or unclear on this screenshot, rely primarily on the name match.

Step 1: Using both methods above, identify the submitting player's row.
Step 2: Read the T, K, D values ONLY from that exact row - do not read from any row above or below it.
Step 3: That same player must NOT appear in team_scores or team_kills - those arrays are for all OTHER teammates only.

Extract ONLY from that highlighted row:
- weapon (exact weapon name if shown - may appear as an icon tooltip or text; null if not visible)
- subclass (class name e.g. Ambusher, Officer, Devastator, Poleman, Man-at-Arms, Longbowman; null if not visible)
- map (full map name shown at the TOP of the screen above the scoreboard, e.g. "The Siege of Rudhelm", "The Battle of Darkforest" — NOT from the leaderboard rows)
NOTE: The two large numbers displayed prominently on the LEFT and RIGHT sides of the screen are the total team takedown scores — one per team. These are NOT individual player stats.
- faction (Agatha, Mason, or Tenosia - whichever team side the highlighted row is on)
- takedowns (integer from T column of highlighted row)
- kills (integer from K column of highlighted row)
- deaths (integer from D column of highlighted row)

The scoreboard shows TWO teams side by side. For ALL other rows (excluding the highlighted player), split by team:
- team_scores: T column integers for players on the SAME team as the highlighted player
- team_kills: K column integers for players on the SAME team as the highlighted player
- enemy_scores: T column integers for players on the ENEMY team
- enemy_kills: K column integers for players on the ENEMY team

COLUMN READING EXAMPLES - study these carefully before reading the image:

Example 1 (highlighted row is rank 2, not rank 1):
  Row data visible: RANK=1,000  NAME=mlowy  SCORE=11,653  T=124  K=54  D=6  PING=8
  Correct output: takedowns=124, kills=54, deaths=6
  WRONG output would be: takedowns=11653 (that is SCORE, not T), or takedowns=1000 (that is RANK)

Example 2 (highlighted row is mid-table):
  Row data visible: RANK=266  NAME=SauceCode  SCORE=9,029  T=79  K=29  D=21  PING=12
  Correct output: takedowns=79, kills=29, deaths=21
  WRONG output would be: takedowns=266 (RANK) or takedowns=9029 (SCORE)

Example 3 (highlighted row is near bottom):
  Row data visible: RANK=88  NAME=ColdestQmurray  SCORE=2,947  T=31  K=9  D=14  PING=60
  Correct output: takedowns=31, kills=9, deaths=14

The T column (takedowns) is always a small integer, typically 10–400. The SCORE column is always a large number (thousands). Never confuse them.

Your response must be ONLY the JSON object below - no explanation, no preamble, no markdown fences. Start your response with `{` and end with `}`. Use null for any field you cannot confidently read.

{"weapon":null,"subclass":null,"map":null,"faction":null,"name":null,"takedowns":null,"kills":null,"deaths":null,"team_scores":[],"team_kills":[],"enemy_scores":[],"enemy_kills":[]}"""


def vision_parse_scorecard(image_url: str, player_name: str = None) -> dict:
    """
    Pass a Discord image URL to Gemini vision and extract scorecard fields.
    player_name: Discord display name of the submitting player - used as a hint to find their row.
    Returns a dict with keys: weapon, subclass, map, faction, takedowns, kills, deaths, other_scores.
    Any field that couldn't be read confidently is None.
    """
    empty = {
        'weapon': None, 'subclass': None, 'map': None, 'faction': None, 'name': None,
        'takedowns': None, 'kills': None, 'deaths': None,
        'team_scores': [], 'team_kills': [], 'enemy_scores': [], 'enemy_kills': [],
    }
    print(f"[VISION] Attempting parse for URL: {image_url[:80]}...")
    if not _gemini_client:
        print("[VISION] No Gemini client - skipping")
        return empty
    try:
        import json as _json
        import urllib.request
        import io

        # Fetch image bytes - Discord CDN URLs with expiry tokens must be fetched immediately
        try:
            req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                image_bytes = resp.read()
                content_type = resp.headers.get('Content-Type', 'image/png').split(';')[0].strip()
            print(f"[VISION] Fetched {len(image_bytes)} bytes, type={content_type}")
        except Exception as fetch_err:
            print(f"[VISION] Image fetch failed: {fetch_err}")
            return empty

        # Pre-process image: upscale small images and sharpen for better OCR accuracy
        try:
            from PIL import Image as _PImage, ImageEnhance as _PIEnhance, ImageFilter as _PIFilter
            import io as _io
            img = _PImage.open(_io.BytesIO(image_bytes)).convert('RGB')
            w, h = img.size
            # Upscale if smaller than 1920px wide — large lobbies have tiny text
            if w < 1920:
                scale = max(2.0, 1920 / w)
                img = img.resize((int(w * scale), int(h * scale)), _PImage.LANCZOS)
            # Sharpen and boost contrast slightly
            img = img.filter(_PIFilter.SHARPEN)
            img = _PIEnhance.Contrast(img).enhance(1.3)
            img = _PIEnhance.Sharpness(img).enhance(2.0)
            buf = _io.BytesIO()
            img.save(buf, format='PNG')
            image_bytes = buf.getvalue()
            content_type = 'image/png'
            print(f"[VISION] Pre-processed to {img.size[0]}x{img.size[1]} PNG")
        except Exception as pp_err:
            print(f"[VISION] Pre-process skipped: {pp_err}")

        from google.genai import types as _gtypes
        image_part = _gtypes.Part.from_bytes(data=image_bytes, mime_type=content_type)
        name_hint = (
            f"\n\nPLAYER NAME HINT: The submitting player may appear under any of these names: {player_name}. "
            f"Their in-game name may differ from their Discord name. "
            f"NEVER read stats from Discord voice overlay cards on the edges — those are NOT scoreboard rows. "
            f"PRIMARY method: find the row with the visually highlighted background (gold/bright/tinted) inside the RANK|NAME|SCORE|T|K|D|PING table. "
            f"SECONDARY method: if a row inside the scoreboard closely matches any of the listed names, use that. "
            f"If no name matches, rely entirely on the visual highlight. "
            f"Also extract the exact NAME text from the highlighted row and return it in the 'name' field."
        ) if player_name else ""
        prompt = _SCORECARD_PROMPT + name_hint

        import time as _time
        raw = None
        for _attempt in range(3):
            try:
                r = _gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[prompt, image_part],
                    config=_gtypes.GenerateContentConfig(
                        temperature=0,
                        response_mime_type='application/json',
                        thinking_config=_gtypes.ThinkingConfig(thinking_budget=2048),
                    )
                )
                raw = r.text.strip()
                break
            except Exception as _e:
                _es = str(_e)
                if '503' in _es or 'UNAVAILABLE' in _es:
                    print(f"[VISION] 503 on attempt {_attempt+1}, retrying in {5 * (_attempt+1)}s...")
                    _time.sleep(5 * (_attempt + 1))
                else:
                    raise
        if raw is None:
            print("[VISION] All retries failed (503)")
            return empty
        raw = raw.strip()
        print(f"[VISION] Raw response ({len(raw)} chars): {raw[:200]}")
        if not raw:
            print("[VISION] Empty response from Gemini")
            return empty
        # Strip markdown fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:].strip()
        data = _json.loads(raw)
        # Coerce numeric fields to int, ignore bad values
        for field in ('takedowns', 'kills', 'deaths'):
            try:
                if data.get(field) is not None:
                    data[field] = int(data[field])
            except (ValueError, TypeError):
                data[field] = None
        for list_field in ('team_scores', 'team_kills', 'enemy_scores', 'enemy_kills'):
            if not isinstance(data.get(list_field), list):
                data[list_field] = []
        return {**empty, **data}
    except Exception as e:
        err = str(e)
        if '429' in err or 'RESOURCE_EXHAUSTED' in err:
            print(f"[VISION] Gemini quota exhausted - user will need to enter stats manually")
        else:
            print(f"[VISION] Error: {e}")
        return empty


def build_manual_embed():
    """Build the butler's-manual embed listing all player-facing slash commands."""
    import discord as _discord

    embed = _discord.Embed(
        title="🎩  Butler's Manual",
        description="*Slash commands available to all players.*",
        colour=_discord.Colour.from_str("#2b2d31"),
    )

    embed.add_field(
        name="📊 Stats & Rankings",
        value=(
            "`/stats` — Your title standings and weapon rank progress. Use `/stats [name]` for any player.\n"
            "`/rank` — Top 10 for any weapon board. e.g. `/rank Messer`\n"
            "`/butlers_report` — Summon the Butler's Favourites weekly report."
        ),
        inline=False,
    )
    embed.add_field(
        name="🏹 Bounty",
        value=(
            "`/bounty_status` — Show the current active bounty card.\n"
            "`/bounty_hunt` — Top 5 hunters for the active bounty.\n"
            "`/my_bounty` — Your personal progress on the active bounty."
        ),
        inline=False,
    )
    embed.add_field(
        name="📋 Registry",
        value=(
            "`/refresh_card` — Refresh your registry card in Butler's Archive."
        ),
        inline=False,
    )
    embed.add_field(
        name="⚖️ Rules",
        value="`/rules` — Show the Cigar Lounge challenge rules.",
        inline=False,
    )
    embed.set_footer(text="Use commands in #🤙 | hotline")
    return embed


def build_manual_content():
    """Legacy plain-text fallback — use build_manual_embed() instead."""
    return "See pinned embed above."


def parse_submission_text(text):
    # Sort aliases longest-first so "war bow" matches before "bow" - otherwise
    # shorter aliases steal the match from longer ones that overlap.
    from difflib import get_close_matches
    text_lower = text.lower().strip()
    words = text_lower.split()
    detected_weapon   = None
    detected_subclass = None

    # 1. Exact alias substring match (original behaviour)
    for alias in sorted(config.WEAPON_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            detected_weapon = config.WEAPON_ALIASES[alias]
            break

    # 2. Fuzzy fallback - check each word against all weapon aliases
    if not detected_weapon:
        all_weapon_aliases = list(config.WEAPON_ALIASES.keys())
        for word in words:
            if len(word) < 3:
                continue
            matches = get_close_matches(word, all_weapon_aliases, n=1, cutoff=0.82)
            if matches:
                detected_weapon = config.WEAPON_ALIASES[matches[0]]
                break
        # Also try two-word combinations for aliases like "war bow"
        if not detected_weapon:
            for i in range(len(words) - 1):
                phrase = words[i] + ' ' + words[i+1]
                matches = get_close_matches(phrase, all_weapon_aliases, n=1, cutoff=0.82)
                if matches:
                    detected_weapon = config.WEAPON_ALIASES[matches[0]]
                    break

    detected_parent = None
    # 3. Exact alias substring match for subclass
    for alias in sorted(config.SUBCLASS_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            raw = config.SUBCLASS_ALIASES[alias]
            if raw in config.PARENT_TO_SUBCLASSES:
                detected_parent = raw
            else:
                detected_subclass = raw
            break

    # 4. Fuzzy fallback for subclass
    if not detected_subclass and not detected_parent:
        all_sub_aliases = list(config.SUBCLASS_ALIASES.keys())
        for word in words:
            if len(word) < 3:
                continue
            matches = get_close_matches(word, all_sub_aliases, n=1, cutoff=0.82)
            if matches:
                raw = config.SUBCLASS_ALIASES[matches[0]]
                if raw in config.PARENT_TO_SUBCLASSES:
                    detected_parent = raw
                else:
                    detected_subclass = raw
                break

    # If they said a parent class (e.g. "vanguard") and a weapon, try to narrow
    # it down to the specific subclass automatically - saves them having to type it.
    if detected_parent and detected_weapon:
        subs = config.PARENT_TO_SUBCLASSES[detected_parent]
        candidates = [s for s in subs if detected_weapon in config.CLASS_WEAPON_MAP.get(s, [])]
        if len(candidates) == 1:
            detected_subclass = candidates[0]

    return detected_weapon, detected_subclass


def format_weapon_marks(marks):
    # Formatting tiers map to rank thresholds - bold at Gold (12), italic+bold at
    # Crimson (60), plus prestige multiplier suffix past Iridescent (150).
    if marks >= 150:
        prestige = sum(1 for t in config.PRESTIGE_THRESHOLDS if marks >= t)
        prestige_str = f" ×**{prestige}**" if prestige > 0 else ""
        return f"***{marks}***{prestige_str}"
    elif marks >= 60:
        return f"***{marks}***"
    elif marks >= 12:
        return f"**{marks}**"
    else:
        return str(marks)


# Only these thresholds get milestone announcements - not every rank crossing,
# just the ones that actually mean something: first mark, Crimson, Prestige, Iridescent.
_MILESTONE_THRESHOLDS = {1, 60, 80, 150}

def detect_weapon_milestones(old_flat, new_flat):
    # old_flat / new_flat: dict of weapon_name -> int marks
    milestones = []
    for weapon in set(old_flat) | set(new_flat):
        old = old_flat.get(weapon, 0)
        new = new_flat.get(weapon, 0)
        if new <= old:
            continue
        for threshold, rank_name in config.WEAPON_RANK_THRESHOLDS:
            if threshold in _MILESTONE_THRESHOLDS and old < threshold <= new:
                milestones.append((weapon, threshold, rank_name))
        # Prestige multiplier - fire each time they cross another prestige threshold past 150
        if old >= 150:
            old_x = sum(1 for t in config.PRESTIGE_THRESHOLDS if old >= t)
            new_x = sum(1 for t in config.PRESTIGE_THRESHOLDS if new >= t)
            if new_x > old_x:
                milestones.append((weapon, new, f"Iridescent ×{new_x}"))
    return milestones


def build_milestone_message(player_name, weapon, threshold, rank_name):
    if rank_name.startswith("Iridescent ×"):
        n = int(rank_name.split("×")[1].strip())
        mark_count = (config.PRESTIGE_THRESHOLDS[n - 1]
                      if n <= len(config.PRESTIGE_THRESHOLDS)
                      else config.PRESTIGE_THRESHOLDS[-1])
        return f"**{player_name}** - **{weapon}** ×{n}. {mark_count} marks. The bald woman would be proud."
    messages = {
        1:   f"*Noted.* **{player_name}** has drawn first blood with the **{weapon}**.",
        60:  f"**{player_name}** has reached Crimson rank on the **{weapon}**. 60 marks. I approve. Quietly.",
        80:  f"**{player_name}** has entered Prestige with the **{weapon}**. 80 marks. I'll say nothing. That is the compliment.",
        150: f"**{player_name}** has gone Iridescent on the **{weapon}**. 150 marks. I'm pouring a drink.",
    }
    return messages.get(threshold)


# Shared mutable state between submissions and personality cogs.
# Using a dict so both modules mutate the same object after import.
submission_state = {'last_submission_time': None, 'dry_spell_posted': False}

# In-memory log for the hourly digest posted to nerve center.
# Nothing persists across restarts - intentional, digest is ephemeral.
_nerve_events = {
    'submissions':         [],  # (timestamp, player, weapon)
    'butler_interactions': [],  # (trigger[:60], response[:60])
    'errors':              [],  # (timestamp, error_str)
    'milestones':          [],  # (player, weapon, rank)
}


def nerve_log_submission(player, weapon):
    _nerve_events['submissions'].append((datetime.utcnow().strftime('%H:%M'), player, weapon))


def nerve_log_butler(trigger, response):
    _nerve_events['butler_interactions'].append((trigger[:60], response[:60]))


def nerve_log_error(context, error):
    _nerve_events['errors'].append((datetime.utcnow().strftime('%H:%M'), f"{context}: {str(error)[:80]}"))


def nerve_log_milestone(player, weapon, rank):
    _nerve_events['milestones'].append((player, weapon, rank))


async def nerve_alert(bot_instance, context, error):
    # Fire-and-forget critical error to nerve center - don't let this crash anything else
    try:
        guild = bot_instance.get_guild(config.GUILD_ID)
        if not guild:
            return
        ch = (guild.get_channel(config.NERVE_CENTER_CHANNEL_ID)
              or await guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID))
        if ch:
            import discord as _discord
            if isinstance(ch, _discord.Thread) and ch.archived:
                await ch.edit(archived=False)
            await ch.send(f"⚠️ **Critical Error** - {context}\n```{str(error)[:300]}```")
    except Exception:
        pass


def nerve_flush():
    # Drain the buffer and return a formatted digest string.
    # Called by the hourly task loop in personality.py.
    subs       = _nerve_events['submissions']
    errors     = _nerve_events['errors']
    milestones = _nerve_events['milestones']

    parts = []

    if errors:
        parts.append(f"⚠️ **Errors — {len(errors)}**")
        for ts, err in errors:
            parts.append(f"  `{ts}` {err}")

    if subs:
        parts.append(f"📋 **Submissions — {len(subs)}**")
        for ts, player, weapon in subs:
            parts.append(f"  `{ts}` **{player}** — {weapon}")
    else:
        parts.append("📋 **Submissions — 0**")

    if milestones:
        parts.append(f"🏆 **Milestones — {len(milestones)}**")
        for player, weapon, rank in milestones:
            parts.append(f"  **{player}** — {weapon} → {rank}")

    _nerve_events['submissions'].clear()
    _nerve_events['butler_interactions'].clear()
    _nerve_events['errors'].clear()
    _nerve_events['milestones'].clear()

    return "\n".join(parts) if parts else ""


async def nerve_alert(bot_instance, context, error):
    try:
        guild = bot_instance.get_guild(config.GUILD_ID)
        if not guild:
            return
        ch = (guild.get_channel(config.NERVE_CENTER_CHANNEL_ID)
              or await guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID))
        if ch:
            import discord as _discord
            if isinstance(ch, _discord.Thread) and ch.archived:
                await ch.edit(archived=False)
            await ch.send(f"\u26a0\ufe0f **Critical Error** - {context}\n```{str(error)[:300]}```")
    except Exception:
        pass
