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
    """A Triple: 150+ takedowns AND 100+ kills AND the 20,000-point bar met. The bar
    is met either by an explicit confirmation at submit/edit time (the '20k+?' prompt,
    or an existing Triple tag on an edit) or by a scorecard score >= 20000."""
    return (takedowns >= 150 and kills >= 100
            and (bool(confirmed) or (score is not None and score >= 20000)))


def derive_stat_feats(kills, takedowns, deaths, weapon, feat_weapons, triple):
    """The stat-derived feats a run earns, in canonical order. `triple` is the result
    of is_triple_run for this run (a Triple supersedes the separate 100 Kills / 200
    Takedowns credits). `feat_weapons` is the set/collection of weapons that carry
    their own 100-kill feat board (config.FEAT_WEAPONS)."""
    feats = []
    if triple:
        feats.append("Triple")
    else:
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
