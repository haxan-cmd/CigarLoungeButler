"""Pure aggregation for two player-facing features:

  * Lounge Wrapped   — a per-player recap (Spotify-Wrapped style) over a window.
  * Season Superlatives — server-wide tongue-in-cheek awards over a window.

Both operate on submission rows in the Sheets-era shape returned by
db.get_all_submissions() (lists of strings), so this module has NO Discord or DB
dependency and is unit-tested in tests/test_wrapped.py. The cog scopes rows to a
season window and hands them here; rendering/narration lives in the cog.

Row indices (see CLAUDE.md submissions map):
  0 submitted_at · 3 weapon · 5 map · 6 faction · 7 takedowns · 8 kills ·
  9 deaths · 10 vip · 11 feats · 12 message_link · 24 score
"""
from datetime import datetime

# Valor tags written on the feats column by the tilt grader.
VALOR_TAGS = ("Brutal", "Outmatched", "Uphill")
# The maps the Butler considers kill-farms (his standing opinion); used by the
# "Farmer" superlative. The cog can override.
DEFAULT_FARM_MAPS = ("Falmire", "Darkforest")


def _i(v):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError, AttributeError):
        return 0


def _feats(row):
    return (row[11] or '') if len(row) > 11 else ''


def _hour(ts):
    try:
        return datetime.strptime(str(ts).strip(), '%Y-%m-%d %H:%M:%S').hour
    except Exception:
        return None


def _is_excluded(row):
    """Resubmit (old run re-uploaded) and Unlisted (mod-hidden) runs don't count."""
    f = _feats(row)
    return 'Resubmit' in f or 'Unlisted' in f


def _ident(row):
    """Stable identity key: discord_id when present, else name-lowercased."""
    did = (row[2] or '').strip() if len(row) > 2 else ''
    name = (row[1] or '').strip() if len(row) > 1 else ''
    return did or ('name:' + name.lower()), name


def build_wrapped(subs):
    """Per-player recap from THAT player's submissions (already scoped to the window
    and to one player). Returns a flat dict of display-ready numbers. Excludes
    Resubmit/Unlisted runs. Order-independent except the flawless streak, which is
    computed in submitted_at order."""
    subs = [r for r in subs if len(r) > 9 and not _is_excluded(r)]
    out = {
        'runs': 0, 'kills': 0, 'takedowns': 0, 'deaths': 0, 'kd': 0.0,
        'signature_weapon': None, 'signature_weapon_runs': 0,
        'signature_map': None, 'signature_map_runs': 0,
        'weapons_used': 0, 'maps_played': 0,
        'best_game': None, 'flawless_streak': 0,
        'carries': 0, 'triples': 0, 'hundred_kills': 0,
        'two_hundred_td': 0, 'flawless_runs': 0, 'night_runs': 0,
    }
    n = len(subs)
    out['runs'] = n
    if n == 0:
        return out
    wcount, mcount = {}, {}
    best = None  # (score, row)
    for r in subs:
        k, td, d = _i(r[8]), _i(r[7]), _i(r[9])
        out['kills'] += k
        out['takedowns'] += td
        out['deaths'] += d
        w = (r[3] or '').strip()
        m = (r[5] or '').strip()
        if w:
            wcount[w] = wcount.get(w, 0) + 1
        if m:
            mcount[m] = mcount.get(m, 0) + 1
        f = _feats(r)
        if any(t in f for t in VALOR_TAGS):
            out['carries'] += 1
        if 'Triple' in f:
            out['triples'] += 1
        if '100 Kills' in f:
            out['hundred_kills'] += 1
        if '200 Takedowns' in f:
            out['two_hundred_td'] += 1
        if d == 0 and td > 0 and not (k == 0 and td <= 10):
            out['flawless_runs'] += 1
        h = _hour(r[0])
        if h is not None and 0 <= h < 6:
            out['night_runs'] += 1
        sc = _i(r[24]) if len(r) > 24 else 0
        if best is None or sc > best[0]:
            best = (sc, r)
    out['weapons_used'] = len(wcount)
    out['maps_played'] = len(mcount)
    if wcount:
        sw = max(wcount, key=wcount.get)
        out['signature_weapon'], out['signature_weapon_runs'] = sw, wcount[sw]
    if mcount:
        sm = max(mcount, key=mcount.get)
        out['signature_map'], out['signature_map_runs'] = sm, mcount[sm]
    out['kd'] = round(out['kills'] / out['deaths'], 2) if out['deaths'] else float(out['kills'])
    if best:
        br = best[1]
        out['best_game'] = {
            'weapon': (br[3] or '').strip(), 'map': (br[5] or '').strip(),
            'takedowns': _i(br[7]), 'kills': _i(br[8]), 'deaths': _i(br[9]),
            'score': _i(br[24]) if len(br) > 24 else 0,
            'link': (br[12] or '').strip() if len(br) > 12 else '',
        }
    ordered = sorted(subs, key=lambda r: (r[0] or ''))
    cur = mx = 0
    for r in ordered:
        if _i(r[9]) == 0 and _i(r[7]) > 0:
            cur += 1
            mx = max(mx, cur)
        else:
            cur = 0
    out['flawless_streak'] = mx
    return out


def compute_superlatives(subs, farm_maps=DEFAULT_FARM_MAPS, min_games=3):
    """Server-wide awards over the window. Returns {award_key: {name, value, detail}}
    or omits an award with no eligible winner. Excludes Resubmit/Unlisted runs.

    Awards:
      martyr        most total deaths
      bloodbath     single highest-kill game
      glass_cannon  highest avg (kills+deaths) per game   (>= min_games)
      farmer        most runs on the farm maps
      comeback_king most valor runs (valor tags)
      one_trick     highest single-weapon share of runs   (>= min_games)
      night_shift   most runs logged between 00:00 and 06:00
      iron_will     most runs overall
    """
    subs = [r for r in subs if len(r) > 9 and not _is_excluded(r)]
    farm = {m.lower() for m in farm_maps}
    agg = {}  # key -> aggregates
    for r in subs:
        key, name = _ident(r)
        if not key:
            continue
        a = agg.setdefault(key, {
            'name': name, 'runs': 0, 'kills': 0, 'deaths': 0, 'carries': 0,
            'farm': 0, 'night': 0, 'best_kills': 0, 'best_kills_row': None,
            'weapons': {},
        })
        if name:
            a['name'] = name
        k, d = _i(r[8]), _i(r[9])
        a['runs'] += 1
        a['kills'] += k
        a['deaths'] += d
        f = _feats(r)
        if any(t in f for t in VALOR_TAGS):
            a['carries'] += 1
        if (r[5] or '').strip().lower() in farm:
            a['farm'] += 1
        h = _hour(r[0])
        if h is not None and 0 <= h < 6:
            a['night'] += 1
        if k > a['best_kills']:
            a['best_kills'] = k
            a['best_kills_row'] = r
        w = (r[3] or '').strip()
        if w:
            a['weapons'][w] = a['weapons'].get(w, 0) + 1

    if not agg:
        return {}

    def _winner(scorefn, eligible=lambda a: True, want_max=True):
        best = None
        for a in agg.values():
            if not eligible(a):
                continue
            v = scorefn(a)
            if v is None:
                continue
            if best is None or (v > best[1] if want_max else v < best[1]):
                best = (a, v)
        return best

    out = {}

    def _put(award, res, detail_fn):
        if res and res[1] and (isinstance(res[1], float) or res[1] > 0):
            a, v = res
            out[award] = {'name': a['name'], 'value': v, 'detail': detail_fn(a, v)}

    _put('martyr', _winner(lambda a: a['deaths']),
         lambda a, v: f"{v} deaths across {a['runs']} runs")
    _put('bloodbath', _winner(lambda a: a['best_kills']),
         lambda a, v: (f"{v} kills in a single game"
                       + (f" on {(a['best_kills_row'][5] or '').strip()}" if a['best_kills_row'] else "")))
    _put('glass_cannon',
         _winner(lambda a: round((a['kills'] + a['deaths']) / a['runs'], 1),
                 eligible=lambda a: a['runs'] >= min_games),
         lambda a, v: f"{v} kills+deaths per game, {a['runs']} runs")
    _put('farmer', _winner(lambda a: a['farm']),
         lambda a, v: f"{v} runs on the farm maps")
    _put('comeback_king', _winner(lambda a: a['carries']),
         lambda a, v: f"{v} valor run{'' if v == 1 else 's'}")
    _put('one_trick',
         _winner(lambda a: round(max(a['weapons'].values()) / a['runs'] * 100) if a['weapons'] else 0,
                 eligible=lambda a: a['runs'] >= min_games),
         lambda a, v: (f"{v}% of runs on {max(a['weapons'], key=a['weapons'].get)}" if a['weapons'] else ""))
    _put('night_shift', _winner(lambda a: a['night']),
         lambda a, v: f"{v} runs after midnight")
    _put('iron_will', _winner(lambda a: a['runs']),
         lambda a, v: f"{v} runs submitted")
    return out


# Human-readable award titles + the Butler's angle, for the cog to render.
SUPERLATIVE_TITLES = {
    'iron_will':     ("\U0001f3c5 The Tireless", "most runs submitted"),
    'bloodbath':     ("\U0001fa78 Bloodbath", "highest single-game kills"),
    'comeback_king': ("\U0001f396️ The Valorous", "most valor runs (Uphill, Outmatched, Brutal)"),
    'martyr':        ("⚰️ The Martyr", "most deaths, forward and swinging"),
    'glass_cannon':  ("\U0001f4a5 Glass Cannon", "lands everything, survives nothing"),
    'one_trick':     ("\U0001f3b0 One-Trick Pony", "most devoted to a single weapon"),
    'farmer':        ("\U0001f33e The Farmer", "most runs on the padding maps"),
    'night_shift':   ("\U0001f989 Night Shift", "most after-midnight submissions"),
}
