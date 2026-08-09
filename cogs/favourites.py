# Stats calculation, Butler Monthly embed, title role assignment, and /butlers_report.
import time
import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands

import config
import utils.db as _db

MOD_ROLE_ID                = config.MOD_ROLE_ID
MAIN_CHANNEL_ID            = config.MAIN_CHANNEL_ID
BUTLERS_FAVOURITES_CHANNEL_ID = config.BUTLERS_FAVOURITES_CHANNEL_ID
DECORATION_TOP             = config.DECORATION_TOP
DECORATION_BOTTOM          = config.DECORATION_BOTTOM
WEAPON_RANK_THRESHOLDS     = config.WEAPON_RANK_THRESHOLDS
PRESTIGE_THRESHOLDS        = config.PRESTIGE_THRESHOLDS
CLASS_RANKS                = config.CLASS_RANKS
SUBCLASS_RANKS             = config.SUBCLASS_RANKS
PLAYER_TITLES              = config.PLAYER_TITLES
GRAND_MARSHAL_ROLE_ID      = config.GRAND_MARSHAL_ROLE_ID
WEAPONS_MASTER_ROLE_ID     = config.WEAPONS_MASTER_ROLE_ID
CAMPAIGN_MASTER_ROLE_ID    = config.CAMPAIGN_MASTER_ROLE_ID
MOST_LETHAL_ROLE_ID        = config.MOST_LETHAL_ROLE_ID
WARLORD_ROLE_ID            = config.WARLORD_ROLE_ID

_butlers_report_cooldowns = {}

# Memoised results of the (expensive) aggregate below. Keyed on the window PLUS
# a data version that bumps on every submissions/leaderboard write, so an entry
# can never go stale — a write changes the key rather than needing invalidation.
# Worth it because this scans both tables in Python and is called repeatedly:
# once per Butler data question, once per /season_standings, and once PER SEASON
# inside the Hall of Fame index rebuild.
# NOTE: returned dicts are shared references — treat them read-only, same
# contract as the db-layer cache.
_STATS_MEMO: dict = {}
_STATS_MEMO_MAX = 12


async def calculate_butler_stats(week_start=None, week_end=None):
    _ver = _db.data_version('submissions', 'leaderboard_data')
    _key = (week_start, week_end, _ver)
    _hit = _STATS_MEMO.get(_key)
    if _hit is not None:
        return _hit
    # Any version bump makes every older entry unreachable; drop them so the memo
    # cannot grow without bound.
    for _k in [k for k in _STATS_MEMO if k[2] != _ver]:
        _STATS_MEMO.pop(_k, None)
    _result = await _calculate_butler_stats_uncached(week_start, week_end)
    if len(_STATS_MEMO) >= _STATS_MEMO_MAX:
        _STATS_MEMO.pop(next(iter(_STATS_MEMO)), None)
    _STATS_MEMO[_key] = _result
    return _result


async def _calculate_butler_stats_uncached(week_start=None, week_end=None):
    # week_start/end are UTC timestamps — if passed, submission stats are scoped to that window.
    # Title holders (Grand Marshal etc.) always use all-time data regardless.
    all_subs = await _db.get_all_submissions()
    ld = await _db.get_all_leaderboard_data()

    # Filter subs to week window if provided
    if week_start is not None and week_end is not None:
        filtered = []
        for row in all_subs:
            if not row or not row[0].strip():
                continue
            try:
                ts = datetime.strptime(row[0].strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
                if week_start <= ts < week_end:
                    # Skip resubmissions (old runs, not new weekly activity) and
                    # unlisted runs (mod-excluded from boards/records by /unlist_submission)
                    feats_col = row[11].strip() if len(row) > 11 else ""
                    if "Resubmit" in feats_col or "Unlisted" in feats_col:
                        continue
                    filtered.append(row)
            except Exception:
                pass
        subs = filtered
    else:
        subs = all_subs

    # Submission stats
    player_counts = {}
    weapon_counts = {}
    map_counts = {}
    top_td = (0, "")
    top_kills = (0, "")
    td_scores_sub = {}
    kills_scores_sub = {}
    players_set = set()
    lethal_ratios = {}       # player -> [kills/td ratios]
    lobby_finishes = {}      # player -> [(rank, size), ...]
    team_score_ratios = {}   # player -> [your_td / avg_teammate_td]
    kill_efficiency = {}     # player -> [(your_kills, total_lobby_kills, lobby_size)]
    team_kill_shares = {}    # player -> [team kill share %]   (Kill Share: kills / team kills)
    warlord_ratios = {}      # player -> [takedowns / team total kills %]  (Warlord)
    team_td_shares = {}      # player -> [team TD share %]
    weapon_kill_shares = {}  # weapon -> [kill share %]
    weapon_td_shares = {}    # weapon -> [TD share %]

    for row in subs:
        if len(row) < 9:
            continue
        player = row[1].strip()
        weapon = row[3].strip()
        map_name = row[5].strip()
        try:
            td = int(row[7])
            kills = int(row[8])
        except (ValueError, IndexError):
            td, kills = 0, 0

        player_counts[player] = player_counts.get(player, 0) + 1
        weapon_counts[weapon] = weapon_counts.get(weapon, 0) + 1
        map_counts[map_name] = map_counts.get(map_name, 0) + 1
        players_set.add(player)
        td_scores_sub[player] = max(td_scores_sub.get(player, 0), td)
        kills_scores_sub[player] = max(kills_scores_sub.get(player, 0), kills)
        # VIP runs count as activity above, but are excluded from every CONVERSION rating
        # below (Lethality, Kill Share, Warlord, kill efficiency, team shares): a VIP run's
        # inflated kills would skew the season rate-titles, matching the board ratings.
        _vip = str(row[10]).strip().upper() in ('TRUE', '1', 'YES') if len(row) > 10 and row[10] else False
        if _vip:
            continue
        # Lethality: kill rate (kills/td)
        if kills > 0 and td > 0:
            lethal_ratios.setdefault(player, []).append(kills / td)
        # Lobby TD rank for Warlord fallback (cols 14/15, index 13/14)
        try:
            lr = int(row[13]) if len(row) > 13 and row[13] else None
            ls = int(row[14]) if len(row) > 14 and row[14] else None
            if lr and ls and 1 < ls <= 64:
                lobby_finishes.setdefault(player, []).append((lr, ls))
        except (ValueError, TypeError):
            pass
        # Warlord: team score ratio (col 20, index 19 — your TD / avg teammate TD)
        try:
            tsr = float(row[19]) if len(row) > 19 and row[19] else None
            if tsr and tsr > 0:
                team_score_ratios.setdefault(player, []).append(tsr)
        except (ValueError, TypeError):
            pass
        # Lethality v2: kill efficiency vs lobby (col 19 index 18 / col 15 index 14)
        try:
            tlk = int(row[18]) if len(row) > 18 and row[18] else None  # total_lobby_kills col 19
            ls2 = int(row[14]) if len(row) > 14 and row[14] else None
            if tlk and tlk > 0 and kills > 0 and ls2 and 1 < ls2 <= 64:
                kill_efficiency.setdefault(player, []).append((kills, tlk, ls2))
        except (ValueError, TypeError):
            pass
        # Team kill share and TD share (cols 20/21)
        try:
            tks = float(row[20]) if len(row) > 20 and row[20] else None
            if tks and 0 < tks <= 100:
                team_kill_shares.setdefault(player, []).append(tks)
                if weapon:
                    weapon_kill_shares.setdefault(weapon, []).append(tks)
                # Warlord = takedowns / team total kills. team_total_kills = kills / kill-share,
                # so takedowns / team_total_kills reduces to takedowns * tks / kills.
                if kills > 0 and td > 0:
                    warlord_ratios.setdefault(player, []).append(td * tks / kills)
        except (ValueError, TypeError):
            pass
        try:
            tds = float(row[21]) if len(row) > 21 and row[21] else None
            if tds and 0 < tds <= 100:
                team_td_shares.setdefault(player, []).append(tds)
                if weapon:
                    weapon_td_shares.setdefault(weapon, []).append(tds)
        except (ValueError, TypeError):
            pass

    # ── PER-WEAPON averages (min 3 runs) ──
    def _weapon_avg(d, min_runs=3):
        return {w: round(sum(v)/len(v), 1) for w, v in d.items() if len(v) >= min_runs}

    weapon_kill_avgs = _weapon_avg(weapon_kill_shares)
    weapon_td_avgs   = _weapon_avg(weapon_td_shares)

    top_weapons_by_kill_share = sorted(weapon_kill_avgs.items(), key=lambda x: -x[1])[:5]
    top_weapons_by_td_share   = sorted(weapon_td_avgs.items(),   key=lambda x: -x[1])[:5]

    most_active = max(player_counts, key=player_counts.get) if player_counts else "N/A"
    top_weapons = sorted(weapon_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_maps = sorted(map_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_busiest = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_td_list = sorted(td_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]
    top_kills_list = sorted(kills_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]

    # PEAK ranking for the ratio categories: rank each player by their single best
    # 5-game run (a contiguous streak) inside the season window, taken as a MAX so it
    # NEVER drops. Hitting a season peak is locked in, and every later game is a free
    # shot at a higher peak with zero downside -- so players stay incentivised to keep
    # playing. Mirrors the all-time board ratings (leaderboards.py _peak), scoped to the
    # season here. The 5-game window + 5-game minimum stop one lucky game topping a board.
    _WINDOW = 5     # games in a "run"
    # Minimum games to qualify for a SEASON rate board / title (Kill Share, Warlord,
    # Dominance). Higher than the all-time boards' 5 on purpose: a season is ~a month, and a
    # 7-game sample topping a title (and colliding with the incumbency logic) is exactly the
    # low-sample noise we don't want. Tunable via config.SEASON_RATE_MIN_GAMES.
    _MIN = max(5, int(getattr(config, 'SEASON_RATE_MIN_GAMES', 10)))

    def _peak_rank(data):
        ranked = []
        for p, v in data.items():   # v is chronological (oldest first)
            if len(v) < _MIN:
                continue
            w = min(_WINDOW, len(v))
            best = max(sum(v[i:i + w]) / w for i in range(len(v) - w + 1))
            ranked.append((p, best, len(v)))
        ranked.sort(key=lambda t: (-t[1], t[0]))  # name tiebreak = stable order on ties
        return ranked

    # ── KILL SHARE -- volume-adjusted kills ÷ team total kills % (games in parens) ──
    # Board display + season category points. Carries no role: the Executioner
    # title moved to true Lethality below, which is what its name always implied.
    _leth = _peak_rank(team_kill_shares)
    most_lethal_top5 = [f"{p} -- {adj:.1f} ({n})" for p, adj, n in _leth[:5]]

    # ── WARLORD -- volume-adjusted takedowns ÷ team total kills % ──
    _dom = _peak_rank(warlord_ratios)
    dom_ranked = [p for p, _adj, _n in _dom]
    most_dominant = [f"{p} -- {adj:.1f} ({n})" for p, adj, n in _dom[:5]]
    warlord_player = dom_ranked[0] if dom_ranked else None

    # ── LETHALITY -- weapon-agnostic kills ÷ takedowns %. CONTEXT ONLY now: it's a ratio
    # you can inflate by taking FEWER takedowns, so it's shown but no longer competed for
    # (the Executioner title moved to Dominance below).
    _true_leth = _peak_rank(lethal_ratios)
    lethality_list = [f"{p} -- {adj * 100:.1f} ({n})" for p, adj, n in _true_leth[:5]]

    # ── DOMINANCE -- harmonic mean of peak Kill Share% and peak Warlord%. The Executioner
    # title is decided on THIS: genuine two-way impact you can't fake by min-maxing one axis
    # (rat for kills, or farm takedowns) while tanking the other. Needs 5+ games on BOTH,
    # which _peak_rank already enforces for each.
    from utils.ratings import dominance as _dom_fn
    _ks_peak = {p: v for p, v, _n in _leth}   # _leth = peak Kill Share
    _wl_peak = {p: v for p, v, _n in _dom}    # _dom  = peak Warlord
    _wl_n = {p: n for p, _v, n in _dom}
    _dominance = sorted(
        ((p, _dom_fn(_wl_peak[p], _ks_peak[p]), _wl_n.get(p, 0))
         for p in (set(_ks_peak) & set(_wl_peak))),
        key=lambda t: (-t[1], t[0]))
    dominance_list = [f"{p} -- {adj:.1f} ({n})" for p, adj, n in _dominance[:5]]
    dominance_player = _dominance[0][0] if _dominance else None

    # Some players have scores in LeaderboardData that predate the Submissions tab —
    # backfill their counts and best scores so they show up correctly in the report.
    # Skip in weekly mode — ld is all-time and would contaminate weekly stats.
    if week_start is None:
        ld_player_boards = {}  # player -> set of board names they appear on
        for row in ld:
            if len(row) < 4:
                continue
            lb_name = row[0].strip()
            player = row[1].strip()
            if not player:
                continue
            try:
                score = int(row[3])
            except (ValueError, IndexError):
                score = 0
            ld_player_boards.setdefault(player, set()).add(lb_name)
            if lb_name == '200 Takedowns':
                td_scores_sub[player] = max(td_scores_sub.get(player, 0), score)
            elif lb_name == '100 Kills':
                kills_scores_sub[player] = max(kills_scores_sub.get(player, 0), score)
        for player, boards in ld_player_boards.items():
            players_set.add(player)
            player_counts[player] = player_counts.get(player, 0) + len(boards)
        top_busiest = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_td_list = sorted(td_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]
        top_kills_list = sorted(kills_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]

    # Title calculations from LeaderboardData
    weapon_placements = {}
    map_placements = {}

    from utils.boards import non_weapon_feat_boards, is_kills_board, is_archer_weapon
    SKIP_LB = {'100 Kills', '200 Takedowns'}
    # Non-weapon feat boards (Score, TUFF, Pacifist, Triple, Hybrid, Flawless,
    # Healing…) are their own category: they count toward NEITHER Weapons Master NOR
    # Grand Marshal. Grand Marshal is exactly Weapons Master (weapon boards) + Campaign
    # Master (map boards), so its count always reconciles as weapons + maps and never
    # exceeds the weapon+map denominator. Single source in utils.boards (tested) so a new
    # feat board can't silently leak into the weapon count.
    NON_WEAPON_FEAT_BOARDS = non_weapon_feat_boards()

    lb_groups = {}
    for row in ld:
        if len(row) < 4:
            continue
        lb_name = row[0].strip()
        _lo = lb_name.lower()
        if (not lb_name or _lo == 'none' or _lo.startswith('none -')
                or lb_name.startswith(' - ') or lb_name.endswith(' - ')):
            continue  # junk board (missing map/weapon name)
        player = row[1].strip()
        try:
            score = int(row[3]) if row[3] else 0
        except (ValueError, TypeError):
            score = 0
        lb_groups.setdefault(lb_name, []).append((player, score))

    _weapon_board_set, _map_board_set = set(), set()   # distinct boards per title universe
    for lb_name, entries in lb_groups.items():
        if lb_name in SKIP_LB:
            continue
        if is_kills_board(lb_name):
            continue   # a weapon's Highest-Kills companion is NOT a separate weapon board
        if is_archer_weapon(lb_name):
            continue   # Archer/ranged weapons don't count toward the melee titles
                       # (Weapons Master / Grand Marshal) by policy
        is_map = ' - ' in lb_name
        if is_map:
            _map_board_set.add(lb_name)
        elif lb_name not in NON_WEAPON_FEAT_BOARDS:
            _weapon_board_set.add(lb_name)
        ranked_entries = sorted(entries, key=lambda t: -t[1])
        for i, (player, _sc) in enumerate(ranked_entries[:10]):
            placement = i + 1
            if is_map:
                map_placements.setdefault(player, []).append(placement)
            elif lb_name in NON_WEAPON_FEAT_BOARDS:
                continue   # feat boards count toward no all-time title (kept out of both)
            else:
                weapon_placements.setdefault(player, []).append(placement)

    def best_placement_title(d, min_boards=1, breadth_first=False):
        if not d:
            return None
        qualified = {p: v for p, v in d.items() if len(v) >= min_boards}
        if not qualified:
            return None
        if breadth_first:
            return min(qualified.keys(), key=lambda p: (-len(qualified[p]), sum(qualified[p]) / len(qualified[p])))
        else:
            return min(qualified.keys(), key=lambda p: (sum(qualified[p]) / len(qualified[p]), -len(qualified[p])))

    # Grand Marshal = Weapons Master boards + Campaign Master boards, nothing else, so
    # a player's combined count is always weapon placements + map placements and can
    # never exceed the weapon+map total (feat boards are deliberately excluded).
    combined = {}
    for p, v in weapon_placements.items():
        combined.setdefault(p, []).extend(v)
    for p, v in map_placements.items():
        combined.setdefault(p, []).extend(v)

    grand_marshal = best_placement_title(combined, min_boards=15, breadth_first=True)
    weapons_master = best_placement_title(weapon_placements, min_boards=9, breadth_first=True)
    campaign_master = best_placement_title(map_placements, min_boards=6, breadth_first=True)

    # Apex / Frenzied — ROLLING WEEKLY window: highest AVERAGE among a player's
    # qualifying runs *this week* (100+ kills / 200+ takedowns), min 3 runs. These
    # two titles (and their roles) rotate weekly; Grand Marshal / Weapons Master /
    # Campaign Master stay all-time. Computed from the week-scoped `subs`.
    kills_scores = {}
    td_scores = {}
    for row in subs:
        if len(row) < 9:
            continue
        player = row[1].strip()
        try:
            _td = int(row[7]); _kills = int(row[8])
        except (ValueError, IndexError):
            continue
        if _kills >= 100:
            kills_scores.setdefault(player, []).append(_kills)
        if _td >= 200:
            td_scores.setdefault(player, []).append(_td)

    def best_score_title(d, min_runs=3):
        eligible = {p: v for p, v in d.items() if len(v) >= min_runs}
        if not eligible:
            return None
        return max(eligible, key=lambda p: round(sum(eligible[p]) / len(eligible[p])))

    apex = best_score_title(kills_scores)
    frenzied = best_score_title(td_scores)

    # (Fastest Learner was retired from the report; its PB-history pass is gone too.)

    # Total Tally — most total takedowns accumulated this week (the grind race).
    _tally = {}
    for _row in subs:
        if len(_row) < 8:
            continue
        try:
            _t = int(_row[7])
        except (ValueError, IndexError):
            continue
        _pn = _row[1].strip()
        _tally[_pn] = _tally.get(_pn, 0) + _t
    top_total_tally = sorted(_tally.items(), key=lambda x: (-x[1], x[0]))[:5]

    return {
        'top_busiest': top_busiest,
        'top_td_list': top_td_list,
        'top_kills_list': top_kills_list,
        'top_weapons': [(w, c) for w, c in top_weapons],
        'top_maps': [(m, c) for m, c in top_maps],
        'total_runs': len(subs),
        'total_players': len(players_set),
        'grand_marshal': grand_marshal or "N/A",
        'weapons_master': weapons_master or "N/A",
        'campaign_master': campaign_master or "N/A",
        '_weapon_placements': weapon_placements,
        '_map_placements': map_placements,
        '_combined_placements': combined,
        '_weapon_board_total': len(_weapon_board_set),
        '_map_board_total': len(_map_board_set),
        '_combined_board_total': len(_weapon_board_set) + len(_map_board_set),
        'apex': apex or "N/A",
        'frenzied': frenzied or "N/A",
        'top_total_tally': top_total_tally,
        'high_lethality': most_lethal_top5 if most_lethal_top5 else [],   # Kill Share board
        'most_lethal_player': dominance_player,                           # Executioner = Dominance #1
        'warlord_player': warlord_player,
        'most_dominant': most_dominant if most_dominant else [],
        'lethality_list': lethality_list if lethality_list else [],       # context only, no title
        'dominance_list': dominance_list if dominance_list else [],
        # Incumbency margin compares like with like: the Executioner is now decided on
        # Dominance, so its scores must come from _dominance (not raw lethality).
        '_lethal_adj': {p: adj for p, adj, _n in _dominance},
        '_warlord_adj': {p: adj for p, adj, _n in _dom},
        'top_weapons_by_kill_share': top_weapons_by_kill_share,
        'top_weapons_by_td_share': top_weapons_by_td_share,
    }


async def build_favourites_embed(stats, bot_avatar_url=None):
    import discord as _discord

    def _short(nm, m=18):
        nm = str(nm)
        return nm if len(nm) <= m else nm[:m - 1] + "…"

    def _table(rows):
        # Monospace table: left column left-justified, right column right-justified,
        # so the numbers line up vertically. rows = [(left, right)].
        rows = [(str(l), str(r)) for l, r in rows]
        if not rows:
            return "```\n—\n```"
        lw = max(len(l) for l, _ in rows)
        rw = max(len(r) for _, r in rows)
        body = "\n".join(f"{l:<{lw}}  {r:>{rw}}" for l, r in rows)
        return "```\n" + body + "\n```"

    def _rows(items, plain=False, n=5):
        out = []
        for it in (items or [])[:n]:
            if plain and isinstance(it, str):
                nm, _, v = it.partition(" -- ")
                out.append((_short(nm.strip()), v.strip()))
            elif isinstance(it, (list, tuple)) and it:
                out.append((_short(str(it[0]).strip()), str(it[1]) if len(it) > 1 else ""))
        return out

    _RULE = "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"
    week_label = stats.get("week_label", "")
    title = "📋  Butler Monthly" + (f"   {week_label}" if week_label else "")
    _greet = ""
    try:
        import random as _r
        from cogs.leaderboards import _ENTRANCE_GREETINGS
        _greet = "*" + _r.choice(_ENTRANCE_GREETINGS) + "*\n\n"
    except Exception:
        pass
    desc = _greet + f"*{stats['total_runs']} runs · {stats['total_players']} players*"
    embed = _discord.Embed(title=title, description=desc, color=0x8b6914)
    _banner = getattr(config, 'LEDGER_BANNER_URL', '') or ''
    if _banner:
        embed.set_image(url=_banner)
    if bot_avatar_url:
        embed.set_thumbnail(url=bot_avatar_url)

    _season = await _db.get_current_season()
    if _season:
        # Season end indicator. No hard end date is stored (a mod closes the season with
        # /bounty_end), so estimate it from the monthly cadence — ~1 month after the start —
        # and mark it approximate. Prominent at the top of the season block.
        try:
            from datetime import datetime as _dt
            import calendar as _cal
            _st = _season.get('started_at')
            if _st:
                _stn = _st.replace(tzinfo=None) if getattr(_st, 'tzinfo', None) else _st
                _em, _ey = ((1, _stn.year + 1) if _stn.month == 12 else (_stn.month + 1, _stn.year))
                _last = _cal.monthrange(_ey, _em)[1]
                _end = _stn.replace(year=_ey, month=_em, day=min(_stn.day, _last))
                _days = (_end - _dt.utcnow()).days
                _tl = f"Started {_stn:%b %d}"
                if _days > 1:
                    _tl += f" · **{_days} days left** · ends ~{_end:%b %d}"
                elif _days >= 0:
                    _tl += f" · **ends within a day** (~{_end:%b %d})"
                else:
                    _tl += " · **past its month** — ends whenever a mod closes it"
                embed.add_field(name="🗓️ Season timeline  *(end date approximate)*",
                                value=_tl, inline=False)
        except Exception as _tle:
            print(f"[REPORT] season timeline error: {_tle}")
        _standings, _core, _featured = await season_total(_season)
        if _standings and getattr(config, 'SEASON_GP_CHAMPION', True):
            crows = [(f"{i:>2} {_short(nm, 16)}", f"{pts} pts") for i, (nm, pts) in enumerate(_standings[:10], 1)]
            embed.add_field(name="🏁 Championship", value=_table(crows), inline=False)
        embed.add_field(name=_RULE, value="​", inline=False)
        if _featured:
            frows = [((f"{lbl}: {focus}"), (f"{top[0][0]} ({top[0][1]})" if top else "—"))
                     for lbl, focus, top in _featured]
            embed.add_field(name="⭐ Special Features  *(random this season)*", value=_table(frows), inline=False)
        embed.add_field(name=_RULE, value="​", inline=False)

    embed.add_field(name="<a:mostlethal:1520490418817601658> Kill Share  *(kills ÷ team kills · best 5-game run)*",
                    value=_table(_rows(stats.get("high_lethality"), plain=True)) if stats.get("high_lethality") else "```\n— not enough data —\n```",
                    inline=False)
    embed.add_field(name="<:warlord:1520490364039860347> Warlord  *(takedowns ÷ team kills · best 5-game run)*",
                    value=_table(_rows(stats.get("most_dominant"), plain=True)) if stats.get("most_dominant") else "```\n— not enough data —\n```",
                    inline=False)
    embed.add_field(name="<a:dominance:1535424879711752233> Dominance  *(Warlord + Kill Share · best 5-game run)*",
                    value=_table(_rows(stats.get("dominance_list"), plain=True)) if stats.get("dominance_list") else "```\n— not enough data —\n```",
                    inline=False)
    # Lethality dropped from the MONTHLY board: it carries no title or GP here, and as a
    # ratio it's gameable, so competing for it on the season board was misleading. It's
    # still shown everywhere it's descriptive (run blurbs, the registry card, all-time boards).

    _tt = stats.get("top_total_tally") or []
    embed.add_field(name="<a:200tkd:1363648828414230538> Total Tally  *(takedowns)*",
                    value=_table([(_short(n), f"{v:,}") for n, v in _tt[:5]]) if _tt else "```\n—\n```",
                    inline=False)

    embed.add_field(name="<a:topkill:1360314538364240024> Most Kills",
                    value=_table(_rows(stats.get("top_kills_list"))), inline=False)
    embed.add_field(name="<a:toptkd:1360312666475728958> Highest Takedowns",
                    value=_table(_rows(stats.get("top_td_list"))), inline=False)
    # 'Busiest' (most submissions) was dropped: it double-counted volume with Total Tally
    # above (same grinders, same order), so Total Tally is the single volume stat now.

    embed.add_field(name="─── Meta ───", value="​", inline=False)
    embed.add_field(name="🗡️ Top Weapons", value=_table(_rows(stats.get("top_weapons"))), inline=False)
    embed.add_field(name="🗺️ Top Maps", value=_table(_rows(stats.get("top_maps"))), inline=False)

    embed.set_footer(text=("Kill Share / Warlord / Lethality here are your best 5-game run for THIS "
                           "season (5+ games) -- a season peak that never drops, so keep playing to beat "
                           "it. The all-time boards show the same over your whole history. Most Dominant goes "
                           "to the Dominance leader, Warlord to the Warlord leader; a challenger must beat "
                           "the holder by 1%."))
    return embed


async def update_title_roles(guild, stats, include_weekly=True):
    main_channel = guild.get_channel(MAIN_CHANNEL_ID)

    title_configs = [
        ('grand_marshal', GRAND_MARSHAL_ROLE_ID, 'Grand Marshal',
         "After careful review of the battlefield records, I must inform {old} that your commission has been reassigned. {new}, the Grand Marshal's standard is yours to carry. Try not to embarrass the household."),
        ('weapons_master', WEAPONS_MASTER_ROLE_ID, 'Weapons Master',
         "It appears the armory has a new curator. {old}, your weapons have been... redistributed. {new}, the Weapons Master title is yours. Do try to keep the blades sharp."),
        ('campaign_master', CAMPAIGN_MASTER_ROLE_ID, 'Campaign Master',
         "The campaign maps have been redrawn. {old}, your routes have been rerouted. {new}, you are hereby appointed Campaign Master. The butler expects nothing less than total domination."),
        ('most_lethal_player', MOST_LETHAL_ROLE_ID, 'Dominance',
         "The two-way tallies have been reviewed. {old}, your grip has slipped. {new}, the Most Dominant title is yours. Takedowns and kills both, no min-maxing. The butler is mildly impressed."),
        ('warlord_player', WARLORD_ROLE_ID, 'Warlord',
         "The TD tallies have been reviewed. {old}, your dominance has waned. {new}, the Warlord title is yours. The butler acknowledges your presence on the battlefield."),
    ]

    for stat_key, role_id, title_name, msg_template in title_configs:
        # Most Lethal / Warlord are volatile season stats. Keep reassigning the
        # role live on every submission (behaviour unchanged), but only ANNOUNCE
        # the change on the weekly pass — otherwise the flip-flop spams chat.
        announce = True
        if not include_weekly and stat_key in ('most_lethal_player', 'warlord_player'):
            announce = False
        new_holder_name = stats.get(stat_key, 'N/A')
        if new_holder_name == 'N/A':
            continue

        role = guild.get_role(role_id)
        if not role:
            continue

        current_holders = [m for m in guild.members if role in m.roles]

        new_member = discord.utils.find(
            lambda m: new_holder_name and (m.nick or m.display_name or '').lower() == new_holder_name.lower(),
            guild.members
        )
        if not new_member:
            continue

        if current_holders and new_member in current_holders:
            continue

        # Volatile season titles (Executioner / Warlord) recompute on every
        # submission, and the Bayesian league mean shifts whenever ANYONE plays,
        # which made the role thrash between two near-tied players who had not even
        # submitted. Require a challenger to clearly beat the incumbent before we
        # take the title off them, so a hair's-width or mean-shift wobble cannot flip it.
        # Margin is 1%, NOT 3%: shrinkage compresses the field so hard that the whole
        # top five spans ~2.5%, and a 3% margin was wider than the entire spread —
        # it made the title permanent for whoever claimed it first.
        _score_key = {'most_lethal_player': '_lethal_adj', 'warlord_player': '_warlord_adj'}.get(stat_key)
        if _score_key and current_holders:
            _scores = stats.get(_score_key) or {}
            def _member_score(mem, _sc=_scores):
                _nm = (mem.nick or mem.display_name or '').lower()
                for _p, _v in _sc.items():
                    if _p.lower() == _nm:
                        return _v
                return None
            _chal = _scores.get(new_holder_name)
            if _chal is None:
                _chal = _member_score(new_member)
            _inc = max((x for x in (_member_score(m) for m in current_holders) if x is not None), default=None)
            if _inc is not None and _chal is not None and _chal <= _inc * 1.01:
                continue  # incumbent still within 1% -> keep the title, no thrash

        for old_member in current_holders:
            try:
                await old_member.remove_roles(role)
            except Exception:
                pass

        try:
            await new_member.add_roles(role)
        except Exception:
            pass

        if main_channel and current_holders and announce:
            old_name = current_holders[0].display_name
            new_name = new_member.display_name
            msg = msg_template.format(old=f"**{old_name}**", new=f"**{new_name}**")
            try:
                await main_channel.send(msg, allowed_mentions=discord.AllowedMentions.none())
            except Exception as e:
                print(f"Title announcement error: {e}")


_SEASON_CATEGORIES = [
    ("Kill Share", "high_lethality", True),
    ("Warlord", "most_dominant", True),
    ("Total Tally", "top_total_tally", False),
    ("Most Kills", "top_kills_list", False),
    ("Highest Takedowns", "top_td_list", False),
]
# Top-5 pay 5/4/3/2/1 (was top-3 at 3/2/1): a category win matches the best
# bounty-race payout, and mid-table players hold real points worth defending.
_GP_POINTS = [5, 4, 3, 2, 1]

# Per-category icons, matching the season board, for /standings and /season.
_CATEGORY_EMOJI = {
    "Kill Share":        "<a:mostlethal:1520490418817601658>",
    "Warlord":           "<:warlord:1520490364039860347>",
    "Total Tally":       "<a:200tkd:1363648828414230538>",
    "Most Kills":        "<a:topkill:1360314538364240024>",
    "Highest Takedowns": "<a:toptkd:1360312666475728958>",
}


def _cat_names(items, plain=False):
    out = []
    for it in (items or [])[:len(_GP_POINTS)]:
        if plain and isinstance(it, str):
            out.append(it.split(" -- ", 1)[0].strip())
        elif isinstance(it, (list, tuple)) and it and it[0]:
            out.append(str(it[0]).strip())
    return out


def _cat_pairs(items, plain=False):
    """[(name, value_str)] for a category's top-5, normalising the two shapes
    calculate_butler_stats produces: "name -- value" strings for the rate
    categories, (name, value) tuples for the count ones."""
    out = []
    for it in (items or [])[:len(_GP_POINTS)]:
        if plain and isinstance(it, str):
            nm, _, val = it.partition(" -- ")
            out.append((nm.strip(), val.strip()))
        elif isinstance(it, (list, tuple)) and it and it[0]:
            out.append((str(it[0]).strip(), str(it[1]) if len(it) > 1 else ""))
    return out


def _ordinal_gp(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _cat_top(items, plain=False):
    for it in (items or [])[:1]:
        if plain and isinstance(it, str):
            nm, _, val = it.partition(" -- ")
            return nm.strip(), val.strip()
        if isinstance(it, (list, tuple)) and it and it[0]:
            return str(it[0]).strip(), (str(it[1]) if len(it) > 1 else "")
    return None, ""


async def compute_season_standings(started_at, ended_at, bonuses):
    """Grand Prix points over the season window: top-5 per category = 5/4/3/2/1,
    summed per player, plus bounty-race bonuses. Returns (standings, stats)."""
    from datetime import datetime, timezone
    start_ts = started_at.timestamp() if hasattr(started_at, "timestamp") else float(started_at)
    if ended_at:
        end_ts = ended_at.timestamp() if hasattr(ended_at, "timestamp") else float(ended_at)
    else:
        end_ts = datetime.now(timezone.utc).timestamp()
    stats = await calculate_butler_stats(week_start=start_ts, week_end=end_ts)
    points = {}
    for _cat, key, plain in _SEASON_CATEGORIES:
        for i, nm in enumerate(_cat_names(stats.get(key), plain)):
            points[nm] = points.get(nm, 0) + _GP_POINTS[i]
    for nm, bp in (bonuses or {}).items():
        points[nm] = points.get(nm, 0) + bp
    return sorted(points.items(), key=lambda x: (-x[1], x[0])), stats


async def roll_featured(season_id):
    """Randomly pick the season's 4 featured focuses: a 1H weapon, a 2H weapon,
    and two maps. Inverse-frequency weighted (overplayed picks are rare) and
    never repeats the previous season's pick in the same slot."""
    import random
    subs = await _db.get_all_submissions()
    wcount, mcount = {}, {}
    for r in subs:
        if len(r) < 6:
            continue
        w = r[3].strip() if r[3] else ""
        m = r[5].strip() if r[5] else ""
        if w:
            wcount[w] = wcount.get(w, 0) + 1
        if m:
            mcount[m] = mcount.get(m, 0) + 1
    prev = {}
    fins = await _db.get_finished_seasons()
    if fins:
        prev = await _db.get_season_features(fins[0]["id"])

    _min_runs = getattr(config, 'FEATURED_MIN_RUNS', 0)

    def _pick(candidates, counts, exclude):
        # Eligible = played enough to be a real objective. Falls back to the raw
        # pool if the floor would leave nothing to choose from.
        live = [c for c in candidates if c and counts.get(c, 0) >= _min_runs]
        base = live or [c for c in candidates if c]
        pool = [c for c in base if c != exclude] or base
        if not pool:
            return None
        # Still favour the less-played, but by sqrt rather than a straight
        # inverse: 1/(n+1) made a never-touched pick ~500x likelier than a
        # popular one, which is how Fist and Shield kept winning.
        weights = [1.0 / ((counts.get(c, 0) + 1) ** 0.5) for c in pool]
        return random.choices(pool, weights=weights, k=1)[0]

    _skip = getattr(config, 'FEATURED_WEAPON_EXCLUDE', set())
    _w1h = [w for w in config.WEAPONS_1H if w not in _skip]
    _w2h = [w for w in config.WEAPONS_2H if w not in _skip]
    # Exclude the CURRENT pick as well as last season's, so a re-roll actually
    # rolls: prev only covers the last FINISHED season.
    cur = await _db.get_season_features(season_id) or {}
    def _avoid(slot):
        return cur.get(slot) or prev.get(slot)
    f1h = _pick(_w1h, wcount, _avoid("weapon_1h"))
    f2h = _pick(_w2h, wcount, _avoid("weapon_2h"))
    m1 = _pick(list(config.MAPS), mcount, _avoid("map_1"))
    m2 = _pick([x for x in config.MAPS if x != m1], mcount, _avoid("map_2"))
    for slot, val in (("weapon_1h", f1h), ("weapon_2h", f2h), ("map_1", m1), ("map_2", m2)):
        if val:
            await _db.set_season_feature(season_id, slot, val)
    return {"weapon_1h": f1h, "weapon_2h": f2h, "map_1": m1, "map_2": m2}


_FEATURED_POINTS = [3, 1]
_FEATURED_SLOTS = [
    ("weapon_1h", "weapon", "1H Weapon"),
    ("weapon_2h", "weapon", "2H Weapon"),
    ("map_1", "map", "Map"),
    ("map_2", "map", "Map"),
]


async def compute_featured(season):
    """(boards, points): best single-game takedowns on each featured weapon/map
    this season; top 2 earn 3/1 championship GP."""
    from datetime import datetime, timezone
    feats = await _db.get_season_features(season["id"])
    if not feats:
        return [], {}
    _sa = season["started_at"]
    start_ts = _sa.timestamp() if hasattr(_sa, "timestamp") else float(_sa)
    end_ts = (season["ended_at"].timestamp() if season.get("ended_at") else datetime.now(timezone.utc).timestamp())
    subs = await _db.get_all_submissions()
    inwin = []
    for r in subs:
        if len(r) < 9 or not r[0].strip():
            continue
        try:
            ts = datetime.strptime(r[0].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            continue
        if start_ts <= ts < end_ts:
            inwin.append(r)
    boards, points = [], {}
    for slot, kind, label in _FEATURED_SLOTS:
        val = feats.get(slot)
        if not val:
            continue
        best = {}
        for r in inwin:
            p = r[1].strip()
            try:
                td = int(r[7])
            except (ValueError, IndexError):
                continue
            hit = (kind == "weapon" and r[3].strip() == val) or (kind == "map" and r[5].strip() == val)
            if hit and (p not in best or td > best[p]):
                best[p] = td
        top = sorted(best.items(), key=lambda x: -x[1])[:3]
        for i, (nm, td) in enumerate(top[:2]):
            points[nm] = points.get(nm, 0) + _FEATURED_POINTS[i]
        boards.append((label, val, top))
    return boards, points


_SEASON_TOTAL_MEMO: dict = {}


async def season_total(season):
    """Combined standings: core category GP + bounty bonuses + featured boards.

    Memoised on (season, data version): the Hall of Fame index calls this once per
    season on every rebuild, and each call scans submissions twice (once for the
    categories, once inside compute_featured). Returned tuple is a shared
    reference — treat it read-only.
    """
    # 'seasons' covers bonuses and featured picks, which change standings without
    # any submission being written.
    _ver = _db.data_version('submissions', 'leaderboard_data', 'seasons')
    _key = (season["id"], season.get("ended_at") is not None, _ver)
    _hit = _SEASON_TOTAL_MEMO.get(_key)
    if _hit is not None:
        return _hit
    for _k in [k for k in _SEASON_TOTAL_MEMO if k[2] != _ver]:
        _SEASON_TOTAL_MEMO.pop(_k, None)
    _res = await _season_total_uncached(season)
    if len(_SEASON_TOTAL_MEMO) >= 24:
        _SEASON_TOTAL_MEMO.pop(next(iter(_SEASON_TOTAL_MEMO)), None)
    _SEASON_TOTAL_MEMO[_key] = _res
    return _res


async def _season_total_uncached(season):
    bonuses = await _db.get_season_bonuses(season["id"])
    core, core_stats = await compute_season_standings(season["started_at"], season.get("ended_at"), bonuses)
    points = dict(core)
    featured, feat_points = await compute_featured(season)
    for nm, pt in feat_points.items():
        points[nm] = points.get(nm, 0) + pt
    standings = sorted(points.items(), key=lambda x: (-x[1], x[0]))
    return standings, core_stats, featured


async def build_season_embed(season):
    import discord as _d
    standings, s_stats, featured = await season_total(season)
    a_stats = await calculate_butler_stats()  # all-time
    label = season.get("label") or f"Season {season['id']}"
    lines = []
    if standings and getattr(config, 'SEASON_GP_CHAMPION', True):
        champ = standings[0]
        lines += [f"🏆 **Champion — {champ[0]}**  ({champ[1]} pts)", "", "**Standings**"]
        for i, (nm, pts) in enumerate(standings[:8], 1):
            lines.append(f"`{i:>2}.` {nm} — {pts} pts")
        lines.append("")
    if featured:
        lines.append("**Special Features**  *(random each season)*")
        for flabel, focus, top in featured:
            winner = f"`{top[0][0]}` ({top[0][1]})" if top else "—"
            lines.append(f"│ **{flabel} — {focus}**: {winner}")
        lines.append("")
    lines.append("🏆 **Category Champions**  *(this season · all-time)*")
    for cat, key, plain in _SEASON_CATEGORIES:
        s_nm, s_val = _cat_top(s_stats.get(key), plain)
        a_nm, a_val = _cat_top(a_stats.get(key), plain)
        s_txt = (f"`{s_nm}`" + (f" {s_val}" if s_val else "")) if s_nm else "—"
        a_txt = (f"{a_nm}" + (f" {a_val}" if a_val else "")) if a_nm else "—"
        lines.append(f"│ **{cat}**: {s_txt}  ·  all-time: {a_txt}")
    return _d.Embed(title=f"🏁 {label} — Hall of Fame",
                    description="\n".join(lines), color=0x8b6914)


async def _hof_index_refresh(guild):
    forum = guild.get_channel(config.HALL_OF_FAME_FORUM_ID) or await guild.fetch_channel(config.HALL_OF_FAME_FORUM_ID)
    if not forum:
        return
    lines = ["**\U0001f3c1 Hall of Fame — Index**", "", "*Each season's category champions inside.*", ""]
    for s in await _db.get_all_seasons():
        tid = s.get("thread_id")
        if not tid:
            continue
        label = s.get("label") or f"Season {s['id']}"
        status = "" if s.get("ended_at") else "  *(in progress)*"
        link = f"  https://discord.com/channels/{guild.id}/{tid}"
        if getattr(config, 'SEASON_GP_CHAMPION', True):
            _st, _, _ = await season_total(s)
            _champ = _st[0][0] if _st else "—"
            lines.append(f"**{label}** — \U0001f3c6 {_champ}{status}{link}")
        else:
            lines.append(f"**{label}**{status}{link}")
    body = "\n".join(lines)
    idx = next((p for p in await _db.get_all_index_posts() if p[0] == "hall_of_fame"), None)
    if idx and idx[1]:
        try:
            thread = guild.get_channel(int(idx[1])) or await guild.fetch_channel(int(idx[1]))
            msg = await thread.fetch_message(int(idx[2]))
            await msg.edit(content=body)
            return
        except Exception:
            pass
    created = await forum.create_thread(name="\U0001f4cb Hall of Fame Index", content=body)
    await _db.upsert_index_post("hall_of_fame", str(created.thread.id), str(created.message.id))


async def finalize_season(guild, season):
    """Create or refresh a season's Hall of Fame forum thread, then update the index."""
    forum = guild.get_channel(config.HALL_OF_FAME_FORUM_ID) or await guild.fetch_channel(config.HALL_OF_FAME_FORUM_ID)
    if not forum:
        print("[HOF] Hall of Fame forum not found")
        return
    embed = await build_season_embed(season)
    label = season.get("label") or f"Season {season['id']}"
    if season.get("thread_id"):
        try:
            thread = guild.get_channel(int(season["thread_id"])) or await guild.fetch_channel(int(season["thread_id"]))
            async for msg in thread.history(oldest_first=True, limit=1):
                await msg.edit(embed=embed)
                break
            await _hof_index_refresh(guild)
            return
        except Exception as e:
            print(f"[HOF] Could not refresh season thread: {e}")
    try:
        # Framing intro so the whole thread reads as ONE closing recap (crown ->
        # standings -> superlatives -> rivalries -> what now), not loose embeds.
        _intro = f"**{label} — Hall of Fame**"
        if getattr(config, 'SEASON_GP_CHAMPION', True):
            try:
                _st, _, _ = await season_total(season)
                _champ = _st[0][0] if _st else None
                if _champ:
                    _intro += f"\n🏆 **{_champ}** takes the season. Standings, superlatives, and the season's rivalries below."
            except Exception:
                pass
        else:
            _intro += "\nThe season's category champions, superlatives, and rivalries below."
        created = await forum.create_thread(name=label, content=_intro, embed=embed)
        await _db.set_season_thread(season["id"], str(created.thread.id))
        # Auto-post the season's Superlatives + rivalries once, when the HoF thread
        # is first created (never on later refreshes, so /force_finalize_season stays
        # idempotent), then one unified closing that points forward.
        try:
            from utils.wrapped import compute_superlatives
            from utils import rivalry_service as _rivsvc
            _start = season["started_at"].timestamp()
            _end = season["ended_at"].timestamp() if season.get("ended_at") else None
            _subs = [r for r in await _db.get_all_submissions() if _sub_in_window(r, _start, _end)]
            _awards = compute_superlatives(_subs)
            _pairs = await _rivsvc.pair_awards(_subs)
            if _awards or _pairs.get('bitter_rivals') or _pairs.get('inseparable'):
                await created.thread.send(embed=_render_superlatives_embed(label, _awards, _pairs))
            await created.thread.send(
                f"That's **{label}** in the books. Your personal recap: `/wrapped`  ·  "
                f"your goals from here: `/next`.")
        except Exception as _se:
            print(f"[HOF] superlatives post error: {_se}")
        await _hof_index_refresh(guild)
        print(f"[HOF] Posted {label}")
    except Exception as e:
        print(f"[HOF] Failed to post season: {e}")


async def refresh_favourites_message(guild, embed):
    """Post/update the Butler Monthly report in its channel WITH the interactive
    buttons, and keep it pinned so it stays the anchor post of the channel. Shared
    by every place that refreshes the report so the buttons/pin can\'t be dropped."""
    if not BUTLERS_FAVOURITES_CHANNEL_ID:
        return
    ch = guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
    if not ch:
        try:
            ch = await guild.fetch_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
        except Exception:
            return
    view = None  # buttons removed — report is a clean pinned embed
    target = None
    try:
        async for msg in ch.history(limit=10):
            if msg.author == guild.me and msg.embeds and 'Butler Monthly' in (msg.embeds[0].title or ''):
                target = msg
                break
    except Exception:
        pass
    try:
        if target:
            await target.edit(content=None, embed=embed, view=view)
        else:
            target = await ch.send(embed=embed, view=view)
        try:
            if not target.pinned:
                await target.pin(reason="Butler Monthly report — keep it anchored")
        except Exception as _pe:
            print(f"Favourites pin error: {_pe}")
    except Exception as e:
        print(f"Favourites refresh error: {e}")


# ── Macro graphs (/lounge_graphs) ─────────────────────────────────────────────

def _macro_collect(subs):
    """Data prep for the macro graphs: monthly stat averages, and per-board
    lead changes replayed from the submission log (boards keep no history,
    so #1 handovers are reconstructed chronologically). Resubmit/Unlisted
    runs are skipped; pacifist runs are skipped for the averages."""
    period = {}    # 3-day bucket start date -> [sum_td, sum_kills, runs]
    lead = {}      # board -> (leader_key, top_score)
    changes = {}   # board -> times #1 changed hands
    for r in subs:
        if len(r) < 13 or not (r[0] or '').strip():
            continue
        feats = (r[11] or '') if len(r) > 11 else ''
        if 'Resubmit' in feats or 'Unlisted' in feats:
            continue
        try:
            td = int(r[7]); k = int(r[8])
        except (ValueError, TypeError):
            continue
        if k == 0 and td <= 10:
            continue
        try:
            d = datetime.strptime((r[0] or '').strip()[:10], '%Y-%m-%d').date()
            po = d.toordinal()
            ps = d.fromordinal(po - po % 3)
            w = period.setdefault(ps, [0, 0, 0])
            w[0] += td; w[1] += k; w[2] += 1
        except (ValueError, TypeError):
            pass
        if td <= 0:
            continue
        pkey = (r[2] or '').strip() or (r[1] or '').strip().lower()
        boards = []
        weapon = (r[3] or '').strip()
        vip = (r[10] or '').strip().lower() == 'yes'
        if weapon and not vip:
            boards.append(weapon)
        mp = (r[5] or '').strip(); fc = (r[6] or '').strip()
        if mp and fc:
            boards.append(f"{mp} - {fc}")
        for b in boards:
            cur = lead.get(b)
            if cur is None:
                lead[b] = (pkey, td)
            elif td > cur[1]:
                if pkey != cur[0]:
                    changes[b] = changes.get(b, 0) + 1
                lead[b] = (pkey, td)
    return period, changes


def _spline(ys, samples=14):
    """Catmull-Rom spline through the points (pure numpy, no scipy).
    Returns (x_float_positions, y_values) for a smooth curve."""
    import numpy as np
    pts = [float(y) for y in ys]
    if len(pts) < 3:
        return list(range(len(pts))), pts
    ext = [pts[0]] + pts + [pts[-1]]
    xs_out, ys_out = [], []
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        for t in np.linspace(0, 1, samples, endpoint=False):
            t2 = t * t; t3 = t2 * t
            y = 0.5 * ((2 * p1) + (-p0 + p2) * t
                       + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                       + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
            xs_out.append(i + t)
            ys_out.append(y)
    xs_out.append(len(pts) - 1)
    ys_out.append(pts[-1])
    return xs_out, ys_out


def _render_macro_png(period, changes, hh_counts, hh_total):
    """Blocking matplotlib render, call via asyncio.to_thread. Returns PNG bytes."""
    import io
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    BG = '#2b2d31'; FG = '#dcddde'; MUT = '#8e9297'; GRID = '#3f4147'
    GOLD = '#e0a84c'; CORAL = '#d85a30'; BLUE = '#5b8dd9'; PURPLE = '#7a89c2'; TEAL = '#4fb3a1'
    fig = plt.figure(figsize=(12, 13))
    fig.patch.set_facecolor(BG)
    gs = fig.add_gridspec(3, 2, height_ratios=[1.15, 1, 1], hspace=0.55, wspace=0.32,
                          top=0.93, bottom=0.06, left=0.10, right=0.97)
    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])
    ax4 = fig.add_subplot(gs[2, 0])
    ax5 = fig.add_subplot(gs[2, 1])
    for ax in (ax1, ax2, ax3, ax4, ax5):
        ax.set_facecolor(BG)
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.tick_params(colors=MUT, labelsize=9)
        ax.yaxis.grid(True, color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)

    # Shared time series: 3-day buckets with 8+ runs, last 30 buckets (~90 days)
    keys = sorted(w for w, v in period.items() if v[2] >= 8)[-30:]
    labels_t = [w.strftime('%b %d') for w in keys]
    xs = list(range(len(keys)))
    avg_td = [period[w][0] / period[w][2] for w in keys]
    avg_k = [period[w][1] / period[w][2] for w in keys]
    runs = [period[w][2] for w in keys]
    leth = [period[w][1] / period[w][0] * 100 if period[w][0] else 0 for w in keys]

    def _timeaxis(ax):
        ax.set_xticks(xs)
        step = 2 if len(xs) > 15 else 1
        ax.set_xticklabels([l if i % step == 0 else '' for i, l in enumerate(labels_t)],
                           rotation=45, ha='right')
        ax.xaxis.grid(False)

    # 1. Power creep (full width): smooth curves + point markers
    sx, sy = _spline(avg_td)
    ax1.plot(sx, sy, color=GOLD, linewidth=2.2, label='avg takedowns')
    ax1.plot(xs, avg_td, 'o', color=GOLD, markersize=4)
    sx, sy = _spline(avg_k)
    ax1.plot(sx, sy, color=CORAL, linewidth=2.2, label='avg kills')
    ax1.plot(xs, avg_k, 'o', color=CORAL, markersize=4)
    if avg_td:
        ax1.set_ylim(0, max(avg_td) * 1.18)
    _timeaxis(ax1)
    ax1.set_title('Power creep: average stats per run (3-day periods)',
                  color=FG, fontsize=12, pad=10)
    ax1.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9, loc='lower right')

    # 2. Board churn: most contested boards by #1 handovers
    top = sorted(changes.items(), key=lambda kv: -kv[1])[:10][::-1]
    names = [b for b, _ in top]; vals = [c for _, c in top]
    ax2.barh(names, vals, color=BLUE, height=0.6)
    ax2.set_title('Most contested boards (#1 handovers, all time)',
                  color=FG, fontsize=12, pad=10)
    ax2.xaxis.grid(True, color=GRID, linewidth=0.7)
    ax2.yaxis.grid(False)
    ax2.tick_params(axis='y', labelcolor=FG, labelsize=8)
    for i, v in enumerate(vals):
        ax2.annotate(str(v), (v, i), textcoords='offset points', xytext=(4, -3),
                     color=MUT, fontsize=8)

    # 3. Hundred-Handed histogram: players per progress bucket
    bins = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 30),
            (31, 35), (36, 40), (41, hh_total - 1), (hh_total, hh_total)]
    labels_h = [f"{a}-{b}" if a != b else "done" for a, b in bins]
    counts = [sum(1 for c in hh_counts if a <= c <= b) for a, b in bins]
    colors = [PURPLE] * (len(bins) - 1) + [GOLD]
    ax3.bar(labels_h, counts, color=colors, width=0.7)
    from matplotlib.ticker import MaxNLocator
    ax3.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax3.tick_params(axis='x', labelsize=8)
    ax3.set_title(f'Hundred-Handed progress (of {hh_total} combos)',
                  color=FG, fontsize=12, pad=10)
    for i, v in enumerate(counts):
        if v:
            ax3.annotate(str(v), (i, v), textcoords='offset points', xytext=(0, 3),
                         color=FG, fontsize=8, ha='center')

    # 4. Activity: runs per period
    ax4.bar(xs, runs, color=TEAL, width=0.7)
    _timeaxis(ax4)
    ax4.set_title('Activity: runs per 3-day period', color=FG, fontsize=12, pad=10)

    # 5. Lounge lethality: kill conversion % over time
    sx, sy = _spline(leth)
    ax5.plot(sx, sy, color=CORAL, linewidth=2.2)
    ax5.plot(xs, leth, 'o', color=CORAL, markersize=4)
    if leth:
        lo, hi = min(leth), max(leth)
        pad = max((hi - lo) * 0.4, 2)
        ax5.set_ylim(max(0, lo - pad), hi + pad)
    _timeaxis(ax5)
    ax5.set_title('Lounge lethality: kills per takedown %', color=FG, fontsize=12, pad=10)

    fig.suptitle('State of the Lounge', color=FG, fontsize=15, y=0.975)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


_ATT_TITLES = [
    ("Grand Marshal",   "_combined_placements", 15),
    ("Weapons Master",  "_weapon_placements",    9),
    ("Campaign Master", "_map_placements",       6),
]


def render_all_time_titles_embed(stats):
    """Combined All-Time Titles board: Grand Marshal / Weapons Master / Campaign
    Master rankings (gated at 15/9/6 boards), crown on the current holder of each.
    Ranked by boards placed on; average placement breaks ties (lower is better)."""
    _te = getattr(config, 'TITLE_EMOJIS', {})
    _totals = {"_combined_placements": stats.get('_combined_board_total', 0),
               "_weapon_placements":   stats.get('_weapon_board_total', 0),
               "_map_placements":       stats.get('_map_board_total', 0)}
    embed = discord.Embed(title="All-Time Titles", colour=0xC9A24B)
    for label, key, min_boards in _ATT_TITLES:
        dct = stats.get(key) or {}
        _total = _totals.get(key, 0)
        ranked = sorted(
            ((p, len(v), sum(v) / len(v)) for p, v in dct.items() if len(v) >= min_boards),
            key=lambda t: (-t[1], t[2]))
        if not ranked:
            body = f"*No one qualifies yet (needs {min_boards}+ boards).*"
        else:
            _rows = []
            for i, (p, cnt, avg) in enumerate(ranked[:6], 1):
                crown = " \U0001f451" if i == 1 else ""
                _cntstr = f"{cnt}/{_total}" if _total else f"{cnt}"
                _rows.append(f"`{i}.` **{p}** \u2014 {_cntstr} boards \u00b7 avg #{avg:.2f}{crown}")
            body = "\n".join(_rows)
        _hdr = f"{_te.get(label, '')} {label}  \u00b7  {min_boards}+ boards"
        if _total:
            _hdr += f"  \u00b7  {_total} total"
        embed.add_field(name=_hdr, value=body, inline=False)
    embed.set_footer(text="Ranked by boards placed on; average placement breaks ties (lower is better). Crown = current holder.")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def refresh_all_time_titles_board(guild):
    """Rebuild the pinned All-Time Titles board embed, if one has been set up."""
    try:
        ptr = await _db.get_titles_board()
    except Exception:
        ptr = None
    if not ptr:
        return
    ch_id, msg_id = ptr
    try:
        stats = await calculate_butler_stats()  # all-time, no window
        embed = render_all_time_titles_embed(stats)
        ch = guild.get_channel(int(ch_id)) or await guild.fetch_channel(int(ch_id))
    except Exception as e:
        print(f"[TITLES_BOARD] refresh failed: {e}")
        return
    try:
        msg = await ch.fetch_message(int(msg_id))
        await msg.edit(content="", embed=embed)
    except Exception:
        # Tracked message is gone (e.g. an old generic reframe wiped the thread).
        # Self-heal: repost the framed board and re-point the pointer.
        try:
            from cogs.leaderboards import DECORATION_TOP as _DTOP, DECORATION_BOTTOM as _DBOT
            await ch.send(file=discord.File(_DTOP))
            msg = await ch.send(embed=embed)
            await ch.send(file=discord.File(_DBOT))
            await _db.set_titles_board(str(ch_id), str(msg.id))
        except Exception as e2:
            print(f"[TITLES_BOARD] repost failed: {e2}")


_WRAP_GOLD = 0xC9A24B


def _sub_in_window(row, start_ts, end_ts=None):
    """True if a submission row's submitted_at falls in [start_ts, end_ts)."""
    try:
        ts = datetime.strptime((row[0] or '').strip(), '%Y-%m-%d %H:%M:%S').replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return False
    if ts < start_ts:
        return False
    if end_ts is not None and ts >= end_ts:
        return False
    return True


async def _windowed_subs():
    """(subs, label) scoped to the current open season if one exists, else all-time."""
    all_subs = await _db.get_all_submissions()
    season = await _db.get_current_season()
    if season and season.get('started_at'):
        start = season['started_at'].timestamp()
        return [r for r in all_subs if _sub_in_window(r, start)], (season.get('label') or 'this season')
    return all_subs, 'all time'


def _faction_line(split):
    """'⚔️ Agatha 60% · Mason 30%' from a {faction: runs} dict, most-flown first."""
    if not split:
        return ""
    fe = getattr(config, 'FACTION_EMOJIS', {}) or {}
    tot = sum(split.values()) or 1
    parts = []
    for fac, n in sorted(split.items(), key=lambda kv: -kv[1]):
        parts.append(f"{fe.get(fac, '')} {fac} {round(n / tot * 100)}%".strip())
    return " · ".join(parts)


def _render_wrapped_embed(name, label, w, *, archetype=None, damage=None,
                          nemesis=None, ally=None, ranks=None, butler_line=None):
    e = discord.Embed(title=f"\U0001f381 {name} — {label} Wrapped", colour=_WRAP_GOLD)
    desc = (f"**{w['runs']}** runs · **{w['kills']:,}** kills · "
            f"**{w['takedowns']:,}** takedowns · **{w['deaths']:,}** deaths "
            f"(K/D **{w['kd']}**)")
    if butler_line:
        desc += f"\n\n*\u201c{butler_line}\u201d*"
    e.description = desc
    if w['signature_weapon']:
        e.add_field(name="\U0001f5e1️ Signature weapon",
                    value=f"**{w['signature_weapon']}** — {w['signature_weapon_runs']} runs", inline=True)
    if w['signature_map']:
        e.add_field(name="\U0001f5fa️ Home turf",
                    value=f"**{w['signature_map']}** — {w['signature_map_runs']} runs", inline=True)
    e.add_field(name="\U0001f3a8 Range",
                value=(f"{w['weapons_used']} weapon{'' if w['weapons_used'] == 1 else 's'} · "
                       f"{w['maps_played']} map{'' if w['maps_played'] == 1 else 's'}"), inline=True)
    if archetype or damage:
        e.add_field(name="\U0001f9ed Playstyle",
                    value=" · ".join(x for x in (archetype, damage) if x), inline=True)
    if ranks:
        e.add_field(name="\U0001f4c8 Standing", value=ranks, inline=True)
    _fac = _faction_line(w.get('faction_split') or {})
    if _fac:
        e.add_field(name="\U0001f6a9 Allegiance", value=_fac, inline=True)
    bg = w['best_game']
    if bg:
        line = f"{bg['takedowns']} TD / {bg['kills']} K / {bg['deaths']} D on {bg['weapon']}"
        if bg.get('map'):
            line += f" ({bg['map']})"
        if bg.get('link'):
            line = f"[{line}]({bg['link']})"
        e.add_field(name="\U0001f3c6 Best game", value=line, inline=False)
    feat_bits = []
    if w['triples']:        feat_bits.append(f"{w['triples']}× Triple")
    if w['hundred_kills']:  feat_bits.append(f"{w['hundred_kills']}× 100 Kills")
    if w['two_hundred_td']: feat_bits.append(f"{w['two_hundred_td']}× 200 TD")
    if w['flawless_runs']:  feat_bits.append(f"{w['flawless_runs']}× Flawless")
    if feat_bits:
        e.add_field(name="⭐ Feats", value=" · ".join(feat_bits), inline=False)
    rl = []
    if nemesis:
        rl.append(f"\U0001f5e1️ **Nemesis:** {nemesis['name']} — faced {nemesis['clashes']}×")
    if ally:
        rl.append(f"\U0001f91d **Closest ally:** {ally['name']} — {ally['matches']} "
                  f"battle{'' if ally['matches'] == 1 else 's'} together")
    if rl:
        e.add_field(name="Rivalries", value="\n".join(rl), inline=False)
    _tl = []
    hl = w.get('hardest_lobby')
    if hl and hl.get('gap', 0) < 0:
        _tl.append(f"{hl['emoji']} Toughest lobby: **{hl['band']}** ({hl['gap']:+d} kill gap)")
    if w['carries']:
        _tl.append(f"\U0001f396️ {w['carries']} uphill valor run{'s' if w['carries'] != 1 else ''}")
    if _tl:
        e.add_field(name="Lobbies braved", value="\n".join(_tl), inline=False)
    extra = []
    if w['flawless_streak'] >= 2:
        extra.append(f"\U0001f9ca {w['flawless_streak']}-game flawless streak")
    if w.get('peak_hour') is not None and w.get('peak_hour_runs', 0) >= 3:
        _h = w['peak_hour']
        extra.append(f"\U0001f989 Prime time: {_h:02d}:00–{(_h + 1) % 24:02d}:00 ({w['peak_hour_runs']} runs)")
    elif w['night_runs']:
        extra.append(f"\U0001f989 {w['night_runs']} after-midnight runs")
    if extra:
        e.add_field(name="​", value="\n".join(extra), inline=False)
    e.set_footer(text=f"{label} · Cigar Lounge Wrapped")
    return e


def _render_superlatives_embed(label, awards, pairs=None):
    from utils.wrapped import SUPERLATIVE_TITLES
    e = discord.Embed(title=f"\U0001f3c6 {label} — Superlatives", colour=_WRAP_GOLD,
                      description="The awards nobody asked for, delivered without ceremony.")
    for key, (title, _blurb) in SUPERLATIVE_TITLES.items():
        if key in awards:
            a = awards[key]
            e.add_field(name=title, value=f"**{a['name']}** — {a['detail']}", inline=False)
    if pairs:
        br = pairs.get('bitter_rivals')
        if br:
            e.add_field(name="\U0001f5e1️ Bitter Rivals",
                        value=f"**{br['a']}** & **{br['b']}** — {br['clashes']} clashes, fated to keep meeting",
                        inline=False)
        ins = pairs.get('inseparable')
        if ins:
            e.add_field(name="\U0001f91d Inseparable",
                        value=f"**{ins['a']}** & **{ins['b']}** — {ins['matches']} battles shoulder to shoulder",
                        inline=False)
    e.set_footer(text=f"{label} · Cigar Lounge")
    return e


class FavouritesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await _db.season_init()

    @app_commands.command(name="wrapped", description="Your season recap — signature weapon, best game, rivals, standing and more.")
    @app_commands.describe(player="Whose recap to show (defaults to you).")
    async def wrapped_cmd(self, interaction: discord.Interaction, player: discord.Member = None):
        await interaction.response.defer()
        from utils.wrapped import build_wrapped
        target = player or interaction.user
        subs, label = await _windowed_subs()
        did = str(target.id)

        # Merge identity — id OR canonical name OR any stored IGN — so legacy runs
        # logged under an old name still count toward the recap (id-only missed them).
        names = {(target.display_name or '').strip().lower()}
        canonical = target.display_name
        try:
            prow = await _db.get_player(did)
            if prow and len(prow) > 1 and (prow[1] or '').strip():
                canonical = prow[1].strip()
                names.add(canonical.lower())
            for ign in (await _db.get_player_igns(did)) or []:
                if ign and ign.strip():
                    names.add(ign.strip().lower())
        except Exception:
            pass
        names.discard('')
        mine = [r for r in subs if len(r) > 2
                and ((r[2] or '').strip() == did
                     or (len(r) > 1 and (r[1] or '').strip().lower() in names))]
        w = build_wrapped(mine)
        if w['runs'] == 0:
            await interaction.followup.send(
                f"No runs for **{canonical}** in {label} yet — submit a scorecard first.")
            return

        # Playstyle descriptors (archetype + damage lean).
        archetype = damage = None
        try:
            from cogs.registry import get_player_descriptors
            archetype, damage = await get_player_descriptors(did)
        except Exception as _de:
            print(f"[WRAPPED] descriptors error: {_de}")

        # Nemesis & closest ally over the window.
        nemesis = ally = None
        try:
            from utils import rivalry_service as _rivsvc
            _riv = await _rivsvc.rivalries_for(did, subs)
            _nem, _al = _riv.get('nemesis'), _riv.get('ally')
            # A one-game "rivalry" reads as noise (and grammar like "1 battles"),
            # so only surface a nemesis/ally with at least two shared games.
            nemesis = _nem if (_nem and _nem.get('clashes', 0) >= 2) else None
            ally = _al if (_al and _al.get('matches', 0) >= 2) else None
        except Exception as _re:
            print(f"[WRAPPED] rivalry error: {_re}")

        # Server standing: rank + percentile by total kills and takedowns this window.
        ranks = None
        try:
            def _n(v):
                try:
                    return int(str(v).strip())
                except Exception:
                    return 0
            agg = {}
            for r in subs:
                if len(r) < 9:
                    continue
                _f = (r[11] or '') if len(r) > 11 else ''
                if 'Resubmit' in _f or 'Unlisted' in _f:
                    continue
                key = (r[2] or '').strip() or ('name:' + (r[1] or '').strip().lower())
                a = agg.setdefault(key, [0, 0])
                a[0] += _n(r[8])
                a[1] += _n(r[7])
            tkeys = {did} | {'name:' + nm for nm in names}
            ok = [a[0] for k, a in agg.items() if k not in tkeys]
            otd = [a[1] for k, a in agg.items() if k not in tkeys]
            field = len(ok) + 1
            if field >= 3:
                kr = 1 + sum(1 for v in ok if v > w['kills'])
                tr = 1 + sum(1 for v in otd if v > w['takedowns'])
                ranks = (f"Kills **#{kr}**/{field} *(top {max(1, round(kr / field * 100))}%)*\n"
                         f"Takedowns **#{tr}**/{field} *(top {max(1, round(tr / field * 100))}%)*")
        except Exception as _se:
            print(f"[WRAPPED] standing error: {_se}")

        # One dry Butler line to cap it — best-effort, silently skipped if the model is down.
        butler_line = None
        try:
            from utils.helpers import butler_complete
            from cogs.personality import BUTLER_SYSTEM_PROMPT
            _bp = (f"Write ONE dry, in-character sentence to cap {canonical}'s {label} recap. "
                   "No preamble, no lists, no stat-dump — a single sardonic line under 30 words. "
                   f"Their season: {w['runs']} runs, {w['kills']} kills, {w['takedowns']} takedowns, "
                   f"K/D {w['kd']}, signature weapon {w['signature_weapon']}, "
                   f"archetype {archetype or 'unknown'}, {w['carries']} uphill valor runs, "
                   f"{w['night_runs']} after-midnight runs.")
            _line = await butler_complete(BUTLER_SYSTEM_PROMPT, _bp, 70)
            if _line and _line.strip() and _line.strip() != 'SKIP':
                butler_line = _line.strip().strip('"').strip("\u201c\u201d").strip()
        except Exception as _be:
            print(f"[WRAPPED] butler line error: {_be}")

        await interaction.followup.send(embed=_render_wrapped_embed(
            canonical, label, w, archetype=archetype, damage=damage,
            nemesis=nemesis, ally=ally, ranks=ranks, butler_line=butler_line))

    @app_commands.command(name="superlatives", description="The season's tongue-in-cheek awards, handed out by the Butler.")
    async def superlatives_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        from utils.wrapped import compute_superlatives
        from utils import rivalry_service as _rivsvc
        subs, label = await _windowed_subs()
        awards = compute_superlatives(subs)
        pairs = await _rivsvc.pair_awards(subs)
        if not awards and not (pairs.get('bitter_rivals') or pairs.get('inseparable')):
            await interaction.followup.send(f"Not enough runs in {label} to hand out awards yet.")
            return
        await interaction.followup.send(embed=_render_superlatives_embed(label, awards, pairs))

    @app_commands.command(name="season_start", description="Open a season now for the current bounty (mod only).")
    @app_commands.describe(label="Season name — e.g. the bounty title")
    async def season_start(self, interaction: discord.Interaction, label: str):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        sid = await _db.start_season(label)
        await roll_featured(sid)
        await interaction.followup.send(
            f"Season **{label}** opened (id {sid}). Stats accrue from now until the bounty ends.", ephemeral=True)

    @app_commands.command(name="roll_features", description="Roll this season's Special Features (mod only).")
    @app_commands.describe(force="Re-roll even if features are already set — changes the live challenges.")
    async def roll_features(self, interaction: discord.Interaction, force: bool = False):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        season = await _db.get_current_season()
        if not season:
            await interaction.followup.send("No season is running.", ephemeral=True)
            return
        existing = await _db.get_season_features(season["id"])
        if existing and not force:
            cur = "\n".join(f"• {k.replace('_', ' ')}: **{v}**" for k, v in existing.items() if v)
            await interaction.followup.send(
                f"Special Features are already set for this season:\n{cur}\n\n"
                "Re-rolling mid-season changes the live challenges — run again with `force: True` if you really mean to.",
                ephemeral=True)
            return
        feats = await roll_featured(season["id"])
        txt = "\n".join(f"• {k.replace('_', ' ')}: **{v}**" for k, v in feats.items() if v)
        await interaction.followup.send(f"Special Features rolled for this season:\n{txt}", ephemeral=True)

    @app_commands.command(name="season_set_start", description="Backdate the current season's start date (mod only).")
    @app_commands.describe(date="Start date YYYY-MM-DD — e.g. the day the bounty began")
    async def season_set_start(self, interaction: discord.Interaction, date: str):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        from datetime import datetime, timezone
        await interaction.response.defer(ephemeral=True)
        try:
            dt = datetime.strptime(date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            await interaction.followup.send("Date must be YYYY-MM-DD, e.g. 2026-06-22.", ephemeral=True)
            return
        season = await _db.get_current_season()
        if not season:
            await interaction.followup.send("No season is running.", ephemeral=True)
            return
        await _db.set_season_start(season["id"], dt)
        label = season.get("label") or f"Season {season['id']}"
        await interaction.followup.send(
            f"Season **{label}** now starts **{date}** — the report and standings include everything from then.", ephemeral=True)

    @app_commands.command(name="standings", description="Live standings for the current season (this bounty cycle).")
    async def season_standings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        season = await _db.get_current_season()
        if not season:
            await interaction.followup.send("No season is running — a season opens when a bounty starts.")
            return
        standings, s_stats, featured = await season_total(season)
        label = season.get("label") or f"Season {season['id']}"
        if getattr(config, 'SEASON_GP_CHAMPION', True):
            if not standings:
                await interaction.followup.send("No stats recorded yet this season.")
                return
            lines = [f"**\U0001f3c1 {label} — Live Standings**", ""]
            for i, (nm, pts) in enumerate(standings[:15], 1):
                lines.append(f"`{i:>2}.` **{nm}** — {pts} pts")
            await interaction.followup.send("\n".join(lines))
            return
        # Category mode: each category is its own race (no overall champion).
        lines = [f"**\U0001f3c1 {label} — Category Leaders**", ""]
        _any = False
        for cat, key, plain in _SEASON_CATEGORIES:
            pairs = _cat_pairs(s_stats.get(key), plain)
            if not pairs:
                continue
            _any = True
            lines.append(f"{_CATEGORY_EMOJI.get(cat, '')} **{cat}**")
            for i, (nm, val) in enumerate(pairs[:5], 1):
                lines.append(f"`{i}.` {nm}" + (f" — {val}" if val else ""))
            lines.append("")
        if featured:
            lines.append("⭐ **Special Features**  *(random this season)*")
            for _flabel, focus, top in featured:
                winner = f"{top[0][0]} ({top[0][1]})" if top else "—"
                lines.append(f"│ **{focus}**: {winner}")
        if not _any:
            await interaction.followup.send("No stats recorded yet this season.")
            return
        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="season", description="Your season: standings, where the points come from, and what's closest to gaining more.")
    @app_commands.describe(player="Whose season to show (defaults to you)")
    async def my_season(self, interaction: discord.Interaction, player: discord.Member = None):
        await interaction.response.defer()
        season = await _db.get_current_season()
        if not season:
            await interaction.followup.send("No season is running — a season opens when a bounty starts.")
            return

        member = player or interaction.user
        # Match on the canonical name the boards use, not the Discord display name:
        # they diverge constantly and a mismatch would miss a real player's placements.
        name = member.display_name
        try:
            _prow = await _db.get_player(str(member.id))
            if _prow and len(_prow) > 1 and (_prow[1] or '').strip():
                name = _prow[1].strip()
        except Exception as _pe:
            print(f"[MY_SEASON] canonical name lookup failed: {_pe}")

        standings, stats, featured = await season_total(season)
        label = season.get("label") or f"Season {season['id']}"

        if not getattr(config, 'SEASON_GP_CHAMPION', True):
            # Category mode: per-category placements, no GP.
            lines = [f"**\U0001f3c1 {label} — {name}**", "", "**Your category placements**"]
            _any = False
            for _lbl, _key, _plain in _SEASON_CATEGORIES:
                _pairs = _cat_pairs(stats.get(_key), _plain)
                _pos = next((i for i, (nm, _v) in enumerate(_pairs, 1) if nm == name), None)
                _em = _CATEGORY_EMOJI.get(_lbl, "")
                if _pos:
                    _any = True
                    lines.append(f"{_em} `{_lbl:<18}` **{_ordinal_gp(_pos)}** in the top 5")
                elif len(_pairs) >= len(_GP_POINTS):
                    _cut = _pairs[-1][1]
                    lines.append(f"{_em} `{_lbl:<18}` — *(needs {_cut} to break the top 5)*")
                else:
                    lines.append(f"{_em} `{_lbl:<18}` — *(open — the top 5 is still forming)*")
            for _flabel, _fval, _ftop in (featured or []):
                _fpos = next((i for i, (nm, _td) in enumerate(_ftop, 1) if nm == name), None)
                if _fpos:
                    _any = True
                    lines.append(f"⭐ `{('Featured: ' + str(_fval)):<18}` **{_ordinal_gp(_fpos)}**")
            if not _any:
                lines.append("*Not in the top 5 of any category yet. Keep submitting.*")
            await interaction.followup.send("\n".join(lines))
            return

        # GP mode: full points breakdown + rendered season card.
        _rank = next((i for i, (nm, _) in enumerate(standings, 1) if nm == name), None)
        _gp = next((p for nm, p in standings if nm == name), 0)

        lines = [f"**\U0001f3c1 {label} — {name}**", ""]
        if _rank:
            lines.append(f"**{_gp} GP** · {_ordinal_gp(_rank)} of {len(standings)}")
        else:
            lines.append("**0 GP** · not on the board yet")
        lines.append("")
        lines.append("**Where the points came from**")

        _any = False
        _card_rows = []      # (category, position|None, gp, note) for the image
        for _lbl, _key, _plain in _SEASON_CATEGORIES:
            _pairs = _cat_pairs(stats.get(_key), _plain)
            _pos = next((i for i, (nm, _v) in enumerate(_pairs, 1) if nm == name), None)
            if _pos:
                _any = True
                lines.append(f"`{_lbl:<18}` {_ordinal_gp(_pos)} — **+{_GP_POINTS[_pos - 1]} GP**")
                _card_rows.append((_lbl, _pos, _GP_POINTS[_pos - 1], None))
            elif len(_pairs) >= len(_GP_POINTS):
                _cut = _pairs[-1][1]
                lines.append(f"`{_lbl:<18}` — *(needs {_cut} to score)*")
                _card_rows.append((_lbl, None, 0, f"needs {_cut} to score"))
            else:
                lines.append(f"`{_lbl:<18}` — *(open, top 5 all score)*")
                _card_rows.append((_lbl, None, 0, "open — top 5 all score"))

        for _flabel, _fval, _ftop in (featured or []):
            _fpos = next((i for i, (nm, _td) in enumerate(_ftop, 1) if nm == name), None)
            if _fpos and _fpos <= len(_FEATURED_POINTS):
                _any = True
                lines.append(f"`{'Featured: ' + str(_fval):<18}` {_ordinal_gp(_fpos)} — "
                             f"**+{_FEATURED_POINTS[_fpos - 1]} GP**")
                _card_rows.append((f"Featured: {_fval}", _fpos,
                                   _FEATURED_POINTS[_fpos - 1], None))

        try:
            _bon = await _db.get_season_bonuses(season["id"])
            if _bon.get(name):
                _any = True
                lines.append(f"`{'Bounty race':<18}` — **+{_bon[name]} GP**")
                _card_rows.append(("Bounty race", None, _bon[name],
                                   f"+{_bon[name]} GP"))
        except Exception as _be:
            print(f"[MY_SEASON] bonus lookup failed: {_be}")

        if not _any:
            lines.append("*Nothing scoring yet. Top 5 in any category pays 5/4/3/2/1.*")

        _behind = None
        if _rank and _rank > 1:
            _above = standings[_rank - 2]
            lines += ["", f"**{_above[1] - _gp} GP** behind {_above[0]} in {_ordinal_gp(_rank - 1)}."]
            _behind = (_above[1] - _gp, _above[0], _rank - 1)

        try:
            import io as _io2
            import utils.charts as _charts
            _png = await _charts.render_async(
                _charts.render_season_card,
                player=name, season_label=label, gp=_gp, rank=_rank,
                field_size=len(standings), rows=_card_rows, behind=_behind,
                footer="Cigar Lounge")
            await interaction.followup.send(
                file=discord.File(_io2.BytesIO(_png), filename="season.png"))
            return
        except Exception as _ce:
            print(f"[SEASON] card render failed, text fallback: {_ce}")

        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="titles", description="Board count + average placement for the all-time titles (the tiebreak).")
    async def title_standings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        stats = await calculate_butler_stats()  # all-time (no window)
        titles = [
            ("Grand Marshal",   "_combined_placements", 15),
            ("Weapons Master",  "_weapon_placements",    9),
            ("Campaign Master", "_map_placements",       6),
        ]
        out = []
        for label, key, min_boards in titles:
            dct = stats.get(key) or {}
            ranked = sorted(
                ((p, len(v), sum(v) / len(v)) for p, v in dct.items() if len(v) >= min_boards),
                key=lambda t: (-t[1], t[2]))
            out.append(f"**{label}**  \u00b7  *needs {min_boards}+ boards*")
            if not ranked:
                out.append("  *no one qualifies yet*")
            else:
                for i, (p, cnt, avg) in enumerate(ranked[:6], 1):
                    holder = "  \U0001f451" if i == 1 else ""
                    out.append(f"  `{i}.` **{p}** \u2014 {cnt} boards \u00b7 avg #{avg:.2f}{holder}")
            out.append("")
        header = (
            "**All-Time Title Standings**\n"
            "Ranked by how many boards you place on, then **average placement** breaks ties "
            "(lower is better). \U0001f451 = current holder.\n\n"
        )
        await interaction.followup.send(header + "\n".join(out).rstrip())

    @app_commands.command(name="setup_titles_board", description="Post the combined All-Time Titles board in THIS thread (mod only).")
    async def setup_titles_board(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            stats = await calculate_butler_stats()
            embed = render_all_time_titles_embed(stats)
            # Frame it like the leaderboards: TOP spacer, the embed, BOTTOM spacer.
            # Use leaderboards' resolved asset paths (config.* is just the filename).
            from cogs.leaderboards import DECORATION_TOP as _DTOP, DECORATION_BOTTOM as _DBOT
            await interaction.channel.send(file=discord.File(_DTOP))
            msg = await interaction.channel.send(embed=embed)
            await interaction.channel.send(file=discord.File(_DBOT))
            await _db.set_titles_board(str(interaction.channel.id), str(msg.id))
            await interaction.followup.send("\u2705 All-Time Titles board posted here (framed). It refreshes with the monthly report or via /refresh_titles_board.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"\u274c Setup failed: {e}", ephemeral=True)

    @app_commands.command(name="refresh_titles_board", description="Rebuild the All-Time Titles board now (mod only).")
    async def refresh_titles_board(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_all_time_titles_board(interaction.guild)
        await interaction.followup.send("\u2705 All-Time Titles board refreshed.", ephemeral=True)

    @app_commands.command(name="force_finalize_season", description="Post/refresh the current season's Hall of Fame entry (mod only).")
    async def force_finalize_season(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        season = await _db.get_current_season()
        if not season:
            fin = await _db.get_finished_seasons()
            season = fin[0] if fin else None
        if not season:
            await interaction.followup.send("No season to finalize.", ephemeral=True)
            return
        await finalize_season(interaction.guild, season)
        label = season.get("label") or f"Season {season['id']}"
        await interaction.followup.send(f"Posted/refreshed the Hall of Fame entry for {label}.", ephemeral=True)

    @app_commands.command(name="lounge_graphs", description="Post the macro graphs: power creep, contested boards, Hundred-Handed histogram (mod only).")
    async def lounge_graphs(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            import asyncio as _aio
            subs = await _db.get_all_submissions()
            monthly, changes = _macro_collect(subs)
            from cogs.leaderboards import _hh_matched_counts, HH_TOTAL
            _mc = _hh_matched_counts(await _db.get_all_hundred_handed())
            hh_counts = [m for _did, (_nm, m, _p) in _mc.items() if m > 0]
            png = await _aio.to_thread(_render_macro_png, monthly, changes, hh_counts, HH_TOTAL)
        except ModuleNotFoundError:
            await interaction.followup.send(
                "matplotlib isn't installed on this deploy. Add it to requirements.txt and redeploy.")
            return
        except Exception as e:
            await interaction.followup.send(f"Graph render failed: {e}")
            return
        import io as _io
        await interaction.followup.send(file=discord.File(_io.BytesIO(png), filename="state_of_the_lounge.png"))

    @app_commands.command(name="refresh_report", description="Rebuild the pinned Butler Monthly report now (mod only).")
    async def refresh_report(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        try:
            _now = datetime.now(timezone.utc)
            _season = await _db.get_current_season()
            if _season:
                stats = await calculate_butler_stats(week_start=_season['started_at'].timestamp(), week_end=_now.timestamp())
                stats['week_label'] = (_season.get('label') or f"Season {_season['id']}") + " — season so far"
            else:
                _ws = (_now - timedelta(days=_now.weekday())).replace(hour=12, minute=0, second=0, microsecond=0)
                if _ws > _now:
                    _ws -= timedelta(weeks=1)
                stats = await calculate_butler_stats(week_start=_ws.timestamp(), week_end=_now.timestamp())
                stats['week_label'] = f"{_ws.strftime('%b %d')} \u2013 {(_ws + timedelta(days=7)).strftime('%b %d')}"
            embed = await build_favourites_embed(stats, bot_avatar_url=guild.me.display_avatar.url if guild else None)
            await refresh_favourites_message(guild, embed)
            await update_title_roles(guild, stats, include_weekly=False)
            await refresh_all_time_titles_board(guild)
            await interaction.followup.send("\u2705 Rebuilt the pinned Butler Monthly report.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"\u274c Report refresh failed: {e}", ephemeral=True)

    @app_commands.command(name="report", description="Summon the Butler Monthly report")
    async def butlers_report(self, interaction: discord.Interaction):
        import time

        # Check if user is in Players table
        player_rows = await _db.get_all_players()
        player_ids = {row[0].strip() for row in player_rows if row and row[0]}

        if str(interaction.user.id) not in player_ids:
            await interaction.response.send_message(
                "I'm afraid I don't recognise you, sir. Only registered players may summon the report.",
                ephemeral=True
            )
            return

        # Rate limit — 5 minutes
        now = time.time()
        last = _butlers_report_cooldowns.get(interaction.user.id, 0)
        if now - last < 30:
            remaining = int(30 - (now - last))
            await interaction.response.send_message(
                f"Do you really think my manager would stand for this kind of excessive nagging? Try again in {remaining} seconds.",
                ephemeral=True
            )
            return

        _butlers_report_cooldowns[interaction.user.id] = now

        await interaction.response.defer(ephemeral=True)

        try:
            _now = datetime.now(timezone.utc)
            _season = await _db.get_current_season()
            if _season:
                stats = await calculate_butler_stats(week_start=_season['started_at'].timestamp(), week_end=_now.timestamp())
                stats['week_label'] = (_season.get('label') or f"Season {_season['id']}") + " — season so far"
            else:
                days_since_monday = _now.weekday()
                week_start_dt = (_now - timedelta(days=days_since_monday)).replace(hour=12, minute=0, second=0, microsecond=0)
                if week_start_dt > _now:
                    week_start_dt -= timedelta(weeks=1)
                stats = await calculate_butler_stats(week_start=week_start_dt.timestamp(), week_end=_now.timestamp())
                stats['week_label'] = f"{week_start_dt.strftime('%b %d')} – {(week_start_dt + timedelta(days=7)).strftime('%b %d')}"
            import discord as _discord
            from cogs.leaderboards import _champion_lines
            summary = _discord.Embed(
                title="🏛️  Current Standings",
                description=(f"*{stats.get('week_label','')}*" if stats.get('week_label') else None),
                colour=_discord.Colour.from_str("#C9A24B"),
            )
            def _top1(lst):
                if lst and isinstance(lst[0], (list, tuple)) and len(lst[0]) >= 2:
                    return f"**{lst[0][0]}** ({lst[0][1]})"
                return None

            _lines = _champion_lines(stats, ['apex', 'frenzied', 'most_lethal_player', 'warlord_player'])
            if _lines:
                summary.add_field(name="👑 Reigning Champions  *(this season)*", value="\n".join(_lines), inline=False)

            _records = []
            _mk = _top1(stats.get('top_kills_list'))
            if _mk: _records.append(f"<a:topkill:1360314538364240024> Most Kills \u2014 {_mk}")
            _mt = _top1(stats.get('top_td_list'))
            if _mt: _records.append(f"<a:toptkd:1360312666475728958> Highest TD \u2014 {_mt}")
            _tt = _top1(stats.get('top_total_tally'))
            if _tt: _records.append(f"<a:200tkd:1363648828414230538> Total Tally \u2014 {_tt}")
            if _records:
                summary.add_field(name="🎯 Season Records", value="\n".join(_records), inline=False)

            _meta = []
            _tw = stats.get('top_weapons')
            if _tw:
                _meta.append("🗡️ Weapons \u2014 " + ", ".join(f"{w} ({c})" for w, c in _tw[:3]))
            _tm = stats.get('top_maps')
            if _tm:
                _meta.append("🗺️ Maps \u2014 " + ", ".join(f"{m} ({c})" for m, c in _tm[:3]))
            _ks = stats.get("top_weapons_by_kill_share")
            if _ks and isinstance(_ks[0], (list, tuple)) and len(_ks[0]) >= 2:
                _meta.append(f"💥 Top Kill Share — **{_ks[0][0]}** ({_ks[0][1]}%)")
            _ts = stats.get("top_weapons_by_td_share")
            if _ts and isinstance(_ts[0], (list, tuple)) and len(_ts[0]) >= 2:
                _meta.append(f"🩸 Top TD Share — **{_ts[0][0]}** ({_ts[0][1]}%)")
            if _meta:
                summary.add_field(name="📋 Meta", value="\n".join(_meta), inline=False)

            _runs = stats.get('total_runs'); _players = stats.get('total_players')
            if _runs is not None:
                _pulse = f"**{_runs}** runs" + (f" \u00b7 **{_players}** players" if _players else "")
                summary.add_field(name="📊 This Season", value=_pulse, inline=False)

            await interaction.followup.send(embed=summary, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ The butler has encountered an error: {e}")


async def setup(bot):
    await bot.add_cog(FavouritesCog(bot))
