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

The Chivalry 2 scoreboard shows player rows with these columns in order:
SCORE | NAME | [icon] | TAKEDOWNS | KILLS | DEATHS | ASSISTS

TAKEDOWNS is the first number column after the player name. It is typically the largest number (often 100-300 for top players).
KILLS is the second number column. It is always less than or equal to takedowns.
DEATHS is the third number column.
ASSISTS is the fourth number column — do NOT confuse this with deaths.

The score (leftmost column) is a large point value (often 1,000-20,000) — do NOT use this as takedowns.

The submitting player's row is visually highlighted (brighter, different colour, or has a marker).

Extract ONLY from the highlighted row:
- weapon (exact weapon name shown — may appear as an icon tooltip or text)
- subclass (class name e.g. Ambusher, Officer, Devastator, Poleman, Man-at-Arms)
- map (map name shown on screen, e.g. Rudhelm, Galencourt, Coxwell)
- faction (Agatha, Mason, or Tenosia — based on which team the highlighted row is on)
- takedowns (integer — first numeric column after name, typically 50-400)
- kills (integer — second numeric column, always <= takedowns)
- deaths (integer — third numeric column, typically 0-50)

Also return:
- other_scores: list of takedown integers (first numeric column) for all other visible rows, in order

Return ONLY valid JSON, null for any field you are not confident about:
{
  "weapon": null,
  "subclass": null,
  "map": null,
  "faction": null,
  "takedowns": null,
  "kills": null,
  "deaths": null,
  "other_scores": []
}

Do not guess. Return null rather than a wrong value."""


def vision_parse_scorecard(image_url: str) -> dict:
    """
    Pass a Discord image URL to Claude vision and extract scorecard fields.
    Returns a dict with keys: weapon, subclass, map, faction, takedowns, kills, deaths, other_scores.
    Any field that couldn't be read confidently is None.
    """
    empty = {
        'weapon': None, 'subclass': None, 'map': None, 'faction': None,
        'takedowns': None, 'kills': None, 'deaths': None, 'other_scores': []
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
            b64_data = base64.standard_b64encode(image_bytes).decode('utf-8')
            print(f"[VISION] Fetched {len(image_bytes)} bytes, type={content_type}")
            image_source = {'type': 'base64', 'media_type': content_type, 'data': b64_data}
        except Exception as fetch_err:
            print(f"[VISION] Image fetch failed ({fetch_err}), falling back to URL source")
            image_source = {'type': 'url', 'url': image_url}

        r = _anthropic_client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=300,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': image_source},
                    {'type': 'text',  'text': _SCORECARD_PROMPT},
                ]
            }]
        )
        print(f"[VISION] stop_reason={r.stop_reason} content_blocks={len(r.content)}")
        if not r.content:
            print("[VISION] Empty content list from API")
            return empty
        raw = r.content[0].text.strip()
        print(f"[VISION] Raw response ({len(raw)} chars): {raw[:200]}")
        if not raw:
            print("[VISION] Empty text block from API")
            return empty
        # Strip markdown code fences if model wraps output
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        data = _json.loads(raw)
        # Coerce numeric fields to int, ignore bad values
        for field in ('takedowns', 'kills', 'deaths'):
            try:
                if data.get(field) is not None:
                    data[field] = int(data[field])
            except (ValueError, TypeError):
                data[field] = None
        if not isinstance(data.get('other_scores'), list):
            data['other_scores'] = []
        return {**empty, **data}
    except Exception as e:
        print(f"[VISION] Error: {e}")
        return empty


def parse_submission_text(text):
    # Sort aliases longest-first so "war bow" matches before "bow" — otherwise
    # shorter aliases steal the match from longer ones that overlap.
    text_lower = text.lower().strip()
    detected_weapon   = None
    detected_subclass = None

    for alias in sorted(config.WEAPON_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            detected_weapon = config.WEAPON_ALIASES[alias]
            break

    detected_parent = None
    for alias in sorted(config.SUBCLASS_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            raw = config.SUBCLASS_ALIASES[alias]
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
