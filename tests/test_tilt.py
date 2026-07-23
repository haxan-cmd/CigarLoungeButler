"""Orientation-adjusted lobby-tilt difficulty ladder.

Guards the single source of truth in utils/tilt.py: role detection from the
map/faction table, the baseline subtraction, band boundaries, and the tag ->
marks mapping the payout depends on.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils import tilt


def test_orientation_from_map_and_faction():
    # Falmire: Agatha attacks, Mason defends (short key matches full map name).
    assert tilt.orientation("Escape from Falmire", "Agatha") == "Attack"
    assert tilt.orientation("Escape from Falmire", "Mason") == "Defense"
    # Darkforest: Mason attacks, Agatha defends.
    assert tilt.orientation("The Battle of Darkforest", "Mason") == "Attack"
    assert tilt.orientation("The Battle of Darkforest", "Agatha") == "Defense"
    # Unknown map or missing faction -> None (falls back to raw tilt).
    assert tilt.orientation("Some Unlisted Map", "Mason") is None
    assert tilt.orientation(None, "Mason") is None
    assert tilt.orientation("Escape from Falmire", None) is None


def test_baseline_by_role():
    assert tilt.baseline("Attack") == config.TILT_BASELINE_ATTACK
    assert tilt.baseline("Defense") == config.TILT_BASELINE_DEFENSE
    assert tilt.baseline(None) == 0


def test_raw_tilt():
    assert tilt.raw_tilt(500, 400) == 25          # winner +25%
    assert tilt.raw_tilt(400, 500) == -25         # loser -25%
    assert tilt.raw_tilt(600, 600) == 0
    assert tilt.raw_tilt(0, 400) is None          # bad totals
    assert tilt.raw_tilt(500, None) is None


def test_adjusted_centres_on_role():
    # A defender at raw +8% sits exactly on the defence baseline -> adjusted 0.
    assert tilt.adjusted(8, "Escape from Falmire", "Mason") == 0
    # An attacker at raw +23% sits on the attack baseline -> adjusted 0.
    assert tilt.adjusted(23, "Escape from Falmire", "Agatha") == 0
    # Defender rolled at raw -30% -> adjusted -38% (harder than raw implies).
    assert tilt.adjusted(-30, "Escape from Falmire", "Mason") == -38
    # Unknown orientation: no adjustment.
    assert tilt.adjusted(-30, "Mystery Map", "Mason") == -30


def test_band_boundaries_and_tags():
    # Deep hard tail.
    assert tilt.band(-60)["name"] == "Brutal"
    assert tilt.band(-60)["marks"] == 3
    assert tilt.band(-60)["tag"] == "Brutal"
    # Outmatched: -50..-30.
    assert tilt.band(-40)["name"] == "Outmatched"
    assert tilt.band(-40)["marks"] == 2
    # Slightly Uphill: -30..-15, +1 mark.
    assert tilt.band(-20)["name"] == "Slightly Uphill"
    assert tilt.band(-20)["marks"] == 1
    assert tilt.band(-20)["tag"] == "Uphill"
    # Even core pays nothing.
    assert tilt.band(0)["name"] == "Even"
    assert tilt.band(0)["marks"] == 0
    assert tilt.band(0)["tag"] is None
    # Easy tail.
    assert tilt.band(40)["name"] == "Favoured"
    assert tilt.band(80)["name"] == "Training Grounds"
    assert tilt.band(80)["marks"] == 0


def test_band_edges_are_inclusive_low():
    # Exactly on an edge lands in the higher (easier) band.
    assert tilt.band(-50)["name"] == "Outmatched"   # -50 is Outmatched's low edge
    assert tilt.band(-30)["name"] == "Slightly Uphill"
    assert tilt.band(-15)["name"] == "Even"
    assert tilt.band(15)["name"] == "Slightly Favoured"
    assert tilt.band(50)["name"] == "Training Grounds"


def test_tag_marks_map():
    tm = tilt.tag_marks()
    assert tm == {"Uphill": 1, "Outmatched": 2, "Brutal": 3}


def test_card_badges_are_outmatched_and_brutal():
    badges = tilt.card_badges()
    tags = [t for t, _e in badges]
    assert tags == ["Outmatched", "Brutal"]
    # Uphill pays a mark but must NOT get a card badge.
    assert "Uphill" not in tags
