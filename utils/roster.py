"""Roster-based rivalry aggregation — the accurate successor to the time-window
fingerprint in utils/rivalries.py.

Every scoreboard screenshot lists EVERY player in the lobby. The vision parser
already reads those rows; we now keep the NAMES (per side) alongside the stats
it already extracts. That gives ground-truth lobby membership from a SINGLE
submission — no guessing whether two uploads were the same game, and a rivalry
shows up even if the other player never submits anything.

This module is pure (no Discord/DB): it takes submission rows, the parsed roster
per submission, and an IGN index (in-game name -> discord_id), and produces the
same nemesis / ally / head-to-head / pair-award shapes the old engine did.

How identity works:
  - Roster names are matched to registered players by normalising (strip clan
    tags, accents, punctuation, case) then exact-then-fuzzy against known IGNs.
  - A name that matches nobody is an unregistered random: skipped, stays
    anonymous. You only ever rival KNOWN members.

Row indices (submissions, see CLAUDE.md): 0 submitted_at · 1 name · 2 discord_id
· 5 map · 7 takedowns · 8 kills · 11 feats · 23 id.
Roster entry shape (per submission id): {'name','side','td','k'} where side is
'team' (ally of the submitter) or 'enemy' (opponent of the submitter).

Unit-tested in tests/test_roster.py.
"""
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

_TAG = re.compile(r'[\[\{\(<][^\]\}\)<>]{1,8}[\]\}\)>]')   # clan tags: [ABC] {xX} (99)
_NONAL = re.compile(r'[^a-z0-9]')


def normalize_name(s):
    """Fold an in-game name to a comparable key: strip accents/unicode, remove
    clan tags and all punctuation/spacing, lowercase. '' for junk/blank."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', str(s))
    s = s.encode('ascii', 'ignore').decode()      # drop accents / non-latin
    s = s.lower()
    s = _TAG.sub(' ', s)                           # remove bracketed clan tags
    s = _NONAL.sub('', s)                          # keep only a-z0-9
    return s


def build_ign_index(players_igns):
    """players_igns: iterable of (discord_id, [name, ...]). Returns
    {normalized_ign: discord_id}. A normalised name of <2 chars is ignored
    (too ambiguous to match reliably). First registrant wins a collision."""
    idx = {}
    for did, names in players_igns:
        _d = str(did or '').strip()
        if not _d:
            continue
        for nm in (names or []):
            n = normalize_name(nm)
            if len(n) >= 2:
                idx.setdefault(n, _d)
    return idx


# OCR look-alikes fold to one representative so a 1/l, 0/O, 5/S slip still
# matches. Applied ONLY for comparison, never for storage or display.
_CONFUSE = str.maketrans({'1': 'i', 'l': 'i', '0': 'o', '5': 's', '8': 'b',
                          '9': 'g', '7': 't', '4': 'a', '3': 'e', '2': 'z'})


def _fold(n):
    return n.translate(_CONFUSE)


def resolve_name(raw, ign_index, threshold=0.86):
    """Map a raw roster name to a registered discord_id, or None if it matches
    nobody (an unregistered random). Tiers: exact on the normalised form, then
    exact on the OCR-confusable-folded form (1/l, 0/O, 5/S...), then a fuzzy
    pass on the folded form gated at `threshold`."""
    n = normalize_name(raw)
    if len(n) < 2 or not ign_index:
        return None
    hit = ign_index.get(n)
    if hit:
        return hit
    fn = _fold(n)
    best, best_r = None, 0.0
    for cand, did in ign_index.items():
        fc = _fold(cand)
        if fn == fc:
            return did
        r = SequenceMatcher(None, fn, fc).ratio()
        if r > best_r:
            best_r, best = r, did
    return best if best_r >= threshold else None


def ident(r):
    """(stable_key, display_name) for a submission row: discord_id when present,
    else name-lowercased. Mirrors utils.rivalries.ident."""
    did = (r[2] or '').strip() if len(r) > 2 else ''
    name = (r[1] or '').strip() if len(r) > 1 else ''
    return (did or ('name:' + name.lower())), name


def _excluded(r):
    f = (r[11] if len(r) > 11 else '') or ''
    return 'Resubmit' in f or 'Unlisted' in f


def _sub_id(r):
    return (str(r[23]).strip() if len(r) > 23 and r[23] not in (None, '') else None)


def _int(v):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def has_roster_coverage(submissions, roster_by_sub):
    """True if ANY non-excluded submission has a stored roster — lets callers
    decide whether to use this engine or fall back to the time-window one."""
    for r in submissions:
        if not _excluded(r) and roster_by_sub.get(_sub_id(r)):
            return True
    return False


def compute_rivalries(target_key, target_names, submissions, roster_by_sub,
                      ign_index, min_meetings=1):
    """Nemesis / ally / foes / allies for one player, built from the rosters of
    THEIR OWN submissions (exact lobby membership, no time window, no double
    counting). Returns the same shape as utils.rivalries.compute_rivalries:
      {'nemesis': {...}|None, 'ally': {...}|None, 'foes': [...], 'allies': [...]}

    target_names: the target's own known IGNs (normalised out), so a roster row
    that is really the target can't make them their own rival.
    """
    self_norms = {normalize_name(n) for n in (target_names or [])}
    self_norms.discard('')
    enc = defaultdict(lambda: {'key': '', 'name': '', 'meetings': 0, 'ally': 0,
                               'opp': 0, 'my_td': 0, 'my_k': 0,
                               'their_td': 0, 'their_k': 0})
    for r in submissions:
        if _excluded(r) or ident(r)[0] != target_key:
            continue
        roster = roster_by_sub.get(_sub_id(r))
        if not roster:
            continue
        my_td, my_k = _int(r[7]) or 0, _int(r[8]) or 0
        seen = set()   # one meeting per opponent per game, even on OCR dupes
        for entry in roster:
            nm = entry.get('name') or ''
            if normalize_name(nm) in self_norms:
                continue
            did = resolve_name(nm, ign_index)
            if not did or did == target_key or did in seen:
                continue
            seen.add(did)
            e = enc[did]
            e['key'] = did
            e['name'] = nm or e['name']
            e['meetings'] += 1
            e['my_td'] += my_td
            e['my_k'] += my_k
            e['their_td'] += _int(entry.get('td')) or 0
            e['their_k'] += _int(entry.get('k')) or 0
            if (entry.get('side') or '') == 'enemy':
                e['opp'] += 1
            elif (entry.get('side') or '') == 'team':
                e['ally'] += 1
    if not enc:
        return {'nemesis': None, 'ally': None, 'foes': [], 'allies': []}

    def _shaped(e):
        n = e['meetings'] or 1
        return {'key': e['key'], 'name': e['name'], 'meetings': e['meetings'],
                'clashes': e['opp'],
                'my_td': round(e['my_td'] / n, 1), 'my_k': round(e['my_k'] / n, 1),
                'their_td': round(e['their_td'] / n, 1),
                'their_k': round(e['their_k'] / n, 1)}

    foes = sorted((e for e in enc.values()
                   if e['opp'] >= min_meetings and e['opp'] >= e['ally']),
                  key=lambda e: (-e['opp'], -e['meetings']))
    allies = sorted((e for e in enc.values() if e['ally'] >= min_meetings),
                    key=lambda e: -e['ally'])
    return {
        'nemesis': _shaped(foes[0]) if foes else None,
        'ally': ({'key': allies[0]['key'], 'name': allies[0]['name'],
                  'matches': allies[0]['ally']} if allies else None),
        'foes': [_shaped(e) for e in foes],
        'allies': [{'key': e['key'], 'name': e['name'], 'matches': e['ally']}
                   for e in allies],
    }


def _time_bucket(ts, minutes=30):
    """Coarse game key so the SAME match uploaded by two people (slightly
    different upload times) dedupes to one meeting. None if unparsable."""
    from datetime import datetime
    try:
        t = datetime.strptime(str(ts).strip(), '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None
    return int(t.timestamp()) // (minutes * 60)


def _iter_meetings(submissions, roster_by_sub, ign_index):
    """Yield (submitter_key, submitter_name, member_did, member_name, side,
    sub_td, sub_k, mem_td, mem_k, game_key) for every resolved roster member of
    every submission. game_key = (map, time-bucket) so duplicate uploads of one
    match collapse."""
    for r in submissions:
        if _excluded(r):
            continue
        roster = roster_by_sub.get(_sub_id(r))
        if not roster:
            continue
        sk, sname = ident(r)
        s_td, s_k = _int(r[7]) or 0, _int(r[8]) or 0
        mp = (r[5] or '').strip().lower() if len(r) > 5 else ''
        gb = _time_bucket(r[0])
        for entry in roster:
            did = resolve_name(entry.get('name') or '', ign_index)
            if not did or did == sk:
                continue
            yield (sk, sname, did, entry.get('name') or '', entry.get('side') or '',
                   s_td, s_k, _int(entry.get('td')) or 0, _int(entry.get('k')) or 0,
                   (mp, gb))


def head_to_head(a_key, a_names, b_key, b_names, submissions, roster_by_sub, ign_index):
    """Pairwise shared-lobby record between two specific players from rosters.
    Dedupes the same match uploaded by both. None if they never shared a lobby.
    Shape matches utils.rivalries.head_to_head (meetings/same_team/opponents/
    averages/maps/last_met)."""
    from datetime import datetime
    a_res = {a_key} | {normalize_name(n) for n in (a_names or [])}
    b_res = {b_key} | {normalize_name(n) for n in (b_names or [])}
    if a_key == b_key:
        return None
    seen = set()
    meetings = same = opp = 0
    a_td = a_k = b_td = b_k = 0
    a_name = b_name = ''
    maps = defaultdict(int)
    last_met = None
    for r in submissions:
        if _excluded(r):
            continue
        roster = roster_by_sub.get(_sub_id(r))
        if not roster:
            continue
        sk, sname = ident(r)
        # Only submissions by A (looking for B in the roster) or by B (for A).
        if sk == a_key:
            me_key, foe_res, foe_key = a_key, b_res, b_key
        elif sk == b_key:
            me_key, foe_res, foe_key = b_key, a_res, a_key
        else:
            continue
        mp = (r[5] or '').strip() if len(r) > 5 else ''
        gb = _time_bucket(r[0])
        for entry in roster:
            nm = entry.get('name') or ''
            did = resolve_name(nm, ign_index)
            if not (did == foe_key or normalize_name(nm) in foe_res):
                continue
            gkey = (mp.lower(), gb)
            if gkey in seen and gb is not None:
                continue
            seen.add(gkey)
            meetings += 1
            side = entry.get('side') or ''
            if side == 'team':
                same += 1
            elif side == 'enemy':
                opp += 1
            s_td, s_k = _int(r[7]) or 0, _int(r[8]) or 0
            m_td, m_k = _int(entry.get('td')) or 0, _int(entry.get('k')) or 0
            if me_key == a_key:
                a_td += s_td; a_k += s_k; b_td += m_td; b_k += m_k
                a_name = sname or a_name; b_name = nm or b_name
            else:
                b_td += s_td; b_k += s_k; a_td += m_td; a_k += m_k
                b_name = sname or b_name; a_name = nm or a_name
            if mp:
                maps[mp] += 1
            try:
                _t = datetime.strptime(str(r[0]).strip(), '%Y-%m-%d %H:%M:%S')
                if last_met is None or _t > last_met:
                    last_met = _t
            except Exception:
                pass
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


def compute_pair_awards(submissions, roster_by_sub, ign_index, min_meetings=2):
    """Server-wide pair awards from rosters (deduped per match):
      'bitter_rivals': the pair confirmed on OPPOSITE sides most
      'inseparable':   the pair confirmed on the SAME team most
    Same return shape as utils.rivalries.compute_pair_awards."""
    pair = defaultdict(lambda: {'a': '', 'b': '', 'opp': 0, 'ally': 0,
                                'seen_opp': set(), 'seen_ally': set()})
    for (sk, sname, did, mname, side, _st, _sk2, _mt, _mk, gkey) in \
            _iter_meetings(submissions, roster_by_sub, ign_index):
        pk = tuple(sorted([sk, did]))
        p = pair[pk]
        # keep a display name for each key
        if pk[0] == sk:
            p['a'], p['b'] = (sname or p['a']), (mname or p['b'])
        else:
            p['a'], p['b'] = (mname or p['a']), (sname or p['b'])
        bucket = 'seen_opp' if side == 'enemy' else ('seen_ally' if side == 'team' else None)
        if bucket is None:
            continue
        if gkey[1] is not None and gkey in p[bucket]:
            continue
        p[bucket].add(gkey)
        p['opp' if side == 'enemy' else 'ally'] += 1
    rivals = [p for p in pair.values() if p['opp'] >= min_meetings and p['opp'] >= p['ally']]
    duos = [p for p in pair.values() if p['ally'] >= min_meetings]
    br = max(rivals, key=lambda p: p['opp']) if rivals else None
    ins = max(duos, key=lambda p: p['ally']) if duos else None
    return {
        'bitter_rivals': ({'a': br['a'], 'b': br['b'], 'clashes': br['opp']} if br else None),
        'inseparable': ({'a': ins['a'], 'b': ins['b'], 'matches': ins['ally']} if ins else None),
    }
