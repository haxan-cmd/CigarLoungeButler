"""Pure statistics engine for the lounge's exploration features.

One source of truth for: per-run stat extraction, the Pearson correlation
matrix (stats × stats), grouped comparisons (1H vs 2H, class, faction, weapon),
and an automatic "what's interesting" finder. Every surface — the button-driven
`/correlate` panel, the weekly auto-insight post, and any future web Stats Lab —
reads from HERE, so a number can never disagree between them.

Operates on submission rows in the Sheets-era shape (lists of strings) returned
by db.get_all_submissions(). NO Discord/DB imports; unit-tested in
tests/test_stats_engine.py.

Row indices (see CLAUDE.md submissions map):
  1 name · 2 discord_id · 3 weapon · 4 subclass · 5 map · 6 faction ·
  7 takedowns · 8 kills · 9 deaths · 11 feats · 20 team_kill_share ·
  21 team_td_share · 24 score · 25 team_total_kills · 26 enemy_total_kills
"""
import config


def _i(s, idx):
    try:
        return int(s[idx]) if len(s) > idx and s[idx] not in (None, '') else None
    except (ValueError, TypeError):
        return None


def _fl(s, idx):
    try:
        return float(s[idx]) if len(s) > idx and s[idx] not in (None, '') else None
    except (ValueError, TypeError):
        return None


def is_excluded(row):
    """Resubmit (old run re-uploaded) and Unlisted (mod-hidden) never count."""
    f = (row[11] or '') if len(row) > 11 else ''
    return 'Resubmit' in f or 'Unlisted' in f


# ── per-run stat extractors ──────────────────────────────────────────────
def _kills(s):
    return _i(s, 8)


def _td(s):
    return _i(s, 7)


def _deaths(s):
    return _i(s, 9)


def _score(s):
    try:
        return int(str(s[24]).replace(',', '').strip()) if len(s) > 24 and s[24] else None
    except (ValueError, TypeError):
        return None


def _kshare(s):
    v = _fl(s, 20)
    return v if (v is not None and 0 < v <= 100) else None


def _tdshare(s):
    v = _fl(s, 21)
    return v if (v is not None and 0 < v <= 100) else None


def _leth(s):
    td, k = _i(s, 7), _i(s, 8)
    return (k / td) if (td and k) else None


def _warl(s):
    # Use the VALIDATED kill share (0<..<=100). A cropped card makes vision misread
    # the team total tiny, so the stored share can exceed 100% and warlord explodes
    # (a real 368% outlier squished the Lab graph). Reject those instead of plotting.
    td, k, t = _i(s, 7), _i(s, 8), _kshare(s)
    return (td * t / k) if (td and k and t) else None


def _dom(s):
    # Dominance = harmonic mean of Kill Share and Warlord (both %). Rewards being
    # high in BOTH; collapses toward the weaker axis so it can't be gamed by
    # specialising. Same definition as the Most Dominant title.
    ks, wl = _kshare(s), _warl(s)
    if not ks or not wl or ks <= 0 or wl <= 0:
        return None
    return 2 * ks * wl / (ks + wl)


def _kd(s):
    k, d = _i(s, 8), _i(s, 9)
    if k is None:
        return None
    return float(k) if not d else k / d          # 0 deaths -> K/D = kills


def _agg(s):
    k, d = _i(s, 8), _i(s, 9)
    return (k + d) if (k is not None and d is not None) else None


def _lobbyk(s):
    a, b = _i(s, 25), _i(s, 26)
    return (a + b) if (a is not None and b is not None) else None


def _gap(s):
    a, b = _i(s, 25), _i(s, 26)
    return (a - b) if (a is not None and b is not None) else None


def _lead2(s):
    # Takedowns minus the best TEAMMATE's takedowns (col 22 = second_place_td, the
    # value TUFF uses). Positive = you topped your side's scoreboard; the margin by
    # which you out-took-down the next-best player on your team. Can be negative.
    td, tp = _i(s, 7), _i(s, 22)
    return (td - tp) if (td is not None and tp is not None) else None


def _marks(s):
    # Weapon marks this run earned, mirroring the registry rules (SUBMISSIONS only —
    # excludes legacy/imported marks the Lab can't see): 0 for a pacifist or a
    # Hybrid/blank-weapon run; else 1 base + feat bonuses (200 Takedowns, 100 Kills,
    # Triple, High Score, Score) + one difficulty valor tag (Uphill 1 / Outmatched 2 /
    # Brutal 3). Sum it per player (Rankings 'Total') for a marks count.
    td, k = _i(s, 7), _i(s, 8)
    if td is None or k is None:
        return None
    if k == 0 and td <= 10:
        return 0
    w = (s[3] or '').strip() if len(s) > 3 else ''
    if not w or w in ('Other', 'Multiple Weapons', 'Hybrid'):
        return 0
    _fs = (s[11] or '') if len(s) > 11 else ''
    feats = [x.strip() for x in _fs.split(',')] if _fs and _fs != 'None' else []
    m = 1
    for _feat in ('200 Takedowns', '100 Kills', 'Triple', 'High Score', 'Score'):
        if _feat in feats:
            m += 1
    try:
        from utils.tilt import tag_marks as _tm
        for _tag, _mv in sorted(_tm().items(), key=lambda kv: -kv[1]):
            if _tag in feats:
                m += _mv
                break
    except Exception:
        pass
    return m


# key -> (extractor, human label). Shared by scatter, matrix, and compare.
STAT_EXTRACTORS = {
    'kills':          (_kills,   'Kills'),
    'td':             (_td,      'Takedowns'),
    'deaths':         (_deaths,  'Deaths'),
    'kd':             (_kd,      'K/D ratio'),
    'aggression':     (_agg,     'Aggression (K+D)'),
    'kill_share':     (_kshare,  'Kill share %'),
    'team_td_share':  (_tdshare, 'Team TD share %'),
    'warlord':        (_warl,    'Warlord %'),
    'dominance':      (_dom,     'Dominance'),
    'lethality':      (_leth,    'Lethality (K/TD)'),
    'score':          (_score,   'Score'),
    'lobby_kills':    (_lobbyk,  'Total lobby kills'),
    'tilt':           (_gap,     'Lobby kill gap'),
    'td_lead':        (_lead2,   'TD lead over teammate'),
    'marks':          (_marks,   'Marks earned'),
}

# A compact, readable default set for the matrix (7×7 stays legible).
DEFAULT_MATRIX_STATS = ['kills', 'td', 'deaths', 'kd', 'kill_share', 'warlord', 'tilt']


def stat_label(key):
    return STAT_EXTRACTORS[key][1] if key in STAT_EXTRACTORS else key


# ── categorisers ─────────────────────────────────────────────────────────
_GRIP = {}
for _w in getattr(config, 'WEAPONS_2H', []) or []:
    _GRIP[_w] = '2H'
for _w in getattr(config, 'WEAPONS_1H', []) or []:
    _GRIP[_w] = '1H'
_SUB2CLASS = {sub: cls for cls, subs in (getattr(config, 'REGISTRY_CLASS_MAP', {}) or {}).items()
              for sub in subs}


def weapon_grip(row):
    """'1H' / '2H' / None (ranged weapons are in neither list)."""
    return _GRIP.get((row[3] or '').strip() if len(row) > 3 else '')


def run_class(row):
    return _SUB2CLASS.get((row[4] or '').strip() if len(row) > 4 else '')


def run_faction(row):
    return ((row[6] or '').strip() or None) if len(row) > 6 else None


def run_weapon(row):
    return ((row[3] or '').strip() or None) if len(row) > 3 else None


GROUPERS = {
    'grip': weapon_grip, 'class': run_class,
    'faction': run_faction, 'weapon': run_weapon,
}


# ── correlation ──────────────────────────────────────────────────────────
def pearson(pairs):
    """Pearson r for [(x, y), ...], or None when <3 points or zero variance."""
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / ((sxx * syy) ** 0.5)


def correlation_matrix(rows, stat_keys=None, min_n=5):
    """{'stats': [keys], 'labels': [...], 'r': {(i, j): r|None}, 'n': {(i, j): count}}.
    r is None where fewer than min_n paired points exist. Symmetric; diagonal 1.0."""
    keys = list(stat_keys or DEFAULT_MATRIX_STATS)
    labels = [stat_label(k) for k in keys]
    rows = [r for r in rows if not is_excluded(r)]
    vals = {k: [STAT_EXTRACTORS[k][0](r) for r in rows] for k in keys}
    R, N = {}, {}
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            if j < i:
                R[(i, j)], N[(i, j)] = R[(j, i)], N[(j, i)]
                continue
            if i == j:
                R[(i, j)] = 1.0
                N[(i, j)] = sum(1 for v in vals[a] if v is not None)
                continue
            pts = [(vals[a][t], vals[b][t]) for t in range(len(rows))
                   if vals[a][t] is not None and vals[b][t] is not None]
            N[(i, j)] = len(pts)
            R[(i, j)] = pearson(pts) if len(pts) >= min_n else None
    return {'stats': keys, 'labels': labels, 'r': R, 'n': N}


def group_compare(rows, group_fn, stat_keys, min_n=3):
    """{group: {stat_key: avg|None, '_n': count}} — each stat averaged per group.
    Groups with fewer than min_n runs are dropped."""
    keys = list(stat_keys)
    rows = [r for r in rows if not is_excluded(r)]
    acc = {}
    for r in rows:
        g = group_fn(r)
        if not g:
            continue
        a = acc.setdefault(g, {'_n': 0, **{k: [0.0, 0] for k in keys}})
        a['_n'] += 1
        for k in keys:
            v = STAT_EXTRACTORS[k][0](r)
            if v is not None:
                a[k][0] += v
                a[k][1] += 1
    out = {}
    for g, a in acc.items():
        if a['_n'] < min_n:
            continue
        out[g] = {'_n': a['_n']}
        for k in keys:
            out[g][k] = round(a[k][0] / a[k][1], 2) if a[k][1] else None
    return out


def find_insights(rows, stat_keys=None, min_n=8):
    """Surface-agnostic findings, strongest first. The cog/web narrates them;
    this only returns structured facts:
      {'kind': 'strongest'|'strongest_negative'|'weakest', a, b, a_label, b_label, r, n}
      {'kind': 'grip_gap', stat, label, oneh, twoh, rel}
    """
    keys = list(stat_keys or DEFAULT_MATRIX_STATS)
    m = correlation_matrix(rows, keys, min_n=min_n)
    cors = []
    for i, a in enumerate(keys):
        for j in range(i + 1, len(keys)):
            r = m['r'].get((i, j))
            if r is None:
                continue
            cors.append({'a': a, 'b': keys[j], 'a_label': stat_label(a),
                         'b_label': stat_label(keys[j]), 'r': round(r, 2),
                         'n': m['n'].get((i, j))})
    cors.sort(key=lambda c: -abs(c['r']))
    out = []
    if cors:
        out.append({'kind': 'strongest', **cors[0]})
        neg = [c for c in cors if c['r'] < 0]
        if neg and neg[0] is not cors[0]:
            out.append({'kind': 'strongest_negative', **neg[0]})
        weak = min(cors, key=lambda c: abs(c['r']))
        if weak is not cors[0]:
            out.append({'kind': 'weakest', **weak})
    gc = group_compare(rows, weapon_grip, keys, min_n=min_n)
    if '1H' in gc and '2H' in gc:
        best = None
        for k in keys:
            v1, v2 = gc['1H'].get(k), gc['2H'].get(k)
            if v1 is None or v2 is None:
                continue
            rel = abs(v2 - v1) / (abs(v1) or 1)
            if best is None or rel > best['rel']:
                best = {'stat': k, 'label': stat_label(k), 'oneh': v1, 'twoh': v2,
                        'rel': round(rel, 3)}
        if best:
            out.append({'kind': 'grip_gap', **best})
    return out


# Fields the web Stats Lab receives per run: categoricals for filtering + every
# numeric stat (from STAT_EXTRACTORS). Ordered so it can be sent as compact arrays.
RECORD_CATEGORICALS = ['name', 'did', 'weapon', 'subclass', 'cls', 'grip',
                       'faction', 'map', 'side', 'vip', 'ts']
RECORD_STATS = list(STAT_EXTRACTORS.keys())
RECORD_FIELDS = RECORD_CATEGORICALS + RECORD_STATS


def run_record(row):
    """One run as a flat dict of categoricals + all numeric stats, for the web
    Lab. Numeric stats are None where the run lacks the inputs."""
    from utils.tilt import orientation as _orientation
    _mp = (row[5] or '').strip() if len(row) > 5 else ''
    _fac = (row[6] or '').strip() if len(row) > 6 else ''
    rec = {
        'name': (row[1] or '').strip() if len(row) > 1 else '',
        'did': (row[2] or '').strip() if len(row) > 2 else '',
        'weapon': run_weapon(row) or '',
        'subclass': (row[4] or '').strip() if len(row) > 4 else '',
        'cls': run_class(row) or '',
        'grip': weapon_grip(row) or '',
        'faction': _fac,
        'map': _mp,
        'side': _orientation(_mp, _fac) or '',
        'vip': ('VIP' if ((row[10] or '').strip().lower() in ('yes', 'true', '1', 'y')
                          if len(row) > 10 else False) else 'Non-VIP'),
        'ts': str(row[0]) if len(row) > 0 and row[0] else '',
    }
    for k, (fn, _lab) in STAT_EXTRACTORS.items():
        rec[k] = fn(row)
    return rec


def records(rows):
    """[run_record, ...] for all non-excluded rows."""
    return [run_record(r) for r in rows if not is_excluded(r)]
