"""Pure rank / title / Hundred-Handed math. These lock the numbers that keep
breaking in production: a wrong rank at a tier boundary, Hundred-Handed counted
out of 85 instead of 46, or a title index off by one."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils.ranks import (
    get_weapon_rank, get_subclass_rank, get_class_rank, get_player_title,
    HH_TOTAL, HH_PRIMARIES, HH_ARCHER,
)


# ── weapon ranks ──
def test_weapon_rank_boundaries():
    assert get_weapon_rank(0)[0]    == "Unranked"
    assert get_weapon_rank(1)[0]    == "Bronze"
    assert get_weapon_rank(4)[0]    == "Bronze"
    assert get_weapon_rank(5)[0]    == "Silver"
    assert get_weapon_rank(59)[0]   == "Diamond"          # Crimson only starts at 60
    assert get_weapon_rank(60)[0]   == "Crimson"
    assert get_weapon_rank(149)[0]  == "Prestige Crimson"
    assert get_weapon_rank(150)[0]  == "Iridescent"
    assert get_weapon_rank(9999)[0] == "Iridescent"


def test_weapon_rank_next_threshold():
    name, cur, nxt = get_weapon_rank(1)     # Bronze at 1, next tier Silver at 5
    assert cur == 1 and nxt == 5
    assert get_weapon_rank(150)[2] is None  # top rank has no next tier


def test_weapon_thresholds_strictly_increasing():
    vals = [t for t, _ in config.WEAPON_RANK_THRESHOLDS]
    assert vals == sorted(vals) and len(set(vals)) == len(vals)
    assert config.WEAPON_RANK_THRESHOLDS[0] == (1, "Bronze")
    assert config.WEAPON_RANK_THRESHOLDS[-1] == (150, "Iridescent")


# ── subclass ranks ──
def test_subclass_rank_fill_and_cap():
    assert get_subclass_rank(0, 5)    == ("Initiate", 0)
    assert get_subclass_rank(5, 5)    == ("Veteran", 1)
    assert get_subclass_rank(9, 5)    == ("Veteran", 1)
    assert get_subclass_rank(10, 5)   == ("Master", 2)
    assert get_subclass_rank(9999, 5)[0] == "Apex"        # caps at the top
    assert get_subclass_rank(3, 0)    == ("Initiate", 0)  # never divides by zero


# ── class ranks ──
def test_class_rank_every_three_levels_and_cap():
    assert get_class_rank(0)  == ("Sworn", 0)
    assert get_class_rank(2)  == ("Sworn", 0)
    assert get_class_rank(3)  == ("Trusted", 1)
    assert get_class_rank(6)  == ("Proven", 2)
    assert get_class_rank(9999)[0] == "Ascended"


# ── player titles ──
def test_player_title_progression_and_cap():
    assert get_player_title(0)  == "Lounger"
    assert get_player_title(1)  == "Insider"
    assert get_player_title(6)  == "Legend"
    assert get_player_title(99) == "Legend"   # cannot exceed the final title


# ── mastery / virtuoso thresholds ──
def test_mastery_thresholds():
    assert config.MASTERY_THRESHOLD == 100
    assert config.VIRTUOSO_THRESHOLD == 250
    assert config.MASTERY_THRESHOLD < config.VIRTUOSO_THRESHOLD


# ── Hundred-Handed ──
def test_hundred_handed_total_is_46():
    assert HH_TOTAL == 46, f"Hundred-Handed target drifted to {HH_TOTAL}, expected 46"


def test_hundred_handed_excludes_archers():
    for sc in HH_ARCHER:
        assert sc not in HH_PRIMARIES
    assert all(len(ws) >= 1 for ws in HH_PRIMARIES.values())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all rank tests passed")
