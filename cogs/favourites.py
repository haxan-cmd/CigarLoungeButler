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

    # ── LETHALITY -- avg kills ÷ takedowns %, min 3 runs ──
    lethal_candidates = {p for p, v in lethal_ratios.items() if len(v) >= 3}
    lethal_ranked = sorted(lethal_candidates, key=lambda p: -(sum(lethal_ratios[p]) / len(lethal_ratios[p])))

    def lethality_label(p):
        ratios = lethal_ratios.get(p, [])
        avg = sum(ratios) / len(ratios) if ratios else 0
        return f"{p} -- {avg * 100:.1f}%"

    most_lethal_top5 = [lethality_label(p) for p in lethal_ranked[:5]]

    # ── WARLORD -- avg team TD share %, min 3 runs with team data ──
    warlord_candidates = {p for p, v in team_td_shares.items() if len(v) >= 3}
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


def build_favourites_embed(stats, bot_avatar_url=None):
    import discord as _discord

    def fmt_list(items, suffix="", n=3):
        subset = items[:n]
        if not subset:
            return "│ *—*"
        pad = max(len(name) for name, _ in subset)
        lines = []
        for i, (name, val) in enumerate(subset):
            sfx = f" {suffix}" if (suffix and i == 0) else ""
            lines.append(f"│ `{name:<{pad}}` — {val}{sfx}")
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
        pad = max(len(name) for name, _ in parsed)
        lines = []
        for name, rest in parsed:
            if rest is not None:
                lines.append(f"│ `{name:<{pad}}` — {rest}")
            else:
                lines.append(f"│ `{name:<{pad}}`")
        return "\n".join(lines)

    week_label = stats.get('week_label', '')
    title = "📋  The Butler's Favourites" + (f"   {week_label}" if week_label else "")
    desc = f"*{stats['total_runs']} runs · {stats['total_players']} players*"

    embed = _discord.Embed(title=title, description=desc, color=0x8b6914)
    if bot_avatar_url:
        embed.set_thumbnail(url=bot_avatar_url)

    lethal_text = fmt_plain(stats['high_lethality']) if stats.get('high_lethality') else "│ *Not enough data yet*"
    embed.add_field(
        name="<a:mostlethal:1520490418817601658> Most Lethal  *(kills ÷ takedowns %)*",
        value=lethal_text,
        inline=False,
    )

    warlord_text = fmt_plain(stats['most_dominant']) if stats.get('most_dominant') else "│ *Not enough team data yet*"
    embed.add_field(
        name="<:warlord:1520490364039860347> Warlord  *(TD share of team %)*",
        value=warlord_text,
        inline=False,
    )

    embed.add_field(
        name="─── This Week's Titles ───",
        value=(
            f"<a:topkill:1360314538364240024> **Apex** — `{stats['headhunter']}`  *(avg kills, 100+ runs)*\n"
            f"<a:200tkd:1363648828414230538> **Frenzied** — `{stats['butcher']}`  *(avg takedowns, 200+ runs)*"
        ),
        inline=False,
    )

    _tt = stats.get('top_total_tally') or []
    embed.add_field(
        name="🩸 Total Tally  *(most takedowns this week)*",
        value=fmt_list([(n, f"{v:,}") for n, v in _tt], "TDs") if _tt else "│ *—*",
        inline=False,
    )
    _fl = stats.get('top_fastest_learner') or []
    embed.add_field(
        name="📈 Fastest Learner  *(personal bests set this week)*",
        value=fmt_list([(n, c) for n, c in _fl], "PBs") if _fl else "│ *No new personal bests yet*",
        inline=False,
    )

    embed.add_field(name="​", value="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯", inline=False)

    embed.add_field(
        name="⚔️ Most Kills",
        value=fmt_list(stats['top_kills_list']),
        inline=False,
    )
    embed.add_field(
        name="<a:toptkd:1360312666475728958> Highest Takedowns",
        value=fmt_list(stats['top_td_list']),
        inline=False,
    )
    embed.add_field(
        name="🏃 Busiest",
        value=fmt_list(stats['top_busiest'], "runs"),
        inline=False,
    )
    embed.add_field(
        name="🗡️ Top Weapons",
        value=fmt_list(stats['top_weapons'], "runs"),
        inline=False,
    )
    embed.add_field(
        name="🗺️ Top Maps",
        value=fmt_list(stats['top_maps'], "runs"),
        inline=False,
    )

    embed.add_field(
        name="─── All-Time Titles ───",
        value=(
            f"<a:grandmarshal:1519928617407348877> **Grand Marshal** — `{stats['grand_marshal']}`\n"
            f"<a:weaponsmaster:1519928521445605488> **Weapons Master** — `{stats['weapons_master']}`\n"
            f"<a:campaignmaster:1520497947115262083> **Campaign Master** — `{stats['campaign_master']}`"
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


class FavouritesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
            days_since_monday = _now.weekday()
            week_start_dt = (_now - timedelta(days=days_since_monday)).replace(hour=12, minute=0, second=0, microsecond=0)
            if week_start_dt > _now:
                week_start_dt -= timedelta(weeks=1)
            week_label = f"{week_start_dt.strftime('%b %d')} – {(week_start_dt + timedelta(days=7)).strftime('%b %d')}"
            stats = await calculate_butler_stats(week_start=week_start_dt.timestamp(), week_end=_now.timestamp())
            stats['week_label'] = week_label
            embed_text = build_favourites_embed(stats, bot_avatar_url=interaction.guild.me.display_avatar.url if interaction.guild else None)

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
