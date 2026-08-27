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
import hmac


def kofi_verification_result(expected_token, provided_token):
    """Decide a Ko-fi webhook's fate from the configured token vs the payload token:
      'reject_unconfigured' — no token set on our side. FAIL CLOSED: without a token we
                              can't tell a real webhook from a spoof, so don't process.
      'reject_bad_token'    — token set but the payload's token doesn't match.
      'ok'                  — verified.
    Failing closed on an unset token stops the public /kofi URL being used to inject
    spoofed donations. Uses a timing-safe compare."""
    if not expected_token:
        return 'reject_unconfigured'
    if not hmac.compare_digest(str(provided_token or ''), str(expected_token)):
        return 'reject_bad_token'
    return 'ok'


def clean_donation_amount(raw):
    """A non-negative float from a webhook's amount field; 0.0 on missing/garbage or a
    negative value (a spoof can't drive the recorded total below zero)."""
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


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


_ARCHER_PSEUDO = frozenset({"Archer", "Hybrid", "Peasant Run", "Marksman",
                            "Longbowman", "Crossbowman", "Skirmisher"})


def reconcile_weapon_subclass(weapon, subclass, class_weapon_map, pseudo_subclasses=_ARCHER_PSEUDO,
                              subclass_parent=None):
    """A weapon can only be wielded by the subclasses that actually list it, so an
    impossible pair (e.g. Warhammer — which only Guardian carries — tagged as Officer,
    from a free-text caption like "warhammer officer") is bad data.

    Returns (subclass_out, corrected_from):
      - pair is valid, or inputs incomplete, or weapon unknown to us -> (subclass, None).
      - weapon owned by exactly ONE real subclass -> (that subclass, old_subclass).
      - weapon owned by several, but the typed subclass's CLASS matches exactly one of
        them (given subclass_parent) -> that owner: respect the class the user meant
        (e.g. "Messer Guardian": Guardian is a Knight, the Messer's Knight owner is
        Crusader, so correct to Crusader rather than the Vanguard/Raider option).
      - weapon owned by several with no class tiebreak -> (subclass, None): don't guess.

    The synthetic/collapsed classes (Archer, Hybrid, Peasant Run, and the underlying
    Longbowman/Crossbowman/Skirmisher we store as 'Archer') are never touched — we
    neither judge them as wrong nor coerce a weapon INTO one. Pure; unit-tested."""
    if not weapon or not subclass:
        return subclass, None
    if subclass in pseudo_subclasses:
        return subclass, None
    owners = [cls for cls, weps in (class_weapon_map or {}).items() if weapon in (weps or [])]
    if not owners or subclass in owners:
        return subclass, None
    real_owners = [c for c in owners if c not in pseudo_subclasses]
    if len(real_owners) == 1:
        return real_owners[0], subclass
    if subclass_parent and len(real_owners) > 1:
        _typed_class = subclass_parent.get(subclass)
        if _typed_class:
            _same = [c for c in real_owners if subclass_parent.get(c) == _typed_class]
            if len(_same) == 1:
                return _same[0], subclass
    return subclass, None


def scoreboard_looks_incomplete(team_total_kills, enemy_total_kills):
    """True when a submitted scoreboard is missing the top-of-screen faction KILL
    TOTALS (one or both). Those two big numbers set the lobby-difficulty read, and a
    cropped or photographed board (top of the screen cut off) loses them even when the
    player's own row read fine. This drives a SOFT nudge to capture the whole board next
    time, never a rejection."""
    return not (isinstance(team_total_kills, int) and isinstance(enemy_total_kills, int))


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
