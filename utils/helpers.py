"""
utils/helpers.py — Pure helper functions shared across cogs:
    • Submission text parser
    • Weapon mark formatter
    • Milestone detection
    • Nerve-center logging
"""
import random
from datetime import datetime

import config


# ── Submission text parser ────────────────────────────────────────────────────
def parse_submission_text(text):
    """Parse message caption for weapon and subclass hints.
    Returns (weapon, subclass) — either may be None if not detected."""
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

    if detected_parent and detected_weapon:
        subs = config.PARENT_TO_SUBCLASSES[detected_parent]
        candidates = [s for s in subs if detected_weapon in config.CLASS_WEAPON_MAP.get(s, [])]
        if len(candidates) == 1:
            detected_subclass = candidates[0]

    return detected_weapon, detected_subclass


# ── Weapon mark formatter ─────────────────────────────────────────────────────
def format_weapon_marks(marks):
    """Format mark count with emphasis based on rank tier, ×N prestige past Iridescent."""
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


# ── Milestone detection ───────────────────────────────────────────────────────
_MILESTONE_THRESHOLDS = {1, 60, 80, 150}

def detect_weapon_milestones(old_flat, new_flat):
    """Return list of (weapon, threshold, rank_name) for significant rank crossings.
    old_flat / new_flat: dict of weapon_name -> int marks (plain weapon keys).
    """
    milestones = []
    for weapon in set(old_flat) | set(new_flat):
        old = old_flat.get(weapon, 0)
        new = new_flat.get(weapon, 0)
        if new <= old:
            continue
        for threshold, rank_name in config.WEAPON_RANK_THRESHOLDS:
            if threshold in _MILESTONE_THRESHOLDS and old < threshold <= new:
                milestones.append((weapon, threshold, rank_name))
        if old >= 150:
            old_x = sum(1 for t in config.PRESTIGE_THRESHOLDS if old >= t)
            new_x = sum(1 for t in config.PRESTIGE_THRESHOLDS if new >= t)
            if new_x > old_x:
                milestones.append((weapon, new, f"Iridescent ×{new_x}"))
    return milestones


def build_milestone_message(player_name, weapon, threshold, rank_name):
    """Return a Butler-voiced announcement string for this milestone, or None."""
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


# ── Nerve-center logging ──────────────────────────────────────────────────────
_nerve_events = {
    'submissions':       [],   # (timestamp, player, weapon)
    'butler_interactions': [], # (trigger[:60], response[:60])
    'errors':            [],   # (timestamp, error_str)
    'milestones':        [],   # (player, weapon, rank)
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
    """Immediately post a critical error alert to nerve center."""
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
    """Return formatted digest string and clear the buffer."""
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


# ── butlers-manual content builder ────────────────────────────────────────────
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
