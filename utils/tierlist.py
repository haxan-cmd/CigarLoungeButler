"""Pure Butler tier-list math.

Blend each player's raw stat components into a single 'Butler Score' RELATIVE to the
active lounge (every component becomes a 0..1 percentile), then bucket into classic S-F
tiers. Hybrid bucketing: relative bands keep tiers populated, but S also needs an absolute
score floor so 'S-tier' always means genuinely elite (not just best-of-a-weak-field). An
activity gate leaves low-sample players UNRANKED rather than dunking on newcomers.

No discord/db imports so it's unit-tested; the cog feeds it raw per-player aggregates.
"""

TIERS = ['S', 'A', 'B', 'C', 'D', 'F']

# Weighted blend of components. Each is turned into a 0..1 percentile across tiered
# players first, so the weights mix *ranks*, not raw units. All-around by design: skill
# (lethality/warlord), difficulty (valor), and breadth (boards/feats/mastery).
DEFAULT_WEIGHTS = {
    'lethality': 0.22,   # kills / takedowns — conversion
    'warlord':   0.18,   # takedowns / team kills — carry
    'valor':     0.15,   # share of runs won in uphill/Brutal lobbies
    'boards':    0.20,   # boards placed on + titles held
    'feats':     0.10,   # 100K / 200TD / Triple / TUFF / Flawless density
    'mastery':   0.15,   # marks / weapon breadth
}

# Cumulative bands from the TOP (position 0 = best player). Relative, so populated.
# top 8% S · next 17% A · next 25% B · next 25% C · next 17% D · bottom 8% F
DEFAULT_BANDS = [('S', 0.08), ('A', 0.25), ('B', 0.50), ('C', 0.75), ('D', 0.92), ('F', 1.0)]


_VALOR_TAGS = ('Uphill', 'Outmatched', 'Brutal')
_FEAT_BOARDS = ('100 Kills', '200 Takedowns', 'Triple', 'TUFF', 'Flawless')


def _peak5(series):
    """Peak best-5-consecutive-game average of a [(ts, value)] series (matches the board
    ratings: a rating never drops). 0.0 if empty."""
    vals = [v for _, v in sorted(series)]
    if not vals:
        return 0.0
    w = min(5, len(vals))
    return max(sum(vals[i:i + w]) / w for i in range(len(vals) - w + 1))


def gather_tier_inputs(subs, ld, players):
    """Build the raw per-player component dict the tier engine consumes, from the legacy
    row lists (submissions, leaderboard_data, players). Pure — the cog fetches the rows.
    Keyed by discord_id, else 'legacy:<name>'. VIP runs are excluded from the skill
    ratings (lethality/warlord) but still count as activity + valor, matching board rules.

    Components: lethality (peak-5 kills/TD), warlord (peak-5 TD/team-kills), valor (# of
    uphill/Brutal runs), boards (# distinct boards placed on), feats (# feat-board rows),
    mastery (career marks), runs (activity gate)."""
    def _key(did, nm):
        did = (did or '').strip()
        nm = (nm or '').strip()
        return did if did else (f"legacy:{nm.lower()}" if nm else '')

    name_by, marks_by = {}, {}
    for p in players or []:
        nm = (p[1] or '').strip() if len(p) > 1 else ''
        k = _key(p[0] if p else '', nm)
        if not k:
            continue
        name_by[k] = nm or k
        try:
            marks_by[k] = int(p[3]) if len(p) > 3 and p[3] else 0
        except (ValueError, TypeError):
            marks_by[k] = 0

    agg, leth, war = {}, {}, {}
    for s in subs or []:
        if len(s) < 9:
            continue
        feats = (s[11] or '') if len(s) > 11 else ''
        if 'Unlisted' in feats:
            continue
        k = _key(s[2], s[1])
        if not k:
            continue
        a = agg.setdefault(k, {'runs': 0, 'valor': 0})
        a['runs'] += 1
        name_by.setdefault(k, (s[1] or '').strip() or k)
        if any(t in feats for t in _VALOR_TAGS):
            a['valor'] += 1
        vip = (s[10] or '').strip().lower() == 'yes' if len(s) > 10 else False
        if vip:
            continue
        ts = s[0] or ''
        try:
            td, kills = int(s[7]), int(s[8])
        except (ValueError, TypeError):
            td = kills = 0
        if td > 0 and kills > 0:
            leth.setdefault(k, []).append((ts, kills / td))
            try:
                tks = float(s[20]) if len(s) > 20 and s[20] else None
            except (ValueError, TypeError):
                tks = None
            if tks and 0 < tks <= 100:
                war.setdefault(k, []).append((ts, td * tks / kills))

    boards, feats_n = {}, {}
    for r in ld or []:
        if len(r) < 4:
            continue
        b = (r[0] or '').strip()
        k = _key(r[2] if len(r) > 2 else '', r[1] if len(r) > 1 else '')
        if not k or not b:
            continue
        boards.setdefault(k, set()).add(b)
        if b in _FEAT_BOARDS:
            feats_n[k] = feats_n.get(k, 0) + 1

    out = {}
    for k in set(agg) | set(marks_by) | set(boards):
        a = agg.get(k, {'runs': 0, 'valor': 0})
        out[k] = {
            'name': name_by.get(k, k),
            'runs': a.get('runs', 0),
            'lethality': _peak5(leth.get(k, [])),
            'warlord': _peak5(war.get(k, [])),
            'valor': a.get('valor', 0),
            'boards': len(boards.get(k, set())),
            'feats': feats_n.get(k, 0),
            'mastery': marks_by.get(k, 0),
        }
    return out


def _percentiles(values):
    """Map numbers to their 0..1 rank percentile (ties share the average rank). Aligned
    to the input order. 0 = lowest, 1 = highest."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    pct = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        p = ((i + j) / 2.0) / (n - 1)   # average rank of the tie group
        for k in range(i, j + 1):
            pct[order[k]] = p
        i = j + 1
    return pct


def compute_butler_scores(raw, weights=None):
    """raw: {key: {component: value, ...}}. Returns {key: {'score': 0..1, 'pct': {comp: 0..1}}}
    where score is the weighted blend of per-component percentiles across all keys."""
    weights = weights or DEFAULT_WEIGHTS
    keys = list(raw.keys())
    if not keys:
        return {}
    comp_pct = {}
    for comp in weights:
        vals = [float(raw[k].get(comp, 0) or 0) for k in keys]
        ps = _percentiles(vals)
        comp_pct[comp] = {keys[idx]: ps[idx] for idx in range(len(keys))}
    wsum = sum(weights.values()) or 1.0
    out = {}
    for k in keys:
        s = sum(weights[c] * comp_pct[c][k] for c in weights) / wsum
        out[k] = {'score': s, 'pct': {c: comp_pct[c][k] for c in weights}}
    return out


def assign_tiers(raw, weights=None, min_runs=10, s_floor=0.72, bands=None):
    """Full pipeline. Each player's raw dict must include a 'runs' field for the activity
    gate. Returns {key: {'tier': 'S'|..|'F'|None, 'score': 0..1, 'pct': {comp: 0..1}}}.
    tier None == UNRANKED (under the runs gate). Hybrid floor: an S band whose blended
    score is under s_floor is demoted to A."""
    bands = bands or DEFAULT_BANDS
    result = {}
    tiered = [k for k, v in raw.items() if int((v or {}).get('runs', 0) or 0) >= min_runs]
    for k in raw:
        if k not in tiered:
            result[k] = {'tier': None, 'score': 0.0, 'pct': {}}
    if not tiered:
        return result
    scores = compute_butler_scores({k: raw[k] for k in tiered}, weights)
    ranked = sorted(tiered, key=lambda k: -scores[k]['score'])
    n = len(ranked)
    for idx, k in enumerate(ranked):
        pos = (idx + 0.5) / n            # 0 = best
        tier = bands[-1][0]
        for label, cutoff in bands:
            if pos <= cutoff:
                tier = label
                break
        sc = scores[k]['score']
        if tier == 'S' and sc < s_floor:
            tier = 'A'
        result[k] = {'tier': tier, 'score': sc, 'pct': scores[k]['pct']}
    return result
