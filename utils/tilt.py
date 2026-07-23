"""Pure lobby-tilt difficulty logic: orientation, role baseline, band lookup.

Single source of truth for the difficulty ladder so the submission blurb label
and the mark payout can never drift apart. No side effects; unit-tested in
tests/test_tilt.py.

'Tilt' is the kill gap between the two banner totals, as a percent of the
smaller team. 'Adjusted tilt' subtracts your role's baseline (attack runs are
target-rich, defence runs are not), so difficulty reads as how far below your
side's NORM the lobby was, not a blanket percentage. The hard (negative) tail
pays valor marks; the easy tail is label-only.
"""
import config


def orientation(map_name, faction):
    """('Attack' | 'Defense' | None) for a run, from config.MAP_ATTACK_DEFENSE.
    Map names are matched by substring so the full display name ('The Fall of
    Lionspire') resolves against the short table key ('Lionspire')."""
    if not map_name or not faction:
        return None
    ml = str(map_name).lower()
    for key, pair in (getattr(config, 'MAP_ATTACK_DEFENSE', {}) or {}).items():
        if key.lower() in ml:
            att, dfd = pair
            if faction == att:
                return 'Attack'
            if faction == dfd:
                return 'Defense'
            return None
    return None


def baseline(orient):
    """Median kill-gap % a posted run shows for this role. 0 when unknown, so an
    unclassifiable lobby falls back to raw tilt rather than a wrong adjustment."""
    if orient == 'Attack':
        return getattr(config, 'TILT_BASELINE_ATTACK', 0)
    if orient == 'Defense':
        return getattr(config, 'TILT_BASELINE_DEFENSE', 0)
    return 0


def raw_tilt(team_total, enemy_total):
    """Kill-gap % relative to the smaller team, or None if totals are unusable.
    Positive = your team outkilled them."""
    if not isinstance(team_total, int) or not isinstance(enemy_total, int):
        return None
    if not (0 < team_total <= 3000 and 0 < enemy_total <= 3000):
        return None
    return round((team_total - enemy_total) / min(team_total, enemy_total) * 100)


def adjusted(raw, map_name, faction):
    """Raw tilt minus the role baseline. None passes through untouched."""
    if raw is None:
        return None
    return raw - baseline(orientation(map_name, faction))


def band(adjusted_tilt):
    """The band for an adjusted tilt value, as a dict: name, emoji, marks, tag.
    Scans config.TILT_BANDS top-down (hardest edges last) and returns the first
    band whose low edge the value clears."""
    bands = config.TILT_BANDS
    for low, name, emoji, marks, tag in bands:
        if adjusted_tilt >= low:
            return {'name': name, 'emoji': emoji, 'marks': marks, 'tag': tag}
    low, name, emoji, marks, tag = bands[-1]
    return {'name': name, 'emoji': emoji, 'marks': marks, 'tag': tag}


def tag_marks():
    """{feat_tag: bonus_marks} for every band that carries a tag. The mark calc
    reads the feats column, so this is how a stored tag maps back to marks."""
    return {tag: marks for (_lo, _nm, _em, marks, tag) in config.TILT_BANDS if tag}


def card_badges():
    """[(tag, emoji)] for the difficulty tags that earn a counting card badge,
    in ladder order (hardest last)."""
    want = getattr(config, 'TILT_CARD_BADGES', ())
    out = []
    for (_lo, _nm, emoji, _mk, tag) in config.TILT_BANDS:
        if tag in want and (tag, emoji) not in out:
            out.append((tag, emoji))
    return out
