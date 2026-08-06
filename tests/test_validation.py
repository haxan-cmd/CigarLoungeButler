"""Tests for utils.validation — impossible-data guard.

Rejects genuinely contradictory (map, faction) pairs; passes anything merely
incomplete. Uses the real config.MAP_FACTIONS so the tests track the map pool.
"""
import config
from utils.validation import (impossible_submission_reason, below_takedown_minimum,
                              scoreboard_looks_incomplete, kofi_verification_result,
                              clean_donation_amount)


def test_kofi_verification_fails_closed_when_unconfigured():
    # No token set on our side -> refuse, so a public /kofi URL can't inject spoofs.
    assert kofi_verification_result("", "anything") == 'reject_unconfigured'
    assert kofi_verification_result(None, "anything") == 'reject_unconfigured'


def test_kofi_verification_matches_token():
    assert kofi_verification_result("secret", "secret") == 'ok'
    assert kofi_verification_result("secret", "nope") == 'reject_bad_token'
    assert kofi_verification_result("secret", None) == 'reject_bad_token'
    assert kofi_verification_result("secret", "") == 'reject_bad_token'


def test_clean_donation_amount():
    assert clean_donation_amount("5.00") == 5.0
    assert clean_donation_amount(10) == 10.0
    assert clean_donation_amount(-3) == 0.0        # a spoof can't drive the total negative
    assert clean_donation_amount(None) == 0.0
    assert clean_donation_amount("garbage") == 0.0


def test_scoreboard_looks_incomplete():
    # Both faction totals read -> complete, no nudge.
    assert scoreboard_looks_incomplete(531, 678) is False
    # Cropped top: one or both totals missing -> incomplete.
    assert scoreboard_looks_incomplete(None, None) is True
    assert scoreboard_looks_incomplete(531, None) is True
    assert scoreboard_looks_incomplete(None, 678) is True
    # A 0 total is a real reading (shutout), not missing.
    assert scoreboard_looks_incomplete(0, 0) is False


def test_below_takedown_minimum():
    assert below_takedown_minimum(80, 40, 100) is True      # under the bar -> reject
    assert below_takedown_minimum(100, 40, 100) is False    # exactly the bar -> ok
    assert below_takedown_minimum(150, 40, 100) is False    # over the bar -> ok
    # Pacifist runs (0 kills, <=10 TD) are exempt even though they're under the bar
    assert below_takedown_minimum(8, 0, 100) is False
    assert below_takedown_minimum(50, 0, 100) is True       # 0 kills but 50 TD is NOT pacifist
    assert below_takedown_minimum(80, 40, 0) is False       # gate disabled
    assert below_takedown_minimum("x", 40, 100) is False    # unreadable -> pass

MF = config.MAP_FACTIONS


def test_impossible_faction_is_rejected():
    r = impossible_submission_reason("Askandir", "Agatha", MF)
    assert r and "Agatha" in r and "Askandir" in r
    # names the actual teams so the submitter knows what to fix
    assert "Mason" in r and "Tenosia" in r


def test_valid_faction_passes():
    assert impossible_submission_reason("Askandir", "Mason", MF) is None
    assert impossible_submission_reason("Askandir", "Tenosia", MF) is None
    assert impossible_submission_reason("Coxwell", "Agatha", MF) is None


def test_blank_faction_is_incomplete_not_impossible():
    # one side of the scoreboard only -> faction unknown -> must pass
    assert impossible_submission_reason("Askandir", "", MF) is None
    assert impossible_submission_reason("Askandir", None, MF) is None


def test_blank_or_unknown_map_passes():
    assert impossible_submission_reason("", "Agatha", MF) is None
    assert impossible_submission_reason(None, "Agatha", MF) is None
    assert impossible_submission_reason("Nonexistent Keep", "Agatha", MF) is None


def test_every_map_accepts_both_its_own_factions():
    for mp, factions in MF.items():
        for f in factions:
            assert impossible_submission_reason(mp, f, MF) is None, f"{mp}/{f} wrongly rejected"


def test_tenosia_only_maps_reject_agatha_where_applicable():
    # Askandir and Baudwyn are Mason/Tenosia -> Agatha impossible there
    for mp in ("Askandir", "Baudwyn"):
        assert impossible_submission_reason(mp, "Agatha", MF) is not None
