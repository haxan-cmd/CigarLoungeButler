"""utils/butler_tools.py — the Butler's stats toolset (function calling).

Instead of pre-stuffing a guessed context blob into the prompt and hoping the model
reads it, these tools let the Butler FETCH exactly the data a question needs — the way
the website queries the database. Each tool wraps logic the project already vetted:

  * stats_engine  — the Stats Lab engine (per-run records, any metric, filtered/sorted)
  * aggregates    — the "who has the most X" ranking registry (career totals + feat counts)
  * registry      — player cards (marks, bests, boards held, ranks, archetype)
  * rivalry_service — nemesis / ally / head-to-head
  * goals         — what's next (rank / mastery / Hundred-Handed)
  * boards        — board classification + score units

So every domain rule (VIP/resubmit/unlisted exclusion, canonical identity collapse,
Score = points not takedowns, archer exclusions, kills-companion boards) is inherited
and cannot be re-derived wrong.

Contract: everything here is READ-ONLY, every result is BOUNDED, and dispatch() never
raises — a failing tool returns {'error': ...} so the model can recover or say it
doesn't have the data.
"""
import utils.db as _db
from utils import stats_engine as _se
from utils import aggregates as _agg
from utils import boards as _boards
from utils import goals as _goals
import config

_RESULT_CAP = 25          # hard ceiling on rows any tool returns
_MAX_TOOL_CALLS = 6       # loop guard, enforced by the caller


def _safe_int(x, d=0):
    try:
        return int(str(x).replace(',', '').strip())
    except (ValueError, TypeError, AttributeError):
        return d


def _num(v):
    """JSON-friendly number: keep ints, round floats to 2dp."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 2)
    return v


def _identity(players, n2i):
    return _agg.Identity(players, n2i, getattr(config, 'LEADERBOARD_NAME_OVERRIDES', {}) or {})


async def _resolve_player(query):
    """(discord_id, display_name) for a name / IGN / discord_id, or (None, query) if
    unknown. Mirrors the registry's resolution + name_to_id IGN-variant collapse."""
    q = (query or '').strip()
    if not q:
        return None, None
    players = await _db.get_all_players()
    for p in players:                                  # exact discord_id
        if (p[0] or '').strip() == q:
            return (p[0] or '').strip(), (p[1] or '').strip()
    ql = q.lower()
    for p in players:                                  # exact registry name
        if (p[1] or '').strip().lower() == ql:
            return (p[0] or '').strip(), (p[1] or '').strip()
    n2i = await _db.get_name_to_id_map()               # IGN variant -> id
    did = n2i.get(ql)
    if did:
        for p in players:
            if (p[0] or '').strip() == str(did):
                return str(did), (p[1] or '').strip()
        return str(did), q
    for p in players:                                  # loose contains, last resort
        if ql and ql in (p[1] or '').strip().lower():
            return (p[0] or '').strip(), (p[1] or '').strip()
    return None, q


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

async def _query_runs(metric=None, filters=None, mode='top_games', agg='avg',
                      min_games=5, limit=10, ascending=False, **_):
    """Per-run records via the Stats Lab engine. mode='top_games' -> best single games;
    mode='rank_players' -> per-player average/total of the metric. Filters are exact
    matches on categoricals. Resubmit/Unlisted already excluded; VIP included (tagged)."""
    metric = (metric or '').strip()
    if metric not in _se.STAT_EXTRACTORS:
        return {'error': f"unknown metric '{metric}'",
                'valid_metrics': list(_se.STAT_EXTRACTORS.keys())}
    subs = await _db.get_all_submissions()
    recs = _se.records(subs)
    players = await _db.get_all_players()
    n2i = await _db.get_name_to_id_map()
    ident = _identity(players, n2i)
    filters = {k: v for k, v in (filters or {}).items() if v not in (None, '')}
    valid_cats = set(_se.RECORD_CATEGORICALS)

    def _keep(rec):
        for k, v in filters.items():
            kk = str(k).lower()
            vv = str(v).strip().lower()
            if kk == 'player':
                key, disp = ident.resolve(rec.get('name', ''), rec.get('did', ''))
                if vv not in (str(rec.get('name', '')).lower(), str(rec.get('did', '')).lower(),
                              str(disp).lower(), str(key).lower()):
                    return False
            elif kk in valid_cats:
                rv = rec.get(kk)
                if rv is None or str(rv).lower() != vv:
                    return False
        return True

    fr = [r for r in recs if _keep(r)]
    limit = max(1, min(_safe_int(limit, 10), _RESULT_CAP))
    if mode == 'rank_players':
        from collections import defaultdict
        grp = defaultdict(lambda: [0.0, 0, ''])       # key -> [sum, n, display]
        for r in fr:
            v = r.get(metric)
            if v is None:
                continue
            key, disp = ident.resolve(r.get('name', ''), r.get('did', ''))
            g = grp[key]; g[0] += v; g[1] += 1; g[2] = disp
        min_games = max(1, _safe_int(min_games, 5))
        rows = []
        for _k, (s, n, disp) in grp.items():
            if n < min_games:
                continue
            rows.append((disp, _num((s / n) if agg == 'avg' else s), n))
        rows.sort(key=lambda x: x[1], reverse=not ascending)
        res = [{'player': d, 'value': v, 'games': n} for d, v, n in rows[:limit]]
        out = {'metric': metric, 'label': _se.stat_label(metric), 'mode': 'rank_players',
               'agg': agg, 'min_games': min_games, 'filters': filters, 'results': res}
        if not res:
            out['note'] = (f"No players had at least {min_games} qualifying games under these "
                           f"filters ({len(grp)} player(s) had any). Retry with min_games=1, or use "
                           f"mode=top_games for the single best game. Also check filter values: "
                           f"faction must be one of Tenosia/Agatha/Mason, map an exact map name.")
        return out
    # top_games (default): best single games
    vals = [r for r in fr if r.get(metric) is not None]
    vals.sort(key=lambda r: r[metric], reverse=not ascending)
    out = [{'player': ident.resolve(r.get('name', ''), r.get('did', ''))[1],
            'value': _num(r[metric]), 'weapon': r.get('weapon'), 'map': r.get('map'),
            'vip': r.get('vip'), 'link': r.get('link')} for r in vals[:limit]]
    res = {'metric': metric, 'label': _se.stat_label(metric), 'mode': 'top_games',
           'filters': filters, 'matched_runs': len(fr), 'results': out}
    if not out:
        res['note'] = (f"No runs matched these filters (matched {len(fr)} run(s) before the metric "
                       f"filter). Check filter VALUES — faction must be Tenosia/Agatha/Mason, map an "
                       f"exact map name (e.g. Falmire), weapon an exact weapon name — or loosen them.")
    return res


_AGG_IDS = {s.id for s in _agg.SPECS}


async def _rank_leaders(metric=None, weapon=None, question=None, limit=10, **_):
    """Server leaderboards for career totals + feat counts via the aggregates registry:
    most marks, career kills/takedowns, most 100-kill/200-td/triple/flawless/tuff/
    pacifist games, best K/D, highest average score/td, most games/maps/vip/deaths/
    brutal lobbies. Pass a metric id, or a natural-language `question` to auto-match."""
    subs = await _db.get_all_submissions()
    boards = await _db.get_all_leaderboard_data()
    players = await _db.get_all_players()
    n2i = await _db.get_name_to_id_map()
    ident = _identity(players, n2i)
    data = {'submissions': subs, 'boards': boards, 'players': players}
    limit = max(1, min(_safe_int(limit, 10), _RESULT_CAP))
    specs = []
    if metric:
        spec = next((s for s in _agg.SPECS if s.id == metric), None)
        if spec:
            specs = [(spec, weapon if spec.parametric else None)]
    elif question:
        specs = _agg.match_specs(question, param_weapon=weapon)
    if not specs:
        return {'error': 'no matching leaderboard metric', 'valid_metrics': sorted(_AGG_IDS)}
    results = []
    for spec, param in specs:
        try:
            ranked = _agg.compute(spec, data, ident, param=param)
        except Exception as e:
            results.append({'metric': spec.id, 'error': str(e)})
            continue
        try:
            label = spec.label.format(param=param or '', min_n=spec.min_n)
        except (KeyError, IndexError):
            label = spec.label
        results.append({'metric': spec.id, 'label': label, 'unit': spec.unit.strip(),
                        'leaders': [{'player': d, 'value': _num(v)} for d, v, _n in ranked[:limit]]})
    return {'results': results}


async def _get_board(board_name=None, limit=10, **_):
    """A single leaderboard's ranking (one row per player, best score), with its unit."""
    board_name = (board_name or '').strip()
    if not board_name:
        return {'error': 'board_name required', 'hint': 'call list_boards for valid names'}
    rows = await _db.get_leaderboard_by_board(board_name)   # pre-sorted score DESC
    if not rows:
        return {'error': f"no board '{board_name}' with entries", 'hint': 'call list_boards'}
    unit = _boards.board_unit(board_name)
    limit = max(1, min(_safe_int(limit, 10), _RESULT_CAP))
    out, seen = [], set()
    for r in rows:
        nm = (r[1] or '').strip()
        key = (r[2] or '').strip() or ('name:' + nm.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({'rank': len(out) + 1, 'player': nm, 'score': _safe_int(r[3]), 'unit': unit})
        if len(out) >= limit:
            break
    return {'board': board_name, 'unit': unit, 'entries': out}


async def _list_boards(kind=None, **_):
    """Distinct board names that actually have entries. kind in {weapon, map, feat, kills}
    filters; blank returns all. Helps pick a valid name for get_board."""
    boards = await _db.get_all_leaderboard_data()
    names = sorted({(r[0] or '').strip() for r in boards if r and (r[0] or '').strip()})
    k = (kind or '').strip().lower()
    if k == 'feat':
        names = [n for n in names if _boards.is_feat_board(n)]
    elif k == 'map':
        names = [n for n in names if _boards.is_map_board(n)]
    elif k == 'kills':
        names = [n for n in names if _boards.is_kills_board(n)]
    elif k == 'weapon':
        names = [n for n in names if not (_boards.is_feat_board(n) or _boards.is_map_board(n)
                                          or _boards.is_kills_board(n))]
    return {'count': len(names), 'boards': names[:120]}


async def _server_overview(**_):
    """Server-wide aggregates: totals, records, community cadence, RANKED most-played
    weapons/maps/subclasses, per-weapon and per-map meta."""
    try:
        from cogs.personality import _server_aggregates
    except Exception as e:
        return {'error': f'server overview unavailable: {e}'}
    subs = await _db.get_all_submissions()
    return {'overview': _server_aggregates(subs)}


async def _get_player_card(player=None, **_):
    """A player's full stat card: marks, submissions, best kills/takedowns/match-points
    (with weapon+map), boards they hold + rank, playstyle archetype + damage lean."""
    did, name = await _resolve_player(player)
    if not did:
        return {'error': f"no player found matching '{player}'"}
    from cogs.registry import (get_personal_bests, get_best_placements_for_player,
                               get_player_descriptors)
    prow = await _db.get_player(did)
    total_marks = _safe_int(prow[3]) if prow and len(prow) > 3 else None
    pb = {}
    try:
        pb = await get_personal_bests(did) or {}
    except Exception as e:
        pb = {'_error': str(e)}
    # Best kills / TD / points games WITH weapon+map, from submissions.
    best_k = best_td = best_pts = None
    try:
        _subs = await _db.get_submissions_by_player(did)
    except Exception:
        _subs = []
    # Count ACTUAL logged runs, not the players-table submission_count column, which can
    # drift stale (Boltzed showed 25 marks + 0 runs because that stored counter had gone
    # to 0 while 18 real submissions existed). Fall back to the counter only if we somehow
    # read no rows.
    sub_count = len(_subs) if _subs else (_safe_int(prow[4]) if prow and len(prow) > 4 else None)
    try:
        for s in _subs:
            if len(s) < 9:
                continue
            k = _safe_int(s[8]); t = _safe_int(s[7]); pts = _safe_int(s[24]) if len(s) > 24 else 0
            wpn = (s[3] or '').strip(); mp = (s[5] or '').strip()
            if best_k is None or k > best_k['kills']:
                best_k = {'kills': k, 'weapon': wpn, 'map': mp}
            if best_td is None or t > best_td['takedowns']:
                best_td = {'takedowns': t, 'weapon': wpn, 'map': mp}
            is_pac = (k == 0 and t <= 10)
            if pts > 0 and not is_pac and (best_pts is None or pts > best_pts['points']):
                best_pts = {'points': pts, 'weapon': wpn, 'map': mp}
    except Exception:
        pass
    boards_held = []
    try:
        for pos, bname, _emoji, gap in (await get_best_placements_for_player(did, top_n=15) or []):
            boards_held.append({'board': bname, 'rank': pos, **({'lead': gap} if pos == 1 and gap else {})})
    except Exception:
        pass
    archetype = damage = None
    try:
        archetype, damage = await get_player_descriptors(did)
    except Exception:
        pass
    return {
        'player': name, 'total_marks': total_marks, 'submissions': sub_count,
        'best_kills_game': best_k, 'best_takedowns_game': best_td,
        'best_match_points_game': best_pts,
        'career_hundos_100kill_games': pb.get('hundos'),
        'best_lethality_pct': pb.get('lethality'), 'lethality_weapon': pb.get('lethality_weapon'),
        'boards_held': boards_held[:_RESULT_CAP],
        'archetype': archetype, 'damage_style': damage,
    }


async def _get_rivalries(player=None, **_):
    """A player's nemesis (most-faced foe) and closest ally (most-teamed), from shared
    lobbies. No win/loss — a scoreboard is a snapshot, not a result."""
    did, name = await _resolve_player(player)
    if not did:
        return {'error': f"no player found matching '{player}'"}
    from utils import rivalry_service as _riv
    r = await _riv.rivalries_for(did) or {}
    nem = r.get('nemesis'); ally = r.get('ally')
    return {
        'player': name,
        'nemesis': ({'name': nem.get('name'), 'meetings': nem.get('meetings'),
                     'their_avg_td': _num(nem.get('their_td')), 'their_avg_kills': _num(nem.get('their_k')),
                     'your_avg_td': _num(nem.get('my_td')), 'your_avg_kills': _num(nem.get('my_k'))}
                    if nem else None),
        'ally': ({'name': ally.get('name'), 'matches_together': ally.get('matches')} if ally else None),
    }


async def _head_to_head(player_a=None, player_b=None, **_):
    """Shared-lobby history between two players: how often they've met, on which sides,
    and each one's average takedowns/kills across those games."""
    a_did, a_nm = await _resolve_player(player_a)
    b_did, b_nm = await _resolve_player(player_b)
    if not a_did or not b_did:
        miss = player_a if not a_did else player_b
        return {'error': f"could not resolve player '{miss}'"}
    from utils import rivalry_service as _riv
    h = await _riv.head_to_head_for(a_did, b_did)
    if not h:
        return {'result': f"{a_nm} and {b_nm} have no shared lobbies on record."}
    return {
        'a': h.get('a_name'), 'b': h.get('b_name'),
        'meetings': h.get('meetings'), 'same_team': h.get('same_team'), 'as_opponents': h.get('opponents'),
        'a_avg_td': _num(h.get('a_td')), 'a_avg_kills': _num(h.get('a_k')),
        'b_avg_td': _num(h.get('b_td')), 'b_avg_kills': _num(h.get('b_k')),
        'last_met': h.get('last_met'), 'maps': h.get('maps'),
    }


async def _whats_next(player=None, **_):
    """A player's nearest goals: next weapon rank, next mastery/virtuoso, Hundred-Handed
    progress. Mirrors the /next command exactly."""
    did, name = await _resolve_player(player)
    if not did:
        return {'error': f"no player found matching '{player}'"}
    from cogs.registry import calculate_weapon_marks_for_player
    from cogs.leaderboards import _HH_PRIMARIES, HH_TOTAL
    marks = await calculate_weapon_marks_for_player(did) or {}
    flat = {}
    for k, v in marks.items():
        w = k[0] if isinstance(k, tuple) else k
        if w and w not in ('Other', 'Multiple Weapons', 'Hybrid'):
            flat[w] = flat.get(w, 0) + v
    req = {(sc, w) for sc, ws in _HH_PRIMARIES.items() for w in ws}
    done = (await _db.get_hh_done_combos(did, name)) & req
    g = _goals.next_goals(flat, req - done,
                          mastery_threshold=config.MASTERY_THRESHOLD,
                          virtuoso_threshold=config.VIRTUOSO_THRESHOLD,
                          rank_thresholds=config.WEAPON_RANK_THRESHOLDS,
                          hh_total=HH_TOTAL)
    if not g.get('nearest'):
        return {'player': name, 'result': 'no logged runs yet — no goals to show.'}
    return {'player': name, 'nearest': g.get('nearest'), 'rank_up': g.get('rank_up'),
            'mastery': g.get('mastery'), 'hundred_handed': g.get('hundred_handed')}


# ─────────────────────────────────────────────────────────────────────────────
# Registry + dispatch
# ─────────────────────────────────────────────────────────────────────────────

_TOOLS = {
    'query_runs': _query_runs,
    'rank_leaders': _rank_leaders,
    'get_board': _get_board,
    'list_boards': _list_boards,
    'server_overview': _server_overview,
    'get_player_card': _get_player_card,
    'get_rivalries': _get_rivalries,
    'head_to_head': _head_to_head,
    'whats_next': _whats_next,
}


async def dispatch(name, args):
    """Run one tool. Never raises: returns {'error': ...} on anything unexpected."""
    fn = _TOOLS.get(name)
    if fn is None:
        return {'error': f"unknown tool '{name}'"}
    if not isinstance(args, dict):
        args = {}
    try:
        return await fn(**args)
    except TypeError as e:
        return {'error': f"bad arguments for {name}: {e}"}
    except Exception as e:
        return {'error': f"{name} failed: {e}"}


_METRIC_KEYS = list(_se.STAT_EXTRACTORS.keys())
_CATEGORICALS = list(_se.RECORD_CATEGORICALS)

# OpenAI function-calling schemas. Descriptions are written FOR the model so it picks
# the right tool: query_runs for filtered per-run/per-player stats, rank_leaders for
# career/feat leaderboards, the rest for cards / boards / rivalries / goals / server meta.
TOOL_SCHEMAS = [
    {'type': 'function', 'function': {
        'name': 'query_runs',
        'description': ("Per-run stats like the website's Stats Lab. Use for 'highest/best X' "
                        "single games and for per-player averages, optionally filtered by weapon, "
                        "map, faction, class, difficulty, VIP, etc. Metrics: kills, td (takedowns), "
                        "deaths, kd, lethality (kills/td), score (match points), kill_share, warlord, "
                        "dominance, tilt, marks, and more. Example: highest kills on Falmire -> "
                        "metric=kills, filters={map:'Falmire'}, mode=top_games."),
        'parameters': {'type': 'object', 'properties': {
            'metric': {'type': 'string', 'enum': _METRIC_KEYS,
                       'description': 'the stat to rank by'},
            'mode': {'type': 'string', 'enum': ['top_games', 'rank_players'],
                     'description': "top_games = best single games; rank_players = per-player avg/total"},
            'filters': {'type': 'object',
                        'description': ("exact-match filters, any of: " + ', '.join(_CATEGORICALS) +
                                        ", plus 'player'. e.g. {\"weapon\":\"Messer\",\"map\":\"Falmire\"}")},
            'agg': {'type': 'string', 'enum': ['avg', 'total'],
                    'description': 'for rank_players: average or total of the metric'},
            'min_games': {'type': 'integer', 'description': 'rank_players: min games to qualify (default 5)'},
            'limit': {'type': 'integer', 'description': 'max rows (default 10, cap 25)'},
            'ascending': {'type': 'boolean', 'description': 'true for lowest-first'},
        }, 'required': ['metric']}}},
    {'type': 'function', 'function': {
        'name': 'rank_leaders',
        'description': ("Server leaderboards for CAREER totals and FEAT counts (things query_runs "
                        "doesn't do): most career marks, most career kills/takedowns, most 100-kill / "
                        "200-takedown / Triple / Flawless / TUFF / Pacifist games, best K/D, highest "
                        "average score/takedowns, most games logged, most maps played, most VIP games, "
                        "most deaths, most Brutal/uphill lobbies. Give a metric id OR a natural question."),
        'parameters': {'type': 'object', 'properties': {
            'metric': {'type': 'string', 'enum': sorted(_AGG_IDS),
                       'description': 'the leaderboard metric id'},
            'weapon': {'type': 'string', 'description': "weapon name, for 'who plays X most' style"},
            'question': {'type': 'string', 'description': 'natural-language fallback to auto-match a metric'},
            'limit': {'type': 'integer', 'description': 'max leaders (default 10, cap 25)'},
        }}}},
    {'type': 'function', 'function': {
        'name': 'get_player_card',
        'description': ("One player's full stats: total marks, submissions, best kills / takedowns / "
                        "match-points games (with weapon+map), boards they hold and their rank, career "
                        "100-kill games, playstyle archetype and damage lean. Use for 'what are my/X's stats'."),
        'parameters': {'type': 'object', 'properties': {
            'player': {'type': 'string', 'description': 'player name, IGN, or discord id'}},
            'required': ['player']}}},
    {'type': 'function', 'function': {
        'name': 'get_board',
        'description': ("The ranking on ONE leaderboard (one row per player, best score), with its unit. "
                        "Board names: a weapon name (takedown board), '{Weapon} Kills' (kills board), "
                        "'{Map} - {Faction}' (map board), or a feat board like '100 Kills', 'Score', "
                        "'Pacifist', 'TUFF'. Call list_boards if unsure of the exact name."),
        'parameters': {'type': 'object', 'properties': {
            'board_name': {'type': 'string'},
            'limit': {'type': 'integer', 'description': 'top N (default 10, cap 25)'}},
            'required': ['board_name']}}},
    {'type': 'function', 'function': {
        'name': 'list_boards',
        'description': "Valid board names that have entries. Optional kind: weapon, map, feat, kills.",
        'parameters': {'type': 'object', 'properties': {
            'kind': {'type': 'string', 'enum': ['weapon', 'map', 'feat', 'kills']}}}}},
    {'type': 'function', 'function': {
        'name': 'server_overview',
        'description': ("Server-wide aggregates: totals and single-run records, community cadence "
                        "(runs/players per day, busiest day), RANKED most-played weapons/maps/subclasses "
                        "by runs, faction split, and per-weapon/per-map meta. Use for 'how active', "
                        "'top maps/weapons by runs', 'server averages', 'the meta'."),
        'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {
        'name': 'get_rivalries',
        'description': "A player's nemesis (most-faced foe) and closest ally (most-teamed), from shared lobbies.",
        'parameters': {'type': 'object', 'properties': {
            'player': {'type': 'string'}}, 'required': ['player']}}},
    {'type': 'function', 'function': {
        'name': 'head_to_head',
        'description': "Shared-lobby history between TWO players: meetings, sides, and each one's average TD/kills.",
        'parameters': {'type': 'object', 'properties': {
            'player_a': {'type': 'string'}, 'player_b': {'type': 'string'}},
            'required': ['player_a', 'player_b']}}},
    {'type': 'function', 'function': {
        'name': 'whats_next',
        'description': "A player's nearest goals: next weapon rank, next mastery/virtuoso, Hundred-Handed progress.",
        'parameters': {'type': 'object', 'properties': {
            'player': {'type': 'string'}}, 'required': ['player']}}},
]
