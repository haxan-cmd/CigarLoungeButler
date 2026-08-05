"""Pure submission-sanity checks.

A check here fires ONLY on data that is *impossible* — a state the game could
never produce — never on data that is merely *incomplete*. A half-read
scoreboard, a blank faction, missing lobby totals: all fine, all pass. The bar
is deliberately high so honest submitters with a partial screenshot are never
turned away; only genuinely contradictory data (a faction that doesn't exist on
the given map, e.g. Agatha on Askandir) gets rejected.

Kept pure (no discord/db imports) so it's unit-tested and reused wherever a run
is validated.
"""


def impossible_submission_reason(selected_map, faction, map_factions):
    """Return a short human reason if this (map, faction) pair cannot exist,
    else None.

    - A blank/None map or faction is INCOMPLETE, not impossible -> None.
    - An unknown map (not in map_factions) -> None (don't block on data we can't
      judge; the map picker constrains this anyway).
    - A faction that isn't one of the map's two teams -> a reason string.
    """
    if not selected_map or not faction:
        return None
    valid = map_factions.get(selected_map)
    if not valid:
        return None
    if faction not in valid:
        return (f"{faction} isn't a team on {selected_map} "
                f"(that map is {' vs '.join(valid)}).")
    return None


def below_takedown_minimum(takedowns, kills, minimum):
    """True if a run is under the takedown minimum and should be rejected. The one
    exemption is a true Pacifist run (0 kills, <=10 takedowns) — objective/support
    play with its own board. `minimum` of None or <=0 disables the gate. Non-numeric
    input passes (don't block on an unreadable value)."""
    try:
        td = int(takedowns)
        k = int(kills)
    except (ValueError, TypeError):
        return False
    if not minimum or minimum <= 0:
        return False
    is_pacifist = (k == 0 and td <= 10)
    return td < minimum and not is_pacifist
