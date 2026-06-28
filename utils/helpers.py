import os
import random
from datetime import datetime

import config

# Shared Anthropic client — initialised once, used by any cog that needs a quick Butler line
_anthropic_client = None
try:
    import anthropic as _anthropic
    _anthropic_client = _anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
except Exception:
    pass

_BUTLER_SYSTEM_BRIEF = (
    "You are the Butler — dry, sardonic, one or two sentences max. "
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
- RANK: leftmost column, a rank number (e.g. 1,000 or 74) — do NOT use this as score or takedowns
- NAME: player name
- SCORE: large point value (often 1,000–20,000) — do NOT use this as takedowns
- T: Takedowns — the number of kills+assists, typically the largest combat stat (50–400 for top players)
- K: Kills — always less than or equal to T
- D: Deaths — typically 0–50
- PING: last column, network latency in ms — ignore this

CRITICAL: The submitting player's row is visually highlighted — it has a noticeably brighter background (often gold/yellow), different colour tint, or a star/crown/icon marker next to their name. This highlighted row is NOT necessarily the top row. It can appear anywhere on the scoreboard. Do NOT default to the top-ranked player.

Step 1: Scan every row on both teams and identify which one looks visually distinct. Note that player's NAME.
Step 2: Read the T, K, D values ONLY from that exact row — do not read from any row above or below it.
Step 3: That same player must NOT appear in team_scores or team_kills — those arrays are for all OTHER teammates only.

Extract ONLY from that highlighted row:
- weapon (exact weapon name if shown — may appear as an icon tooltip or text; null if not visible)
- subclass (class name e.g. Ambusher, Officer, Devastator, Poleman, Man-at-Arms, Longbowman; null if not visible)
- map (full map name shown on screen e.g. "The Battle of Darkforest", "Galencourt")
- faction (Agatha, Mason, or Tenosia — whichever team side the highlighted row is on)
- takedowns (integer from T column of highlighted row)
- kills (integer from K column of highlighted row)
- deaths (integer from D column of highlighted row)

The scoreboard shows TWO teams side by side. For ALL other rows (excluding the highlighted player), split by team:
- team_scores: T column integers for players on the SAME team as the highlighted player
- team_kills: K column integers for players on the SAME team as the highlighted player
- enemy_scores: T column integers for players on the ENEMY team
- enemy_kills: K column integers for players on the ENEMY team

COLUMN READING EXAMPLES — study these carefully before reading the image:

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

Your response must be ONLY the JSON object below — no explanation, no preamble, no markdown fences. Start your response with `{` and end with `}`. Use null for any field you cannot confidently read.

{"weapon":null,"subclass":null,"map":null,"faction":null,"takedowns":null,"kills":null,"deaths":null,"team_scores":[],"team_kills":[],"enemy_scores":[],"enemy_kills":[]}"""


def vision_parse_scorecard(image_url: str) -> dict:
    """
    Pass a Discord image URL to Claude vision and extract scorecard fields.
    Returns a dict with keys: weapon, subclass, map, faction, takedowns, kills, deaths, other_scores.
    Any field that couldn't be read confidently is None.
    """
    empty = {
        'weapon': None, 'subclass': None, 'map': None, 'faction': None,
        'takedowns': None, 'kills': None, 'deaths': None,
        'team_scores': [], 'team_kills': [], 'enemy_scores': [], 'enemy_kills': [],
    }
    print(f"[VISION] Attempting parse for URL: {image_url[:80]}...")
    if not _anthropic_client:
        print("[VISION] No Anthropic client — skipping")
        return empty
    try:
        import json as _json
        import base64
        import urllib.request

        # Fetch image bytes first — Discord CDN URLs with expiry tokens (?ex=...)
        # may expire by the time Sonnet tries to fetch them remotely.
        try:
            req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                image_bytes = resp.read()
                content_type = resp.headers.get('Content-Type', 'image/png').split(';')[0].strip()
            print(f"[VISION] Fetched {len(image_bytes)} bytes, type={content_type}")
            # Resize large images to max 1600px wide — higher res improves row-level accuracy.
            try:
                import io
                from PIL import Image as _PILImage
                img = _PILImage.open(io.BytesIO(image_bytes))
                max_w = 1600
                if img.width > max_w:
                    ratio = max_w / img.width
                    new_h = int(img.height * ratio)
                    img = img.resize((max_w, new_h), _PILImage.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format='PNG', optimize=True)
                    image_bytes = buf.getvalue()
                    content_type = 'image/png'
                    print(f"[VISION] Resized to {img.width}x{img.height}, {len(image_bytes)} bytes")
            except Exception as resize_err:
                print(f"[VISION] Resize skipped: {resize_err}")
            b64_data = base64.standard_b64encode(image_bytes).decode('utf-8')
            image_source = {'type': 'base64', 'media_type': content_type, 'data': b64_data}
        except Exception as fetch_err:
            print(f"[VISION] Image fetch failed ({fetch_err}), falling back to URL source")
            image_source = {'type': 'url', 'url': image_url}

        r = _anthropic_client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=1800,
            system="You are a JSON-only data extractor. Output ONLY a single valid JSON object. No prose, no explanation, no markdown. Your entire response must start with { and end with }.",
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {'type': 'image', 'source': image_source},
                        {'type': 'text',  'text': _SCORECARD_PROMPT},
                    ]
                },
                {
                    'role': 'assistant',
                    'content': '{'
                }
            ]
        )
        print(f"[VISION] stop_reason={r.stop_reason} content_blocks={len(r.content)}")
        if not r.content:
            print("[VISION] Empty content list from API")
            return empty
        raw = '{' + r.content[0].text.strip()
        print(f"[VISION] Raw response ({len(raw)} chars): {raw[:200]}")
        if not raw:
            print("[VISION] Empty text block from API")
            return empty
        # Strip markdown code fences if model wraps output
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
        print(f"[VISION] Error: {e}")
        return empty


def parse_submission_text(text):
    # Sort aliases longest-first so "war bow" matches before "bow" — otherwise
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

    # 2. Fuzzy fallback — check each word against all weapon aliases
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
    # it down to the specific subclass automatically — saves them having to type it.
    if detected_parent and detected_weapon:
        subs = config.PARENT_TO_SUBCLASSES[detected_parent]
        candidates = [s for s in subs if detected_weapon in config.CLASS_WEAPON_MAP.get(s, [])]
        if len(candidates) == 1:
            detected_subclass = candidates[0]

    return detected_weapon, detected_subclass


def format_weapon_marks(marks):
    # Formatting tiers map to rank thresholds — bold at Gold (12), italic+bold at
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


# Only these thresholds get milestone announcements — not every rank crossing,
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
        # Prestige multiplier — fire each time they cross another prestige threshold past 150
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
        return f"**{player_name}** — **{weapon}** ×{n}. {mark_count} marks. The bald woman would be proud."
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
# Nothing persists across restarts — intentional, digest is ephemeral.
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
    # Fire-and-forget critical error to nerve center — don't let this crash anything else
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
            await ch.send(f"⚠️ **Critical Error** — {context}\n```{str(error)[:300]}```")
    except Exception:
        pass


def nerve_flush():
    # Drain the buffer and return a formatted digest string.
    # Called by the hourly task loop in personality.py.
    subs         = _nerve_events['submissions']
    interactions = _nerve_events['butler_interactions']
    errors       = _nerve_events['errors']
    milestones   = _nerve_events['milestones']

    if not subs and not interactions and not errors and not milestones:
        quiet_lines = [
            "All quiet. The Butler approves.",
            "Nothing to report. The lounge is running smoothly.",
            "Silence. The Butler finds it acceptable.",
            "No errors. No chaos. The Butler is mildly surprised.",
            "Everything in order. The Manager need not be disturbed.",
        ]
        return f"🧠 **Hourly Digest**\n*{random.choice(quiet_lines)}*"

    lines = ["🧠 **Hourly Digest**"]
    if subs:
        lines.append(f"\n**Submissions ({len(subs)})**")
        for ts, p, w in subs[-10:]:
            lines.append(f"• `{ts}` {p} — {w}")
    if milestones:
        lines.append(f"\n**Milestones**")
        for p, w, r in milestones:
            lines.append(f"• {p} — {w} — {r}")
    if interactions:
        lines.append(f"\n**Butler ({len(interactions)} interactions)**")
        for t, r in interactions[-5:]:
            lines.append(f'• {t[:40]} -> {r[:40]}')
    if errors:
        lines.append(f"\n**⚠️ Errors ({len(errors)})**")
        for ts, e in errors[-5:]:
            lines.append(f"• `{ts}` {e}")

    for k in _nerve_events:
        _nerve_events[k].clear()

    return "\n".join(lines)


def build_manual_content():
    lines = [
        "📖 **BUTLER'S MANUAL**",
        "*A reference for registered players.*",
        "",
        "**Commands**",
    ]
    for cmd, desc in config.PLAYER_COMMANDS:
        lines.append(f"`{cmd}` — {desc}")
    lines.append("")
    lines.append("*Submit a run by posting a screenshot in the submissions channel.*")
    return "\n".join(lines)
