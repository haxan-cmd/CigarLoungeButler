# Stats calculation, Butler's Favourites embed, title role assignment, and /butlers_report.
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
HEADHUNTER_ROLE_ID         = config.HEADHUNTER_ROLE_ID
BUTCHER_ROLE_ID            = config.BUTCHER_ROLE_ID
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
                    # Skip resubmissions — old runs, not new weekly activity
                    feats_col = row[11].strip() if len(row) > 11 else ""
                    if "Resubmit" in feats_col:
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
    team_kill_shares = {}    # player -> [team kill share %]
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

    # -- Median-anchored qualification floor for the average categories: you need
    # about half as many games as a typical player (min 3), so one lucky game
    # can't top a percentage board. Robust to grinders (median ignores whales).
    import statistics as _stats
    _active = [c for c in player_counts.values() if c > 0]
    _min_games = max(3, int(_stats.median(_active) // 2)) if _active else 3

    # ── LETHALITY -- avg kills ÷ takedowns %, median-floor qualified ──
    lethal_candidates = {p for p, v in lethal_ratios.items() if len(v) >= _min_games}
    lethal_ranked = sorted(lethal_candidates, key=lambda p: -(sum(lethal_ratios[p]) / len(lethal_ratios[p])))

    def lethality_label(p):
        ratios = lethal_ratios.get(p, [])
        avg = sum(ratios) / len(ratios) if ratios else 0
        return f"{p} -- {avg * 100:.1f}%"

    most_lethal_top5 = [lethality_label(p) for p in lethal_ranked[:5]]

    # ── WARLORD -- avg team TD share %, min 3 runs with team data ──
    warlord_candidates = {p for p, v in team_td_shares.items() if len(v) >= _min_games}
    dom_ranked = sorted(warlord_candidates, key=lambda p: -(sum(team_td_shares[p]) / len(team_td_shares[p])))

    most_dominant = []
    for p in dom_ranked[:5]:
        shares = team_td_shares.get(p, [])
        avg = sum(shares) / len(shares) if shares else 0
        most_dominant.append(f"{p} -- {avg:.1f}%")
    warlord_player = dom_ranked[0] if dom_ranked else None

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
        player = row[1].strip()
        if lb_name not in lb_groups:
            lb_groups[lb_name] = []
        lb_groups[lb_name].append(player)

    for lb_name, players in lb_groups.items():
        if lb_name in SKIP_LB:
            continue
        is_map = ' - ' in lb_name
        for i, player in enumerate(players[:10]):
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

    # Headhunter / Butcher — ROLLING WEEKLY window: highest AVERAGE among a player's
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

    headhunter = best_score_title(kills_scores)
    butcher = best_score_title(td_scores)

    # Fastest Learner — most personal-best runs set THIS WEEK (a run beating the
    # player's prior best kills or takedowns). Debut runs don't count. Rewards
    # improvement, so newer players can compete for it, not just the veterans.
    _pb_history = {}
    for _row in all_subs:
        if not _row or len(_row) < 9 or not _row[0].strip():
            continue
        try:
            _ts = datetime.strptime(_row[0].strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
            _k = int(_row[8]); _t = int(_row[7])
        except (ValueError, IndexError):
            continue
        _pb_history.setdefault(_row[1].strip(), []).append((_ts, _k, _t))

    pb_counts = {}
    for _pname, _runs in _pb_history.items():
        _runs.sort(key=lambda x: x[0])
        _best_k = _best_t = None
        _cnt = 0
        for _ts, _k, _t in _runs:
            if _best_k is None:
                _best_k, _best_t = _k, _t
                continue
            _is_pb = _k > _best_k or _t > _best_t
            if _k > _best_k: _best_k = _k
            if _t > _best_t: _best_t = _t
            if _is_pb and week_start is not None and week_start <= _ts < week_end:
                _cnt += 1
        if _cnt > 0:
            pb_counts[_pname] = _cnt
    top_fastest_learner = sorted(pb_counts.items(), key=lambda x: (-x[1], x[0]))[:3]

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
    top_total_tally = sorted(_tally.items(), key=lambda x: (-x[1], x[0]))[:3]

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
        'headhunter': headhunter or "N/A",
        'butcher': butcher or "N/A",
        'top_fastest_learner': top_fastest_learner,
        'top_total_tally': top_total_tally,
        'high_lethality': most_lethal_top5 if most_lethal_top5 else [],
        'most_lethal_player': lethal_ranked[0] if lethal_ranked else None,
        'warlord_player': warlord_player,
        'most_dominant': most_dominant if most_dominant else [],
        'top_weapons_by_kill_share': top_weapons_by_kill_share,
        'top_weapons_by_td_share': top_weapons_by_td_share,
    }


async def build_favourites_embed(stats, bot_avatar_url=None):
    import discord as _discord

    def fmt_list(items, suffix="", n=3):
        subset = items[:n]
        if not subset:
            return "│ *—*"
        lines = []
        for i, (name, val) in enumerate(subset):
            sfx = f" {suffix}" if (suffix and i == 0) else ""
            lines.append(f"│ `{name}` — {val}{sfx}")
        return "\n".join(lines)

    def fmt_plain(items, n=3):
        subset = items[:n]
        if not subset:
            return "│ *—*"
        parsed = []
        for p in subset:
            if ' -- ' in p:
                name, rest = p.split(' -- ', 1)
                parsed.append((name, rest))
            else:
                parsed.append((p, None))
        lines = []
        for name, rest in parsed:
            if rest is not None:
                lines.append(f"│ `{name}` — {rest}")
            else:
                lines.append(f"│ `{name}`")
        return "\n".join(lines)

    week_label = stats.get('week_label', '')
    title = "📋  The Butler's Favourites" + (f"   {week_label}" if week_label else "")
    desc = f"*{stats['total_runs']} runs · {stats['total_players']} players*"

    embed = _discord.Embed(title=title, description=desc, color=0x8b6914)
    if bot_avatar_url:
        embed.set_thumbnail(url=bot_avatar_url)

    # Live championship + Special Features (shown when a season is running)
    _season = await _db.get_current_season()
    if _season:
        _standings, _core, _featured = await season_total(_season)
        if _standings:
            embed.add_field(
                name="🏁 Championship",
                value="\n".join(f"`{i:>2}.` **{nm}** — {pts} pts" for i, (nm, pts) in enumerate(_standings[:10], 1)),
                inline=False)
        if _featured:
            _fl = []
            for _flabel, _focus, _top in _featured:
                _w = f"`{_top[0][0]}` ({_top[0][1]})" if _top else "—"
                _fl.append(f"│ **{_flabel}: {_focus}** — {_w}")
            embed.add_field(name="⭐ Special Features", value="\n".join(_fl), inline=False)
        embed.add_field(name="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", value="​", inline=False)

    lethal_text = fmt_plain(stats['high_lethality']) if stats.get('high_lethality') else "│ *Not enough data yet*"
    warlord_text = fmt_plain(stats['most_dominant']) if stats.get('most_dominant') else "│ *Not enough team data yet*"

    def _pair(a, b):
        # two half-width columns (2 inline fields ≈ 50% each); non-inline fields break rows
        embed.add_field(name=a[0], value=a[1], inline=True)
        embed.add_field(name=b[0], value=b[1], inline=True)

    def _spacer():
        embed.add_field(name="​", value="​", inline=False)

    _spacer()
    _pair(
        ("<a:mostlethal:1520490418817601658> Most Lethal  *(kills ÷ td %)*", lethal_text),
        ("<:warlord:1520490364039860347> Warlord  *(TD share %)*", warlord_text),
    )

    _spacer()

    _tt = stats.get('top_total_tally') or []
    _fl = stats.get('top_fastest_learner') or []
    _pair(
        ("<a:200tkd:1363648828414230538> Total Tally  *(takedowns)*", fmt_list([(n, f"{v:,}") for n, v in _tt], "TDs") if _tt else "│ *—*"),
        ("📈 Fastest Learner  *(PBs)*", fmt_list([(n, c) for n, c in _fl], "PBs") if _fl else "│ *—*"),
    )
    _spacer()
    _pair(
        ("<a:topkill:1360314538364240024> Most Kills", fmt_list(stats['top_kills_list'], "kills")),
        ("<a:toptkd:1360312666475728958> Highest Takedowns", fmt_list(stats['top_td_list'], "TDs")),
    )
    _spacer()
    embed.add_field(name="🏃 Busiest", value=fmt_list(stats['top_busiest'], "runs"), inline=False)

    _spacer()
    embed.add_field(name="─── Meta ───", value="​", inline=False)
    _pair(
        ("🗡️ Top Weapons", fmt_list(stats['top_weapons'], "runs")),
        ("🗺️ Top Maps", fmt_list(stats['top_maps'], "runs")),
    )

    _spacer()
    embed.add_field(
        name="─── All-Time Titles ───",
        value=(
            f"│ <a:grandmarshal:1519928617407348877> **Grand Marshal** — `{stats['grand_marshal']}`\n"
            f"│ <a:weaponsmaster:1519928521445605488> **Weapons Master** — `{stats['weapons_master']}`\n"
            f"│ <a:campaignmaster:1520497947115262083> **Campaign Master** — `{stats['campaign_master']}`"
        ),
        inline=False,
    )
    return embed


async def update_title_roles(guild, stats):
    main_channel = guild.get_channel(MAIN_CHANNEL_ID)

    title_configs = [
        ('grand_marshal', GRAND_MARSHAL_ROLE_ID, 'Grand Marshal',
         "After careful review of the battlefield records, I must inform {old} that your commission has been reassigned. {new}, the Grand Marshal's standard is yours to carry. Try not to embarrass the household."),
        ('weapons_master', WEAPONS_MASTER_ROLE_ID, 'Weapons Master',
         "It appears the armory has a new curator. {old}, your weapons have been... redistributed. {new}, the Weapons Master title is yours. Do try to keep the blades sharp."),
        ('campaign_master', CAMPAIGN_MASTER_ROLE_ID, 'Campaign Master',
         "The campaign maps have been redrawn. {old}, your routes have been rerouted. {new}, you are hereby appointed Campaign Master. The butler expects nothing less than total domination."),
        ('most_lethal_player', HEADHUNTER_ROLE_ID, 'Most Lethal',
         "The kill tallies have been reviewed. {old}, your edge has been lost. {new}, the Most Lethal title is yours. The butler is mildly impressed."),
        ('warlord_player', WARLORD_ROLE_ID, 'Warlord',
         "The TD tallies have been reviewed. {old}, your dominance has waned. {new}, the Warlord title is yours. The butler acknowledges your presence on the battlefield."),
    ]

    for stat_key, role_id, title_name, msg_template in title_configs:
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

        for old_member in current_holders:
            try:
                await old_member.remove_roles(role)
            except Exception:
                pass

        try:
            await new_member.add_roles(role)
        except Exception:
            pass

        if main_channel and current_holders:
            old_name = current_holders[0].display_name
            new_name = new_member.display_name
            msg = msg_template.format(old=f"**{old_name}**", new=f"**{new_name}**")
            try:
                await main_channel.send(msg, allowed_mentions=discord.AllowedMentions.none())
            except Exception as e:
                print(f"Title announcement error: {e}")


_SEASON_CATEGORIES = [
    ("Most Lethal", "high_lethality", True),
    ("Warlord", "most_dominant", True),
    ("Total Tally", "top_total_tally", False),
    ("Fastest Learner", "top_fastest_learner", False),
    ("Most Kills", "top_kills_list", False),
    ("Highest Takedowns", "top_td_list", False),
    ("Busiest", "top_busiest", False),
]
_GP_POINTS = [3, 2, 1]


def _cat_names(items, plain=False):
    out = []
    for it in (items or [])[:3]:
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
    """Grand Prix points over the season window: top-3 per category = 3/2/1,
    summed per player, plus bounty-completion bonuses. Returns (standings, stats)."""
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


_FEATURED_POINTS = [2, 1]
_FEATURED_SLOTS = [
    ("weapon_1h", "weapon", "1H Weapon"),
    ("weapon_2h", "weapon", "2H Weapon"),
    ("map_1", "map", "Map"),
    ("map_2", "map", "Map"),
]


async def compute_featured(season):
    """(boards, points): best single-game takedowns on each featured weapon/map
    this season; top 2 earn 2/1 championship GP."""
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

    @app_commands.command(name="roll_features", description="Roll this season's Special Features now (mod only).")
    async def roll_features(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        season = await _db.get_current_season()
        if not season:
            await interaction.followup.send("No season is running.", ephemeral=True)
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

    @app_commands.command(name="butlers_report", description="Summon the Butler's Favourites report")
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

        await interaction.response.defer()

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
            embed_text = await build_favourites_embed(stats, bot_avatar_url=interaction.guild.me.display_avatar.url if interaction.guild else None)

            await interaction.followup.send(embed=embed_text)

            if BUTLERS_FAVOURITES_CHANNEL_ID:
                fav_channel = interaction.guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
                if fav_channel:
                    try:
                        async for msg in fav_channel.history(limit=5):
                            if msg.author == interaction.guild.me:
                                await msg.edit(content=None, embed=embed_text)
                                break
                        else:
                            await fav_channel.send(embed=embed_text)
                    except Exception as e:
                        print(f"Favourites channel update error: {e}")

        except Exception as e:
            await interaction.followup.send(f"❌ The butler has encountered an error: {e}")


async def setup(bot):
    await bot.add_cog(FavouritesCog(bot))
