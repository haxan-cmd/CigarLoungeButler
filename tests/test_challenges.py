"""Bounty special-challenge parsing.

The challenge is free text authored in /bounty_create and matched by regex, so a
reworded challenge can silently never qualify. These lock the wording contract.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.challenges import (describe, parse_special, parse_ts, run_qualifies,
                              special_weapon_ok)


FIELD_TEST = {
    'special_challenge': ('100 Takedowns and fewer than 10 deaths in a run, '
                          'complete 3 times using any bounty weapon'),
    'weapons': {w: {'current': 0, 'total': 3} for w in
                ['Falchion', 'Axe', 'Pick Axe', 'Goedendag',
                 'War Club', 'Maul', 'Polehammer', 'Two-Handed Hammer']},
}

# The pre-existing style: a weapon named in the text, no death cap, single run.
LEGACY = {
    'special_challenge': '100 Takedowns on Cat Claws (Katars)',
    'weapons': {'Katars': {'current': 0, 'total': 3}},
}


def test_parses_all_four_fields():
    s = parse_special(FIELD_TEST)
    assert s['min_td'] == 100
    assert s['max_deaths'] == 10
    assert s['need'] == 3
    assert s['any_weapon'] is True


def test_legacy_challenge_unchanged():
    s = parse_special(LEGACY)
    assert s['min_td'] == 100
    assert s['max_deaths'] is None
    assert s['need'] == 1
    assert s['any_weapon'] is False


def test_no_challenge_is_none():
    assert parse_special({'special_challenge': ''}) is None
    assert parse_special({}) is None


def test_death_cap_phrasings():
    for phrase in ('fewer than 8 deaths', 'less than 8 deaths', 'under 8 deaths',
                   'sub 8 deaths', 'below 8 deaths', '<8 deaths'):
        s = parse_special({'special_challenge': f'100 takedowns, {phrase}'})
        assert s['max_deaths'] == 8, phrase


def test_repeat_count_phrasings():
    assert parse_special({'special_challenge': 'do it 4 times'})['need'] == 4
    assert parse_special({'special_challenge': 'complete 4 times'})['need'] == 4
    assert parse_special({'special_challenge': 'maul run x4'})['need'] == 4
    # Absent means once.
    assert parse_special({'special_challenge': '150 takedowns'})['need'] == 1


def test_any_weapon_matches_only_bounty_roster():
    s = parse_special(FIELD_TEST)
    assert special_weapon_ok(FIELD_TEST, s, 'Maul') is True
    assert special_weapon_ok(FIELD_TEST, s, 'maul') is True          # case-insensitive
    assert special_weapon_ok(FIELD_TEST, s, 'Two-Handed Hammer') is True
    assert special_weapon_ok(FIELD_TEST, s, 'Longsword') is False    # not on the bounty
    assert special_weapon_ok(FIELD_TEST, s, '') is False


def test_named_weapon_matches_text_only():
    s = parse_special(LEGACY)
    assert special_weapon_ok(LEGACY, s, 'Katars') is True
    assert special_weapon_ok(LEGACY, s, 'Maul') is False


def test_challenge_naming_no_real_weapon_never_qualifies():
    """The silent-failure case: reworded challenge, no weapon named, no 'any
    bounty weapon' phrase. Nothing can satisfy it."""
    b = {'special_challenge': '100 takedowns with a big stick',
         'weapons': {'Maul': {'total': 3}}}
    s = parse_special(b)
    assert s['any_weapon'] is False
    assert special_weapon_ok(b, s, 'Maul') is False


def test_run_qualifies_boundaries():
    s = parse_special(FIELD_TEST)
    ok = lambda td, dk, feats='': run_qualifies(FIELD_TEST, s, 'Maul', td, dk, feats)
    assert ok(100, 9) is True        # exactly at the TD floor, one under the cap
    assert ok(150, 0) is True
    assert ok(99, 0) is False        # below TD floor
    assert ok(100, 10) is False      # cap is strict: 10 deaths fails
    assert ok(100, 9, 'Resubmit') is False
    assert ok(100, 9, 'Triple, Resubmit') is False
    assert ok(100, 9, 'Triple') is True
    assert run_qualifies(FIELD_TEST, s, 'Longsword', 200, 0) is False


def test_run_qualifies_handles_dirty_values():
    s = parse_special(FIELD_TEST)
    assert run_qualifies(FIELD_TEST, s, 'Maul', '120', '4') is True   # strings
    assert run_qualifies(FIELD_TEST, s, 'Maul', None, None) is False
    assert run_qualifies(FIELD_TEST, s, 'Maul', 'abc', '4') is False


def test_describe_is_compact_and_derived():
    """The card label comes from the parse, not the prose, so it can't drift
    from what is actually enforced."""
    assert describe(parse_special(FIELD_TEST)) == '100+ TD, <10 deaths x3'
    assert describe(parse_special(LEGACY)) == '100+ TD'
    assert describe(parse_special({'special_challenge': '150 takedowns twice, under 5 deaths'})) \
        == '150+ TD, <5 deaths'
    assert describe(None) == ''


def test_describe_fits_the_card_column():
    """Authored text is a sentence; the label has to stay near the 22-char
    column the weapon rows use."""
    assert len(describe(parse_special(FIELD_TEST))) <= 24
    assert len(FIELD_TEST['special_challenge']) > 60  # the thing we're replacing


def test_parse_ts_formats():
    assert parse_ts('2026-07-20 13:04 UTC').year == 2026
    assert parse_ts('2026-07-20 14:22:31').hour == 14
    assert parse_ts('2026-07-20').day == 20
    assert parse_ts('') is None
    assert parse_ts('not a date') is None
