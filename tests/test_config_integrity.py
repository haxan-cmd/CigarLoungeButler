"""Config data-integrity guards. These catch the class of bug that shipped this
season (a weapon with no caption alias, an alias pointing at a non-weapon, a
subclass with no alias, a broken parent->subclass map)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

MELEE_WEAPONS = set(config.WEAPONS_1H) | set(config.WEAPONS_2H) | set(getattr(config, "FEAT_WEAPONS", []))
SUBCLASSES = set(config.CLASS_WEAPON_MAP.keys())


def test_every_melee_weapon_has_an_alias():
    aliased = set(config.WEAPON_ALIASES.values())
    missing = sorted(MELEE_WEAPONS - aliased)
    assert not missing, f"weapons with no caption alias: {missing}"


def test_every_subclass_has_an_alias():
    aliased = set(config.SUBCLASS_ALIASES.values())
    missing = sorted(SUBCLASSES - aliased)
    assert not missing, f"subclasses with no caption alias: {missing}"


def test_weapon_alias_values_are_non_empty_strings():
    for k, v in config.WEAPON_ALIASES.items():
        assert isinstance(v, str) and v, f"alias {k!r} maps to bad value {v!r}"


def test_parent_map_points_at_real_subclasses():
    for parent, subs in config.PARENT_TO_SUBCLASSES.items():
        for s in subs:
            assert s in SUBCLASSES, f"{parent}->{s} is not a real subclass"


def test_subclass_alias_values_are_real():
    valid = SUBCLASSES | set(config.PARENT_TO_SUBCLASSES.keys())
    for k, v in config.SUBCLASS_ALIASES.items():
        assert v in valid, f"subclass alias {k!r} -> unknown {v!r}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all config-integrity tests passed")
