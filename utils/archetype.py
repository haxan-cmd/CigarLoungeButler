"""Pure derivation of a player's descriptive 'archetype' from their marks
distribution across classes and weapons.

Neutral, factual tone by design (e.g. 'Knight Specialist', 'Vanguard Main',
'Generalist', 'Messer Specialist') — it describes where a player's marks
concentrate, nothing more. Shown on the registry card and available to the
Butler. No I/O; unit-tested.

Ladder (first match wins):
  1. a single weapon holds >= `weapon_specialist` of all weapon marks -> "<Weapon> Specialist"
  2. one class holds >= `class_specialist` of all class marks            -> "<Class> Specialist"
  3. one class holds >= `class_main` of all class marks                  -> "<Class> Main"
  4. marks spread across 3+ classes (each >= `spread_floor`)             -> "Generalist"
  5. otherwise the leading class                                          -> "<Class> Main"

Returns None when the player has fewer than `min_total` class marks — too little
to characterise, so callers simply omit the label.
"""


def _normalise_weapon_marks(weapon_marks):
    """Collapse marks to one entry per weapon name. Keys may be a plain weapon
    name or a (weapon, subclass) tuple (the registry uses both)."""
    out = {}
    for k, v in (weapon_marks or {}).items():
        if not v or v <= 0:
            continue
        name = k[0] if isinstance(k, tuple) else k
        if not name:
            continue
        out[name] = out.get(name, 0) + v
    return out


def derive_archetype(class_marks, weapon_marks, *, min_total=10,
                     weapon_specialist=0.5, class_specialist=0.6,
                     class_main=0.4, spread_floor=0.15):
    cm = {c: m for c, m in (class_marks or {}).items() if m and m > 0}
    ctotal = sum(cm.values())
    if ctotal < min_total:
        return None

    wm = _normalise_weapon_marks(weapon_marks)
    wtotal = sum(wm.values())
    if wtotal:
        # (marks, name) key makes ties deterministic.
        w, wmarks = max(wm.items(), key=lambda kv: (kv[1], kv[0]))
        if wmarks / wtotal >= weapon_specialist:
            return f"{w} Specialist"

    cls, cmarks = max(cm.items(), key=lambda kv: (kv[1], kv[0]))
    share = cmarks / ctotal
    if share >= class_specialist:
        return f"{cls} Specialist"
    if share >= class_main:
        return f"{cls} Main"
    if sum(1 for m in cm.values() if m / ctotal >= spread_floor) >= 3:
        return "Generalist"
    return f"{cls} Main"
