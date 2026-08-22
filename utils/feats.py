"""Pure feat-derivation logic shared by the submission finalise path and the edit
path. These two used to hand-maintain byte-identical feat blocks inline, which is
exactly how they drifted (a Flawless tweak or a Triple rule landing in one and not
the other). Centralising them here keeps them in lockstep and, because there is no
Discord or DB dependency, makes them unit-testable (tests/test_feats.py)."""


def is_pacifist(kills, takedowns):
    """A pacifist run: no kills and at most a handful of takedowns (objective/support
    play). Earns no weapon marks and stays off the weapon/feat boards."""
    return kills == 0 and takedowns <= 10


def is_triple_run(kills, takedowns, score, confirmed=False):
    """A Triple: 150+ takedowns AND 100+ kills AND the 20,000-point bar met.

    The PARSED scoreboard score is authoritative: when a score was actually read, the
    Triple stands only if score >= 20000. A manual '20k+?' confirmation can NOT override
    a score we read below the bar — that hole let 19,500-point 'Triples' through.
    Confirmation (the prompt, or an existing Triple tag on an edit) is the fallback ONLY
    when the score is unknown/unreadable (None)."""
    if not (takedowns >= 150 and kills >= 100):
        return False
    if score is not None:
        return score >= 20000
    return bool(confirmed)


def derive_stat_feats(kills, takedowns, deaths, weapon, feat_weapons, triple):
    """The stat-derived feats a run earns, in canonical order. `triple` is the result
    of is_triple_run for this run. Feats STACK: a Triple also earns the 100 Kills
    credit (it is by definition a 100-kill game) and, when it clears 200 takedowns,
    the 200 Takedowns credit too — so a single legendary run banks a mark for each
    milestone it hit, not just one. `feat_weapons` is the set/collection of weapons
    that carry their own 100-kill feat board (config.FEAT_WEAPONS)."""
    feats = []
    if triple:
        feats.append("Triple")
    if kills >= 100:
        feats.append("100 Kills")
    if takedowns >= 200:
        feats.append("200 Takedowns")
    if deaths == 0 and takedowns > 0 and not is_pacifist(kills, takedowns):
        feats.append("Flawless")
    if takedowns >= 150 and deaths == 0:
        feats.append("Predator")
    if weapon in feat_weapons and kills >= 100:
        feats.append(weapon)
    return feats


def tilt_mark(feats, tilt_bands):
    """The valor mark a hard-lobby run earns from its tilt tag. Returns
    (marks, emoji, name) for the FIRST matching band (bands are ordered hardest
    first), or (0, None, None) if the run carries no tilt tag. `tilt_bands` is
    config.TILT_BANDS: rows of (low_gap, name, emoji, marks, tag)."""
    for _low, name, emoji, marks, tag in tilt_bands:
        if tag and tag in feats:
            return marks, emoji, name
    return 0, None, None
