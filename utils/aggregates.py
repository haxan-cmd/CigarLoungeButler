"""Pure server-wide aggregate engine for the Butler.

Whenever the Butler is asked a "who has the most / highest / best X" question that
ranks players by some computed metric, the answer lives here — instead of another
hand-written injection block in personality.py. TWO ideas:

1. ONE canonical-identity resolver (`Identity`), so a player's multiple IGNs
   (e.g. "Llama" / "Arbiter of Lethality") collapse to a single person, displayed
   under the registry name. Every metric shares it, so the double-count class of bug
   cannot come back per-metric.
2. A REGISTRY of ranking specs (`SPECS`). Each `AggSpec` maps a family of natural
   phrasings (keywords) to a metric computed over a row source (submissions, players,
   or leaderboard boards), grouped by canonical player, ranked, and formatted into a
   context line. Adding a new answerable ranking = one AggSpec entry. Its keywords are
   also exported via `gate_keywords()`, so the Butler's data-question gate unlocks
   automatically — a metric can never be answerable-but-gated (the failure mode that
   made "who has the most 100 kill games" deflect).

Pure: takes already-fetched rows (the legacy list-of-strings Sheets shape) plus a
name->id map and the display-name override table. No I/O, no cog imports. Unit-tested
in tests/test_aggregates.py. The async caller (personality._build_player_stats_ctx)
fetches the rows and calls `context_block` once.

Row shapes (see CLAUDE.md):
  submissions: 0 submitted_at 1 name 2 did 3 weapon 4 subclass 5 map 6 faction
               7 takedowns 8 kills 9 deaths 10 vip 11 feats ... 24 score
  players:     0 did 1 name 2 thread 3 total_marks 4 submission_count
               ... 8 kills_100 override 9 takedowns_200 override 10 triple override
  leaderboard: 0 board_name 1 name 2 did 3 score
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from utils.feats import is_pacifist

# submissions column indices
_S_NAME, _S_DID, _S_WEAPON, _S_MAP = 1, 2, 3, 5
_S_TD, _S_KILLS, _S_DEATHS, _S_VIP, _S_FEATS, _S_SCORE = 7, 8, 9, 10, 11, 24


def _s(x):
    return str(x).strip() if x is not None else ''


def _num(x):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return None


def _excluded(row):
    """A resubmitted or mod-unlisted run: excluded from records/boards, so also
    from these aggregates (matches how the rest of the bot treats them)."""
    feats = _s(row[_S_FEATS]).lower() if len(row) > _S_FEATS else ''
    return 'unlisted' in feats or 'resubmit' in feats


class Identity:
    """Canonical player identity. `resolve(name, did)` -> (key, display):
      key     — discord id when known (row's own id, else the name->id map),
                else the lowercased name (an unregistered player stays distinct).
      display — the LEADERBOARD_NAME_OVERRIDES forced name, else the registry
                player_name, else the raw name."""

    def __init__(self, players_rows=None, name_to_id=None, overrides=None):
        self.name_to_id = {}
        for k, v in (name_to_id or {}).items():
            if _s(k):
                self.name_to_id[_s(k).lower()] = _s(v)
        self.overrides = {_s(k): v for k, v in (overrides or {}).items() if _s(k)}
        self.did2name = {}
        for p in players_rows or []:
            did = _s(p[0]) if len(p) > 0 else ''
            if did:
                self.did2name[did] = _s(p[1]) if len(p) > 1 else ''

    def resolve(self, name, did=''):
        name = _s(name)
        did = _s(did)
        if not did:
            did = self.name_to_id.get(name.lower(), '')
        key = did or name.lower()
        display = self.overrides.get(did) or self.did2name.get(did) or name
        return key, display


# ── metric contributors ──────────────────────────────────────────────────────
# Each returns (identity_key, display, value) for one row, or None to skip it.
# `value` meaning depends on the spec's reduce: count -> ignored (each row = 1),
# sum/max/avg -> a number, ratio -> (numerator, denominator), distinct -> hashable.

def _sub_id(row, identity):
    return identity.resolve(
        _s(row[_S_NAME]) if len(row) > _S_NAME else '',
        _s(row[_S_DID]) if len(row) > _S_DID else '')


def _c_games(row, identity, param):
    if len(row) <= _S_NAME or not _s(row[_S_NAME]) or _excluded(row):
        return None
    k, d = _sub_id(row, identity)
    return (k, d, 1)


def _c_vip(row, identity, param):
    if len(row) <= _S_VIP or _excluded(row):
        return None
    if _s(row[_S_VIP]).lower() not in ('yes', 'y', 'true', '1'):
        return None
    k, d = _sub_id(row, identity)
    return (k, d, 1)


def _c_sum(idx):
    def f(row, identity, param):
        if len(row) <= idx or _excluded(row):
            return None
        v = _num(row[idx])
        if v is None:
            return None
        k, d = _sub_id(row, identity)
        return (k, d, v)
    return f


def _c_kd(row, identity, param):
    if len(row) <= _S_DEATHS or _excluded(row):
        return None
    kills, deaths = _num(row[_S_KILLS]), _num(row[_S_DEATHS])
    if kills is None or deaths is None:
        return None
    k, d = _sub_id(row, identity)
    return (k, d, (kills, deaths))


def _c_map(row, identity, param):
    if len(row) <= _S_MAP or _excluded(row) or not _s(row[_S_MAP]):
        return None
    k, d = _sub_id(row, identity)
    return (k, d, _s(row[_S_MAP]).lower())


def _c_weapon_usage(row, identity, param):
    if len(row) <= _S_WEAPON or _excluded(row) or not param:
        return None
    if _s(row[_S_WEAPON]).lower() != _s(param).lower():
        return None
    k, d = _sub_id(row, identity)
    return (k, d, 1)


def _c_pacifist(row, identity, param):
    # Pacifist runs STACK per game, but the Pacifist BOARD keeps one row per player
    # (personal-best by score) — so counting board rows gives everyone 1. Count the
    # qualifying submissions instead, via the shared predicate.
    if len(row) <= max(_S_KILLS, _S_TD) or _excluded(row):
        return None
    kills, td = _num(row[_S_KILLS]), _num(row[_S_TD])
    if kills is None or td is None or not is_pacifist(kills, td):
        return None
    k, d = _sub_id(row, identity)
    return (k, d, 1)


def _c_marks(row, identity, param):
    did = _s(row[0]) if row else ''
    if not did:
        return None
    v = _num(row[3]) if len(row) > 3 else None
    if v is None:
        return None
    k, d = identity.resolve(_s(row[1]) if len(row) > 1 else '', did)
    return (k, d, v)


def _c_board(board):
    def f(row, identity, param):
        if len(row) < 4 or _s(row[0]) != board or not _s(row[1]):
            return None
        k, d = identity.resolve(_s(row[1]), _s(row[2]) if len(row) > 2 else '')
        return (k, d, 1)
    return f


# ── spec + engine ────────────────────────────────────────────────────────────

@dataclass
class AggSpec:
    id: str
    keywords: tuple           # substring triggers (already lowercased)
    source: str               # 'submissions' | 'players' | 'board'
    label: str                # human header; may use {param} / {min_n}
    contribute: Callable      # row, identity, param -> (key, disp, value) | None
    reduce: str = 'count'     # count | sum | max | avg | ratio | distinct
    direction: str = 'desc'   # desc = biggest first
    min_n: int = 1            # min qualifying rows (avg/ratio) so 1-game flukes don't win
    unit: str = ''           # appended to each value, e.g. ' games'
    fmt: str = '{:.0f}'      # per-value number format
    parametric: bool = False # needs a weapon param (and its keywords stay OUT of the gate)
    override_idx: Optional[int] = None  # players[] index whose manual count wins (board specs)
    regexes: tuple = ()      # extra triggers needing word boundaries (e.g. r'\btuff\b' vs "stuff")


def _reduce(spec, vals):
    n = len(vals)
    if spec.reduce == 'count':
        return float(n)
    if spec.reduce == 'sum':
        return float(sum(vals))
    if spec.reduce == 'max':
        return float(max(vals))
    if spec.reduce == 'distinct':
        return float(len(set(vals)))
    if spec.reduce == 'avg':
        if n < spec.min_n:
            return None
        return sum(vals) / n
    if spec.reduce == 'ratio':
        num = sum(v[0] for v in vals)
        den = sum(v[1] for v in vals)
        if n < spec.min_n or den <= 0:
            return None
        return num / den
    return None


def rank(spec, rows, identity, param=None):
    """-> list of (display, value, sample_n), best first."""
    acc, disp = {}, {}
    for row in rows or []:
        try:
            c = spec.contribute(row, identity, param)
        except (ValueError, TypeError, IndexError):
            c = None
        if not c:
            continue
        key, d, val = c
        disp[key] = d
        acc.setdefault(key, []).append(val)
    out = []
    for key, vals in acc.items():
        v = _reduce(spec, vals)
        if v is None:
            continue
        out.append((disp[key], v, len(vals)))
    out.sort(key=lambda t: (t[1], t[2]), reverse=(spec.direction == 'desc'))
    return out


def _apply_overrides(spec, ranked, data, identity):
    """Manual feat-count overrides on the players row win over the auto board count,
    matching the registry card. Only for board specs that declare an override_idx."""
    if spec.source != 'board' or spec.override_idx is None:
        return ranked
    ov = {}
    for p in data.get('players') or []:
        did = _s(p[0]) if p else ''
        if did and len(p) > spec.override_idx and p[spec.override_idx] is not None:
            n = _num(p[spec.override_idx])
            if n is None:
                continue
            _, dname = identity.resolve(_s(p[1]) if len(p) > 1 else '', did)
            ov[dname] = n
    if not ov:
        return ranked
    merged = {d: v for d, v, _ in ranked}
    merged.update({d: float(v) for d, v in ov.items()})
    return sorted(((d, v, 0) for d, v in merged.items()), key=lambda t: t[1], reverse=True)


def compute(spec, data, identity, param=None):
    src = {'submissions': 'submissions', 'players': 'players', 'board': 'boards'}[spec.source]
    ranked = rank(spec, data.get(src) or [], identity, param)
    return _apply_overrides(spec, ranked, data, identity)


def _fmt_line(spec, ranked, param=None, top=8):
    if not ranked:
        return ''
    label = spec.label.format(param=(param or ''), min_n=spec.min_n)
    parts = [f"{d} ({spec.fmt.format(v)}{spec.unit})" for d, v, _ in ranked[:top]]
    return f"{label}: " + ", ".join(parts)


# ── the registry ─────────────────────────────────────────────────────────────
# Order matters only for output ordering when multiple specs fire. Keywords must be
# specific enough not to fire on banter (parametric keywords are kept out of the gate
# because a weapon mention already trips it independently).

SPECS = [
    AggSpec('most_games',
            ('most submissions', 'most games logged', 'most runs logged', 'logged the most',
             'most games all time', 'most logged games', 'most active all-time', 'most active all time'),
            'submissions', 'Most games logged (all-time)', _c_games, reduce='count', unit=' games'),
    AggSpec('most_marks',
            ('most marks', 'highest marks', 'most career marks', 'marks leader', 'most total marks'),
            'players', 'Most career marks', _c_marks, reduce='sum', unit=' marks'),
    AggSpec('most_vip',
            ('most vip', 'vip games', 'vip runs', 'most vips', 'most vip games'),
            'submissions', 'Most VIP games', _c_vip, reduce='count', unit=' VIP games'),
    AggSpec('most_deaths',
            ('most deaths', 'dies the most', 'die the most', 'most times died', 'most total deaths'),
            'submissions', 'Most total deaths', _c_sum(_S_DEATHS), reduce='sum', unit=' deaths'),
    AggSpec('career_kills',
            ('most total kills', 'most career kills', 'most kills all time', 'most kills all-time',
             'most lifetime kills', 'most kills overall'),
            'submissions', 'Most career kills', _c_sum(_S_KILLS), reduce='sum', unit=' kills'),
    AggSpec('career_td',
            ('most total takedowns', 'most career takedowns', 'most takedowns all time',
             'most takedowns all-time', 'most lifetime takedowns'),
            'submissions', 'Most career takedowns', _c_sum(_S_TD), reduce='sum', unit=' TDs'),
    AggSpec('best_kd',
            ('best kd', 'best k/d', 'highest kd', 'best kill death', 'best kill/death',
             'highest kill death', 'highest kill/death', 'best ratio'),
            'submissions', 'Best K/D ratio (min {min_n} games)', _c_kd,
            reduce='ratio', min_n=5, fmt='{:.2f}'),
    AggSpec('avg_score',
            ('highest average score', 'best average score', 'highest avg score', 'best avg score',
             'highest scoring player'),
            'submissions', 'Highest average score (min {min_n} games)', _c_sum(_S_SCORE),
            reduce='avg', min_n=5),
    AggSpec('avg_td',
            ('highest average takedowns', 'best average takedowns', 'highest avg td',
             'best avg td', 'highest average td'),
            'submissions', 'Highest average takedowns (min {min_n} games)', _c_sum(_S_TD),
            reduce='avg', min_n=5, fmt='{:.1f}'),
    AggSpec('map_variety',
            ('most maps played', 'most different maps', 'map variety', 'most map variety',
             'widest map', 'most varied maps', 'most maps'),
            'submissions', 'Most maps played (distinct)', _c_map, reduce='distinct', unit=' maps'),
    # Parametric: "who plays <weapon> the most". Keywords stay OUT of the gate (a weapon
    # mention trips the gate on its own); needs param_weapon to fire.
    AggSpec('weapon_usage',
            ('most', 'plays', 'play the most', 'uses', 'use the most', 'used', 'played',
             'favourite', 'favorite', 'main'),
            'submissions', '{param} — most games logged', _c_weapon_usage,
            reduce='count', unit=' games', parametric=True),
    # Stacking feat boards (one row per qualifying run) — supersedes the old ad-hoc block.
    AggSpec('feat_100k', ('100 kill', '100-kill', 'hundred kill'),
            'board', 'Most 100 Kills games', _c_board('100 Kills'),
            reduce='count', unit=' games', override_idx=8),
    AggSpec('feat_200td', ('200 takedown', '200-takedown', '200 td'),
            'board', 'Most 200 Takedowns games', _c_board('200 Takedowns'),
            reduce='count', unit=' games', override_idx=9),
    AggSpec('feat_flawless', ('flawless',),
            'board', 'Most Flawless games', _c_board('Flawless'), reduce='count', unit=' games'),
    AggSpec('feat_triple', ('triple',),
            'board', 'Most Triple games', _c_board('Triple'), reduce='count', unit=' games'),
    # Pacifist STACKS per game but its board keeps one row per player, so count runs
    # from submissions (via the shared is_pacifist predicate), not board rows.
    AggSpec('most_pacifist', ('pacifist',),
            'submissions', 'Most Pacifist runs', _c_pacifist, reduce='count', unit=' runs'),
    AggSpec('feat_tuff', (), 'board', 'Most TUFF games', _c_board('TUFF'),
            reduce='count', unit=' games', regexes=(r'\btuff\b',)),
]


def gate_keywords():
    """Every non-parametric keyword, for the Butler's data-question gate. Parametric
    specs are excluded — a weapon mention already trips the gate independently, and
    their keywords ('most', 'plays', ...) are too generic to gate on."""
    ks = set()
    for spec in SPECS:
        if spec.parametric:
            continue
        ks.update(spec.keywords)
    return ks


def match_specs(question, param_weapon=None):
    q = (question or '').lower()
    hits = []
    for spec in SPECS:
        if not (any(k in q for k in spec.keywords)
                or any(re.search(rx, q) for rx in spec.regexes)):
            continue
        if spec.parametric:
            if not param_weapon:
                continue
            hits.append((spec, param_weapon))
        else:
            hits.append((spec, None))
    return hits


def context_block(question, data, name_to_id=None, overrides=None, param_weapon=None, top=8):
    """The single entry point. `data` = {'submissions': [...], 'boards': [...],
    'players': [...]}. Returns a '\\n\\n'-joined block of ranking lines for every spec
    the question triggers, or '' when none fire."""
    identity = Identity(data.get('players'), name_to_id, overrides)
    lines = []
    for spec, param in match_specs(question, param_weapon):
        line = _fmt_line(spec, compute(spec, data, identity, param), param, top)
        if line:
            lines.append(line)
    return "\n\n".join(lines)
