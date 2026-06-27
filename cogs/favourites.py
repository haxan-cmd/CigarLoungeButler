# Stats calculation, Butler's Favourites embed, title role assignment, and /butlers_report.
import time
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.sheets import (
    _sheet_cache, players_ws, submissions_ws, leaderboard_data_ws,
    bounty_players_ws, cached_players, cached_submissions,
    cached_leaderboard_data, cached_bounty_players, gspread_retry,
)

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

_butlers_report_cooldowns = {}

def calculate_butler_stats(week_start=None, week_end=None):
    # week_start/end are UTC timestamps — if passed, submission stats are scoped to that window.
    # Title holders (Grand Marshal etc.) always use all-time data regardless.
    all_subs = cached_submissions()
    ld = cached_leaderboard_data()

    # Filter subs to week window if provided
    if week_start is not None and week_end is not None:
        filtered = []
        for row in all_subs:
            if not row or not row[0].strip():
                continue
            try:
                ts = datetime.strptime(row[0].strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
                if week_start <= ts < week_end:
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
        # Warlord: team score ratio (col 19, index 18 — your TD / avg teammate TD)
        try:
            tsr = float(row[18]) if len(row) > 18 and row[18] else None
            if tsr and tsr > 0:
                team_score_ratios.setdefault(player, []).append(tsr)
        except (ValueError, TypeError):
            pass
        # Lethality v2: kill efficiency vs lobby (cols 18/15, index 17/18)
        try:
            tlk = int(row[17]) if len(row) > 17 and row[17] else None  # total_lobby_kills col 18
            ls2 = int(row[14]) if len(row) > 14 and row[14] else None
            if tlk and tlk > 0 and kills > 0 and ls2 and 1 < ls2 <= 64:
                kill_efficiency.setdefault(player, []).append((kills, tlk, ls2))
        except (ValueError, TypeError):
            pass

    most_active = max(player_counts, key=player_counts.get) if player_counts else "N/A"
    top_weapons = sorted(weapon_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_maps = sorted(map_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_busiest = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_td_list = sorted(td_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]
    top_kills_list = sorted(kills_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]

    # ── LETHALITY — kill share efficiency, min 3 submissions with lobby data ──
    # Score = avg(your_kills / (total_lobby_kills / lobby_size))
    # i.e. how many times the lobby average in kills you got per game
    # Falls back to kill rate (kills/td) for players without lobby data yet
    qualified_lethal = {p: v for p, v in lethal_ratios.items() if len(v) >= 3}

    def lethality_score(p):
        eff = kill_efficiency.get(p, [])
        if len(eff) >= 2:
            # Primary: kill efficiency vs lobby average
            scores = [k / (tlk / ls) for k, tlk, ls in eff if tlk > 0 and ls > 1]
            return sum(scores) / len(scores) if scores else 0
        # Fallback: raw kill rate
        if p in qualified_lethal:
            return sum(qualified_lethal[p]) / len(qualified_lethal[p]) * 0.5  # scale down vs efficiency
        return 0

    lethal_candidates = set(qualified_lethal.keys()) | {p for p, v in kill_efficiency.items() if len(v) >= 2}
    lethal_ranked = sorted(lethal_candidates, key=lambda p: -lethality_score(p))

    def lethality_label(p):
        eff = kill_efficiency.get(p, [])
        if len(eff) >= 2:
            avg_eff = sum(k / (tlk / ls) for k, tlk, ls in eff if tlk > 0 and ls > 1) / len(eff)
            rate = sum(qualified_lethal[p]) / len(qualified_lethal[p]) * 100 if p in qualified_lethal else None
            rate_str = f" · {rate:.0f}% kill rate" if rate else ""
            return f"{p} ({avg_eff:.1f}× lobby avg kills{rate_str})"
        if p in qualified_lethal:
            rate = sum(qualified_lethal[p]) / len(qualified_lethal[p]) * 100
            return f"{p} ({rate:.0f}% kill rate)"
        return p

    high_lethality = [lethality_label(p) for p in lethal_ranked[:5]]
    most_lethal_top5 = high_lethality

    # ── WARLORD — team dominance, min 2 submissions with team data ──
    # Primary: avg(your_td / avg_teammate_td) — how much you outscored your team
    # Fallback: lobby finish rank for players without team data yet
    def _ord(n):
        return f"{n}{'th' if 11<=n%100<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"

    def warlord_score(p):
        ratios = team_score_ratios.get(p, [])
        if len(ratios) >= 2:
            return sum(ratios) / len(ratios)
        # Fallback: convert lobby rank percentile
        finishes = lobby_finishes.get(p, [])
        if len(finishes) >= 2:
            avg_pct = sum((s - r) / (s - 1) for r, s in finishes if s > 1) / len(finishes)
            return avg_pct * 0.5  # scale down vs ratio
        return 0

    warlord_candidates = (
        {p for p, v in team_score_ratios.items() if len(v) >= 2} |
        {p for p, v in lobby_finishes.items() if len(v) >= 2}
    )
    dom_ranked = sorted(warlord_candidates, key=lambda p: -warlord_score(p))

    most_dominant = []
    for p in dom_ranked[:5]:
        ratios = team_score_ratios.get(p, [])
        if len(ratios) >= 2:
            avg_ratio = sum(ratios) / len(ratios)
            best_ratio = max(ratios)
            entry = f"{p} — {avg_ratio:.1f}× teammates avg · peak {best_ratio:.1f}×"
        else:
            finishes = lobby_finishes.get(p, [])
            best_r, best_s = min(finishes, key=lambda x: (x[0], -x[1]))
            avg_pct = sum((s - r) / (s - 1) * 100 for r, s in finishes if s > 1) / len(finishes)
            entry = f"{p} — {_ord(best_r)}/{best_s} · avg top {100-avg_pct:.0f}%"
        most_dominant.append(entry)

    # Some players have scores in LeaderboardData that predate the Submissions tab —
    # backfill their counts and best scores so they show up correctly in the report.
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
        # Count each unique board entry as a run for busiest
        ld_player_boards.setdefault(player, set()).add(lb_name)
        # Backfill best TD and kills scores from their respective boards
        if lb_name == '200 Takedowns':
            td_scores_sub[player] = max(td_scores_sub.get(player, 0), score)
        elif lb_name == '100 Kills':
            kills_scores_sub[player] = max(kills_scores_sub.get(player, 0), score)
    # Add LeaderboardData board counts to player_counts (only boards not already in submissions)
    for player, boards in ld_player_boards.items():
        players_set.add(player)
        player_counts[player] = player_counts.get(player, 0) + len(boards)
    # Recalculate sorted lists after backfill
    top_busiest = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_td_list = sorted(td_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]
    top_kills_list = sorted(kills_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]

    # Title calculations from LeaderboardData
    # Placement boards: weapon boards, map boards (" - "), and feat top-10 boards (Mallet, Knife, Flawless, Healing Horn)
    # Excluded from placement titles: 100 Kills, 200 Takedowns (have their own title logic)
    weapon_placements = {}   # player -> [placements] — weapon + feat boards
    map_placements = {}      # player -> [placements] — map boards
    non_weapon_feat_placements = {}  # player -> [placements] — Flawless/Healing Horn (grand marshal only)

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
                # Flawless and Healing Horn count toward Grand Marshal only
                non_weapon_feat_placements.setdefault(player, []).append(placement)
            else:
                # Regular weapon boards + Mallet/Knife count toward Weapons Master
                weapon_placements.setdefault(player, []).append(placement)

    def best_placement_title(d, min_boards=1, breadth_first=False):
        # breadth_first=True: show up on the most boards, tiebreak by avg placement (Grand Marshal style)
        # breadth_first=False: best avg placement wins, tiebreak by board count (Weapons Master style)
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

    # Headhunter — 100 Kills board: best average kills score, tiebreak on submission count
    # Butcher — 200 Takedowns board: best average takedowns score, tiebreak on submission count
    kills_scores = {}    # player -> [kill scores]
    td_scores = {}       # player -> [takedown scores]

    for row in ld:
        if len(row) < 3:
            continue
        lb_name = row[0].strip()
        player = row[1].strip()
        try:
            score = int(row[2])
        except (ValueError, IndexError):
            continue
        if lb_name == '100 Kills':
            kills_scores.setdefault(player, []).append(score)
        elif lb_name == '200 Takedowns':
            td_scores.setdefault(player, []).append(score)

    def best_score_title(d):
        # Weight avg score by log(submissions) so someone with 50 entries and a
        # slightly lower avg beats someone with 1 lucky outlier.
        if not d:
            return None
        import math
        return max(d.keys(), key=lambda p: (sum(d[p]) / len(d[p])) * math.log(len(d[p]) + 1))

    headhunter = best_score_title(kills_scores)
    butcher = best_score_title(td_scores)

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
        'high_lethality': high_lethality if high_lethality else [],
        'most_dominant': most_dominant if most_dominant else [],
    }



def build_favourites_embed(stats):
    def fmt_list(items, suffix, n=3):
        return "\n".join(f"{i+1}. {name} — {val} {suffix}" for i, (name, val) in enumerate(items[:n]))

    def fmt_plain(items, n=3):
        return "\n".join(f"{i+1}. {p}" for i, p in enumerate(items[:n]))

    week_label = stats.get('week_label', '')
    header = (
        f"**📋 The Butler's Favourites** | {week_label}\n"
        if week_label else
        f"**📋 The Butler's Favourites** | {stats['total_runs']} runs · {stats['total_players']} players\n"
    )

    warlord_section = (fmt_plain(stats['most_dominant']) if stats.get('most_dominant') else "*Not enough lobby data yet*")

    return (
        header +
        f"\n"
        f"**<a:mostlethal:1520490418817601658> Lethality** *(kill rate × lobby kills rank, min 3 runs)*\n" + fmt_plain(stats['high_lethality']) + "\n"
        f"\n"
        f"**<:warlord:1520490364039860347> Warlord** *(lobby dominance, min 2 runs)*\n" + warlord_section +
        f"\n\n─────────────────────\n"
        f"*All-Time Titles*\n"
        f"<a:grandmarshal:1519928617407348877> **Grand Marshal** — {stats['grand_marshal']}\n"
        f"<a:weaponsmaster:1519928521445605488> **Weapons Master** — {stats['weapons_master']}\n"
        f"🗺️ **Campaign Master** — {stats['campaign_master']}\n"
        f"<a:mostlethal:1520490418817601658> **Headhunter** — {stats['headhunter']}\n"
        f"<:warlord:1520490364039860347> **Butcher** — {stats['butcher']}\n"
        f"\n─────────────────────\n"
        f"\n**Busiest**\n" + fmt_list(stats['top_busiest'], "runs") + "\n"
        f"\n"
        f"**<a:toptkd:1360312666475728958> Highest Takedowns**\n" + fmt_list(stats['top_td_list'], "TD") + "\n"
        f"\n"
        f"**Top Weapons**\n" + fmt_list(stats['top_weapons'], "runs") + "\n"
        f"\n"
        f"**Top Maps**\n" + fmt_list(stats['top_maps'], "runs") + "\n"
    )



async def update_title_roles(guild, stats):
    # Called after every /butlers_report — reassigns title roles if the holder changed.
    main_channel = guild.get_channel(MAIN_CHANNEL_ID)

    title_configs = [
        ('grand_marshal', GRAND_MARSHAL_ROLE_ID, 'Grand Marshal',
         "After careful review of the battlefield records, I must inform {old} that your commission has been reassigned. {new}, the Grand Marshal's standard is yours to carry. Try not to embarrass the household."),
        ('weapons_master', WEAPONS_MASTER_ROLE_ID, 'Weapons Master',
         "It appears the armory has a new curator. {old}, your weapons have been... redistributed. {new}, the Weapons Master title is yours. Do try to keep the blades sharp."),
        ('campaign_master', CAMPAIGN_MASTER_ROLE_ID, 'Campaign Master',
         "The campaign maps have been redrawn. {old}, your routes have been rerouted. {new}, you are hereby appointed Campaign Master. The butler expects nothing less than total domination."),
        ('headhunter', HEADHUNTER_ROLE_ID, 'Headhunter',
         "The tally has been reviewed. {old}, your count has been surpassed. {new}, the Headhunter title is yours. The butler suggests you stop being modest about it."),
        ('butcher', BUTCHER_ROLE_ID, 'Butcher',
         "The battlefield reports are in. {old}, someone has left more bodies behind. {new}, you are hereby declared the Butcher. The butler finds the whole affair rather distasteful, but acknowledges your commitment."),
    ]

    for stat_key, role_id, title_name, msg_template in title_configs:
        new_holder_name = stats.get(stat_key, 'N/A')
        if new_holder_name == 'N/A':
            continue

        role = guild.get_role(role_id)
        if not role:
            continue

        # Find current holder
        current_holders = [m for m in guild.members if role in m.roles]

        # Find new holder by display name
        new_member = discord.utils.find(
            lambda m: (m.nick or m.display_name).lower() == new_holder_name.lower(),
            guild.members
        )
        if not new_member:
            continue

        # Check if it changed hands
        if current_holders and new_member in current_holders:
            continue  # Same person, no change

        # Remove from old holders
        for old_member in current_holders:
            try:
                await old_member.remove_roles(role)
            except Exception:
                pass

        # Give to new holder
        try:
            await new_member.add_roles(role)
        except Exception:
            pass

        # Announce in main
        if main_channel and current_holders:
            old_mention = current_holders[0].mention
            new_mention = new_member.mention
            msg = msg_template.format(old=old_mention, new=new_mention)
            try:
                await main_channel.send(msg)
            except Exception as e:
                print(f"Title announcement error: {e}")


class FavouritesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="butlers_report", description="Summon the Butler's Favourites report")
    async def butlers_report(self, interaction: discord.Interaction):
        import time

        # Check if user is in Players sheet
        player_ids = set()
        for row in players_ws.get_all_values()[1:]:
            if row and row[0]:
                player_ids.add(row[0].strip())

        if str(interaction.user.id) not in player_ids:
            await interaction.response.send_message(
                "I'm afraid I don't recognise you, sir. Only registered players may summon the report.",
                ephemeral=True
            )
            return

        # Rate limit — 5 minutes
        now = time.time()
        last = _butlers_report_cooldowns.get(interaction.user.id, 0)
        if now - last < 300:
            remaining = int(300 - (now - last))
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
            stats = calculate_butler_stats(week_start=week_start_dt.timestamp(), week_end=_now.timestamp())
            stats['week_label'] = week_label
            embed_text = build_favourites_embed(stats)

            # Post publicly in the channel
            await interaction.followup.send(embed_text)

            # Update pinned favourites channel if set
            if BUTLERS_FAVOURITES_CHANNEL_ID:
                fav_channel = interaction.guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
                if fav_channel:
                    try:
                        async for msg in fav_channel.history(limit=5):
                            if msg.author == interaction.guild.me:
                                await msg.edit(content=embed_text)
                                break
                        else:
                            await fav_channel.send(embed_text)
                    except Exception as e:
                        print(f"Favourites channel update error: {e}")

            # Update title roles
            try:
                await update_title_roles(interaction.guild, stats)
            except Exception as e:
                print(f"Title role update error: {e}")

        except Exception as e:
            await interaction.followup.send(f"❌ The butler has encountered an error: {e}")


async def setup(bot):
    await bot.add_cog(FavouritesCog(bot))
