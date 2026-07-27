"""Pure head-to-head / ally aggregation for the Nemesis & Friend system.

Reuses the same lobby-fingerprint idea as db.get_lobbymates (same map, tight time
window, matching faction banner totals, with a kill-share fallback for side
detection) but computes it across a player's WHOLE history in-Python, so it has no
Discord/DB dependency and is unit-tested (tests/test_rivalries.py).

Row indices (submissions shape): 0 submitted_at · 1 player_name · 2 discord_id ·
3 weapon · 5 map · 7 takedowns · 8 kills · 11 feats · 18 total_lobby_kills ·
20 team_kill_share · 25 team_total_kills · 26 enemy_total_kills.
"""
from collections import defaultdict
from datetime import datetime


def _i(v):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _f(v):
    try:
        return float(str(v).strip())
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
    """Do two runs look like the same match? Same map, within the time window, and
    matching banner totals (or the legacy roster-sum fallback). Mirrors get_lobbymates."""
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


def _team_total(kills, share):
    if kills and share and share > 0:
        return kills * 100.0 / share
    return None


def _same_team(r1, r2):
    """True=allies, False=opponents, None=undetermined. Prefers the ORIENTED banner
    totals (teammates share the (team, enemy) pair, opponents see it swapped). When
    banner totals are missing, falls back to kill-share-derived team totals, matching
    db.get_lobbymates. Balanced banner totals return None (honestly can't tell)."""
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
    _t1 = _team_total(_i(r1[8]), _f(r1[20]) if len(r1) > 20 else None)
    _t2 = _team_total(_i(r2[8]), _f(r2[20]) if len(r2) > 20 else None)
    if _t1 and _t2:
        return abs(_t1 - _t2) <= max(_t1, _t2) * 0.10
    return None


def compute_rivalries(target_key, all_subs, window_min=45):
    """Aggregate a player's shared-lobby history. Every shared lobby is an ENCOUNTER;
    when sides resolve, it also counts as an opponent clash (with win/loss by kills) or
    an ally match. Returns:
      {
        'nemesis': {key, name, encounters, wins, losses} | None,
        'ally':    {key, name, matches} | None,
        'opponents':[{key, name, encounters, wins, losses}, ...],  # opp-clash desc
        'allies':   [{key, name, matches}, ...],                   # matches desc
      }
    nemesis = the player you clash with as an OPPONENT most; if no clash ever resolves
    to opponents, it falls back to the player you simply share lobbies with most."""
    subs = [r for r in all_subs if len(r) > 9 and not _excluded(r)]
    target_runs = [r for r in subs if ident(r)[0] == target_key]
    enc = defaultdict(lambda: {'key': '', 'name': '', 'encounters': 0,
                               'wins': 0, 'losses': 0, 'ally': 0})
    for tr in target_runs:
        tk = _i(tr[8]) or 0
        for r in subs:
            k, name = ident(r)
            if k == target_key or not _same_lobby(tr, r, window_min):
                continue
            e = enc[k]
            e['key'] = k
            e['name'] = name or e['name']
            e['encounters'] += 1
            side = _same_team(tr, r)
            if side is False:
                rk = _i(r[8]) or 0
                if tk > rk:
                    e['wins'] += 1
                elif rk > tk:
                    e['losses'] += 1
            elif side is True:
                e['ally'] += 1
    if not enc:
        return {'nemesis': None, 'ally': None, 'opponents': [], 'allies': []}

    def _clashes(e):
        return e['wins'] + e['losses']

    all_e = list(enc.values())
    opps = [e for e in all_e if _clashes(e) > 0]
    opps.sort(key=lambda e: (-_clashes(e), -(e['losses'] - e['wins'])))
    allies = sorted((e for e in all_e if e['ally'] > 0), key=lambda e: -e['ally'])
    if opps:
        nemesis = opps[0]
    else:  # no clash ever resolved to opponents — fall back to most-shared-lobby
        nemesis = max(all_e, key=lambda e: e['encounters'])
    nem_out = {'key': nemesis['key'], 'name': nemesis['name'],
               'encounters': nemesis['encounters'],
               'wins': nemesis['wins'], 'losses': nemesis['losses']}
    ally_out = None
    if allies:
        a = allies[0]
        ally_out = {'key': a['key'], 'name': a['name'], 'matches': a['ally']}
    return {
        'nemesis': nem_out,
        'ally': ally_out,
        'opponents': [{'key': e['key'], 'name': e['name'], 'encounters': e['encounters'],
                       'wins': e['wins'], 'losses': e['losses']} for e in opps],
        'allies': [{'key': e['key'], 'name': e['name'], 'matches': e['ally']} for e in allies],
    }


def rivalry_context(display_name, data, top=3):
    """Compact text block for the Butler's chat context, or '' if there's nothing.
    The Butler narrates from this; it never invents matchups not listed here."""
    nem, al = data.get('nemesis'), data.get('ally')
    if not nem and not al:
        return ''
    lines = [f"RIVALRY DATA for {display_name} (from shared-lobby history, approximate):"]
    if nem:
        if nem['wins'] or nem['losses']:
            lines.append(f"- Nemesis (most-faced opponent): {nem['name']}, {nem['encounters']} clashes, "
                         f"head-to-head {nem['wins']}-{nem['losses']} (their kills decided each).")
        else:
            _tm = f"{nem['encounters']} time{'s' if nem['encounters'] != 1 else ''}"
            lines.append(f"- Most-shared lobby: {nem['name']} ({_tm}). The sides were too even to keep an "
                         f"honest win-loss, so treat them as a frequent foe, not a scored one.")
    if al:
        lines.append(f"- Closest ally (most matches on the same team): {al['name']}, {al['matches']} together.")
    others = [o for o in data.get('opponents', [])[1:top + 1] if (o['wins'] or o['losses'])]
    if others:
        lines.append("- Other rivals: "
                     + ", ".join(f"{o['name']} ({o['wins']}-{o['losses']}, {o['encounters']} clashes)"
                                 for o in others) + ".")
    return "\n".join(lines)
