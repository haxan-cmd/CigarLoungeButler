"""Tests for utils.stats_engine — correlation matrix, grouped comparisons, insights.

Rows mimic db.get_all_submissions() shape (lists of strings)."""
import math

from utils.stats_engine import (
    pearson, correlation_matrix, group_compare, find_insights,
    weapon_grip, run_class, STAT_EXTRACTORS, DEFAULT_MATRIX_STATS, is_excluded,
)


def row(name="Alice", did="1", weapon="Messer", subclass="Crusader", mp="Falmire",
        faction="Agatha", td=100, k=60, d=5, feats="", score=9000,
        tkshare=45.0, tdshare=40.0, team_tot=250, enemy_tot=230):
    r = [""] * 27
    r[1] = name; r[2] = did; r[3] = weapon; r[4] = subclass; r[5] = mp; r[6] = faction
    r[7] = str(td); r[8] = str(k); r[9] = str(d); r[11] = feats
    r[20] = str(tkshare); r[21] = str(tdshare); r[24] = str(score)
    r[25] = str(team_tot); r[26] = str(enemy_tot)
    return r


# ── pearson ──────────────────────────────────────────────────────────────
def test_pearson_perfect_positive_and_negative():
    assert abs(pearson([(1, 2), (2, 4), (3, 6), (4, 8)]) - 1.0) < 1e-9
    assert abs(pearson([(1, 8), (2, 6), (3, 4), (4, 2)]) + 1.0) < 1e-9


def test_pearson_guards():
    assert pearson([(1, 1), (2, 2)]) is None                 # <3 points
    assert pearson([(1, 5), (2, 5), (3, 5)]) is None          # zero variance in y


# ── categorisers ───────────────────────────────────────────────────────────
def test_weapon_grip_from_config_lists():
    assert weapon_grip(row(weapon="Messer")) == "2H"
    assert weapon_grip(row(weapon="Sword")) == "1H"
    assert weapon_grip(row(weapon="Bow")) is None            # ranged -> neither


def test_run_class_from_subclass():
    assert run_class(row(subclass="Crusader")) == "Knight"
    assert run_class(row(subclass="Raider")) == "Vanguard"
    assert run_class(row(subclass="Poleman")) == "Footman"


def test_dominance_is_harmonic_mean_of_killshare_and_warlord():
    dom = STAT_EXTRACTORS['dominance'][0]
    # kills=50, td=100, kill_share=45% -> warlord=100*45/50=90 -> HM(45,90)=60
    assert abs(dom(row(td=100, k=50, tkshare=45.0)) - 60.0) < 1e-6
    # missing an axis (no takedowns -> no warlord) yields None, not a bogus value
    assert dom(row(td=0, k=50, tkshare=45.0)) is None


# ── matrix ─────────────────────────────────────────────────────────────────
def test_matrix_is_symmetric_with_unit_diagonal():
    # kills tracks takedowns; deaths anti-tracks K/D.
    subs = [row(td=t, k=t // 2 + 5, d=max(1, 10 - i)) for i, t in enumerate(range(40, 120, 8))]
    m = correlation_matrix(subs, ['kills', 'td', 'deaths', 'kd'], min_n=3)
    keys = m['stats']
    n = len(keys)
    for i in range(n):
        assert m['r'][(i, i)] == 1.0
        for j in range(n):
            assert m['r'][(i, j)] == m['r'][(j, i)]
    # kills vs td should be a strong positive
    ki, ti = keys.index('kills'), keys.index('td')
    assert m['r'][(ki, ti)] is not None and m['r'][(ki, ti)] > 0.8


def test_matrix_none_below_min_sample():
    m = correlation_matrix([row(), row()], ['kills', 'td'], min_n=5)
    assert m['r'][(0, 1)] is None            # only 2 rows, need 5


def test_matrix_excludes_resubmit_and_unlisted():
    subs = [row(k=40) for _ in range(6)] + [row(feats="Resubmit", k=9999),
                                            row(feats="Unlisted", k=9999)]
    m = correlation_matrix(subs, ['kills', 'td'], min_n=3)
    # diagonal count for kills should be 6, not 8
    assert m['n'][(0, 0)] == 6


# ── group compare ──────────────────────────────────────────────────────────
def test_group_compare_averages_and_min_n():
    subs = [row(weapon="Messer", k=80, td=120), row(weapon="Greatsword", k=60, td=140),
            row(weapon="Sword", k=40, td=90), row(weapon="Mace", k=50, td=100),
            row(weapon="Dagger", k=30, td=70)]
    gc = group_compare(subs, weapon_grip, ['kills', 'td'], min_n=1)
    assert '1H' in gc and '2H' in gc
    assert gc['2H']['kills'] == 70.0        # (80+60)/2
    assert gc['1H']['_n'] == 3
    # raise the threshold and the small group drops
    gc2 = group_compare(subs, weapon_grip, ['kills'], min_n=3)
    assert '2H' not in gc2 and '1H' in gc2


# ── insights ───────────────────────────────────────────────────────────────
def test_find_insights_surfaces_strongest_correlation():
    # deaths and K/D pull hard apart; kills and takedowns move together.
    subs = []
    for i in range(14):
        subs.append(row(k=40 + i * 4, td=80 + i * 6, d=14 - i))
    ins = find_insights(subs, ['kills', 'td', 'deaths', 'kd'], min_n=5)
    assert ins and ins[0]['kind'] == 'strongest'
    # the strongest pair should be a genuine, high-|r| correlation
    assert abs(ins[0]['r']) >= 0.8
    kinds = {i['kind'] for i in ins}
    assert 'strongest' in kinds
