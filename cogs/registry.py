"""
cogs/registry.py — Player registry card system: rank calculations, card builder,
                   sheet helpers, archive index, and registry slash commands.
"""
import re
import json
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

import config
from config import (
    WEAPONS_1H_FORUM_ID, WEAPONS_2H_FORUM_ID,
    MAP_RECORDS_FORUM_ID, FEATS_FORUM_ID, BOUNTY_CARDS_FORUM_ID,
)
import utils.db as _db
from utils.helpers import format_weapon_marks, nerve_log_error


async def _player_name_ac(interaction: discord.Interaction, current: str):
    """Autocomplete a player param from known player names."""
    cur = current.lower()
    try:
        rows = await _db.get_all_players()
        names = sorted({r[1].strip() for r in rows if r and len(r) > 1 and r[1].strip()})
    except Exception:
        names = []
    return [app_commands.Choice(name=n, value=n) for n in names if cur in n.lower()][:25]

# Local lock for registry card updates (was imported from utils.sheets)
_registry_lock = asyncio.Lock()

# Short aliases for config constants
REGISTRY_WEAPON_MAP    = config.REGISTRY_WEAPON_MAP
REGISTRY_CLASS_MAP     = config.REGISTRY_CLASS_MAP
_SUBCLASS_PRIMARIES    = config._SUBCLASS_PRIMARIES
WEAPON_RANK_THRESHOLDS = config.WEAPON_RANK_THRESHOLDS
PRESTIGE_THRESHOLDS    = config.PRESTIGE_THRESHOLDS
PLAYER_TITLES          = config.PLAYER_TITLES
SUBCLASS_RANKS         = config.SUBCLASS_RANKS
CLASS_RANKS            = config.CLASS_RANKS
FEAT_EMOJIS            = config.FEAT_EMOJIS
SPECIAL_OPS_EMOJIS     = config.SPECIAL_OPS_EMOJIS
WEAPON_RANK_EMOJIS     = config.WEAPON_RANK_EMOJIS
SUBCLASS_RANK_EMOJIS   = config.SUBCLASS_RANK_EMOJIS
CLASS_RANK_EMOJIS      = config.CLASS_RANK_EMOJIS
REGISTRY_FORUM_CHANNEL_ID = config.REGISTRY_FORUM_CHANNEL_ID
FEAT_WEAPONS           = config.FEAT_WEAPONS
WEAPONS_2H             = config.WEAPONS_2H
WEAPONS_1H             = config.WEAPONS_1H
CLASS_WEAPON_MAP       = config.CLASS_WEAPON_MAP

def get_weapon_rank(marks):
    """Return (rank_name, marks_for_current_tier, marks_for_next_tier) for a weapon."""
    rank = None
    current_threshold = 0
    for threshold, name in WEAPON_RANK_THRESHOLDS:
        if marks >= threshold:
            rank = name
            current_threshold = threshold
        else:
            next_threshold = threshold
            return rank or "Unranked", current_threshold, next_threshold
    return WEAPON_RANK_THRESHOLDS[-1][1], current_threshold, None  # Iridescent

def get_subclass_rank(subclass_marks, num_weapons):
    """Return (rank_name, level) based on how many times the meter filled."""
    if num_weapons == 0:
        return SUBCLASS_RANKS[0], 0
    level = min(subclass_marks // num_weapons, len(SUBCLASS_RANKS) - 1)
    return SUBCLASS_RANKS[level], level

def get_class_rank(class_marks):
    """Class rank advances every 3 subclass level-ups."""
    level = min(class_marks // 3, len(CLASS_RANKS) - 1)
    return CLASS_RANKS[level], level

def get_player_title(bounties_completed):
    idx = min(bounties_completed, len(PLAYER_TITLES) - 1)
    return PLAYER_TITLES[idx]

async def calculate_weapon_marks_for_player(discord_id, cached_data=None):
    """
    Count weapon marks per weapon for a player.
    Sources: Submissions + LeaderboardData + LegacyMarks.
    1 mark per submission + 1 bonus for 200 Takedowns feat + 1 for 100 Kills + 1 for Triple.
    LeaderboardData entries count as 1 mark each (historical pre-Submissions data).
    Returns dict: weapon_name -> total_marks
    """
    discord_id_str = str(discord_id)
    weapon_marks = {}

    # --- Source 1: Submissions ---
    subs = (cached_data or {}).get('submissions') or await _db.get_all_submissions()
    for row in subs:
        if len(row) < 13:
            continue
        if row[2].strip() != discord_id_str:
            continue
        weapon = row[3].strip() if len(row) > 3 else ''
        submitted_class = row[4].strip() if len(row) > 4 else ''
        feats_str = row[11].strip() if len(row) > 11 else ''
        feats = [f.strip() for f in feats_str.split(',')] if feats_str and feats_str != 'None' else []
        if not weapon or weapon in ('Other', 'Multiple Weapons'):
            continue
        marks = 1
        if '200 Takedowns' in feats:
            marks += 1
        if '100 Kills' in feats:
            marks += 1
        if 'Triple' in feats:
            marks += 1
        if 'High Score' in feats:
            marks += 1

        # Use submitted subclass to disambiguate shared weapons (e.g. Messer in Raider vs Crusader)
        # Key: (weapon, subclass) if subclass known, else plain weapon name
        subclass_key = None
        if submitted_class:
            for subclass, weapons in REGISTRY_WEAPON_MAP.items():
                if weapon in weapons and submitted_class == subclass:
                    subclass_key = (weapon, subclass)
                    break
        key = subclass_key if subclass_key else weapon
        weapon_marks[key] = weapon_marks.get(key, 0) + marks

    # --- Source 2: LeaderboardData (historical entries, 1 mark each) ---
    # Only add plain weapon key if no subclass-keyed entry already exists for this weapon
    # (avoids double-counting shared weapons like Greatsword across Knight/Vanguard)
    try:
        ld_rows = (cached_data or {}).get('leaderboard_data') or await _db.get_all_leaderboard_data()
        for row in ld_rows:
            if len(row) < 6:
                continue
            if row[2].strip() != discord_id_str:
                continue
            weapon = row[5].strip() if len(row) > 5 else ''
            if not weapon or weapon in ('Other', 'Multiple Weapons'):
                continue
            # Skip plain key if any subclass-keyed entry exists for this weapon
            has_subclass_key = any(
                isinstance(k, tuple) and k[0] == weapon
                for k in weapon_marks
            )
            if not has_subclass_key:
                weapon_marks[weapon] = weapon_marks.get(weapon, 0) + 1
    except Exception as e:
        print(f"LeaderboardData mark read error: {e}")

    # --- Source 3: LegacyMarks ---
    try:
        player_rows = (cached_data or {}).get('players') or await _db.get_all_players()
        player_name = None
        for row in player_rows:
            if row and row[0].strip() == discord_id_str:
                player_name = row[1].strip() if len(row) > 1 else None
                break
        if player_name:
            if cached_data and 'legacy_marks' in cached_data:
                legacy_rows = cached_data['legacy_marks']
            else:
                legacy_rows = await _db.get_legacy_marks_for_player(player_name)
            for row in legacy_rows:
                if len(row) < 4:
                    continue
                # DB rows are already filtered to this player — check anyway for safety
                if row[0].strip().lower() != player_name.lower():
                    continue
                weapon = row[1].strip()
                subclass = row[2].strip() if len(row) > 2 else ''
                try:
                    marks = int(row[3])
                except ValueError:
                    continue
                if subclass:
                    key = (weapon, subclass)
                else:
                    key = weapon
                weapon_marks[key] = weapon_marks.get(key, 0) + marks
    except Exception:
        pass

    return weapon_marks

async def calculate_weapon_shares_for_player(discord_id, cached_data=None):
    """Return per-weapon avg kill share % and TD share % from submissions (cols 20/21)."""
    discord_id_str = str(discord_id)
    subs = (cached_data or {}).get('submissions') or await _db.get_all_submissions()
    kill_shares = {}   # weapon -> [share %]
    td_shares   = {}   # weapon -> [share %]
    for row in subs:
        if len(row) < 4 or row[2].strip() != discord_id_str:
            continue
        weapon = row[3].strip()
        if not weapon:
            continue
        try:
            ks = float(row[20]) if len(row) > 20 and row[20] else None
            if ks and 0 < ks <= 100:
                kill_shares.setdefault(weapon, []).append(ks)
        except (ValueError, TypeError):
            pass
        try:
            ts = float(row[21]) if len(row) > 21 and row[21] else None
            if ts and 0 < ts <= 100:
                td_shares.setdefault(weapon, []).append(ts)
        except (ValueError, TypeError):
            pass
    avg_kill = {w: round(sum(v)/len(v), 1) for w, v in kill_shares.items() if len(v) >= 2}
    avg_td   = {w: round(sum(v)/len(v), 1) for w, v in td_shares.items()   if len(v) >= 2}
    return avg_kill, avg_td


async def calculate_registry_stats(discord_id, cached_data=None):
    """Calculate all progression stats for a player."""
    weapon_marks = await calculate_weapon_marks_for_player(discord_id, cached_data)
    avg_kill_shares, avg_td_shares = await calculate_weapon_shares_for_player(discord_id, cached_data)

    class_stats = {}
    for cls, subclasses in REGISTRY_CLASS_MAP.items():
        subclass_stats = {}
        class_marks_total = 0

        for subclass in subclasses:
            all_weapons = REGISTRY_WEAPON_MAP.get(subclass, [])
            primary_weapons = set(_SUBCLASS_PRIMARIES.get(subclass, all_weapons))
            num_weapons = len(primary_weapons)

            # Count subclass marks = sum of weapon rank-ups across PRIMARY weapons only
            subclass_marks = 0
            weapon_details = {}
            for w in all_weapons:
                # Check subclass-specific key first, fall back to plain weapon name
                marks = weapon_marks.get((w, subclass), weapon_marks.get(w, 0))
                rank_name, _, _ = get_weapon_rank(marks) if marks > 0 else ("Unranked", 0, 1)
                # Count how many rank tiers this weapon has achieved
                tiers_achieved = sum(1 for threshold, _ in WEAPON_RANK_THRESHOLDS if marks >= threshold)
                # Only primary weapons count toward the subclass meter
                if w in primary_weapons:
                    subclass_marks += tiers_achieved
                weapon_details[w] = {
                    'marks': marks,
                    'rank': rank_name,
                    'tiers': tiers_achieved,
                    'avg_kill_share': avg_kill_shares.get(w),
                    'avg_td_share': avg_td_shares.get(w),
                }

            sub_rank, sub_level = get_subclass_rank(subclass_marks, num_weapons)
            class_marks_total += sub_level

            subclass_stats[subclass] = {
                'rank': sub_rank,
                'level': sub_level,
                'marks': subclass_marks,
                'num_weapons': num_weapons,
                'weapons': weapon_details,
            }

        cls_rank, _ = get_class_rank(class_marks_total)
        class_stats[cls] = {
            'rank': cls_rank,
            'class_marks': class_marks_total,
            'subclasses': subclass_stats,
        }

    return class_stats, weapon_marks

async def get_player_bounties_completed(discord_id):
    """Count distinct bounties completed by player."""
    try:
        rows = await _db.get_all_bounty_players()
        discord_id_str = str(discord_id)
        completed = set()
        bounty_rows = await _db.get_all_bounties()
        for row in rows:
            if len(row) < 5:
                continue
            if row[1].strip() == discord_id_str:
                progress_str = row[4].strip() if len(row) > 4 else '{}'
                try:
                    progress = json.loads(progress_str)
                    # Find target for this bounty
                    target = {}
                    for brow in bounty_rows:
                        if brow and brow[0].strip() == row[0].strip() and len(brow) > 4 and brow[4]:
                            try:
                                target = json.loads(brow[4])
                            except Exception:
                                pass
                            break
                    # Complete only if ALL weapons hit their target
                    if target and all(progress.get(w, 0) >= (t['total'] if isinstance(t, dict) else t) for w, t in target.items()):
                        completed.add(row[0].strip())
                except Exception:
                    pass
        return len(completed)
    except Exception:
        return 0

async def get_butler_titles_for_player(discord_id, stats, cached_data=None):
    """Return list of Butler's Favourites titles held by this player."""
    discord_id_str = str(discord_id)
    titles = []
    _te = config.TITLE_EMOJIS
    title_checks = [
        ('grand_marshal',   f"{_te['Grand Marshal']} Grand Marshal"),
        ('weapons_master',  f"{_te['Weapons Master']} Weapons Master"),
        ('campaign_master', f"{_te['Campaign Master']} Campaign Master"),
        ('headhunter',      f"{_te['Headhunter']} Apex"),
        ('butcher',         f"{_te['Butcher']} Frenzied"),
    ]
    rows = (cached_data or {}).get('players') or await _db.get_all_players()
    player_name = None
    for row in rows:
        if row and row[0] == discord_id_str:
            player_name = row[1] if len(row) > 1 else None
            break
    if not player_name:
        return []
    for key, label in title_checks:
        if stats.get(key) == player_name:
            titles.append(label)
    return titles

async def get_special_ops_for_player(discord_id, cached_data=None):
    """Find qualifying Special Ops submissions (feat weapons with 100+ TD)."""
    subs = (cached_data or {}).get('submissions') or await _db.get_all_submissions()
    discord_id_str = str(discord_id)
    special_ops = {}  # weapon -> best submission link
    feat_weapons = {"Fist and Shield", "Healing Horn", "Mallet", "Knife"}
    for row in subs:
        if len(row) < 13:
            continue
        if row[2].strip() != discord_id_str:
            continue
        weapon = row[3].strip()
        if weapon not in feat_weapons:
            continue
        try:
            td = int(row[7])
        except (ValueError, IndexError):
            continue
        if td >= 100:
            link = row[12].strip() if len(row) > 12 else ''
            if weapon not in special_ops:
                special_ops[weapon] = link

    # Also check SpecialOps DB table for manually awarded achievements
    try:
        rows = (cached_data or {}).get('special_ops') or await _db.get_all_special_ops()
        for row in rows:
            if len(row) < 3 or row[0].strip() != discord_id_str:
                continue
            achievement = row[2].strip()
            if achievement == 'KnifeOp' and 'Knife' not in special_ops:
                special_ops['Knife'] = ''
            elif achievement == 'FistAndShieldOp' and 'Fist and Shield' not in special_ops:
                special_ops['Fist and Shield'] = ''
            elif achievement == 'MalletOp' and 'Mallet' not in special_ops:
                special_ops['Mallet'] = ''
    except Exception as e:
        print(f"SpecialOps DB read error: {e}")

    return special_ops

async def get_feats_for_player(discord_id, cached_data=None):
    """Get all feat submissions (200TD, 100K, Triple, Predator, Flawless) with links."""
    subs = (cached_data or {}).get('submissions') or await _db.get_all_submissions()
    discord_id_str = str(discord_id)
    feats = []  # list of (feat_combo_emojis, link)
    seen_links = set()  # deduplicate across all sources by link
    named_feats = set()

    # Check for Hundred-Handed — one submission per (subclass, weapon) pair for all non-archer subclasses
    try:
        from cogs.leaderboards import _HH_PRIMARIES, HH_TOTAL
        hh_progress = await _db.get_hundred_handed_progress(discord_id_str)
        _hh_done = {(r[0], r[1]) for r in hh_progress}
        _hh_required = {(sc, w) for sc, ws in _HH_PRIMARIES.items() for w in ws}
        if _hh_required and _hh_required.issubset(_hh_done):
            named_feats.add('hhanded')
        elif _hh_done:
            named_feats.add(f'hhanded_progress:{len(_hh_done)}:{HH_TOTAL}')
    except Exception:
        pass

    # Collect feat submissions from Submissions sheet
    for row in subs:
        if len(row) < 13 or row[2].strip() != discord_id_str:
            continue
        feats_str = row[11].strip() if len(row) > 11 else ''
        row_feats = [f.strip() for f in feats_str.split(',')] if feats_str and feats_str != 'None' else []
        link = row[12].strip() if len(row) > 12 else ''
        feat_emojis = ''.join(FEAT_EMOJIS[f] for f in ['200 Takedowns', '100 Kills', 'Triple', 'Predator', 'Flawless'] if f in row_feats)
        if feat_emojis:
            if link and link not in seen_links:
                seen_links.add(link)
            feats.append((feat_emojis, link))

    # Also pull legacy feat entries from LeaderboardData
    FEAT_BOARD_EMOJIS = {
        '200 Takedowns': FEAT_EMOJIS['200 Takedowns'],
        '100 Kills':     FEAT_EMOJIS['100 Kills'],
        'Triple':        FEAT_EMOJIS['Triple'],
        'Flawless':      FEAT_EMOJIS['Flawless'],
    }
    board_counts = {}  # lb_name -> count of entries on that board for this player
    try:
        ld_rows = (cached_data or {}).get('leaderboard_data') or await _db.get_all_leaderboard_data()
        for row in ld_rows:
            if len(row) < 5 or row[2].strip() != discord_id_str:
                continue
            lb_name = row[0].strip()
            if lb_name in FEAT_BOARD_EMOJIS:
                board_counts[lb_name] = board_counts.get(lb_name, 0) + 1
                link = row[4].strip() if len(row) > 4 else ''
                if link and link in seen_links:
                    continue
                emoji = FEAT_BOARD_EMOJIS[lb_name]
                # Don't add to seen_links — LegacyFeats may have a richer combo for same game
                feats.append((emoji, link))
    except Exception as e:
        print(f"LeaderboardData feats read error: {e}")

    # Apply manual feat count overrides from players table (indices 8, 9, 10).
    # If a manual value is set, it wins — ignores auto-detected leaderboard counts.
    try:
        player_rows_for_override = (cached_data or {}).get('players') or await _db.get_all_players()
        for p in player_rows_for_override:
            if p and p[0].strip() == discord_id_str:
                if len(p) > 8 and p[8] is not None:
                    board_counts['100 Kills'] = int(p[8])
                if len(p) > 9 and p[9] is not None:
                    board_counts['200 Takedowns'] = int(p[9])
                # triple_count manual override removed — Triple now auto-counted from leaderboard_data
                break
    except Exception as e:
        nerve_log_error("Feats manual override", e)

    # Also pull from LegacyFeats DB table
    try:
        player_rows = (cached_data or {}).get('players') or await _db.get_all_players()
        player_name = None
        for row in player_rows:
            if row and row[0].strip() == discord_id_str:
                player_name = row[1].strip() if len(row) > 1 else None
                break
        if player_name:
            lf_rows = (cached_data or {}).get('legacy_feats') or await _db.get_legacy_feats_for_player(player_name)
            for row in lf_rows:
                if len(row) < 2:
                    continue
                if row[0].strip().lower() != player_name.lower():
                    continue
                emojis = row[1].strip()
                link = row[2].strip() if len(row) > 2 else ''
                if emojis:
                    feats.append((emojis, link))
    except Exception as e:
        print(f"LegacyFeats DB read error: {e}")

    # Deduplicate by link — keep the entry with the most emojis (richest combo) per link
    link_to_best = {}  # link -> (emojis, link)
    no_link_feats = []
    for emojis, link in feats:
        if not link:
            no_link_feats.append((emojis, link))
            continue
        if link not in link_to_best or len(emojis) > len(link_to_best[link][0]):
            link_to_best[link] = (emojis, link)
    feats = list(link_to_best.values()) + no_link_feats

    return named_feats, feats, board_counts

# NOTE: _SUBCLASS_PRIMARIES is defined once, at module top (line ~27), as an alias
# of config._SUBCLASS_PRIMARIES. A second hardcoded copy used to live here and was
# stale relative to config.py (e.g. missing Falchion for Man-at-Arms after config.py
# was updated) — because it was assigned AFTER the top-of-file alias, it silently
# shadowed config's version for every primary/secondary split and Mastered Weapon
# check in this file, with no error. Removed; this file now always reflects
# whatever config._SUBCLASS_PRIMARIES says. (Falchion/Man-at-Arms bug, 2026-06-30.)

def is_primary_weapon(weapon, subclass):
    """Return True if weapon is a primary for the given subclass."""
    primaries = _SUBCLASS_PRIMARIES.get(subclass)
    if primaries is None:
        return True  # Unknown subclass — allow by default
    return weapon in primaries


async def get_mastered_weapons_for_player(discord_id, cached_data=None):
    """Weapons with 100+ primary-weapon submissions. Checks Submissions and LegacyMarks."""
    subs = (cached_data or {}).get('submissions') or await _db.get_all_submissions()
    discord_id_str = str(discord_id)
    weapon_counts = {}
    for row in subs:
        if len(row) < 9 or row[2].strip() != discord_id_str:
            continue
        weapon = row[3].strip()
        subclass = row[4].strip() if len(row) > 4 else ''
        if not is_primary_weapon(weapon, subclass):
            continue
        try:
            td = int(row[7])
        except (ValueError, IndexError):
            continue
        if td >= 100:
            weapon_counts[weapon] = weapon_counts.get(weapon, 0) + 1

    # Also check LegacyMarks — 100+ marks = 100+ submissions
    try:
        player_rows = (cached_data or {}).get('players') or await _db.get_all_players()
        player_name = None
        for row in player_rows:
            if row and row[0].strip() == discord_id_str:
                player_name = row[1].strip() if len(row) > 1 else None
                break
        if player_name:
            legacy_rows = (cached_data or {}).get('legacy_marks') or await _db.get_legacy_marks_for_player(player_name)
            for row in legacy_rows:
                if len(row) < 4 or row[0].strip().lower() != player_name.lower():
                    continue
                weapon = row[1].strip()
                try:
                    marks = int(row[3])
                except ValueError:
                    continue
                if marks >= 100:
                    weapon_counts[weapon] = max(weapon_counts.get(weapon, 0), marks)
    except Exception as e:
        print(f"LegacyMarks mastered check error: {e}")

    return [w for w, c in weapon_counts.items() if c >= 100]

async def get_lobby_stats_for_player(discord_id, cached_data=None):
    """Return avg team TD/kill share percentages from submissions with lobby data."""
    subs = (cached_data or {}).get('submissions') or await _db.get_all_submissions()
    discord_id_str = str(discord_id)
    td_shares = []    # team_td_share values (0–100)
    kill_shares = []  # team_kill_share values (0–100)
    for row in subs:
        if not row or row[2].strip() != discord_id_str:
            continue
        try:
            td_share  = float(row[21]) if len(row) > 21 and row[21] else None
            kill_share = float(row[20]) if len(row) > 20 and row[20] else None
            if td_share is not None:
                td_shares.append(td_share)
            if kill_share is not None:
                kill_shares.append(kill_share)
        except (ValueError, TypeError):
            pass
    if not td_shares:
        return None
    avg_td_share   = sum(td_shares) / len(td_shares)
    avg_kill_share = (sum(kill_shares) / len(kill_shares)) if kill_shares else None
    return {
        'avg_td_share':   avg_td_share,
        'avg_kill_share': avg_kill_share,
        'games':          len(td_shares),
    }


async def get_personal_bests(discord_id, cached_data=None):
    """Return dict with highest kills, highest TDs, and best lethality from all submissions."""
    subs = (cached_data or {}).get('submissions') or await _db.get_all_submissions()
    discord_id_str = str(discord_id)
    best_kills = 0
    best_td = 0
    best_lethality = 0.0
    for row in subs:
        if len(row) < 9 or row[2].strip() != discord_id_str:
            continue
        try:
            td = int(row[7])
            kills = int(row[8])
        except (ValueError, IndexError):
            continue
        if kills > best_kills:
            best_kills = kills
        if td > best_td:
            best_td = td
        if td >= 100 and kills > 0:
            lethality = round((kills / td) * 100, 1)
            if lethality > best_lethality:
                best_lethality = lethality
    return {
        'kills': best_kills,
        'td': best_td,
        'lethality': best_lethality
    }


async def get_best_placements_for_player(discord_id, top_n=5, cached_data=None):
    """Get top N best leaderboard placements for a player across all boards."""
    discord_id_str = str(discord_id)
    try:
        all_rows = (cached_data or {}).get('leaderboard_data') or await _db.get_all_leaderboard_data()
    except Exception:
        return []

    # Build board -> all scores, and find player's score on each board
    board_scores = {}   # board_name -> sorted list of scores (desc)
    player_scores = {}  # board_name -> player's score

    for row in all_rows:
        if len(row) < 4 or not row[3]:
            continue
        lb_name = row[0].strip()
        # Skip junk boards (missing map/weapon name): "", "None - Agatha", " - X".
        _lo = lb_name.lower()
        if (not lb_name or _lo == 'none' or _lo.startswith('none -')
                or lb_name.startswith(' - ') or lb_name.endswith(' - ')):
            continue
        try:
            score = int(row[3])
        except ValueError:
            continue
        board_scores.setdefault(lb_name, []).append(score)
        if row[2].strip() == discord_id_str:
            if lb_name not in player_scores or score > player_scores[lb_name]:
                player_scores[lb_name] = score

    # Calculate placement for each board the player is on
    placements = []
    for lb_name, player_score in player_scores.items():
        scores = sorted(board_scores.get(lb_name, []), reverse=True)
        pos = next((i + 1 for i, s in enumerate(scores) if s <= player_score), len(scores))
        is_map = ' - ' in lb_name
        emoji = '🏆' if is_map else '<:weapon_hs:1350656128635375698>'
        # Calculate gap to #2 if player is #1
        gap = None
        if pos == 1 and len(scores) >= 2:
            second = scores[1]
            gap = player_score - second
        placements.append((pos, lb_name, emoji, gap))

    # Sort: #1 entries by gap descending (bigger gap = more dominant), others by placement
    def sort_key(p):
        pos, _, _, gap = p
        if pos == 1:
            return (0, -(gap or 0))  # #1 first, sorted by gap desc
        return (1, pos)              # others sorted by placement

    placements.sort(key=sort_key)
    return placements[:top_n]


async def get_bounty_completions_for_player(discord_id, cached_data=None):
    """Return list of (bounty_name, placement) tuples completed by player, including legacy."""
    try:
        rows = (cached_data or {}).get('bounty_players') or await _db.get_all_bounty_players()
        discord_id_str = str(discord_id)
        completions = []  # list of (title, placement)
        bounty_rows = (cached_data or {}).get('bounties') or await _db.get_all_bounties()

        # Build emoji lookup from Bounty sheet
        bounty_emoji = {}
        for brow in bounty_rows:
            if brow and len(brow) > 3:
                bounty_emoji[brow[0].strip()] = brow[3].strip()

        for row in rows:
            if len(row) < 5 or row[1].strip() != discord_id_str:
                continue
            bounty_title = row[0].strip()
            progress_str = row[4].strip() if len(row) > 4 else '{}'
            try:
                progress = json.loads(progress_str)
                target = {}
                for brow in bounty_rows:
                    if brow and brow[0].strip() == bounty_title and len(brow) > 4 and brow[4]:
                        try:
                            target = json.loads(brow[4])
                        except Exception:
                            pass
                        break
                if target and all(progress.get(w, 0) >= (t['total'] if isinstance(t, dict) else t) for w, t in target.items()):
                    placement = None
                    for brow in bounty_rows:
                        if brow and brow[0].strip() == bounty_title and len(brow) > 7 and brow[7]:
                            try:
                                comp_list = json.loads(brow[7])
                                # Support both plain ID list and object list formats
                                def _find_placement(comp_list, discord_id_str):
                                    for i, entry in enumerate(comp_list):
                                        if isinstance(entry, dict):
                                            if str(entry.get('id', '')) == discord_id_str:
                                                return i + 1
                                        elif str(entry) == discord_id_str:
                                            return i + 1
                                    return None
                                placement = _find_placement(comp_list, discord_id_str)
                            except Exception:
                                pass
                            break
                    emoji = bounty_emoji.get(bounty_title, '')
                    completions.append((bounty_title, placement, emoji))
            except Exception:
                pass

        # Also pull from LegacyBounties DB table
        try:
            player_rows = (cached_data or {}).get('players') or await _db.get_all_players()
            player_name = None
            for r in player_rows:
                if r and r[0].strip() == discord_id_str:
                    player_name = r[1].strip() if len(r) > 1 else None
                    break
            lb_rows = (await _db.get_legacy_bounties_for_player(player_name)) if player_name else []
            if player_name:
                existing_titles = {t.lower() for t, _, _ in completions}
                # Build emoji lookup from bounty sheet
                bounty_emoji_lookup = {}
                for brow in bounty_rows:
                    if brow and len(brow) > 3:
                        bounty_emoji_lookup[brow[0].strip().lower()] = brow[3].strip()
                for r in lb_rows:
                    if len(r) < 2 or r[0].strip().lower() != player_name.lower():
                        continue
                    raw_title = r[1].strip()
                    import re as _re
                    # Extract discord emoji if present
                    discord_emoji_match = _re.search(r'<a?:[^:]+:\d+>', raw_title)
                    extracted_emoji = discord_emoji_match.group(0) if discord_emoji_match else ''
                    # Extract unicode emoji if no discord emoji
                    if not extracted_emoji:
                        unicode_match = _re.match(r'([\U00010000-\U0010ffff])', raw_title)
                        if unicode_match:
                            extracted_emoji = unicode_match.group(1)
                    # Clean the name
                    bounty_name = _re.sub(r'<[^>]+>', '', raw_title)
                    bounty_name = _re.sub(r'\*+', '', bounty_name)
                    bounty_name = _re.sub(r'#\d+', '', bounty_name)
                    bounty_name = _re.sub(r'[\U00010000-\U0010ffff]', '', bounty_name)
                    bounty_name = bounty_name.strip()
                    if not bounty_name or bounty_name.lower() in existing_titles:
                        continue
                    placement = None
                    try:
                        placement = int(r[2]) if len(r) > 2 and r[2] else None
                    except (ValueError, TypeError):
                        pass
                    # Use extracted emoji, fall back to bounty sheet lookup
                    emoji = extracted_emoji or bounty_emoji_lookup.get(bounty_name.lower(), '')
                    completions.append((bounty_name, placement, emoji))
                    existing_titles.add(bounty_name.lower())
        except Exception:
            pass

        return completions
    except Exception:
        return []

def format_weapon_marks(marks):
    """Format mark count with emphasis based on rank tier, ×N prestige past Iridescent."""
    # Check prestige level past Iridescent
    if marks >= 150:
        prestige = 0
        for threshold in PRESTIGE_THRESHOLDS:
            if marks >= threshold:
                prestige += 1
        prestige_str = f" ×**{prestige}**" if prestige > 0 else ""
        return f"***{marks}***{prestige_str}"
    elif marks >= 60:
        return f"***{marks}***"  # bold italic for Crimson+
    elif marks >= 12:
        return f"**{marks}**"    # bold for Gold+
    else:
        return str(marks)        # plain for Bronze/Silver


async def build_registry_messages(player_name, discord_id, cached_data=None):
    """Build list of message strings for a player's registry card (one per class + header)."""
    class_stats, weapon_marks = await calculate_registry_stats(discord_id, cached_data)
    bounties_done = await get_bounty_completions_for_player(discord_id, cached_data)
    player_title = get_player_title(len(bounties_done))
    mastered = await get_mastered_weapons_for_player(discord_id, cached_data)
    named_feats, feat_submissions, board_counts = await get_feats_for_player(discord_id, cached_data)
    special_ops = await get_special_ops_for_player(discord_id, cached_data)
    best_placements = await get_best_placements_for_player(discord_id, cached_data=cached_data)
    personal_bests = await get_personal_bests(discord_id, cached_data)
    lobby_stats = await get_lobby_stats_for_player(discord_id, cached_data)

    try:
        from cogs.favourites import calculate_butler_stats  # lazy to avoid circular
        butler_stats = await calculate_butler_stats()
        butler_titles = await get_butler_titles_for_player(discord_id, butler_stats, cached_data)
    except Exception:
        butler_titles = []

    messages = []

    # --- Message 1: Header card ---
    lines = []
    lines.append(f"*{player_title}*")
    lines.append("")
    lines.append("**Titles:**")
    for cls, cdata in class_stats.items():
        cls_emoji = CLASS_RANK_EMOJIS.get(cdata['rank'], '')
        lines.append(f"• {cls}: {cls_emoji} — {cdata['rank']}")
    lines.append("")

    if butler_titles:
        lines.append("**Butler's Favourites:**")
        for t in butler_titles:
            lines.append(f"• {t}")
        lines.append("")

    if bounties_done:
        lines.append("**Bounties Completed:**")
        for b, placement, emoji in bounties_done:
            placement_str = f" **#{placement}**" if placement else ""
            prefix = f"{emoji} " if emoji else ""
            lines.append(f"• {prefix}{b}{placement_str}")
        lines.append("")

    if named_feats or feat_submissions:
        lines.append("**Feats of Legend:**")
        if 'hhanded' in named_feats:
            lines.append(f"• <:hhanded:1430199468246044772> The Hundred-Handed")
        else:
            _hh_prog = next((f for f in named_feats if f.startswith('hhanded_progress:')), None)
            if _hh_prog:
                _, _hh_cur, _hh_tot = _hh_prog.split(':')
                lines.append(f"• <:hhanded:1430199468246044772> Hundred-Handed — {_hh_cur}/{_hh_tot}")
        # Flawless shows with link as PB; everything else groups with ×N count
        flawless_emoji = FEAT_EMOJIS['Flawless']
        flawless_entry = None
        feat_counts = {}  # normalized_key -> count
        feat_display = {}  # normalized_key -> display emoji string
        # Preferred display order for known combos
        FEAT_DISPLAY_ORDER = [
            FEAT_EMOJIS['200 Takedowns'],
            FEAT_EMOJIS['100 Kills'],
            FEAT_EMOJIS['Triple'],
            FEAT_EMOJIS['Predator'],
        ]
        for emojis, link in feat_submissions:
            parts = re.findall(r'<a?:[^>]+>|[\U0001F000-\U0010FFFF]', emojis)
            normalized = ''.join(sorted(parts))
            if normalized == flawless_emoji:
                if flawless_entry is None:
                    flawless_entry = (emojis, link)
                continue
            # Skip incomplete Triple combos — must have all three: 200TD, 100K, Triple emoji
            if FEAT_EMOJIS['Triple'] in normalized:
                if not (FEAT_EMOJIS['200 Takedowns'] in normalized and FEAT_EMOJIS['100 Kills'] in normalized):
                    continue
            feat_counts[normalized] = feat_counts.get(normalized, 0) + 1
            if normalized not in feat_display:
                # Build display string in preferred order
                ordered = [e for e in FEAT_DISPLAY_ORDER if e in normalized]
                # Add any remaining emojis not in the order list
                remaining = [p for p in parts if p not in FEAT_DISPLAY_ORDER]
                feat_display[normalized] = ''.join(ordered + remaining)

        # Label map: normalized emoji string -> display label
        _e = FEAT_EMOJIS
        FEAT_LABELS = {
            ''.join(sorted([_e['200 Takedowns']])):                                          "200 Takedowns",
            ''.join(sorted([_e['100 Kills']])):                                              "100 Kills",
            ''.join(sorted([_e['Triple']])):                                                 "Triple",
            ''.join(sorted([_e['Predator']])):                                               "Predator",
            ''.join(sorted([_e['200 Takedowns'], _e['100 Kills']])):                         "200 TD / 100 Kills",
            ''.join(sorted([_e['200 Takedowns'], _e['Triple']])):                            "Triple",
            ''.join(sorted([_e['200 Takedowns'], _e['100 Kills'], _e['Triple']])):           "Triple",
            ''.join(sorted([_e['200 Takedowns'], _e['Predator']])):                          "Predator",
            ''.join(sorted([_e['200 Takedowns'], _e['100 Kills'], _e['Predator']])):         "Predator",
            ''.join(sorted([_e['200 Takedowns'], _e['100 Kills'], _e['Triple'], _e['Predator']])): "Triple + Predator",
            ''.join(sorted([_e['200 Takedowns'], _e['100 Kills'], _e['Triple'], _e['Flawless']])): "Hundred-Handed",
            ''.join(sorted([_e['200 Takedowns'], _e['100 Kills'], _e['Triple'], _e['Flawless'], _e['Predator']])): "Hundred-Handed + Predator",
        }

        if flawless_entry:
            emojis, link = flawless_entry
            lines.append(f"• {emojis} ***Flawless*** —[Link]({link})" if link else f"• {emojis} ***Flawless***")
        # Board counts override for standalone feats.
        # If manual DB value > 0, it wins over submission scan count.
        # Keyed by emoji combo for 100K/200TD; Triple matches by label (combos vary).
        _board_count_map = {
            ''.join(sorted([_e['100 Kills']])):     board_counts.get('100 Kills', 0),
            ''.join(sorted([_e['200 Takedowns']])): board_counts.get('200 Takedowns', 0),
        }
        _triple_db = board_counts.get('Triple') or None  # >0 wins; 0/None = use feat_counts
        _rendered_labels = set()
        for normalized, count in feat_counts.items():
            # Strip hhanded emoji before label lookup
            hhanded_emoji = "<:hhanded:1430199468246044772>"
            has_hhanded = hhanded_emoji in normalized
            lookup_key = normalized.replace(hhanded_emoji, '')
            if has_hhanded:
                if 'hhanded' in named_feats:
                    continue  # already rendered as "The Hundred-Handed" above
                label = "Hundred-Handed"
            else:
                label = FEAT_LABELS.get(lookup_key, FEAT_LABELS.get(normalized, "Feat"))
            # Prefer board counts for standalone feat labels
            if label == "Triple" and _triple_db is not None:
                display_count = _triple_db
            elif label == "200 Takedowns" and board_counts.get('200 Takedowns'):
                display_count = board_counts['200 Takedowns']
            elif label == "100 Kills" and board_counts.get('100 Kills'):
                display_count = board_counts['100 Kills']
            else:
                _db_override = _board_count_map.get(normalized)
                display_count = _db_override if _db_override is not None else count
            if display_count >= 5:
                label_str = f"**{label}**"
            else:
                label_str = f"*{label}*"
            suffix = f" ×{display_count}" if display_count > 1 else ""
            display_emojis = feat_display.get(normalized, normalized)
            lines.append(f"• {display_emojis}{suffix} {label_str}")
            _rendered_labels.add(label)
        # Fallback: render board counts for feats not covered by feat_counts loop
        _fallback_feats = [
            ('200 Takedowns', FEAT_EMOJIS['200 Takedowns']),
            ('100 Kills',     FEAT_EMOJIS['100 Kills']),
            ('Triple',        FEAT_EMOJIS['Triple']),
        ]
        for _fb_label, _fb_emoji in _fallback_feats:
            if _fb_label in _rendered_labels:
                continue
            _fb_count = board_counts.get(_fb_label, 0)
            if _fb_count == 0:
                continue
            _fb_suffix = f" ×{_fb_count}" if _fb_count > 1 else ""
            _fb_label_str = f"**{_fb_label}**" if _fb_count >= 5 else f"*{_fb_label}*"
            lines.append(f"• {_fb_emoji}{_fb_suffix} {_fb_label_str}")
        lines.append("")

    if best_placements:
        lines.append("**Best Placements:**")
        for pos, lb_name, emoji, gap in best_placements:
            gap_str = f" (+{gap})" if gap is not None else ""
            lines.append(f"• {emoji} {lb_name} — #{pos}{gap_str}")
        lines.append("")

    if personal_bests['kills'] > 0 or personal_bests['td'] > 0:
        lines.append("**Personal Bests:**")
        if personal_bests['kills'] > 0:
            lines.append(f"• <a:topkill:1360314538364240024> Kills — **{personal_bests['kills']}**")
        if personal_bests['td'] > 0:
            lines.append(f"• <a:200tkd:1363648828414230538> Takedowns — **{personal_bests['td']}**")
        if personal_bests['lethality'] > 0:
            lines.append(f"• {config.TITLE_EMOJIS['Lethality']} Most Lethal — **{personal_bests['lethality']}%**")
        lines.append("")

    if lobby_stats:
        lines.append("**Lobby Stats:**")
        lines.append(f"• Avg TD share of team — **{lobby_stats['avg_td_share']:.0f}%**")
        if lobby_stats.get('avg_kill_share') is not None:
            lines.append(f"• Avg kill share of team — **{lobby_stats['avg_kill_share']:.0f}%**")
        lines.append(f"*({lobby_stats['games']} tracked games)*")
        lines.append("")

    lines.append("**Mastered Weapons:**")
    if mastered:
        for w in mastered:
            lines.append(f"• {w}")
    else:
        lines.append("• None")
    lines.append("")

    if special_ops:
        lines.append(f"<:special_ops:1361410852686921788> **Special Ops**")
        for w, link in special_ops.items():
            emoji = SPECIAL_OPS_EMOJIS.get(w, '')
            lines.append(f"• {emoji} {w} —[Link]({link})" if link else f"• {emoji} {w}")

    messages.append("\n".join(lines))

    # --- Messages 2-5: One per class ---
    for cls, cdata in class_stats.items():
        cls_emoji = CLASS_RANK_EMOJIS.get(cdata['rank'], '')
        lines = []
        lines.append(f"## {cls}: {cls_emoji} — {cdata['rank']}")
        lines.append("")

        for subclass, sdata in cdata['subclasses'].items():
            sub_emoji = SUBCLASS_RANK_EMOJIS.get(sdata['rank'], '')
            num_weapons = sdata['num_weapons']

            # Subclass meter: tracks weapon rank-ups toward next subclass level-up
            # Each weapon rank-up = 1 subclass mark; meter fills when marks = num_weapons
            subclass_marks = sdata['marks']
            progress_in_current_level = subclass_marks % num_weapons if num_weapons else 0
            meter = '▰' * progress_in_current_level + '▱' * (num_weapons - progress_in_current_level)
            lines.append(f"**{sub_emoji} {subclass}: {sdata['rank']}** `[{meter}]`")

            primary_set = set(_SUBCLASS_PRIMARIES.get(subclass, []))
            def _weapon_line(w, wdata):
                w_emoji = WEAPON_RANK_EMOJIS.get(wdata['rank'], WEAPON_RANK_EMOJIS['Unranked'])
                marks = wdata['marks']
                _, _, next_threshold = get_weapon_rank(marks)
                mark_str = format_weapon_marks(marks)
                progress_str = f"{mark_str}/{next_threshold}" if next_threshold else mark_str
                share_parts = []
                if wdata.get('avg_kill_share') is not None:
                    share_parts.append(f"{wdata['avg_kill_share']}% K")
                if wdata.get('avg_td_share') is not None:
                    share_parts.append(f"{wdata['avg_td_share']}% TD")
                share_str = f" `{' · '.join(share_parts)}`" if share_parts else ""
                return f"• {w_emoji} {w} — {progress_str}{share_str}"

            primaries = sorted(
                [(w, d) for w, d in sdata['weapons'].items() if w in primary_set],
                key=lambda x: -x[1]['marks']
            )
            secondaries = sorted(
                [(w, d) for w, d in sdata['weapons'].items() if w not in primary_set],
                key=lambda x: -x[1]['marks']
            )
            for w, wdata in primaries:
                lines.append(_weapon_line(w, wdata))
            if secondaries:
                lines.append("*Secondary*")
                for w, wdata in secondaries:
                    lines.append(_weapon_line(w, wdata))
            lines.append("")

        messages.append("\n".join(lines))

    return messages

async def get_registry_thread_id(discord_id):
    """Get existing forum thread ID for player, or None."""
    try:
        record = await _db.get_registry_card(str(discord_id))
        if record and len(record) > 2 and record[2]:
            return int(record[2])
    except Exception:
        pass
    return None

async def save_registry_thread_id(discord_id, player_name, thread_id):
    """Save or update the registry thread ID for a player."""
    try:
        await _db.upsert_registry_card(str(discord_id), player_name, str(thread_id))
    except Exception as e:
        print(f"Registry thread ID save error: {e}")


async def update_butlers_archive_row(discord_id, player_name, thread_id, total_marks,
                                      submission_count, last_submission,
                                      weapon_marks_str, class_marks_str):
    """Write snapshot stats into the Players table row for this player."""
    try:
        await _db.update_player_stats(
            discord_id=str(discord_id),
            total_marks=total_marks,
            submission_count=submission_count,
            last_submission_str=str(last_submission) if last_submission else '',
            weapon_marks_str=weapon_marks_str,
            class_marks_str=class_marks_str,
            forum_thread_id=str(thread_id) if thread_id else None,
        )
    except Exception as e:
        nerve_log_error("ButlersArchive", e)
        print(f"update_butlers_archive_row error: {e}")


# ---------------------------------------------------------------------------
# Milestone detection
# ---------------------------------------------------------------------------
_MILESTONE_THRESHOLDS = {1, 60, 80, 150}

def detect_weapon_milestones(old_flat, new_flat):
    """Return list of (weapon, threshold, rank_name) for significant rank crossings.
    old_flat / new_flat: dict of weapon_name -> int marks (plain weapon keys, not tuples).
    """
    milestones = []
    for weapon in set(old_flat) | set(new_flat):
        old = old_flat.get(weapon, 0)
        new = new_flat.get(weapon, 0)
        if new <= old:
            continue
        for threshold, rank_name in WEAPON_RANK_THRESHOLDS:
            if threshold in _MILESTONE_THRESHOLDS and old < threshold <= new:
                milestones.append((weapon, threshold, rank_name))
        # Iridescent ×N — each prestige tier past 150
        if old >= 150:
            old_x = sum(1 for t in PRESTIGE_THRESHOLDS if old >= t)
            new_x = sum(1 for t in PRESTIGE_THRESHOLDS if new >= t)
            if new_x > old_x:
                milestones.append((weapon, new, f"Iridescent ×{new_x}"))
    return milestones


def build_milestone_message(player_name, weapon, threshold, rank_name):
    """Return a Butler-voiced announcement string for this milestone, or None."""
    if rank_name.startswith("Iridescent ×"):
        n = int(rank_name.split("×")[1].strip())
        mark_count = PRESTIGE_THRESHOLDS[n - 1] if n <= len(PRESTIGE_THRESHOLDS) else PRESTIGE_THRESHOLDS[-1]
        return f"**{player_name}** — **{weapon}** ×{n}. {mark_count} marks. The bald woman would be proud."
    messages = {
        1:   f"*Noted.* **{player_name}** has drawn first blood with the **{weapon}**.",
        60:  f"**{player_name}** has reached Crimson rank on the **{weapon}**. 60 marks. I approve. Quietly.",
        80:  f"**{player_name}** has entered Prestige with the **{weapon}**. 80 marks. I'll say nothing. That is the compliment.",
        150: f"**{player_name}** has gone Iridescent on the **{weapon}**. 150 marks. I'm pouring a drink.",
    }
    return messages.get(threshold)




async def update_archive_index(guild):
    """Build or update the pinned index post in butlers-archive."""
    try:
        forum = guild.get_channel(REGISTRY_FORUM_CHANNEL_ID)
        if not forum:
            return

        # Build entries from registry_cards table (anyone with a thread)
        registry_rows = await _db.get_all_registry_cards()
        entries = []
        for row in registry_rows:
            if len(row) < 3 or not row[2] or not row[2].strip():
                continue
            player_name = row[1].strip() if len(row) > 1 else ''
            try:
                thread_id = int(row[2].strip())
            except (ValueError, TypeError):
                continue
            if player_name:
                entries.append((player_name, thread_id))

        entries.sort(key=lambda x: x[0].lower())

        # Build per-letter inline fields (3-column grid layout)
        def _make_letter_fields(letter, letter_entries):
            """One inline field per letter, splitting at 1000 chars."""
            links = [f"[{n}](https://discord.com/channels/{guild.id}/{t})" for n, t in letter_entries]
            fields = []
            current_links = []
            for link in links:
                candidate = "\n".join(current_links + [link])
                if len(candidate) > 950:
                    fields.append((letter if not fields else f"{letter} (cont.)", "\n".join(current_links), True))
                    current_links = [link]
                else:
                    current_links.append(link)
            if current_links:
                fields.append((letter if not fields else f"{letter} (cont.)", "\n".join(current_links), True))
            return fields

        embed_fields = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            letter_entries = [(n, t) for n, t in entries if n and n[0].upper() == letter]
            if letter_entries:
                embed_fields.extend(_make_letter_fields(letter, letter_entries))
        other = [(n, t) for n, t in entries if not n or n[0].upper() not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ']
        if other:
            embed_fields.extend(_make_letter_fields("#", other))

        # Build embed(s) — max 25 fields per embed
        EMBED_TITLE = "📋 Player Registry Index"
        EMBED_DESC = "Jump to a player's card"
        EMBED_OVERHEAD = len(EMBED_TITLE) + len(EMBED_DESC)
        EMBED_CHAR_LIMIT = 5800

        _BLANK = ("​", "​", True)

        def _pad_to_3(fields):
            """Pad with blank inline fields so every row of 3 is complete — no gaps."""
            remainder = len(fields) % 3
            if remainder:
                fields = fields + [_BLANK] * (3 - remainder)
            return fields

        def _build_embeds(fields):
            embeds = []
            current_fields = []
            current_chars = EMBED_OVERHEAD
            for fname, fval, finline in fields:
                cost = len(fname) + len(fval)
                if current_fields and (current_chars + cost > EMBED_CHAR_LIMIT or len(current_fields) >= 24):
                    padded = _pad_to_3(current_fields)
                    e = discord.Embed(
                        title=EMBED_TITLE,
                        description=EMBED_DESC,
                        colour=discord.Colour.from_str("#2b2d31"),
                    )
                    for fn, fv, fi in padded:
                        e.add_field(name=fn, value=fv, inline=fi)
                    embeds.append(e)
                    current_fields = []
                    current_chars = EMBED_OVERHEAD
                current_fields.append((fname, fval, finline))
                current_chars += cost
            if current_fields:
                padded = _pad_to_3(current_fields)
                e = discord.Embed(
                    title=EMBED_TITLE,
                    description=EMBED_DESC,
                    colour=discord.Colour.from_str("#2b2d31"),
                )
                for fn, fv, fi in padded:
                    e.add_field(name=fn, value=fv, inline=fi)
                embeds.append(e)
            return embeds

        embeds = _build_embeds(embed_fields)
        content = None  # using embeds instead of text

        # Find existing index thread by searching Discord directly
        existing_thread_id = None
        for t in forum.threads:
            if t.name == "📋 Player Index":
                existing_thread_id = t.id
                break
        if not existing_thread_id:
            async for t in forum.archived_threads(limit=None):
                if t.name == "📋 Player Index":
                    existing_thread_id = t.id
                    break

        if existing_thread_id:
            try:
                thread = guild.get_thread(existing_thread_id)
                if not thread:
                    thread = await guild.fetch_channel(existing_thread_id)
                msgs = []
                async for msg in thread.history(limit=50, oldest_first=True):
                    msgs.append(msg)
                print(f"Archive index: found {len(msgs)} messages in index thread")
                # Delete all non-starter messages and resend fresh embeds
                for msg in msgs[1:]:
                    try:
                        await msg.delete()
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass
                for embed in embeds:
                    await asyncio.sleep(0.5)
                    await thread.send(embed=embed)
                print("Archive index updated")
                return
            except Exception as e:
                print(f"Index edit error: {e}")
                return  # found thread but failed to update — don't create a duplicate

        # Thread not found at all — create new

        result = await forum.create_thread(name="📋 Player Index", content="**➜ GUIDANCE HERE**")
        await asyncio.sleep(0.5)

        for embed in embeds:
            await asyncio.sleep(0.5)
            await result.thread.send(embed=embed)

        _index_thread_id = result.thread.id

        await asyncio.sleep(0.5)
        readme = (
            "📌 **How Your Registry Card Works**\n\n"
            "Your card is built from your submitted runs. If something looks missing or outdated, run `/refresh_card` to regenerate it.\n\n"
            "**Common reasons data may be missing:**\n"
            "• Your run was never reacted to by a mod — unreacted posts are not logged\n"
            "• You submitted before the bot was tracking that stat\n"
            "• Your name changed since your legacy card was created\n\n"
            "**Legacy data** (pre-bot runs) was imported from the old registry. If your legacy marks are missing or wrong, contact a mod.\n\n"
            "**Special Ops** entries (Knife, Mallet, Fist and Shield) — some are awarded manually, some come from the leaderboards under Feats of War. Contact a mod if yours is missing."
        )
        await result.thread.send(readme)

        print("Archive index created")

    except Exception as e:
        print(f"Archive index error: {e}")


def _chunk_message(msg_text, limit=1900):
    """Split a message into Discord-safe chunks (<= limit chars), breaking on blank lines."""
    if len(msg_text) <= limit:
        return [msg_text]
    chunks = []
    current = ""
    for block in msg_text.split("\n\n"):
        if len(current) + len(block) + 2 > limit:
            if current:
                chunks.append(current.strip())
            current = block
        else:
            current += ("\n\n" if current else "") + block
    if current:
        chunks.append(current.strip())
    return chunks


async def create_or_update_registry_card(guild, discord_id, player_name, cached_data=None, skip_index=False):
    """Create or update a player's registry card in the butlers-archive forum."""
    import os
    try:
        await asyncio.wait_for(_registry_lock.acquire(), timeout=60)
    except asyncio.TimeoutError:
        print(f"Registry lock timeout for {player_name} — skipping card update")
        return
    try:
        forum = guild.get_channel(REGISTRY_FORUM_CHANNEL_ID)
        if not forum:
            print(f"Registry forum channel not found: {REGISTRY_FORUM_CHANNEL_ID}")
            return

        messages = await build_registry_messages(player_name, discord_id, cached_data)
        # Chunk every top-level message up front (including the header, messages[0])
        # so the create path and the edit path always agree on exactly how many
        # text messages the card needs. Previously the edit path never chunked at
        # all: a card whose text crossed Discord's ~2000-char edit limit would
        # either throw on .edit() (silently falling through to spawn a *second*
        # duplicate thread while the old one stayed stale) or, if it had been
        # chunked once before at creation time, permanently desync text_msgs[i]
        # from messages[i] on every future refresh. That looked exactly like
        # "the mark is in the DB but the card never updates" even though the
        # underlying weapon-mark calculation was correct.
        # (OctoLemon Sword/Man-at-Arms card bug, investigated 2026-06-30.)
        chunks_per_message = [_chunk_message(m) for m in messages]
        chunked_messages = [c for chunks in chunks_per_message for c in chunks]
        boundary_indices = set()
        _idx = 0
        for _chunks in chunks_per_message:
            boundary_indices.add(_idx)
            _idx += len(_chunks)

        thread_id = await get_registry_thread_id(discord_id)

        top_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'WMMR_Spacer_Top.png')
        bot_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'WMMR_Spacer_Bottom.png')

        if thread_id:
            # Edit existing thread in place
            try:
                thread = guild.get_thread(thread_id)
                if not thread:
                    thread = await guild.fetch_channel(thread_id)

                # Collect existing text messages (skip image-only messages).
                # Raised from 30 -> 50 since chunking can push a long card past 30 messages.
                existing = []
                async for msg in thread.history(limit=50, oldest_first=True):
                    existing.append(msg)
                text_msgs = [m for m in existing if m.content and m.content != '🗂️']

                # Edit existing text messages against the flattened, chunk-aware list
                for i, new_text in enumerate(chunked_messages):
                    if i < len(text_msgs):
                        if text_msgs[i].content != new_text:
                            await text_msgs[i].edit(content=new_text)
                    else:
                        # New message needed — send it
                        await asyncio.sleep(0.5)
                        await thread.send(new_text)

                # Clear any extra messages beyond what we need
                for extra_msg in text_msgs[len(chunked_messages):]:
                    try:
                        await extra_msg.edit(content='\u200b')
                    except Exception:
                        pass

                # Update player name in thread if changed
                if thread.name != player_name:
                    await thread.edit(name=player_name)

                await save_registry_thread_id(discord_id, player_name, thread.id)
                print(f"Registry card updated for {player_name}")
                if not skip_index:
                    asyncio.create_task(update_archive_index(guild))
                return
            except Exception as e:
                print(f"Registry thread edit error for {player_name}: {e}")
                # Fall through to create new thread

        # Create new thread
        thread_with_msg = await forum.create_thread(
            name=player_name,
            content='🗂️',
        )
        thread = thread_with_msg.thread

        has_top = os.path.exists(top_path)
        has_bot = os.path.exists(bot_path)

        if has_top:
            await asyncio.sleep(0.5)
            await thread.send(file=discord.File(top_path))

        await asyncio.sleep(0.5)
        await thread.send(chunked_messages[0])

        for i in range(1, len(chunked_messages)):
            if has_bot and i in boundary_indices:
                await asyncio.sleep(0.5)
                await thread.send(file=discord.File(bot_path))
            await asyncio.sleep(0.5)
            await thread.send(chunked_messages[i])

        await save_registry_thread_id(discord_id, player_name, thread.id)
        print(f"Registry card created for {player_name}")
        if not skip_index:
            asyncio.create_task(update_archive_index(guild))

    except Exception as e:
        print(f"Registry card error for {player_name}: {e}")
    finally:
        _registry_lock.release()


def get_classes_for_category(category):
    weapon_list = WEAPONS_2H if category == "2h" else WEAPONS_1H
    result = []
    for cls, weapons in CLASS_WEAPON_MAP.items():
        if any(w in weapon_list for w in weapons):
            result.append(cls)
    return sorted(set(result))

def get_weapons_for_class_and_category(selected_class, category):
    weapon_list = WEAPONS_2H if category == "2h" else WEAPONS_1H
    class_weapons = CLASS_WEAPON_MAP.get(selected_class, [])
    return sorted([w for w in class_weapons if w in weapon_list])

def get_all_weapons_for_class(selected_class):
    """Return all weapons for a subclass regardless of 1H/2H category."""
    class_weapons = CLASS_WEAPON_MAP.get(selected_class, [])
    return sorted([w for w in class_weapons if w not in FEAT_WEAPONS])

# upsert_player and log_submission are now in utils.db as _db.upsert_player / _db.add_submission


async def _process_registry_thread(guild, thread, cached_data=None, player_name=None, discord_id=None):
    """Parse an old registry thread and extract weapon marks and bounty completions."""
    import re
    if player_name is None:
        player_name = thread.name.strip()

    # Read all messages in the thread
    messages = []
    async for msg in thread.history(limit=50, oldest_first=True):
        if msg.content:
            messages.append(msg.content)

    full_text = "\n".join(messages)


    # --- Parse weapon marks ---
    # Actual format:
    #   Subclass header: "### :veteran2: Devastator: Veteran [■□□□□□]"
    #   Weapon line:     "- :level6_15: Battle Axe: [✦✦✦✦✧]"
    #   level emoji format: :levelTIER_THRESHOLD: where THRESHOLD = marks at start of current tier
    legacy_marks = {}
    current_subclass = None

    for line in full_text.split("\n"):
        line = line.strip()

        # Detect subclass header: contains a known subclass name followed by colon and a rank
        matched_subclass = None
        for subclass in REGISTRY_WEAPON_MAP.keys():
            if re.search(rf'\b{re.escape(subclass)}:\s*(?:Novice|' + '|'.join(SUBCLASS_RANKS) + r')\b', line):
                matched_subclass = subclass
                break
        if matched_subclass:
            current_subclass = matched_subclass
            continue

        if not current_subclass:
            continue

        # Detect weapon line: "- :levelTIER_THRESHOLD: WeaponName: [✦✧...]"
        level_match = re.search(r':level\d+_(\d+):', line)
        bracket_match = re.search(r'\[([✦✧]+)\]', line)

        if not (level_match and bracket_match):
            continue

        threshold = int(level_match.group(1))
        filled = bracket_match.group(1).count('✦')
        total_marks = threshold + filled

        # Extract weapon name between level emoji and bracket
        name_match = re.search(r':level\d+_\d+:\s*(.+?):\s*\[', line)
        if not name_match:
            continue

        weapon_raw = name_match.group(1).strip()
        # Strip any leading discord emoji from weapon name
        weapon_raw = re.sub(r'^(<[^>]+>|[\U0001F000-\U0010FFFF])\s*', '', weapon_raw).strip()

        if total_marks == 0:
            continue

        for w in REGISTRY_WEAPON_MAP.get(current_subclass, []):
            if w.lower() in weapon_raw.lower() or weapon_raw.lower() in w.lower():
                key = (w, current_subclass)
                legacy_marks[key] = max(legacy_marks.get(key, 0), total_marks)
                break

    if not legacy_marks:
        print(f"No legacy marks found for {player_name}, skipping")
        return

    # --- Parse legacy bounty completions ---
    KNOWN_SECTIONS = ["Feats of Legend", "Mastered Weapons", "Special Ops", "Titles:", "Vanguard:", "Knight:", "Footman:", "Archer:", "Marksman:"]
    legacy_bounties = []
    in_bounties_section = False
    for line in full_text.split("\n"):
        line = line.strip()
        if "Bounties Completed" in line:
            in_bounties_section = True
            continue
        if in_bounties_section:
            # Stop at any known next section
            if any(s in line for s in KNOWN_SECTIONS):
                in_bounties_section = False
                continue
            if not line:
                continue
            if line.startswith("•") or line.startswith("*") or line.startswith("-"):
                bounty_line = re.sub(r'^[•*\-]\s*', '', line).strip()
                # Skip weapon lines (contain bracket pattern like [✦✧] or emoji patterns)
                if not bounty_line or bounty_line.lower() == "none":
                    continue
                if re.search(r'\[.*\]|:level\d+', bounty_line):
                    continue
                # Extract placement if present (#1, #2 etc)
                placement_match = re.search(r'#(\d+)', bounty_line)
                placement = int(placement_match.group(1)) if placement_match else None
                bounty_name = re.sub(r'\s*#\d+\s*$', '', bounty_line).strip()
                # Remove any trailing emoji/discord formatting
                bounty_name = re.sub(r'<[^>]+>', '', bounty_name).strip()
                if bounty_name:
                    legacy_bounties.append((bounty_name, placement))

    # --- Parse legacy feats of legend ---
    legacy_feats = []
    in_feats_section = False
    FEAT_STOP_SECTIONS = ["Mastered Weapons", "Special Ops", "Bounties Completed", "Titles:", "Vanguard:", "Knight:", "Footman:", "Archer:", "Marksman:"]
    for line in full_text.split("\n"):
        line = line.strip()
        if "Feats of Legend" in line:
            in_feats_section = True
            continue
        if in_feats_section:
            if any(s in line for s in FEAT_STOP_SECTIONS):
                in_feats_section = False
                continue
            if not line:
                continue
            if line.startswith("•") or line.startswith("*") or line.startswith("-"):
                feat_line = re.sub(r'^[•*\-]\s*', '', line).strip()
                if not feat_line or feat_line.lower() == "none":
                    continue
                # Extract link
                link_match = re.search(r'\[.*?\]\((https?://[^\)]+)\)', feat_line)
                link = link_match.group(1) if link_match else ''
                # Extract emoji string (custom discord emojis + unicode emojis before the dash/link)
                emoji_part = re.split(r'—|\[', feat_line)[0].strip()
                # Keep only discord custom emoji tags and unicode emoji
                emojis = ''.join(re.findall(r'<a?:[^>]+>|[\U0001F000-\U0010FFFF]', emoji_part))
                if emojis:
                    legacy_feats.append((emojis, link))

    await _save_legacy_marks(player_name, guild, legacy_marks)
    await asyncio.sleep(1)

    # Save legacy bounties
    if legacy_bounties:
        await _save_legacy_bounties(player_name, legacy_bounties)
        await asyncio.sleep(1)

    # Save legacy feats
    if legacy_feats:
        await _save_legacy_feats(player_name, legacy_feats)
        await asyncio.sleep(1)

    # Use passed discord_id, or fall back to name lookup
    if discord_id is None:
        player_rows_data = (cached_data or {}).get('players') or await _db.get_all_players()
        for row in player_rows_data:
            if len(row) > 1 and row[1].strip().lower() == player_name.lower():
                try:
                    discord_id = int(row[0].strip())
                except ValueError:
                    pass
                break

    if discord_id:
        await create_or_update_registry_card(guild, discord_id, player_name, cached_data, skip_index=True)
        print(f"Registry card created for {player_name} (discord_id={discord_id})")
    else:
        print(f"No Discord ID found for {player_name}, skipping card creation")


async def _save_legacy_marks(player_name, guild, legacy_marks):
    """Save legacy weapon marks to LegacyMarks DB, avoiding duplicates."""
    try:
        existing = await _db.get_legacy_marks_for_player(player_name)
        existing_keys = {(r[0].strip(), r[1].strip()) for r in existing if len(r) >= 2}
        for (weapon, subclass), marks in legacy_marks.items():
            key = (player_name, weapon)
            if key not in existing_keys:
                await _db.add_legacy_mark(player_name, weapon, subclass, marks)
    except Exception as e:
        print(f"Legacy marks save error for {player_name}: {e}")


async def _save_legacy_bounties(player_name, legacy_bounties):
    """Save legacy bounty completions to LegacyBounties DB, avoiding duplicates."""
    try:
        existing = await _db.get_legacy_bounties_for_player(player_name)
        existing_keys = {(r[0].strip(), r[1].strip()) for r in existing if len(r) >= 2}
        for bounty_name, placement in legacy_bounties:
            import re as _re
            clean_name = _re.sub(r'<[^>]+>', '', bounty_name)
            clean_name = _re.sub(r'\*+', '', clean_name)
            clean_name = _re.sub(r'#\d+', '', clean_name)
            clean_name = _re.sub(r'[\U00010000-\U0010ffff]', '', clean_name)
            clean_name = clean_name.strip()
            if not clean_name:
                continue
            key = (player_name, clean_name)
            if key not in existing_keys:
                await _db.add_legacy_bounty(player_name, clean_name, placement or '')
    except Exception as e:
        print(f"Legacy bounties save error for {player_name}: {e}")


async def _save_legacy_feats(player_name, legacy_feats):
    """Save legacy feats of legend to LegacyFeats DB, avoiding duplicates."""
    try:
        existing = await _db.get_legacy_feats_for_player(player_name)
        existing_keys = {(r[0].strip(), r[2].strip()) for r in existing if len(r) >= 3}
        for emojis, link in legacy_feats:
            key = (player_name, link)
            if key not in existing_keys:
                await _db.add_legacy_feat(player_name, emojis, link)
    except Exception as e:
        print(f"Legacy feats save error for {player_name}: {e}")



class RegistryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="create_card", description="Create or refresh a player's registry card (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The player to create/refresh a card for")
    async def create_card(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        try:
            await create_or_update_registry_card(interaction.guild, member.id, member.display_name)
            await interaction.followup.send(f"Registry card created/updated for {member.display_name}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="refresh_card", description="Refresh your registry card.")
    @discord.app_commands.checks.cooldown(1, 300, key=lambda i: i.user.id)
    async def refresh_card(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            discord_id_str = str(interaction.user.id)

            # Check player is registered
            rows = await _db.get_all_players()
            registered = any(row and row[0].strip() == discord_id_str for row in rows)
            if not registered:
                await interaction.followup.send("No card on file. Submit a run first.", ephemeral=True)
                return

            await create_or_update_registry_card(interaction.guild, interaction.user.id, interaction.user.display_name)
            await interaction.followup.send("Registry card updated.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="purge_archive", description="Delete all threads in butlers-archive (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def purge_archive(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            forum = interaction.guild.get_channel(REGISTRY_FORUM_CHANNEL_ID)
            if not forum:
                await interaction.followup.send("Could not find butlers-archive channel.", ephemeral=True)
                return

            deleted = 0

            # Delete active threads
            for thread in list(forum.threads):
                try:
                    await thread.delete()
                    deleted += 1
                except Exception as e:
                    print(f"Error deleting thread {thread.name}: {e}")

            # Delete archived threads
            async for thread in forum.archived_threads(limit=200):
                try:
                    await thread.delete()
                    deleted += 1
                except Exception as e:
                    print(f"Error deleting archived thread {thread.name}: {e}")

            # Clear thread IDs from registry_cards so import doesn't get 404s
            try:
                reg_rows = await _db.get_all_registry_cards()
                for row in reg_rows:
                    if row and len(row) > 2 and row[2]:
                        await _db.upsert_registry_card(row[0], row[1], '')
            except Exception as e:
                print(f"Error clearing registry thread IDs: {e}")

            await interaction.followup.send(f"Purge complete — deleted {deleted} threads.", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Purge error: {e}", ephemeral=True)

    @app_commands.command(name="update_index", description="Rebuild an index thread in a forum (admin only).")
    @app_commands.describe(forum="Which forum to rebuild the index for (omit for all)")
    @app_commands.choices(forum=[
        discord.app_commands.Choice(name="all",             value="all"),
        discord.app_commands.Choice(name="butlers-archive", value="archive"),
        discord.app_commands.Choice(name="map-records",     value="map_records"),
        discord.app_commands.Choice(name="2h-weapons",      value="weapons_2h"),
        discord.app_commands.Choice(name="1h-weapons",      value="weapons_1h"),
        discord.app_commands.Choice(name="feats-of-war",    value="feats"),
        discord.app_commands.Choice(name="bounty-cards",    value="bounty_cards"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def update_index(self, interaction: discord.Interaction, forum: str = "all"):
        await interaction.response.defer(ephemeral=True)

        # Build blurbs
        weapons_blurb = (
            "**What qualifies?** Your highest kill count with a given weapon on a single submitted run. "
            "VIP map submissions do not count toward weapon high scores."
        )
        map_blurb = (
            "**What qualifies?** Your highest raw takedown count on a single submitted run for each map."
        )

        # Bounty blurb — pull active bounty weapons dynamically
        bounty_blurb = "**What is this?** A roughly monthly community challenge. Only specific weapons count for each bounty."
        try:
            from cogs.bounty import get_active_bounty
            active_bounty = await get_active_bounty()
            if active_bounty:
                weapon_list = ', '.join(active_bounty['weapons'].keys())
                bounty_blurb = (
                    f"[{active_bounty['title']}](https://discord.com/channels/1324379304544567356/1518657579088216217)\n\n"
                    f"A monthly bounty where select weapons qualify toward completion. Submit the required number of runs per weapon to complete the bounty. Often comes with a bonus challenge.\n\n"
                    f"**Weapons & Requirements:**\n" +
                    "\n".join(f"▸ {w}: {d['total']} runs" for w, d in active_bounty['weapons'].items())
                )
        except Exception as e:
            print(f"Bounty blurb fetch error: {e}")

        from cogs.leaderboards import update_leaderboard_index
        LEADERBOARD_FORUMS = {
            "map_records":  (MAP_RECORDS_FORUM_ID,  "Map Records",  map_blurb),
            "weapons_2h":   (WEAPONS_2H_FORUM_ID,   "2H Weapons",   weapons_blurb),
            "weapons_1h":   (WEAPONS_1H_FORUM_ID,   "1H Weapons",   weapons_blurb),
            "feats":        (FEATS_FORUM_ID,         "Feats of War", None),
            "bounty_cards": (BOUNTY_CARDS_FORUM_ID,  "Bounty Cards", bounty_blurb),
        }
        if forum == "all":
            await update_archive_index(interaction.guild)
            for channel_id, label, blurb in LEADERBOARD_FORUMS.values():
                await update_leaderboard_index(interaction.guild, channel_id, label, blurb)
        elif forum == "archive":
            await update_archive_index(interaction.guild)
        elif forum in LEADERBOARD_FORUMS:
            channel_id, label, blurb = LEADERBOARD_FORUMS[forum]
            await update_leaderboard_index(interaction.guild, channel_id, label, blurb)
        await interaction.followup.send("Index rebuilt.", ephemeral=True)

    @app_commands.command(name="purge_blank_cards", description="Delete registry cards for players with no marks data (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def purge_blank_cards(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            forum = interaction.guild.get_channel(REGISTRY_FORUM_CHANNEL_ID)
            if not forum:
                await interaction.followup.send("Could not find butlers-archive channel.", ephemeral=True)
                return

            rows = await _db.get_all_registry_cards()
            deleted = 0
            skipped = 0

            for row in rows:
                if len(row) < 3 or not row[0].strip() or not row[2] or not row[2].strip():
                    continue
                try:
                    discord_id = int(row[0].strip())
                except ValueError:
                    continue
                try:
                    thread_id = int(row[2].strip())
                except (ValueError, TypeError):
                    continue

                weapon_marks = await calculate_weapon_marks_for_player(discord_id)
                if weapon_marks:
                    skipped += 1
                    continue

                # No marks — delete the thread and clear the thread ID
                try:
                    thread = interaction.guild.get_thread(thread_id)
                    if not thread:
                        thread = await interaction.guild.fetch_channel(thread_id)
                    await thread.delete()
                except Exception as e:
                    print(f"Could not delete thread {thread_id}: {e}")

                await _db.upsert_registry_card(row[0], row[1], '')
                deleted += 1
                print(f"Purged blank card for {row[1].strip()} (discord_id={discord_id})")
                await asyncio.sleep(1)

            await interaction.followup.send(
                f"Purge complete — {deleted} blank cards deleted, {skipped} cards kept.",
                ephemeral=True
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Purge error: {e}", ephemeral=True)

    @app_commands.checks.has_permissions(administrator=True)
    async def rebuild_archive(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            player_rows = await _db.get_all_players()
            if not player_rows:
                await interaction.followup.send("No players found.", ephemeral=True)
                return

            total = 0
            failed = 0

            for row in player_rows:
                if len(row) < 2 or not row[0].strip() or not row[1].strip():
                    continue
                try:
                    discord_id = int(row[0].strip())
                except ValueError:
                    continue
                player_name = row[1].strip()

                try:
                    weapon_marks = await calculate_weapon_marks_for_player(discord_id)
                    if not weapon_marks:
                        print(f"Skipping {player_name} — no marks data")
                        continue
                    await create_or_update_registry_card(interaction.guild, discord_id, player_name, skip_index=True)
                    total += 1
                    print(f"Rebuilt card for {player_name}")
                except Exception as e:
                    failed += 1
                    print(f"Failed to rebuild card for {player_name}: {e}")

                await asyncio.sleep(15)  # avoid rate limits

            await update_archive_index(interaction.guild)
            await interaction.followup.send(
                f"Rebuild complete — {total} cards created/updated, {failed} failed.",
                ephemeral=True
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Rebuild error: {e}", ephemeral=True)

    @app_commands.command(name="import_single", description="Import one player's legacy registry data by name (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(thread_name="Exact thread name in the-registry (e.g. 'Massive Eggplant')")
    async def import_single(self, interaction: discord.Interaction, thread_name: str):
        await interaction.response.defer(ephemeral=True)
        try:
            old_forum = interaction.guild.get_channel(1362435483061195022)
            if not old_forum:
                await interaction.followup.send("Could not find the-registry channel.", ephemeral=True)
                return

            player_rows = await _db.get_all_players()
            id_to_name = {row[0].strip(): row[1].strip() for row in player_rows if len(row) > 1}
            name_to_id = {row[1].strip().lower(): row[0].strip() for row in player_rows if len(row) > 1}

            cached_data = {
                'players': player_rows,
                'submissions': await _db.get_all_submissions(),
                'leaderboard_data': await _db.get_all_leaderboard_data(),
                'bounty_players': await _db.get_all_bounty_players(),
                'bounties': await _db.get_all_bounties(),
            }

            # Find matching thread
            all_threads = list(old_forum.threads)
            async for thread in old_forum.archived_threads(limit=200):
                all_threads.append(thread)

            target = None
            for thread in all_threads:
                if thread.name.strip().lower() == thread_name.strip().lower():
                    target = thread
                    break

            if not target:
                await interaction.followup.send(f"No thread found named '{thread_name}' in the-registry.", ephemeral=True)
                return

            resolved_name = id_to_name.get(name_to_id.get(thread_name.strip().lower(), ''), thread_name.strip())
            discord_id = None
            id_str = name_to_id.get(thread_name.strip().lower())
            if id_str:
                try:
                    discord_id = int(id_str)
                except ValueError:
                    pass

            await _process_registry_thread(interaction.guild, target, cached_data, resolved_name, discord_id)
            await update_archive_index(interaction.guild)
            await interaction.followup.send(f"Import complete for **{resolved_name}**.", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="import_registry", description="Import old registry cards from the-registry into butlers-archive (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def import_registry(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            old_forum = interaction.guild.get_channel(1362435483061195022)  # the-registry
            if not old_forum:
                await interaction.followup.send("Could not find the-registry channel.", ephemeral=True)
                return

            # Name aliases for players who have renamed since their registry thread was created
            NAME_ALIASES = {
                "makeitrainwater": "Rainwater",
                "[legacy] shieldy": "Shieldy",
            }

            # Build name -> discord_id map from Players DB (lowercase for matching)
            player_rows = await _db.get_all_players()
            id_to_name = {row[0].strip(): row[1].strip() for row in player_rows if len(row) > 1}
            name_to_id = {row[1].strip().lower(): row[0].strip() for row in player_rows if len(row) > 1}

            # All registered player names are eligible
            players_eligible = set(name_to_id.keys())

            # Also add anyone with submissions even if not in Players table
            subs = await _db.get_all_submissions()
            for row in subs:
                discord_id = row[2].strip() if len(row) > 2 else ''
                name = row[1].strip().lower() if len(row) > 1 else ''
                if discord_id and name:
                    players_eligible.add(name)

            # Add alias names as eligible
            for alias in NAME_ALIASES:
                players_eligible.add(alias.lower())

            imported = 0
            skipped = 0

            # Pre-load all data once to avoid repeated DB queries during import
            print("Pre-loading data...")
            cached_data = {
                'players': player_rows,
                'submissions': subs,
                'leaderboard_data': await _db.get_all_leaderboard_data(),
                'bounty_players': await _db.get_all_bounty_players(),
                'bounties': await _db.get_all_bounties(),
            }
            await asyncio.sleep(2)

            all_threads = list(old_forum.threads)
            async for thread in old_forum.archived_threads(limit=200):
                all_threads.append(thread)

            processed_names = set()

            for thread in all_threads:
                thread_name = thread.name.strip()
                thread_name_lower = thread_name.lower()

                # Resolve alias to current name if applicable
                resolved_name = NAME_ALIASES.get(thread_name_lower, thread_name)
                resolved_name_lower = resolved_name.lower()

                if resolved_name_lower in players_eligible and resolved_name_lower not in processed_names:
                    processed_names.add(resolved_name_lower)
                    # Look up discord_id from Players sheet by resolved name
                    discord_id = None
                    resolved_id_str = name_to_id.get(resolved_name_lower)
                    if resolved_id_str:
                        try:
                            discord_id = int(resolved_id_str)
                        except ValueError:
                            pass
                    await _process_registry_thread(interaction.guild, thread, cached_data, resolved_name, discord_id)
                    imported += 1
                    await asyncio.sleep(15)
                else:
                    skipped += 1
                    print(f"Skipping thread '{thread_name}' — already processed or not eligible")

            await update_archive_index(interaction.guild)
            await interaction.followup.send(f"Import complete — {imported} cards created, {skipped} skipped (no submissions).", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Import error: {e}", ephemeral=True)

    @app_commands.command(name="bulk_refresh_cards", description="Refresh all player registry cards in-place (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def bulk_refresh_cards(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await _db.get_all_players()
            total = 0
            failed = 0
            for row in rows:
                if not row or not row[0].strip():
                    continue
                try:
                    discord_id = int(row[0].strip())
                except ValueError:
                    continue
                player_name = row[1].strip() if len(row) > 1 else str(discord_id)
                try:
                    await create_or_update_registry_card(interaction.guild, discord_id, player_name, skip_index=True)
                    total += 1
                    await asyncio.sleep(1)  # Avoid rate limits
                except Exception as e:
                    print(f"Bulk refresh error for {player_name}: {e}")
                    failed += 1

            # Rebuild index once at the end
            await update_archive_index(interaction.guild)

            msg = f"✅ Bulk refresh complete — {total} cards updated."
            if failed:
                msg += f" {failed} failed (check logs)."
            await interaction.followup.send(msg, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="populate_butlers_archive", description="Pre-populate ButlersArchive sheet for all players (admin only).")
    async def populate_butlers_archive(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            players = await _db.get_all_players()
            subs = await _db.get_all_submissions()
            ld_rows = await _db.get_all_leaderboard_data()
            cached_data = {'submissions': subs, 'leaderboard_data': ld_rows, 'players': players}
            total = 0
            failed = 0
            for player_row in players:
                if not player_row or not player_row[0].strip():
                    continue
                discord_id_str = player_row[0].strip()
                player_name = player_row[1].strip() if len(player_row) > 1 else discord_id_str
                try:
                    player_subs = [r for r in subs if len(r) > 2 and r[2].strip() == discord_id_str]
                    submission_count = len(player_subs)
                    last_submission = player_subs[-1][0] if player_subs else ""
                    weapon_marks_data = await calculate_weapon_marks_for_player(int(discord_id_str), cached_data=cached_data)
                    # Flatten tuple keys to weapon name only for display
                    flat_marks = {}
                    for k, v in weapon_marks_data.items():
                        w = k[0] if isinstance(k, tuple) else k
                        flat_marks[w] = flat_marks.get(w, 0) + v
                    weapon_marks_str = ", ".join(f"{w}: {int(v)}" for w, v in sorted(flat_marks.items(), key=lambda x: -x[1]) if v > 0) if flat_marks else ""
                    class_counts = {}
                    for r in player_subs:
                        if len(r) > 4:
                            cls = r[4].strip()
                            base = cls.split("(")[0].strip() if "(" in cls else cls
                            class_counts[base] = class_counts.get(base, 0) + 1
                    class_marks_str = ", ".join(f"{c}: {n}" for c, n in sorted(class_counts.items(), key=lambda x: -x[1]))
                    total_marks = sum(flat_marks.values()) if flat_marks else 0
                    # thread_id comes from the players row itself (col 2)
                    thread_id = player_row[2].strip() if len(player_row) > 2 and player_row[2] else None
                    await update_butlers_archive_row(
                        discord_id_str, player_name, thread_id,
                        total_marks, submission_count, last_submission,
                        weapon_marks_str, class_marks_str
                    )
                    total += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"ButlersArchive prepop error for {player_name}: {e}")
                    failed += 1
            msg = f"✅ ButlersArchive populated — {total} players."
            if failed:
                msg += f" {failed} failed (check logs)."
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="stats", description="Show a player's title standings and weapon ranks.")
    @app_commands.describe(player="Player name (leave blank for your own)")
    @app_commands.autocomplete(player=_player_name_ac)
    async def progress_command(self, interaction: discord.Interaction, player: str = None):
        await interaction.response.defer()

        # ── Resolve player ────────────────────────────────────────────────────────
        all_players = await _db.get_all_players()
        discord_id_str = None
        resolved_name = None

        if player is None:
            discord_id_str = str(interaction.user.id)
            for row in all_players:
                if row and row[0].strip() == discord_id_str:
                    resolved_name = row[1].strip() if len(row) > 1 else interaction.user.display_name
                    break
            if not resolved_name:
                resolved_name = interaction.user.display_name
        else:
            target = player.lower()
            for row in all_players:
                if len(row) > 1 and row[1].strip().lower() == target:
                    discord_id_str = row[0].strip()
                    resolved_name = row[1].strip()
                    break
            if not discord_id_str:
                await interaction.followup.send(f"Player **{player}** not found.", ephemeral=True)
                return

        # ── Weapon rank progress ──────────────────────────────────────────────────
        weapon_marks_data = await calculate_weapon_marks_for_player(int(discord_id_str))
        flat_marks = {}
        for k, v in weapon_marks_data.items():
            w = k[0] if isinstance(k, tuple) else k
            flat_marks[w] = flat_marks.get(w, 0) + v

        weapon_lines = []
        for weapon, marks in sorted(flat_marks.items(), key=lambda x: -x[1]):
            if marks <= 0:
                continue
            rank_name, _, next_thresh = get_weapon_rank(marks)
            rank_emoji = WEAPON_RANK_EMOJIS.get(rank_name, "")
            marks_fmt = format_weapon_marks(marks)
            if next_thresh is None:
                # Iridescent — check prestige
                prestige = sum(1 for t in PRESTIGE_THRESHOLDS if marks >= t)
                next_prestige = next((t for t in PRESTIGE_THRESHOLDS if marks < t), None)
                if next_prestige:
                    delta = next_prestige - marks
                    weapon_lines.append(f"{rank_emoji} **{weapon}** — {marks_fmt} *(+{delta} to ×{prestige + 1})*")
                else:
                    weapon_lines.append(f"{rank_emoji} **{weapon}** — {marks_fmt} *(max prestige)*")
            else:
                delta = next_thresh - marks
                next_rank = next((name for thresh, name in WEAPON_RANK_THRESHOLDS if thresh == next_thresh), "")
                weapon_lines.append(f"{rank_emoji} **{weapon}** — {marks_fmt} *(+{delta} to {next_rank})*")

        # ── Title standings ───────────────────────────────────────────────────────
        ld = await _db.get_all_leaderboard_data()
        SKIP_LB = {"100 Kills", "200 Takedowns"}
        WEAPON_FEAT_BOARDS = {"Mallet", "Knife"}
        NON_WEAPON_FEAT_BOARDS = {"Flawless", "Healing Horn"}

        lb_groups = {}
        for row in ld:
            if len(row) < 4:
                continue
            lb_name = row[0].strip()
            p_name = row[1].strip()
            if lb_name not in lb_groups:
                lb_groups[lb_name] = []
            lb_groups[lb_name].append(p_name)

        player_weapon_boards = 0
        player_map_boards = 0
        player_combined_boards = 0

        holder_weapon = {}   # player -> count
        holder_map = {}
        holder_combined = {}

        for lb_name, players_on_board in lb_groups.items():
            if lb_name in SKIP_LB:
                continue
            is_map = " - " in lb_name
            is_non_weapon_feat = lb_name in NON_WEAPON_FEAT_BOARDS
            for i, p in enumerate(players_on_board[:10]):
                if is_map:
                    holder_map[p] = holder_map.get(p, 0) + 1
                    holder_combined[p] = holder_combined.get(p, 0) + 1
                elif is_non_weapon_feat:
                    holder_combined[p] = holder_combined.get(p, 0) + 1
                else:
                    holder_weapon[p] = holder_weapon.get(p, 0) + 1
                    holder_combined[p] = holder_combined.get(p, 0) + 1

        player_weapon_boards = holder_weapon.get(resolved_name, 0)
        player_map_boards = holder_map.get(resolved_name, 0)
        player_combined_boards = holder_combined.get(resolved_name, 0)

        # Current holders
        def breadth_leader(d, min_boards):
            qualified = {p: v for p, v in d.items() if v >= min_boards}
            if not qualified:
                return None, 0
            top = max(qualified, key=lambda p: qualified[p])
            return top, qualified[top]

        gm_holder, gm_count = breadth_leader(holder_combined, 15)
        wm_holder, wm_count = breadth_leader(holder_weapon, 9)
        cm_holder, cm_count = breadth_leader(holder_map, 6)

        # Headhunter / Butcher — average score across a player's 100-Kill / 200-TD runs
        kills_best = {}  # player -> list of scores
        td_best = {}   # player -> list of scores
        for row in ld:
            if len(row) < 4:
                continue
            lb_name = row[0].strip()
            p_name = row[1].strip()
            try:
                score = int(row[3])
            except (ValueError, IndexError):
                continue
            if lb_name == "100 Kills":
                kills_best.setdefault(p_name, []).append(score)
            elif lb_name == "200 Takedowns":
                td_best.setdefault(p_name, []).append(score)

        # Highest AVERAGE score among players with enough qualifying runs — a
        # single lucky game shouldn't crown anyone.
        _MIN_QUALIFYING_RUNS = 3

        def _avg(scores):
            return round(sum(scores) / len(scores)) if scores else 0

        def _title_holder(best):
            eligible = {p: s for p, s in best.items() if len(s) >= _MIN_QUALIFYING_RUNS}
            if not eligible:
                return None, 0
            holder = max(eligible, key=lambda p: _avg(eligible[p]))
            return holder, _avg(eligible[holder])

        hh_holder, hh_score = _title_holder(kills_best)
        bt_holder, bt_score = _title_holder(td_best)

        player_kills_best = _avg(kills_best.get(resolved_name, []))
        player_td_best = _avg(td_best.get(resolved_name, []))
        player_kills_runs = len(kills_best.get(resolved_name, []))
        player_td_runs = len(td_best.get(resolved_name, []))

        # Total board counts
        total_combined_boards = len(set(holder_combined.keys()) and holder_combined) and len(holder_combined) or 0
        total_weapon_boards = len(holder_weapon) if holder_weapon else 0
        total_map_boards = len(holder_map) if holder_map else 0
        # More accurate: count unique board names
        all_board_names = set(lb_groups.keys()) - {"100 Kills", "200 Takedowns"}
        total_combined_boards = len(all_board_names)
        total_weapon_boards = len([b for b in all_board_names if " - " not in b and b not in {"Flawless", "Healing Horn"}])
        total_map_boards = len([b for b in all_board_names if " - " in b])

        _TITLE_PAD = max(len(l) for l in ["Grand Marshal", "Weapons Master", "Campaign Master", "Apex", "Frenzied"])

        def fmt_title(emoji, label, player_val, holder_name, holder_val, resolved, is_board=True, total=None, player_runs=None):
            padded = f"{label:<{_TITLE_PAD}}"
            if is_board:
                total_str = f"/{total}" if total is not None else ""
                if resolved == holder_name:
                    return f"{emoji} `{padded}` \u2713 ({player_val}{total_str})"
                diff = holder_val - player_val
                return f"{emoji} `{padded}` \u2014 `{player_val}{total_str}` / `{holder_val}{total_str}` {holder_name} **(-{diff})**"
            # Stat titles (Headhunter / Butcher): minimalist average display
            if resolved == holder_name and holder_name not in (None, "N/A"):
                return f"{emoji} `{padded}` \u2014 avg {player_val} \U0001f451"
            # Below the qualifying-run minimum: say so, instead of an apples-to-oranges compare
            if player_runs is not None and player_runs < _MIN_QUALIFYING_RUNS:
                you = (f"avg {player_val} ({player_runs}/{_MIN_QUALIFYING_RUNS} runs to qualify)"
                       if player_val else f"{player_runs}/{_MIN_QUALIFYING_RUNS} runs to qualify")
                if holder_name in (None, "N/A") or not holder_val:
                    return f"{emoji} `{padded}` \u2014 {you}"
                return f"{emoji} `{padded}` \u2014 {you} \u00b7 leader {holder_name} ({holder_val})"
            parts = []
            if player_val:
                parts.append(f"avg {player_val}")
            if holder_name not in (None, "N/A") and holder_val:
                parts.append(f"leader {holder_name} ({holder_val})")
            if not parts:
                parts.append("no runs yet")
            return f"{emoji} `{padded}` \u2014 " + " \u00b7 ".join(parts)

        title_lines = [
            fmt_title(config.TITLE_EMOJIS["Grand Marshal"],   "Grand Marshal",   player_combined_boards, gm_holder or "N/A", gm_count, resolved_name, total=total_combined_boards),
            fmt_title(config.TITLE_EMOJIS["Weapons Master"],  "Weapons Master",  player_weapon_boards,   wm_holder or "N/A", wm_count, resolved_name, total=total_weapon_boards),
            fmt_title(config.TITLE_EMOJIS["Campaign Master"], "Campaign Master", player_map_boards,      cm_holder or "N/A", cm_count, resolved_name, total=total_map_boards),
            fmt_title(config.TITLE_EMOJIS["Headhunter"],      "Apex",            player_kills_best,      hh_holder or "N/A", hh_score, resolved_name, is_board=False, player_runs=player_kills_runs),
            fmt_title(config.TITLE_EMOJIS["Butcher"],         "Frenzied",        player_td_best,         bt_holder or "N/A", bt_score, resolved_name, is_board=False, player_runs=player_td_runs),
        ]

        # Weapon ranks — Gold+ only, top 10
        SHOW_RANKS = {"Gold", "Emerald", "Diamond", "Crimson", "Prestige Bronze", "Prestige Silver",
                      "Prestige Gold", "Prestige Emerald", "Prestige Diamond", "Prestige Crimson", "Iridescent"}
        weapon_lines_filtered = []
        for weapon, marks in sorted(flat_marks.items(), key=lambda x: -x[1]):
            if marks <= 0:
                continue
            rank_name, _, next_thresh = get_weapon_rank(marks)
            if rank_name not in SHOW_RANKS:
                continue
            rank_emoji = WEAPON_RANK_EMOJIS.get(rank_name, "")
            marks_fmt = format_weapon_marks(marks)
            if next_thresh is None:
                prestige = sum(1 for t in PRESTIGE_THRESHOLDS if marks >= t)
                next_prestige = next((t for t in PRESTIGE_THRESHOLDS if marks < t), None)
                if next_prestige:
                    delta = next_prestige - marks
                    weapon_lines_filtered.append(f"{rank_emoji} **{weapon}** \u2014 {marks_fmt} *(+{delta} to \xd7{prestige + 1})*")
                else:
                    weapon_lines_filtered.append(f"{rank_emoji} **{weapon}** \u2014 {marks_fmt} *(max prestige)*")
            else:
                delta = next_thresh - marks
                next_rank = next((name for thresh, name in WEAPON_RANK_THRESHOLDS if thresh == next_thresh), "")
                weapon_lines_filtered.append(f"{rank_emoji} **{weapon}** \u2014 {marks_fmt} *(+{delta} to {next_rank})*")
            if len(weapon_lines_filtered) >= 10:
                break

        # \u2500\u2500 Personal bests from submissions \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        all_subs = await _db.get_all_submissions()
        discord_id_str_for_subs = discord_id_str
        player_subs = [r for r in all_subs if len(r) > 8 and r[2].strip() == discord_id_str_for_subs]
        sub_count = len(player_subs)

        # Add legacy run count from LegacyMarks
        try:
            p_name = None
            for pr in all_players:
                if pr and pr[0].strip() == discord_id_str:
                    p_name = pr[1].strip() if len(pr) > 1 else None
                    break
            if p_name:
                legacy_rows = await _db.get_legacy_marks_for_player(p_name)
                legacy_run_count = sum(
                    int(r[3]) for r in legacy_rows
                    if len(r) > 3 and r[3].strip().isdigit()
                )
                sub_count += legacy_run_count
        except Exception:
            pass

        best_td_row = None
        best_kills_row = None
        pb_td = 0
        pb_kills = 0
        td_list = []
        kill_list = []
        for r in player_subs:
            try:
                rtd = int(r[7]); rk = int(r[8])
            except (ValueError, IndexError):
                continue
            td_list.append(rtd); kill_list.append(rk)
            if rtd > pb_td:
                pb_td = rtd; best_td_row = r
            if rk > pb_kills:
                pb_kills = rk; best_kills_row = r

        # Legacy LeaderboardData check for best TD
        ld_all = ld  # already fetched above
        for ld_r in ld_all:
            if len(ld_r) < 4:
                continue
            if ld_r[1].strip() != resolved_name:
                continue
            lb = ld_r[0].strip()
            if ' - ' in lb or lb in {'Flawless', 'Healing Horn', '200 Takedowns', '100 Kills'}:
                continue
            try:
                ld_td = int(ld_r[3])
            except ValueError:
                continue
            if ld_td > pb_td:
                pb_td = ld_td
                best_td_row = ['legacy', resolved_name, '', lb, '', '', '', str(ld_td), '?', '?']

        def _pb_str(row):
            if row is None:
                return None
            is_legacy = row[0] == 'legacy'
            weapon = row[3].strip() if len(row) > 3 else '?'
            tds = row[7].strip() if len(row) > 7 else '?'
            if is_legacy:
                return f"**{weapon}** \u2014 {tds} TD *(legacy, no map data)*"
            map_ = row[5].strip() if len(row) > 5 else '?'
            kills = row[8].strip() if len(row) > 8 else '?'
            deaths = row[9].strip() if len(row) > 9 else '?'
            return f"**{weapon}** \u2014 {tds} TD / {kills} K / {deaths} D on {map_}"

        # Biggest lead — largest gap between this player's 1st place score and 2nd place on any board
        biggest_lead_str = ''
        try:
            from collections import defaultdict
            boards: dict = defaultdict(list)
            SKIP_BOARDS = {'100 Kills', '200 Takedowns', 'Flawless', 'Healing Horn'}
            for ld_r in ld_all:
                if len(ld_r) < 4:
                    continue
                lb = ld_r[0].strip()
                if ' - ' in lb or lb in SKIP_BOARDS:
                    continue
                try:
                    score = int(ld_r[3])
                except ValueError:
                    continue
                boards[lb].append((score, ld_r[1].strip()))
            best_gap = 0
            best_gap_board = ''
            best_gap_score = 0
            best_gap_second = 0
            for lb, entries in boards.items():
                entries.sort(key=lambda x: x[0], reverse=True)
                if not entries or entries[0][1] != resolved_name:
                    continue
                if len(entries) < 2:
                    continue
                gap = entries[0][0] - entries[1][0]
                if gap > best_gap:
                    best_gap = gap
                    best_gap_board = lb
                    best_gap_score = entries[0][0]
                    best_gap_second = entries[1][0]
            if best_gap > 0:
                biggest_lead_str = f"+{best_gap} TD lead on {best_gap_board} ({best_gap_score} vs {best_gap_second})"
        except Exception:
            biggest_lead_str = ''


        # ── Special Ops ──────────────────────────────────────────────────
        special_ops = await get_special_ops_for_player(int(discord_id_str))
        # ── Bounties completed ───────────────────────────────────────────
        bounty_completions = await get_bounty_completions_for_player(int(discord_id_str))
        # ── Hundred Handed progress ──────────────────────────────────────
        try:
            from cogs.leaderboards import _HH_PRIMARIES, HH_TOTAL
            _hh_rows = await _db.get_hundred_handed_progress(discord_id_str)
            _hh_done = {(r[0], r[1]) for r in _hh_rows}
            _hh_required = {(sc, w) for sc, ws in _HH_PRIMARIES.items() for w in ws}
            hh_count = len(_hh_done & _hh_required)
            hh_complete = hh_count >= HH_TOTAL
        except Exception:
            hh_count = 0
            hh_complete = False
        # ── Lethality ────────────────────────────────────────────────────
        best_lethality = 0.0
        for r in player_subs:
            try:
                rk = int(r[8]); rtd = int(r[7])
                if rtd > 0:
                    leth = round(rk / rtd * 100, 1)
                    if leth > best_lethality:
                        best_lethality = leth
            except (ValueError, IndexError):
                continue
        # ── Butler titles ────────────────────────────────────────────────
        try:
            from cogs.favourites import calculate_butler_stats
            fav_stats = await calculate_butler_stats()
            butler_titles = await get_butler_titles_for_player(int(discord_id_str), fav_stats)
        except Exception:
            butler_titles = []

        # -- Total marks
        total_marks = sum(flat_marks.values())

        # -- Build output
        cigar = "<:cigar:1444893851427803298>"
        lines = [f"{cigar} **`{resolved_name}`** — {sub_count} submissions", ""]

        if butler_titles:
            lines.append("**Current Titles**")
            for t in butler_titles:
                lines.append(f"│ {t}")
            lines.append("")

        lines.append("**Title Standings**")
        for t in title_lines:
            lines.append(f"│ {t}")

        # Personal Bests
        pb_td_str = _pb_str(best_td_row)
        pb_kills_str = _pb_str(best_kills_row) if best_kills_row and _pb_str(best_kills_row) != pb_td_str else None
        has_pb = pb_td_str or pb_kills_str or biggest_lead_str
        has_lethality = best_lethality > 0

        if has_pb or has_lethality:
            lines.append("")
            lines.append("**Personal Bests**")
            if pb_td_str:
                lines.append(f"│ <a:toptkd:1360312666475728958> {pb_td_str}")
            if pb_kills_str:
                lines.append(f"│ <a:topkill:1360314538364240024> {pb_kills_str}")
            if biggest_lead_str:
                lines.append(f"│ 🏆 {biggest_lead_str}")
            if has_lethality:
                lethal_emoji = "<a:mostlethal:1520490418817601658>" if best_lethality >= 5.0 else "🧪"
                lines.append(f"│ {lethal_emoji} {best_lethality}% peak lethality")

        if special_ops:
            lines.append("")
            lines.append("**Special Ops**")
            ops_parts = []
            for feat, link in special_ops.items():
                emoji = SPECIAL_OPS_EMOJIS.get(feat, "")
                if link:
                    ops_parts.append(f"[{emoji} {feat}]({link})")
                else:
                    ops_parts.append(f"{emoji} {feat}")
            lines.append("│ " + "  ".join(ops_parts))

        if hh_count > 0:
            _hh_emoji = "<:hhanded:1430199468246044772>"
            hh_suffix = " ✓" if hh_complete else ""
            lines.append("")
            lines.append(f"**Hundred Handed**")
            lines.append(f"│ {_hh_emoji} {hh_count}/{HH_TOTAL}{hh_suffix}")

        if bounty_completions:
            def _place(n):
                if n is None:
                    return ""
                suf = {1: "st", 2: "nd", 3: "rd"}.get(n if n <= 3 else 0, "th")
                return f" ({n}{suf})"
            _dart = "🎯"
            _sorted_bounties = sorted(bounty_completions, key=lambda x: x[1] if x[1] is not None else 999)
            bounty_row = "  ".join(
                (emoji or _dart) + _place(pl)
                for _, pl, emoji in _sorted_bounties
            )
            lines.append("")
            lines.append(f"**Bounties**")
            lines.append(f"│ {bounty_row}")

        mastered_weapons = [w for w, m in flat_marks.items() if m >= 100]
        if mastered_weapons:
            _iridescent = WEAPON_RANK_EMOJIS.get("Iridescent", "")
            lines.append("")
            lines.append("**Mastered Weapons**")
            for w in sorted(mastered_weapons):
                lines.append(f"│ {_iridescent} {w}")

        output = "\n".join(lines)
        await interaction.followup.send(output[:1900])


async def setup(bot):
    await bot.add_cog(RegistryCog(bot))
