"""Caption parsing: whole-word matching must not mis-detect from names/chatter,
but must still resolve real weapon/class hints (incl. parent+weapon -> subclass)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.parsing import parse_submission_text as _p


# Chatter / names that must NOT trigger a weapon or class detection.
NO_MATCH = [
    "axel", "he mauled us", "knightly duel", "archery is fun",
    "gg speared", "daggered him", "caravan", "that was close", "nice game",
]

# Real hints that must resolve. (weapon, subclass) — None means "don't care".
MATCH = [
    ("messer knight",             "Messer",   "Crusader"),   # parent+weapon -> unique subclass
    ("war axe knight",            "War Axe",  "Officer"),
    ("dane axe raider",           "Dane Axe", "Raider"),
    ("resubmit poleman halberd",  "Halberd",  "Poleman"),    # resubmit word ignored
    ("mace",                      "Mace",     None),
    ("just used the greatsword",  "Greatsword", None),
]


def test_no_false_positives():
    for text in NO_MATCH:
        w, s = _p(text)
        assert w is None and s is None, f"{text!r} falsely matched weapon={w} class={s}"


def test_real_hints_resolve():
    for text, exp_w, exp_s in MATCH:
        w, s = _p(text)
        assert w == exp_w, f"{text!r}: expected weapon {exp_w}, got {w}"
        if exp_s is not None:
            assert s == exp_s, f"{text!r}: expected class {exp_s}, got {s}"


def test_empty_and_none_safe():
    assert _p("") == (None, None)
    assert _p(None) == (None, None)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all parsing tests passed")
