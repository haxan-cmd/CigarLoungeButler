"""Pure combat-rating math shared by the season stats.

Kept import-free (no discord/db) so it's unit-tested and reused wherever a rating is
combined.
"""


def dominance(warlord_pct, killshare_pct):
    """Two-way impact score: the HARMONIC MEAN of a player's Warlord% (takedowns ÷ team
    kills) and Kill-Share% (kills ÷ team kills). It is only high when BOTH are high, so it
    can't be gamed by min-maxing one — ratting for kills or farming takedowns — while
    tanking the other (unlike raw Lethality, which a lower takedown count inflates).

    HM = 2ab / (a + b). Returns 0.0 if either input is missing, zero, or negative (you can't
    be dominant while contributing nothing on one axis)."""
    try:
        w = float(warlord_pct)
        k = float(killshare_pct)
    except (TypeError, ValueError):
        return 0.0
    if w <= 0 or k <= 0:
        return 0.0
    return 2 * w * k / (w + k)
