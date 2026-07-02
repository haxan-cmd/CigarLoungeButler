"""Pure text-parsing helpers (no discord/db/AI imports) so they're unit-testable.

parse_submission_text reads a caption like "resubmit poleman halberd" and pulls
out (weapon, subclass). Matching is whole-word/phrase based — NOT substring — so
names and chatter ("Axel", "he mauled us", "knightly") don't mis-detect a weapon
or class. Fuzzy fallback is restricted to longer aliases with a tight cutoff for
the same reason.
"""
import re
from difflib import get_close_matches

import config


def _whole_match(text_lower: str, alias: str) -> bool:
    """True if alias appears as a whole word/phrase (bounded by non-word chars)."""
    return re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text_lower) is not None


def parse_submission_text(text):
    text_lower = (text or '').lower().strip()
    words = text_lower.split()
    detected_weapon = None
    detected_subclass = None

    # 1. Whole-word/phrase alias match (longest-first so "war axe" beats "axe").
    for alias in sorted(config.WEAPON_ALIASES.keys(), key=len, reverse=True):
        if _whole_match(text_lower, alias):
            detected_weapon = config.WEAPON_ALIASES[alias]
            break

    # 2. Fuzzy fallback — only aliases >= 5 chars, tight cutoff, so short aliases
    #    (axe/van/mace/dane) don't catch words like axel/axed/mauled/daned.
    if not detected_weapon:
        long_aliases = [a for a in config.WEAPON_ALIASES if len(a) >= 5]
        for word in words:
            if len(word) < 5:
                continue
            m = get_close_matches(word, long_aliases, n=1, cutoff=0.86)
            if m:
                detected_weapon = config.WEAPON_ALIASES[m[0]]
                break
        if not detected_weapon:
            for i in range(len(words) - 1):
                phrase = words[i] + ' ' + words[i + 1]
                m = get_close_matches(phrase, long_aliases, n=1, cutoff=0.86)
                if m:
                    detected_weapon = config.WEAPON_ALIASES[m[0]]
                    break

    detected_parent = None
    # 3. Whole-word alias match for subclass.
    for alias in sorted(config.SUBCLASS_ALIASES.keys(), key=len, reverse=True):
        if _whole_match(text_lower, alias):
            raw = config.SUBCLASS_ALIASES[alias]
            if raw in config.PARENT_TO_SUBCLASSES:
                detected_parent = raw
            else:
                detected_subclass = raw
            break

    # 4. Fuzzy fallback for subclass (same tightening).
    if not detected_subclass and not detected_parent:
        long_sub = [a for a in config.SUBCLASS_ALIASES if len(a) >= 5]
        for word in words:
            if len(word) < 5:
                continue
            m = get_close_matches(word, long_sub, n=1, cutoff=0.86)
            if m:
                raw = config.SUBCLASS_ALIASES[m[0]]
                if raw in config.PARENT_TO_SUBCLASSES:
                    detected_parent = raw
                else:
                    detected_subclass = raw
                break

    # Parent class + weapon -> resolve the unique subclass automatically
    # (e.g. "knight" + Messer -> Crusader, the only Knight with Messer).
    if detected_parent and detected_weapon:
        subs = config.PARENT_TO_SUBCLASSES[detected_parent]
        candidates = [s for s in subs if detected_weapon in config.CLASS_WEAPON_MAP.get(s, [])]
        if len(candidates) == 1:
            detected_subclass = candidates[0]

    return detected_weapon, detected_subclass
