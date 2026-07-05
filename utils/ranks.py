"""Pure rank / title / Hundred-Handed math — no discord, no database.

Lifted out of the cogs so there is a single source of truth that can be imported
and unit-tested in isolation (see tests/test_ranks.py). The cogs import from here;
behaviour is unchanged.
"""
from config import (
    WEAPON_RANK_THRESHOLDS, SUBCLASS_RANKS, CLASS_RANKS, PLAYER_TITLES,
    _SUBCLASS_PRIMARIES,
)


def get_weapon_rank(marks):
    """Return (rank_name, marks_for_current_tier, marks_for_next_tier) for a weapon."""
    rank = None
    current_threshold = 0
    for threshold, name in WEAPON_RANK_THRESHOLDS:
        if marks >= threshold:
            rank = name
            current_threshold = threshold
        else:
            next_threshold = threshold
            return rank or "Unranked", current_threshold, next_threshold
    return WEAPON_RANK_THRESHOLDS[-1][1], current_threshold, None  # Iridescent


def get_subclass_rank(subclass_marks, num_weapons):
    """Return (rank_name, level) based on how many times the meter filled."""
    if num_weapons == 0:
        return SUBCLASS_RANKS[0], 0
    level = min(subclass_marks // num_weapons, len(SUBCLASS_RANKS) - 1)
    return SUBCLASS_RANKS[level], level


def get_class_rank(class_marks):
    """Class rank advances every 3 subclass level-ups."""
    level = min(class_marks // 3, len(CLASS_RANKS) - 1)
    return CLASS_RANKS[level], level


def get_player_title(bounties_completed):
    idx = min(bounties_completed, len(PLAYER_TITLES) - 1)
    return PLAYER_TITLES[idx]


# ── Hundred-Handed ──
# A 100-takedown run with every primary weapon on every non-archer subclass.
# Archer subclasses are excluded; HH_TOTAL is the target combo count (46).
HH_ARCHER = {'Longbowman', 'Crossbowman', 'Skirmisher'}
HH_PRIMARIES = {sc: ws for sc, ws in _SUBCLASS_PRIMARIES.items() if sc not in HH_ARCHER}
HH_TOTAL = sum(len(v) for v in HH_PRIMARIES.values())
