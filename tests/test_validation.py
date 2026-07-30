"""Tests for utils.validation — impossible-data guard.

Rejects genuinely contradictory (map, faction) pairs; passes anything merely
incomplete. Uses the real config.MAP_FACTIONS so the tests track the map pool.
"""
import config
from utils.validation import impossible_submission_reason

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
