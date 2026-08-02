"""Pure 'what's next' goal picker.

The lounge has three progression tracks that pull in different directions and are
never surfaced together, so a player can't tell which is closest:
  - rank-up      : short-term, the next weapon-rank threshold
  - mastery      : mid-term depth, 100+ marks on ONE weapon (then Virtuoso at 250)
  - hundred-handed: long-term breadth, a qualifying run on every subclass primary

next_goals() returns the nearest target on EACH track so they can be shown side by
side. Pure (no db/discord) — feed it already-computed numbers; unit-tested.
"""


def _nearest_rank_up(weapon_marks, rank_thresholds):
    """Weapon closest to its next rank threshold. rank_thresholds = [(marks, name), ...]
    ascending. Returns a goal dict or None."""
    best = None
    for w, m in weapon_marks.items():
        if m <= 0:
            continue
        nxt = next(((t, nm) for t, nm in rank_thresholds if t > m), None)
        if not nxt:
            continue  # already at the top rank
        remaining = nxt[0] - m
        if best is None or remaining < best['remaining']:
            best = {'kind': 'rank_up', 'weapon': w, 'remaining': remaining,
                    'target': nxt[1],
                    'label': f"{remaining} mark{'s' if remaining != 1 else ''} from {nxt[1]} on {w}"}
    return best


def _nearest_mastery(weapon_marks, mastery_threshold, virtuoso_threshold):
    """Closest weapon to Mastery (or Virtuoso if already mastered). Returns a goal
    dict or None. Prefers the highest weapon still short of the next tier."""
    # If a weapon is between mastery and virtuoso, chase Virtuoso on the closest one.
    virt = [(w, m) for w, m in weapon_marks.items()
            if mastery_threshold <= m < virtuoso_threshold]
    if virt:
        w, m = max(virt, key=lambda t: t[1])
        r = virtuoso_threshold - m
        return {'kind': 'virtuoso', 'weapon': w, 'remaining': r,
                'target': 'Virtuoso',
                'label': f"{r} more toward Virtuoso on {w} ({m}/{virtuoso_threshold})"}
    under = [(w, m) for w, m in weapon_marks.items() if 0 < m < mastery_threshold]
    if not under:
        return None
    w, m = max(under, key=lambda t: t[1])
    r = mastery_threshold - m
    return {'kind': 'mastery', 'weapon': w, 'remaining': r,
            'target': 'Mastered',
            'label': f"{r} more toward Mastering {w} ({m}/{mastery_threshold})"}


def _hundred_handed_goal(hh_missing, hh_total):
    """hh_missing = iterable of (subclass, weapon) combos still owed."""
    missing = list(hh_missing or [])
    if not missing:
        return None
    n = len(missing)
    by_sub = {}
    for sc, w in sorted(missing):
        by_sub.setdefault(sc, []).append(w)
    # Name the subclass closest to done (fewest owed) as the concrete next step.
    closest_sub = min(by_sub.items(), key=lambda kv: len(kv[1]))
    return {'kind': 'hundred_handed', 'remaining': n, 'target': 'Hundred-Handed',
            'done': (hh_total - n) if hh_total else None, 'total': hh_total,
            'closest_subclass': closest_sub[0], 'closest_weapons': closest_sub[1],
            'label': f"{n} combo{'s' if n != 1 else ''} from the Hundred-Handed"}


def next_goals(weapon_marks, hh_missing, *, mastery_threshold, virtuoso_threshold,
               rank_thresholds, hh_total=0):
    """Nearest target on each track. Returns a dict with keys 'rank_up', 'mastery',
    'hundred_handed' (each a goal dict or None) and 'nearest' (the goal with the
    smallest 'remaining' across all tracks, for a one-line nudge)."""
    goals = {
        'rank_up': _nearest_rank_up(weapon_marks or {}, rank_thresholds or []),
        'mastery': _nearest_mastery(weapon_marks or {}, mastery_threshold, virtuoso_threshold),
        'hundred_handed': _hundred_handed_goal(hh_missing, hh_total),
    }
    present = [g for g in goals.values() if g]
    goals['nearest'] = min(present, key=lambda g: g['remaining']) if present else None
    return goals
