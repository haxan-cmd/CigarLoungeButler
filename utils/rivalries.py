"""Pure head-to-head / ally aggregation for the Nemesis & Friend system.

Deliberately does NOT track per-game win/loss: a submitted scoreboard is a snapshot,
not a final result, so "you beat X" would be misleading. Instead it counts how often
two players share a lobby and compares their TYPICAL output across those shared games
(apples-to-apples: same lobbies, same difficulty), which is robust to when someone
screenshots. Ally sides come from the reliable banner totals only.

Reuses the db.get_lobbymates fingerprint (same map, tight time window, matching
banner totals). No Discord/DB dependency; unit-tested in tests/test_rivalries.py.

Row indices: 0 submitted_at · 1 player_name · 2 discord_id · 5 map · 7 takedowns ·
8 kills · 11 feats · 18 total_lobby_kills · 25 team_total_kills · 26 enemy_total_kills.
"""
from collections import defaultdict
from datetime import datetime


def _i(v):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _ts(v):
    try:
        return datetime.strptime(str(v).strip(), '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def _excluded(r):
    from utils.feats import is_excluded as _fx
    return _fx((r[11] if len(r) > 11 else '') or '')


def ident(r):
    """(stable_key, display_name). discord_id when present, else name-lowercased."""
    did = (r[2] or '').strip() if len(r) > 2 else ''
    name = (r[1] or '').strip() if len(r) > 1 else ''
    return (did or ('name:' + name.lower())), name


def _pair(a, b):
    vals = [v for v in (a, b) if isinstance(v, int) and v > 0]
    return (min(vals), max(vals)) if len(vals) == 2 else None


def _same_lobby(r1, r2, window_min):
    """Same map, within the time window, and matching banner totals (or the legacy
    roster-sum fallback). Mirrors db.get_lobbymates."""
    if not (r1[5] or '').strip() or (r1[5] or '').strip().lower() != (r2[5] or '').strip().lower():
        return False
    t1, t2 = _ts(r1[0]), _ts(r2[0])
    if not t1 or not t2 or abs((t1 - t2).total_seconds()) / 60.0 > window_min:
        return False
    p1 = _pair(_i(r1[25]) if len(r1) > 25 else None, _i(r1[26]) if len(r1) > 26 else None)
    p2 = _pair(_i(r2[25]) if len(r2) > 25 else None, _i(r2[26]) if len(r2) > 26 else None)
    if p1 and p2:
        tol = max(12, int(p1[1] * 0.04))
        return abs(p1[0] - p2[0]) <= tol and abs(p1[1] - p2[1]) <= tol
    tot1 = _i(r1[18]) if len(r1) > 18 else None
    tot2 = _i(r2[18]) if len(r2) > 18 else None
    if tot1 and tot2:
        return abs(tot1 - tot2) <= max(30, int(tot1 * 0.06))
    return False


def _same_team(r1, r2):
    """True=allies, None=not confirmed. Uses ONLY the oriented banner totals: teammates
    share the (team, enemy) pair, opponents see it swapped. No kill-share fallback
    (it can't tell sides apart in a balanced game and invents false allies)."""
    myt = _i(r1[25]) if len(r1) > 25 else None
    mye = _i(r1[26]) if len(r1) > 26 else None
    tht = _i(r2[25]) if len(r2) > 25 else None
    the = _i(r2[26]) if len(r2) > 26 else None
    if all(isinstance(x, int) and x > 0 for x in (myt, mye, tht, the)):
        same = abs(myt - tht) + abs(mye - the)
        opp = abs(myt - the) + abs(mye - tht)
        if abs(same - opp) > max(6, int(max(myt, mye) * 0.03)):
            return same < opp
    return None


def compute_rivalries(target_key, all_subs, window_min=45):
    """Aggregate a player's shared-lobby history — NO per-game win/loss. Returns:
      {
        'nemesis': {key, name, meetings, my_td, my_k, their_td, their_k} | None,
        'ally':    {key, name, matches} | None,
        'foes':    [ ...nemesis-shaped, meetings desc... ],
        'allies':  [{key, name, matches}, ...],
      }
    nemesis = the player they meet most who ISN'T a confirmed teammate; the averages
    (over all their shared games) say who tends to show up bigger. ally = the most
    banner-confirmed teammate."""
    subs = [r for r in all_subs if len(r) > 9 and not _excluded(r)]
    target_runs = [r for r in subs if ident(r)[0] == target_key]
    enc = defaultdict(lambda: {'key': '', 'name': '', 'meetings': 0, 'ally': 0, 'opp': 0,
                               'my_td': 0, 'my_k': 0, 'their_td': 0, 'their_k': 0})
    for tr in target_runs:
        _mtd, _mk = _i(tr[7]) or 0, _i(tr[8]) or 0
        for r in subs:
            k, name = ident(r)
            if k == target_key or not _same_lobby(tr, r, window_min):
                continue
            e = enc[k]
            e['key'] = k
            e['name'] = name or e['name']
            e['meetings'] += 1
            e['my_td'] += _mtd
            e['my_k'] += _mk
            e['their_td'] += (_i(r[7]) or 0)
            e['their_k'] += (_i(r[8]) or 0)
            _st = _same_team(tr, r)
            if _st is True:
                e['ally'] += 1
            elif _st is False:
                e['opp'] += 1
    if not enc:
        return {'nemesis': None, 'ally': None, 'foes': [], 'allies': []}

    def _shaped(e):
        n = e['meetings'] or 1
        return {'key': e['key'], 'name': e['name'], 'meetings': e['meetings'],
                'clashes': e['opp'],
                'my_td': round(e['my_td'] / n, 1), 'my_k': round(e['my_k'] / n, 1),
                'their_td': round(e['their_td'] / n, 1), 'their_k': round(e['their_k'] / n, 1)}

    # Nemesis = the most-faced CONFIRMED opponent. Only games whose banner totals put the
    # two on OPPOSITE sides count (e['opp']); a frequent TEAMMATE whose side merely can't
    # be confirmed no longer floats up as a false nemesis (the "@X you play with every
    # game" bug). Require opp >= ally so someone you mostly team with is never a nemesis.
    foes = sorted((e for e in enc.values() if e['opp'] > 0 and e['opp'] >= e['ally']),
                  key=lambda e: (-e['opp'], -e['meetings']))
    allies = sorted((e for e in enc.values() if e['ally'] > 0), key=lambda e: -e['ally'])
    return {
        'nemesis': _shaped(foes[0]) if foes else None,
        'ally': ({'key': allies[0]['key'], 'name': allies[0]['name'], 'matches': allies[0]['ally']}
                 if allies else None),
        'foes': [_shaped(e) for e in foes],
        'allies': [{'key': e['key'], 'name': e['name'], 'matches': e['ally']} for e in allies],
    }


def head_to_head(a_key, b_key, all_subs, window_min=45):
    """Pairwise shared-lobby record between two specific players. Same philosophy as
    compute_rivalries: NO per-game win/loss (a scoreboard is a snapshot). Returns
    None if they've never shared a lobby, else:
      {
        'meetings': int, 'same_team': int, 'opponents': int,   # opponents = confirmed foes
        'a_name': str, 'b_name': str,
        'a_td', 'a_k', 'b_td', 'b_k': float,   # each player's AVERAGE across shared games
        'maps': {map_name: n, ...},            # where they cross paths, most-frequent first
        'last_met': 'YYYY-MM-DD' | None,
      }
    'same_team' + 'opponents' won't always sum to meetings — a game whose banner
    totals can't confirm the side is counted as a meeting but neither."""
    if a_key == b_key:
        return None
    subs = [r for r in all_subs if len(r) > 9 and not _excluded(r)]
    a_runs = [r for r in subs if ident(r)[0] == a_key]
    b_runs = [r for r in subs if ident(r)[0] == b_key]
    if not a_runs or not b_runs:
        return None
    meetings = same = opp = 0
    a_td = a_k = b_td = b_k = 0
    a_name = b_name = ''
    maps = defaultdict(int)
    last_met = None
    for ar in a_runs:
        a_name = ident(ar)[1] or a_name
        for br in b_runs:
            b_name = ident(br)[1] or b_name
            if not _same_lobby(ar, br, window_min):
                continue
            meetings += 1
            a_td += _i(ar[7]) or 0; a_k += _i(ar[8]) or 0
            b_td += _i(br[7]) or 0; b_k += _i(br[8]) or 0
            st = _same_team(ar, br)
            if st is True:
                same += 1
            elif st is False:
                opp += 1
            _m = (ar[5] or '').strip()
            if _m:
                maps[_m] += 1
            _t = _ts(ar[0])
            if _t and (last_met is None or _t > last_met):
                last_met = _t
    if meetings == 0:
        return None
    n = meetings
    return {
        'meetings': meetings, 'same_team': same, 'opponents': opp,
        'a_name': a_name, 'b_name': b_name,
        'a_td': round(a_td / n, 1), 'a_k': round(a_k / n, 1),
        'b_td': round(b_td / n, 1), 'b_k': round(b_k / n, 1),
        'maps': dict(sorted(maps.items(), key=lambda kv: -kv[1])),
        'last_met': last_met.strftime('%Y-%m-%d') if last_met else None,
    }


def rivalry_context(display_name, data, top=3):
    """Compact text block for the Butler's chat context, or '' if there's nothing.
    The Butler narrates from this; it never invents matchups not listed here."""
    nem, al = data.get('nemesis'), data.get('ally')
    if not nem and not al:
        return ''
    lines = [f"RIVALRY DATA for {display_name} (shared-lobby history, approximate; NO per-game win/loss):"]
    if nem:
        _c = nem.get('clashes', nem['meetings'])
        _mt = f"{_c} time{'s' if _c != 1 else ''} as opponents"
        lines.append(f"- Nemesis (most-faced opponent): {nem['name']}, faced {_mt}. Across your shared games "
                     f"{display_name} averages {nem['my_td']} TD / {nem['my_k']} K to {nem['name']}'s "
                     f"{nem['their_td']} TD / {nem['their_k']} K (who tends to show up bigger).")
    if al:
        _m = f"{al['matches']} time{'s' if al['matches'] != 1 else ''}"
        lines.append(f"- Closest ally (most confirmed on the same team): {al['name']}, {_m} together.")
    others = data.get('foes', [])[1:top + 1]
    if others:
        lines.append("- Other frequent foes: "
                     + ", ".join(f"{o['name']} ({o['meetings']})" for o in others) + ".")
    return "\n".join(lines)


def compute_pair_awards(all_subs, window_min=45, min_meetings=2):
    """Server-wide pair awards from shared-lobby history (no win/loss):
      'bitter_rivals': the two players who meet as NON-teammates most (most clashes)
      'inseparable':   the two players confirmed on the SAME team most
    Returns {'bitter_rivals': {a, b, clashes} | None, 'inseparable': {a, b, matches} | None}.
    Map-bucketed and time-sorted, so it avoids a full O(N^2) scan: within each map the
    inner loop stops as soon as the time gap exceeds the window."""
    subs = [r for r in all_subs if len(r) > 9 and not _excluded(r)]
    by_map = defaultdict(list)
    for r in subs:
        mp = (r[5] or '').strip().lower()
        if mp and _ts(r[0]):
            by_map[mp].append(r)
    pair = defaultdict(lambda: {'a': '', 'b': '', 'meetings': 0, 'ally': 0, 'opp': 0})
    for runs in by_map.values():
        runs.sort(key=lambda r: _ts(r[0]))
        for i in range(len(runs)):
            r1 = runs[i]
            t1 = _ts(r1[0])
            k1, n1 = ident(r1)
            for j in range(i + 1, len(runs)):
                r2 = runs[j]
                if (_ts(r2[0]) - t1).total_seconds() / 60.0 > window_min:
                    break
                k2, n2 = ident(r2)
                if k1 == k2 or not _same_lobby(r1, r2, window_min):
                    continue
                pk = tuple(sorted([k1, k2]))
                p = pair[pk]
                if pk[0] == k1:
                    p['a'], p['b'] = (n1 or p['a']), (n2 or p['b'])
                else:
                    p['a'], p['b'] = (n2 or p['a']), (n1 or p['b'])
                p['meetings'] += 1
                _st = _same_team(r1, r2)
                if _st is True:
                    p['ally'] += 1
                elif _st is False:
                    p['opp'] += 1

    # Bitter Rivals = the pair confirmed on OPPOSITE sides most often (not just frequent
    # lobby-mates), so two constant teammates can't win it and require opp >= ally.
    rivals = [p for p in pair.values() if p['opp'] >= min_meetings and p['opp'] >= p['ally']]
    duos = [p for p in pair.values() if p['ally'] >= min_meetings]
    br = max(rivals, key=lambda p: p['opp']) if rivals else None
    ins = max(duos, key=lambda p: p['ally']) if duos else None
    return {
        'bitter_rivals': ({'a': br['a'], 'b': br['b'], 'clashes': br['opp']} if br else None),
        'inseparable': ({'a': ins['a'], 'b': ins['b'], 'matches': ins['ally']} if ins else None),
    }
