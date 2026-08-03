from utils.archetype import derive_archetype, derive_damage_style

_DMG = {"Maul": "Blunt", "War Club": "Blunt", "Mace": "Blunt",
        "Axe": "Chop", "War Axe": "Chop",
        "Sword": "Cut", "Messer": "Cut",
        "Bow": "Ranged"}


def test_damage_none_below_min():
    assert derive_damage_style({"Maul": 3}, _DMG) is None


def test_damage_specialist():
    assert derive_damage_style({"Maul": 8, "Mace": 4}, _DMG) == "Blunt specialist"


def test_damage_leaning():
    # Blunt 10 / total 22 = 45% -> leaning, not specialist.
    wm = {"Maul": 10, "Axe": 7, "Sword": 5}
    assert derive_damage_style(wm, _DMG) == "Blunt-leaning"


def test_damage_mixed():
    wm = {"Maul": 5, "Axe": 5, "Sword": 5}   # 33% each
    assert derive_damage_style(wm, _DMG) == "Mixed damage"


def test_damage_ignores_unmapped_weapons():
    wm = {"Maul": 8, "Unknownium": 100}      # unmapped weapon dropped
    assert derive_damage_style(wm, _DMG) == "Blunt specialist"


def test_none_below_min_total():
    assert derive_archetype({"Knight": 4, "Vanguard": 3}, {}) is None


def test_weapon_specialist_takes_priority():
    # One weapon dominates -> weapon specialist, even though class also concentrates.
    cm = {"Knight": 20, "Vanguard": 4}
    wm = {"Messer": 18, "Sword": 2, "Axe": 4}   # Messer = 18/24 = 75%
    assert derive_archetype(cm, wm) == "Messer Specialist"


def test_tuple_weapon_keys_are_aggregated():
    cm = {"Knight": 20}
    wm = {("Messer", "Crusader"): 10, ("Messer", "Raider"): 8, ("Axe", "Officer"): 2}
    assert derive_archetype(cm, wm) == "Messer Specialist"   # 18/20 = 90%


def test_class_specialist():
    cm = {"Knight": 18, "Vanguard": 5, "Footman": 2}          # Knight 18/25 = 72%
    wm = {"Messer": 6, "Sword": 6, "Axe": 6, "Mace": 5}       # no weapon >= 50%
    assert derive_archetype(cm, wm) == "Knight Specialist"


def test_class_main():
    cm = {"Knight": 12, "Vanguard": 9, "Footman": 4}          # Knight 12/25 = 48%
    wm = {"Messer": 5, "Sword": 5, "Maul": 5, "Halberd": 4}
    assert derive_archetype(cm, wm) == "Knight Main"


def test_generalist_when_spread():
    cm = {"Knight": 10, "Vanguard": 9, "Footman": 9, "Archer": 2}  # top 10/30 = 33%, 3 classes >=15%
    wm = {"Messer": 4, "Maul": 4, "Halberd": 4, "Sword": 4}
    assert derive_archetype(cm, wm) == "Generalist"


def test_two_class_lean_falls_back_to_leading_main():
    # Two classes lead, neither hits 40%, and fewer than 3 clear the spread floor.
    cm = {"Knight": 11, "Vanguard": 10, "Footman": 1, "Archer": 1}  # top 11/23 = 48%? -> ensure < .4
    # adjust so top share < .4 to exercise the fallback branch
    cm = {"Knight": 9, "Vanguard": 9, "Footman": 3, "Archer": 3}    # top 9/24 = 37.5%, spread: 2 classes >=15%
    wm = {"Messer": 4, "Maul": 4, "Sword": 3}
    assert derive_archetype(cm, wm) == "Vanguard Main"   # tie broken by name (Vanguard > Knight)
