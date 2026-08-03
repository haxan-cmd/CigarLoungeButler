"""Integration tests for the mark-calculation core (cogs/registry.py
`calculate_weapon_marks_for_player`) against the in-memory FakeDB.

These lock the exact mark bugs fixed this year: feat bonuses stacking, the
Score-vs-High-Score substring collision, valor tiers, canonical weapon folding,
pacifist earning nothing, and VIP still earning marks (VIP only bars boards).
Skipped where discord/asyncpg aren't installed (see conftest).
"""
import asyncio
import pytest

pytest.importorskip("discord")
pytest.importorskip("asyncpg")

from cogs.registry import calculate_weapon_marks_for_player


def run(coro):
    return asyncio.run(coro)


def _flat(marks):
    """Sum marks per weapon regardless of (weapon, subclass) vs plain keying."""
    out = {}
    for k, v in (marks or {}).items():
        w = k[0] if isinstance(k, tuple) else k
        out[w] = out.get(w, 0) + v
    return out


def test_base_mark_one_per_run(fake_db, make_sub):
    fake_db.submissions = [make_sub(weapon="Messer", td=120, feats="")]
    assert _flat(run(calculate_weapon_marks_for_player(1))).get("Messer") == 1


def test_feat_bonuses_stack(fake_db, make_sub):
    fake_db.submissions = [make_sub(weapon="Messer",
                                    feats="200 Takedowns, 100 Kills, Triple, High Score")]
    # 1 base + 4 feat bonuses
    assert _flat(run(calculate_weapon_marks_for_player(1))).get("Messer") == 5


def test_score_and_high_score_do_not_collide(fake_db, make_sub):
    # 'Score' is a substring of 'High Score' — both must count (token-exact check).
    fake_db.submissions = [make_sub(weapon="Messer", feats="High Score, Score")]
    assert _flat(run(calculate_weapon_marks_for_player(1))).get("Messer") == 3

    # 'Score' alone must NOT also fire the High Score bonus.
    fake_db.submissions = [make_sub(weapon="Messer", feats="Score")]
    assert _flat(run(calculate_weapon_marks_for_player(1))).get("Messer") == 2


def test_valor_tiers(fake_db, make_sub):
    for tag, expected in (("Brutal", 4), ("Outmatched", 3), ("Uphill", 2)):
        fake_db.submissions = [make_sub(weapon="Messer", feats=tag)]
        assert _flat(run(calculate_weapon_marks_for_player(1)))["Messer"] == expected, tag


def test_canonical_weapon_folds_casing(fake_db, make_sub):
    # An off-canonical "polehammer" must count under the real "Polehammer".
    fake_db.submissions = [make_sub(weapon="polehammer", subclass="Poleman")]
    m = _flat(run(calculate_weapon_marks_for_player(1)))
    assert m.get("Polehammer") == 1 and "polehammer" not in m


def test_pacifist_earns_no_weapon_marks(fake_db, make_sub):
    fake_db.submissions = [make_sub(weapon="Messer", kills=0, td=5, feats="")]
    assert _flat(run(calculate_weapon_marks_for_player(1))).get("Messer", 0) == 0


def test_vip_run_still_earns_marks(fake_db, make_sub):
    # VIP bars WEAPON BOARDS, not marks — the run still earns its submission mark.
    fake_db.submissions = [make_sub(weapon="Messer", vip="Yes", td=120)]
    assert _flat(run(calculate_weapon_marks_for_player(1))).get("Messer") == 1


def test_multiple_runs_accumulate(fake_db, make_sub):
    fake_db.submissions = [
        make_sub(weapon="Messer", feats="", link="a"),
        make_sub(weapon="Messer", feats="Triple", link="b"),
        make_sub(weapon="Axe", subclass="Guardian", feats="", link="c"),
    ]
    m = _flat(run(calculate_weapon_marks_for_player(1)))
    assert m.get("Messer") == 3 and m.get("Axe") == 1   # 1 + (1+Triple) ; 1
