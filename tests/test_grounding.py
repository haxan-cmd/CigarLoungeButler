"""Anti-fabrication grounding check — pure, runs in `pytest -q`."""
from utils.grounding import extract_numbers, ungrounded_numbers


def test_extract_handles_commas_percent_and_decimals():
    got = extract_numbers("27,799 points, 63.0% lethality, 203 TD")
    assert 27799.0 in got and 63.0 in got and 203.0 in got


def test_reply_numbers_present_in_context_are_grounded():
    ctx = "375 marks, best game 203 TD / 115 K, lethality 63.0% on Messer"
    assert ungrounded_numbers("You have 375 marks and a 203 TD best.", ctx) == []


def test_fabricated_number_is_flagged():
    ctx = "375 marks, 203 TD best"
    # 999 appears nowhere in context -> fabrication
    assert ungrounded_numbers("An imperious 999 takedown effort.", ctx) == [999.0]


def test_small_numbers_are_ignored():
    # ranks / counts / 'one or two' must not trip it, even absent from context
    assert ungrounded_numbers("You're #1, top 3, no contest.", "no numbers here") == []


def test_display_rounding_is_tolerated():
    # context carries the unrounded 47.6; reply shows 48% -> grounded, not flagged
    assert ungrounded_numbers("lounge average is 48%.", "avg_lethality 47.6") == []


def test_multiple_fabrications_sorted_and_deduped():
    assert ungrounded_numbers("500 and 500 and 800", "nothing") == [500.0, 800.0]


def test_years_are_not_flagged():
    # INCIDENT: "rank the best CoD games" answered with years 2009/2011/2023 got
    # flagged as fabricated stats. Years (1900-2100) are general knowledge, not stats.
    assert ungrounded_numbers("Modern Warfare 2009, MW3 2011, and the 2023 one", "") == []
    # but a real out-of-range fabricated stat still flags
    assert ungrounded_numbers("a 2400-mark career", "") == [2400.0]
