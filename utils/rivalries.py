"""Pure head-to-head / ally aggregation for the Nemesis & Friend system.

Reuses the same lobby-fingerprint idea as db.get_lobbymates (same map, tight time
window, matching faction banner totals) but computes it across a player's WHOLE
history in-Python, so it has no Discord/DB dependency and is unit-tested
(tests/test_rivalries.py). The cog scopes/fetches submissions and hands them here.

Row indices (submissions shape): 0 submitted_at · 1 player_name · 2 discord_id ·
3 weapon · 5 map · 7 takedowns · 8 kills · 11 feats · 18 total_lobby_kills ·
25 team_total_kills · 26 enemy_total_kills.
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
    """Do two runs look like the same match? Same map, within the time window, and
    matching banner totals (or the legacy roster-sum fallback). Mirrors get_lobbymates."""
    if (r1[5] or '').strip().lower() != (r2[5] or '').strip().lower() or not (r1[5] or '').strip():
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
    """True=allies, False=opponents, None=too symmetric to tell. Uses the ORIENTED
    banner totals (your team total + the enemy total): teammates share the pair,
    opponents see it swapped."""
    myt = _i(r1[25]) if len(r1) > 25 else None
    mye = _i(r1[26]) if len(r1) > 26 else None
    tht = _i(r2[25]) if len(r2) > 25 else None
    the = _i(r2[26]) if len(r2) > 26 else None
    if all(isinstance(x, int) and x > 0 for x in (myt, mye, tht, the)):
        same = abs(myt - tht) + abs(mye - the)
        opp = abs(myt - the) + abs(mye - tht)
        if abs(same - opp) <= max(6, int(max(myt, mye) * 0.03)):
            return None
        return same < opp
    return None


def compute_rivalries(target_key, all_subs, window_min=45):
    """Aggregate a player's head-to-head (opponents) and ally records across every
    match we can fingerprint. Returns:
      {
        'nemesis':  {name, encounters, wins, losses} | None,   # most-faced opponent
        'ally':     {name, matches} | None,                     # most-played-with
        'opponents':[{name, encounters, wins, losses}, ...],    # by encounters desc
        'allies':   [{name, matches}, ...],                     # by matches desc
      }
    wins/losses are from the target's view, decided by kills in that shared match."""
    subs = [r for r in all_subs if len(r) > 9 and not _excluded(r)]
    target_runs = [r for r in subs if ident(r)[0] == target_key]
    opp = defaultdict(lambda: {'key': '', 'name': '', 'encounters': 0, 'wins': 0, 'losses': 0})
    ally = defaultdict(lambda: {'key': '', 'name': '', 'matches': 0})
    for tr in target_runs:
        tk = _i(tr[8]) or 0
        for r in subs:
            k, name = ident(r)
            if k == target_key:
                continue
            if not _same_lobby(tr, r, window_min):
                continue
            side = _same_team(tr, r)
            if side is True:
                a = ally[k]
                a['key'] = k
                a['name'] = name or a['name']
                a['matches'] += 1
            elif side is False:
                o = opp[k]
                o['key'] = k
                o['name'] = name or o['name']
                o['encounters'] += 1
                rk = _i(r[8]) or 0
                if tk > rk:
                    o['wins'] += 1
                elif rk > tk:
                    o['losses'] += 1
    opponents = sorted(opp.values(), key=lambda d: (-d['encounters'], -(d['losses'] - d['wins'])))
    allies = sorted(ally.values(), key=lambda d: -d['matches'])
    return {
        'nemesis': opponents[0] if opponents else None,
        'ally': allies[0] if allies else None,
        'opponents': opponents,
        'allies': allies,
    }


def rivalry_context(display_name, data, top=3):
    """Compact text block for the Butler's chat context, or '' if there's nothing.
    The Butler narrates from this; it never invents matchups not listed here."""
    nem, al = data.get('nemesis'), data.get('ally')
    if not nem and not al:
        return ''
    lines = [f"RIVALRY DATA for {display_name} (from shared-lobby history, approximate):"]
    if nem:
        rec = f"{nem['wins']}-{nem['losses']}" if (nem['wins'] or nem['losses']) else "even/unclear"
        lines.append(f"- Nemesis (most-faced opponent): {nem['name']}, {nem['encounters']} clashes, "
                     f"head-to-head {rec} (target's kills vs theirs).")
    if al:
        lines.append(f"- Closest ally (most matches on the same team): {al['name']}, {al['matches']} together.")
    others = [o for o in data.get('opponents', [])[1:top + 1]]
    if others:
        lines.append("- Other rivals: "
                     + ", ".join(f"{o['name']} ({o['wins']}-{o['losses']}, {o['encounters']} clashes)"
                                 for o in others) + ".")
    return "\n".join(lines)
