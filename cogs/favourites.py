# Stats calculation, Butler Monthly embed, title role assignment, and /butlers_report.
import time
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

async def calculate_butler_stats(week_start=None, week_end=None):
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

    # Volume-adjusted (Bayesian shrinkage) ranking for the ratio categories:
    # pull each player's average toward the global mean based on how few games
    # they've played, so a few lucky games can't top a percentage board and
    # sustained high performance over many games ranks highest.
    #   adjusted = (sum_of_ratios + PRIOR * global_mean) / (games + PRIOR)
    _PRIOR = 5      # pseudo-games at the global mean; higher = rewards volume more
    _MIN = 5        # 5+ games to qualify (matches the all-time boards' minimum)
    _HALFLIFE = 30.0  # submissions — recent games weigh most, older ones fade (never fully drop)

    def _shrunk_rank(data):
        # Recency-weighted Bayesian shrinkage: each game is weighted by how recent
        # it is (0.5 ** games_ago/HALFLIFE), then blended toward the league mean via
        # the prior. So the stat tracks current form, and low volume still can't cheese it.
        elig = {p: v for p, v in data.items() if len(v) >= _MIN}
        allv = [x for v in elig.values() for x in v]
        gmean = (sum(allv) / len(allv)) if allv else 0.0
        ranked = []
        for p, v in elig.items():
            n = len(v)  # v is chronological (oldest first)
            wsum = 0.0
            wtot = 0.0
            for i, r in enumerate(v):
                w = 0.5 ** ((n - 1 - i) / _HALFLIFE)  # newest game -> weight 1
                wsum += w * r
                wtot += w
            adj = (wsum + _PRIOR * gmean) / (wtot + _PRIOR)
            ranked.append((p, adj, n))
        ranked.sort(key=lambda t: (-t[1], t[0]))  # name tiebreak = stable order on ties
        return ranked

    # ── EXECUTIONER -- volume-adjusted kills ÷ team total kills % (games in parens) ──
    _leth = _shrunk_rank(team_kill_shares)
    lethal_ranked = [p for p, _adj, _n in _leth]
    most_lethal_top5 = [f"{p} -- {adj:.1f} ({n})" for p, adj, n in _leth[:5]]

    # ── WARLORD -- volume-adjusted takedowns ÷ team total kills % ──
    _dom = _shrunk_rank(warlord_ratios)
    dom_ranked = [p for p, _adj, _n in _dom]
    most_dominant = [f"{p} -- {adj:.1f} ({n})" for p, adj, n in _dom[:5]]
    warlord_player = dom_ranked[0] if dom_ranked else None

    # ── LETHALITY -- weapon-agnostic kills ÷ takedowns % (display-only on the report) ──
    _true_leth = _shrunk_rank(lethal_ratios)
    lethality_list = [f"{p} -- {adj * 100:.1f} ({n})" for p, adj, n in _true_leth[:5]]

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
    non_weapon_feat_placements = {}

    WEAPON_FEAT_BOARDS = {'Mallet', 'Knife'}
    NON_WEAPON_FEAT_BOARDS = {'Flawless', 'Healing Horn'}
    SKIP_LB = {'100 Kills', '200 Takedowns'}

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

    for lb_name, entries in lb_groups.items():
        if lb_name in SKIP_LB:
            continue
        is_map = ' - ' in lb_name
        ranked_entries = sorted(entries, key=lambda t: -t[1])
        for i, (player, _sc) in enumerate(ranked_entries[:10]):
            placement = i + 1
            if is_map:
                map_placements.setdefault(player, []).append(placement)
            elif lb_name in NON_WEAPON_FEAT_BOARDS:
                non_weapon_feat_placements.setdefault(player, []).append(placement)
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

    combined = {}
    for p, v in weapon_placements.items():
        combined.setdefault(p, []).extend(v)
    for p, v in map_placements.items():
        combined.setdefault(p, []).extend(v)
    for p, v in non_weapon_feat_placements.items():
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
        'apex': apex or "N/A",
        'frenzied': frenzied or "N/A",
        'top_total_tally': top_total_tally,
        'high_lethality': most_lethal_top5 if most_lethal_top5 else [],
        'most_lethal_player': lethal_ranked[0] if lethal_ranked else None,
        'warlord_player': warlord_player,
        'most_dominant': most_dominant if most_dominant else [],
        'lethality_list': lethality_list if lethality_list else [],
        '_lethal_adj': {p: adj for p, adj, _n in _leth},
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
        _standings, _core, _featured = await season_total(_season)
        if _standings:
            crows = [(f"{i:>2} {_short(nm, 16)}", f"{pts} pts") for i, (nm, pts) in enumerate(_standings[:10], 1)]
            embed.add_field(name="🏁 Championship", value=_table(crows), inline=False)
        embed.add_field(name=_RULE, value="​", inline=False)
        if _featured:
            frows = [((f"{lbl}: {focus}"), (f"{top[0][0]} ({top[0][1]})" if top else "—"))
                     for lbl, focus, top in _featured]
            embed.add_field(name="⭐ Special Features  *(random this season)*", value=_table(frows), inline=False)
        embed.add_field(name=_RULE, value="​", inline=False)

    embed.add_field(name="<a:mostlethal:1520490418817601658> Kill Share  *(kills ÷ team kills · recent-weighted)*",
                    value=_table(_rows(stats.get("high_lethality"), plain=True)) if stats.get("high_lethality") else "```\n— not enough data —\n```",
                    inline=False)
    embed.add_field(name="<:warlord:1520490364039860347> Warlord  *(takedowns ÷ team kills · recent-weighted)*",
                    value=_table(_rows(stats.get("most_dominant"), plain=True)) if stats.get("most_dominant") else "```\n— not enough data —\n```",
                    inline=False)
    embed.add_field(name="🩸 Lethality  *(kills per takedown · recent-weighted)*",
                    value=_table(_rows(stats.get("lethality_list"), plain=True)) if stats.get("lethality_list") else "```\n— not enough data —\n```",
                    inline=False)

    _tt = stats.get("top_total_tally") or []
    embed.add_field(name="<a:200tkd:1363648828414230538> Total Tally  *(takedowns)*",
                    value=_table([(_short(n), f"{v:,}") for n, v in _tt[:5]]) if _tt else "```\n—\n```",
                    inline=False)

    embed.add_field(name="<a:topkill:1360314538364240024> Most Kills",
                    value=_table(_rows(stats.get("top_kills_list"))), inline=False)
    embed.add_field(name="<a:toptkd:1360312666475728958> Highest Takedowns",
                    value=_table(_rows(stats.get("top_td_list"))), inline=False)
    embed.add_field(name="🏃 Busiest",
                    value=_table([(_short(n), str(v)) for n, v in (stats.get("top_busiest") or [])[:5]]),
                    inline=False)

    embed.add_field(name="─── Meta ───", value="​", inline=False)
    embed.add_field(name="🗡️ Top Weapons", value=_table(_rows(stats.get("top_weapons"))), inline=False)
    embed.add_field(name="🗺️ Top Maps", value=_table(_rows(stats.get("top_maps"))), inline=False)

    embed.add_field(name="─── All-Time Titles ───", value=_table([
        ("Grand Marshal", stats.get("grand_marshal") or "—"),
        ("Weapons Master", stats.get("weapons_master") or "—"),
        ("Campaign Master", stats.get("campaign_master") or "—"),
    ]), inline=False)
    embed.set_footer(text=("Kill Share / Warlord / Lethality here are recency-weighted averages for THIS "
                           "season (5+ games) -- current form, not an all-time peak. The all-time boards "
                           "show your best 5-games-in-a-row instead."))
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
        ('most_lethal_player', MOST_LETHAL_ROLE_ID, 'Kill Share',
         "The kill tallies have been reviewed. {old}, your edge has dulled. {new}, the Kill Share title is yours. The butler is mildly impressed."),
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

        # Volatile season titles (Most Lethal / Warlord) recompute on every
        # submission, and the Bayesian league mean shifts whenever ANYONE plays,
        # which made the role thrash between two near-tied players who had not even
        # submitted. Require a challenger to clearly beat the incumbent before we
        # take the title off them, so a hair's-width or mean-shift wobble cannot flip it.
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
            if _inc is not None and _chal is not None and _chal <= _inc * 1.03:
                continue  # incumbent still within 3% -> keep the title, no thrash

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


def _cat_names(items, plain=False):
    out = []
    for it in (items or [])[:len(_GP_POINTS)]:
        if plain and isinstance(it, str):
            out.append(it.split(" -- ", 1)[0].strip())
        elif isinstance(it, (list, tuple)) and it and it[0]:
            out.append(str(it[0]).strip())
    return out


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

    def _pick(candidates, counts, exclude):
        pool = [c for c in candidates if c and c != exclude] or [c for c in candidates if c]
        if not pool:
            return None
        weights = [1.0 / (counts.get(c, 0) + 1) for c in pool]
        return random.choices(pool, weights=weights, k=1)[0]

    f1h = _pick(list(config.WEAPONS_1H), wcount, prev.get("weapon_1h"))
    f2h = _pick(list(config.WEAPONS_2H), wcount, prev.get("weapon_2h"))
    m1 = _pick(list(config.MAPS), mcount, prev.get("map_1"))
    m2 = _pick([x for x in config.MAPS if x != m1], mcount, prev.get("map_2"))
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


async def season_total(season):
    """Combined standings: core category GP + bounty bonuses + featured boards."""
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
    if standings:
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
    lines.append("**Category Winners**  *(this season · all-time)*")
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
    lines = ["**\U0001f3c1 Hall of Fame — Index**", "", "*Champions of each season.*", ""]
    for s in await _db.get_all_seasons():
        tid = s.get("thread_id")
        if not tid:
            continue
        label = s.get("label") or f"Season {s['id']}"
        standings, _, _ = await season_total(s)
        champ = standings[0][0] if standings else "—"
        status = "" if s.get("ended_at") else "  *(in progress)*"
        link = f"  https://discord.com/channels/{guild.id}/{tid}"
        lines.append(f"**{label}** — \U0001f3c6 {champ}{status}{link}")
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
        created = await forum.create_thread(name=label, content=f"**{label} — Hall of Fame**", embed=embed)
        await _db.set_season_thread(season["id"], str(created.thread.id))
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


class FavouritesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await _db.season_init()

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

    @app_commands.command(name="season_standings", description="Live standings for the current season (this bounty cycle).")
    async def season_standings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        season = await _db.get_current_season()
        if not season:
            await interaction.followup.send("No season is running — a season opens when a bounty starts.")
            return
        standings, _s, _feat = await season_total(season)
        if not standings:
            await interaction.followup.send("No stats recorded yet this season.")
            return
        label = season.get("label") or f"Season {season['id']}"
        lines = [f"**\U0001f3c1 {label} — Live Standings**", ""]
        for i, (nm, pts) in enumerate(standings[:15], 1):
            lines.append(f"`{i:>2}.` **{nm}** — {pts} pts")
        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="title_standings", description="Board count + average placement for the all-time titles (the tiebreak).")
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
            await interaction.followup.send("\u2705 Rebuilt the pinned Butler Monthly report.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"\u274c Report refresh failed: {e}", ephemeral=True)

    @app_commands.command(name="butlers_report", description="Summon the Butler Monthly report")
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
            _bz = _top1(stats.get('top_busiest'))
            if _bz: _records.append(f"🏃 Busiest \u2014 {_bz}")
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

            _alltime = _champion_lines(stats, ['grand_marshal', 'weapons_master', 'campaign_master'])
            if _alltime:
                summary.add_field(name="🏛️ All-Time Titles", value="\n".join(_alltime), inline=False)
            await interaction.followup.send(embed=summary, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ The butler has encountered an error: {e}")


async def setup(bot):
    await bot.add_cog(FavouritesCog(bot))
