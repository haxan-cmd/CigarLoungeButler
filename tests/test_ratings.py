"""Tests for utils.ratings.dominance — the harmonic-mean two-way impact score."""
from utils.ratings import dominance


def test_balanced_equals_the_value():
    # When both are equal, the harmonic mean equals that value.
    assert dominance(20, 20) == 20
    assert dominance(12.5, 12.5) == 12.5


def test_lopsided_is_pulled_toward_the_smaller():
    # 30 & 10: plain average is 20, HM is 15 (dragged to the weaker axis).
    assert abs(dominance(30, 10) - 15.0) < 1e-9
    # always <= the arithmetic mean, and <= the larger of the two.
    assert dominance(30, 10) < 20 < 30


def test_min_maxing_one_axis_to_zero_scores_zero():
    assert dominance(40, 0) == 0.0
    assert dominance(0, 40) == 0.0


def test_maxing_both_beats_min_maxing_one():
    # A player high in both out-dominates one who maxes a single axis.
    both_high = dominance(18, 16)
    min_maxed = dominance(35, 3)
    assert both_high > min_maxed


def test_garbage_and_negative_inputs_are_zero():
    assert dominance(None, 20) == 0.0
    assert dominance("x", 20) == 0.0
    assert dominance(-5, 20) == 0.0
