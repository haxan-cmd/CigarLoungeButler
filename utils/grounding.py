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

# Discord link/mention/emoji syntax carries 17-19 digit SNOWFLAKE ids (guild / channel /
# message / user / emoji). The linkifier adds these to a reply AFTER the model writes it,
# so they are never the model's fabricated stats — strip them (and jump-link URLs) before
# pulling numbers, or every hyperlinked reply reads as a fabrication.
_NOISE_RX = re.compile(
    r'https?://\S+'          # any URL (jump links embed channel/message ids)
    r'|<a?:\w+:\d+>'         # custom emoji  <:cigar:1444...>
    r'|<[@#][!&]?\d+>'       # user/channel/role mentions  <@123> <#123>
)
# No real server stat is anywhere near this; a Discord snowflake is ~1.5e18. A value this
# large is an id that slipped through, not a fabricated number. Backstop for a bare id.
_SNOWFLAKE_FLOOR = 1e12


def _strip_noise(text):
    return _NOISE_RX.sub(' ', text or '')


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
    ctx = {round(c) for c in extract_numbers(_strip_noise(context))}
    bad = set()
    for v in extract_numbers(_strip_noise(reply)):
        if v < threshold:
            continue
        # A Discord id that survived stripping (bare snowflake) — never a stat.
        if v >= _SNOWFLAKE_FLOOR:
            continue
        # Skip year-shaped numbers. Server stats (marks/TD/kills/scores) never land in
        # 1900-2100, but off-topic answers do ("rank the best CoD games" -> 2009, 2011),
        # and those years aren't fabricated stats. Prevents that false positive.
        if 1900 <= v <= 2100 and float(v).is_integer():
            continue
        if round(v) in ctx:
            continue
        bad.add(v)
    return sorted(bad)
