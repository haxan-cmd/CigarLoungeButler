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
    f = (r[11] if len(r) > 11 else '') or ''
    return 'Resubmit' in f or 'Unlisted' in f


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
    enc = defaultdict(lambda: {'key': '', 'name': '', 'meetings': 0, 'ally': 0,
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
            if _same_team(tr, r) is True:
                e['ally'] += 1
    if not enc:
        return {'nemesis': None, 'ally': None, 'foes': [], 'allies': []}

    def _shaped(e):
        n = e['meetings'] or 1
        return {'key': e['key'], 'name': e['name'], 'meetings': e['meetings'],
                'my_td': round(e['my_td'] / n, 1), 'my_k': round(e['my_k'] / n, 1),
                'their_td': round(e['their_td'] / n, 1), 'their_k': round(e['their_k'] / n, 1)}

    def _foe_score(e):
        return e['meetings'] - e['ally']   # shared lobbies not confirmed as teammate

    foes = sorted((e for e in enc.values() if _foe_score(e) > 0), key=lambda e: -_foe_score(e))
    allies = sorted((e for e in enc.values() if e['ally'] > 0), key=lambda e: -e['ally'])
    return {
        'nemesis': _shaped(foes[0]) if foes else None,
        'ally': ({'key': allies[0]['key'], 'name': allies[0]['name'], 'matches': allies[0]['ally']}
                 if allies else None),
        'foes': [_shaped(e) for e in foes],
        'allies': [{'key': e['key'], 'name': e['name'], 'matches': e['ally']} for e in allies],
    }


def rivalry_context(display_name, data, top=3):
    """Compact text block for the Butler's chat context, or '' if there's nothing.
    The Butler narrates from this; it never invents matchups not listed here."""
    nem, al = data.get('nemesis'), data.get('ally')
    if not nem and not al:
        return ''
    lines = [f"RIVALRY DATA for {display_name} (shared-lobby history, approximate; NO per-game win/loss):"]
    if nem:
        _mt = f"{nem['meetings']} meeting{'s' if nem['meetings'] != 1 else ''}"
        lines.append(f"- Nemesis (the foe met most): {nem['name']}, {_mt}. Across those games {display_name} "
                     f"averages {nem['my_td']} TD / {nem['my_k']} K to {nem['name']}'s "
                     f"{nem['their_td']} TD / {nem['their_k']} K (who tends to show up bigger).")
    if al:
        _m = f"{al['matches']} time{'s' if al['matches'] != 1 else ''}"
        lines.append(f"- Closest ally (most confirmed on the same team): {al['name']}, {_m} together.")
    others = data.get('foes', [])[1:top + 1]
    if others:
        lines.append("- Other frequent foes: "
                     + ", ".join(f"{o['name']} ({o['meetings']})" for o in others) + ".")
    return "\n".join(lines)
