"""Locks the registry `archetype_label` wiring — specifically that it weights
classes by RAW weapon marks (not the coarse class-level count), so an active
one-weapon player gets a label instead of a blank card. Regression guard for the
"cards showed no archetype" recalibration.

Skipped where discord/asyncpg aren't installed (see conftest).
"""
import pytest

pytest.importorskip("discord")
pytest.importorskip("asyncpg")

from cogs.registry import archetype_label


def _stats(**classes):
    """Build a minimal class_stats structure: {class: {subclasses: {S: {weapons:
    {weapon: {marks: n}}}}}}."""
    return {c: {"subclasses": {"S": {"weapons": {w: {"marks": m} for w, m in wm.items()}}}}
            for c, wm in classes.items()}


def test_active_one_weapon_player_is_labeled():
    # 6 raw marks on one weapon -> Specialist. Under the old class-level weighting
    # this player scored 0 levels and got NO label; raw marks fix that.
    s = _stats(Knight={"Messer": 6})
    assert archetype_label(s, {"Messer": 6}) == "Messer Specialist"


def test_class_heavy_without_single_weapon():
    s = _stats(Knight={"Sword": 6, "Mace": 6}, Vanguard={"Maul": 3})
    assert archetype_label(s, {"Sword": 6, "Mace": 6, "Maul": 3}) == "Knight Specialist"


def test_spread_is_generalist():
    s = _stats(Knight={"Sword": 4}, Vanguard={"Maul": 4}, Footman={"Spear": 4})
    assert archetype_label(s, {"Sword": 4, "Maul": 4, "Spear": 4}) == "Generalist"


def test_below_floor_stays_blank():
    # Fewer than 5 raw marks: too little to characterise -> no label.
    s = _stats(Knight={"Sword": 3})
    assert archetype_label(s, {"Sword": 3}) is None
