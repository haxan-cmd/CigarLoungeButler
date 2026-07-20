"""utils/challenges.py — pure parsing for bounty special challenges.

The special challenge is authored as free text in /bounty_create, then matched
by regex. Keeping that logic here (no discord, no db) means it can be unit
tested, the same way utils/parsing.py and utils/ranks.py are.
"""
from datetime import datetime
import re


def parse_ts(raw):
    """Best-effort parse of a stored timestamp string to a naive UTC datetime."""
    if not raw:
        return None
    s = str(raw).strip().replace('UTC', '').strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_special(bounty):
    """Break the special-challenge text into machine-checkable parts.

    Returns None when there is no challenge, else a dict:
      text        lowercased challenge string
      min_td      takedowns a run must reach (default 100)
      max_deaths  deaths a run must stay UNDER, or None if unconstrained
      need        how many qualifying runs are required (default 1)
      any_weapon  True when the challenge accepts any weapon on the bounty
    """
    sc = (bounty.get('special_challenge') or '').lower()
    if not sc:
        return None
    td = re.search(r'(\d+)\s*takedown', sc)
    deaths = re.search(r'(?:fewer than|less than|under|sub|below|<)\s*(\d+)\s*death', sc)
    count = re.search(r'(?:complete\s*)?(\d+)\s*times', sc) or re.search(r'\bx\s*(\d+)\b', sc)
    return {
        'text': sc,
        'min_td': int(td.group(1)) if td else 100,
        'max_deaths': int(deaths.group(1)) if deaths else None,
        'need': max(1, int(count.group(1))) if count else 1,
        'any_weapon': ('any bounty weapon' in sc) or ('any weapon' in sc),
    }


def describe(spec):
    """Short label for the challenge, built from what was actually parsed.

    The authored text is a sentence and runs far past the weapon column on a
    player card. This stays compact and, because it is derived from the parse
    rather than the prose, it cannot drift from what is being enforced.
    """
    if not spec:
        return ''
    bits = [f"{spec['min_td']}+ TD"]
    if spec['max_deaths'] is not None:
        bits.append(f"<{spec['max_deaths']} deaths")
    label = ', '.join(bits)
    if spec['need'] > 1:
        label += f" x{spec['need']}"
    return label


def special_weapon_ok(bounty, spec, weapon):
    """Does this weapon satisfy the challenge? Either it is named in the challenge
    text, or the challenge accepts any weapon on the bounty roster."""
    if not weapon:
        return False
    w = weapon.strip().lower()
    if spec['any_weapon']:
        return any(w == str(k).strip().lower() for k in (bounty.get('weapons') or {}))
    return w in spec['text']


def run_qualifies(bounty, spec, weapon, takedowns, deaths, feats=''):
    """Does a single submission satisfy the challenge? Resubmits never count,
    matching how they are excluded from bounty progress elsewhere."""
    if 'resubmit' in (feats or '').lower():
        return False
    if not special_weapon_ok(bounty, spec, weapon):
        return False
    try:
        td = int(takedowns) if takedowns else 0
        dk = int(deaths) if deaths else 0
    except (ValueError, TypeError):
        return False
    if td < spec['min_td']:
        return False
    if spec['max_deaths'] is not None and dk >= spec['max_deaths']:
        return False
    return True
