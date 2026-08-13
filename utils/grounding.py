"""Anti-fabrication grounding check (pure, unit-tested).

The Butler must only cite SERVER/player numbers that appear in the context it was
handed. This extracts the numbers from a reply and reports any MATERIAL ones (above
a small-talk threshold) that aren't grounded in the context, so a suspected
fabrication can be logged and fed into the eval loop.

Used LOG-ONLY — it never rewrites a reply. Rounding-tolerant so a displayed "48%"
counts as grounded against a context "47.6"; the small-number threshold skips ranks
and counts ("#1", "top 3", "one or two sentences") where a literal match is noise.
"""
import re

# A number token: 1,234 / 27,799 / 63.0 / 200. Guard against matching inside words
# or version-like dotted runs by requiring a non-word, non-dot char (or start) before.
_NUM_RX = re.compile(r'(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)')


def extract_numbers(text):
    """Set of numeric VALUES mentioned in text (commas stripped), as floats."""
    out = set()
    for m in _NUM_RX.finditer(text or ''):
        try:
            out.add(float(m.group(1).replace(',', '')))
        except ValueError:
            pass
    return out


def ungrounded_numbers(reply, context, threshold=13):
    """Material numbers (>= threshold) in `reply` not grounded in `context`.

    Grounded = the rounded value matches some rounded context number, so display
    rounding doesn't cause false positives. Returns a sorted list of offenders;
    empty means the reply's stats are all accounted for.
    """
    ctx = {round(c) for c in extract_numbers(context)}
    bad = set()
    for v in extract_numbers(reply):
        if v < threshold:
            continue
        if round(v) in ctx:
            continue
        bad.add(v)
    return sorted(bad)
