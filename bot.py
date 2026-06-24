import discord
import os
import asyncio
import gspread
import json
from google.oauth2.service_account import Credentials
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
SHEET_ID = '1aT7MbBa3qZxx9ZyaFvlgmbjvCDe2kkQMt5Qsnq_6lzY'
DECORATION_TOP = os.getenv('DECORATION_TOP', 'WMMR_Spacer_Top.png')
DECORATION_BOTTOM = os.getenv('DECORATION_BOTTOM', 'WMMR_Spacer_Bottom.png')

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
creds = Credentials.from_service_account_info(json.loads(google_creds_json), scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID)
submissions_ws = sheet.worksheet('Submissions')
players_ws = sheet.worksheet('Players')
leaderboards_ws = sheet.worksheet('Leaderboards')
leaderboard_data_ws = sheet.worksheet('LeaderboardData')

# RegistryCards sheet — columns: DiscordID, PlayerName, ForumThreadID
try:
    registry_ws = sheet.worksheet('RegistryCards')
except gspread.exceptions.WorksheetNotFound:
    registry_ws = sheet.add_worksheet(title='RegistryCards', rows=500, cols=5)
    registry_ws.append_row(['DiscordID', 'PlayerName', 'ForumThreadID'])

# BountyPlayers sheet — columns: BountyTitle, DiscordID, PlayerName, ForumPostID, Progress (JSON)
try:
    bounty_players_ws = sheet.worksheet('BountyPlayers')
except gspread.exceptions.WorksheetNotFound:
    bounty_players_ws = sheet.add_worksheet(title='BountyPlayers', rows=500, cols=10)
    bounty_players_ws.append_row(['BountyTitle','DiscordID','PlayerName','ForumPostID','Progress'])

# Bounty sheet — columns: Title, ChannelID, MessageID, ThemeEmoji, Weapons (JSON),
#                          SpecialChallenge, SpecialDone (0/1), Completions (JSON), Active (TRUE/FALSE), RoleID
try:
    bounty_ws = sheet.worksheet('Bounty')
except gspread.exceptions.WorksheetNotFound:
    bounty_ws = sheet.add_worksheet(title='Bounty', rows=100, cols=20)
    bounty_ws.append_row(['Title','ChannelID','MessageID','ThemeEmoji','Weapons','SpecialChallenge','SpecialDone','Completions','Active','RoleID','ForumChannelID','CompletionsMsgID','BonusMsgID'])

REGISTRY_FORUM_CHANNEL_ID = 1519127645286170654  # butlers-archive forum

SUBMISSIONS_CHANNEL_ID = 1328832440927518920
BOUNTY_FORUM_CHANNEL_ID = 1456640264004435978  # The Ledger forum for player bounty cards
BULLETIN_BOARD_CATEGORY_ID = 1359537379039252550
LEDGER_CATEGORY_ID = 1456640264004435978
MOD_ROLE_ID = 1472259982241300611
BUTLERS_NOTES_CHANNEL_ID = 1518771519075909702
BUTLERS_FAVOURITES_CHANNEL_ID = 1518822798116524092
MAIN_CHANNEL_ID = 1324447691467526338  # #main

GRAND_MARSHAL_ROLE_ID = 1467680214560674020
WEAPONS_MASTER_ROLE_ID = 1467679890706010277
CAMPAIGN_MASTER_ROLE_ID = 1518820158821367858
HEADHUNTER_ROLE_ID = 1518827472718921819
BUTCHER_ROLE_ID = 1518827620572205097

# Rate limiting for /butlers_report — user_id -> last used timestamp
_butlers_report_cooldowns = {}

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

WEAPONS_2H = [
    "Battle Axe", "Dane Axe", "Executioner's Axe", "Glaive",
    "Goedendag", "Greatsword", "Halberd", "Highland Sword", "Katars",
    "Longsword", "Maul", "Messer", "Morning Star", "Pole Axe", "Polehammer",
    "Quarterstaff", "Shovel", "Sledge Hammer", "Spear", "Two-Handed Hammer",
    "War Axe", "War Club", "Heavy Mace"
]

WEAPONS_1H = [
    "Axe", "Dagger", "Falchion", "Fist and Shield", "Hatchet", "Healing Horn",
    "Heavy Cavalry Sword", "Knife", "Mace", "Mallet", "One-Handed Spear",
    "Pick Axe", "Rapier", "Short Sword", "Sword", "Warhammer", "Cudgel"
]

CLASS_WEAPON_MAP = {
    # Knight subclasses
    "Officer": ["Greatsword", "Heavy Mace", "Longsword", "Mace", "Pole Axe", "War Axe"],
    "Guardian": ["Axe", "Falchion", "Fist and Shield", "Heavy Cavalry Sword", "One-Handed Spear", "Warhammer"],
    "Crusader": ["Battle Axe", "Executioner's Axe", "Messer", "Morning Star", "Quarterstaff", "Two-Handed Hammer"],
    # Vanguard subclasses
    "Devastator": ["Battle Axe", "Executioner's Axe", "Greatsword", "Highland Sword", "Maul", "War Club"],
    "Raider": ["Dane Axe", "Glaive", "Messer", "Two-Handed Hammer"],
    "Ambusher": ["Cudgel", "Dagger", "Hatchet", "Katars", "Knife", "Short Sword"],
    # Footman subclasses
    "Poleman": ["Glaive", "Goedendag", "Halberd", "Polehammer", "Quarterstaff", "Spear"],
    "Man-at-Arms": ["Falchion", "Fist and Shield", "Healing Horn", "Heavy Cavalry Sword", "Mace", "Morning Star", "One-Handed Spear", "Rapier", "Sword"],
    "Field Engineer": ["Goedendag", "Mallet", "Pick Axe", "Shovel", "Sledge Hammer"],
}

SUBCLASS_PARENT = {
    "Officer": "Knight",
    "Guardian": "Knight",
    "Crusader": "Knight",
    "Devastator": "Vanguard",
    "Raider": "Vanguard",
    "Ambusher": "Vanguard",
    "Poleman": "Footman",
    "Man-at-Arms": "Footman",
    "Field Engineer": "Footman",
    "Longbowman": "Archer",
    "Crossbowman": "Archer",
    "Skirmisher": "Archer",
}

MAP_FACTIONS = {
    "Aberfell": ["Agatha", "Mason"],
    "Askandir": ["Mason", "Tenosia"],
    "Baudwyn": ["Mason", "Tenosia"],
    "Bridgetown": ["Agatha", "Tenosia"],
    "Coxwell": ["Agatha", "Mason"],
    "Darkforest": ["Agatha", "Mason"],
    "Falmire": ["Agatha", "Mason"],
    "Galencourt": ["Agatha", "Mason"],
    "Lionspire": ["Agatha", "Mason"],
    "Montcrux": ["Agatha", "Tenosia"],
    "Rudhelm": ["Agatha", "Mason"],
    "Thayic Stronghold": ["Agatha", "Mason"],
    "Trayan Citadel": ["Agatha", "Mason"],
}

MAPS = sorted(MAP_FACTIONS.keys())
FEAT_WEAPONS = ["Mallet", "Knife", "Healing Horn", "Fist and Shield"]

MARKSMAN_SUBCLASSES = {
    "Longbowman": ["Bow", "War Bow"],
    "Crossbowman": ["Crossbow", "Siege Crossbow"],
    "Skirmisher": ["Javelin", "Throwing Axe"],
}


# ---------------------------------------------------------------------------
# Submission text parser — alias map for weapon/class inference
# Add new aliases here as the community uses them
# ---------------------------------------------------------------------------
WEAPON_ALIASES = {
    "ls": "Longsword",
    "longsword": "Longsword",
    "hmace": "Heavy Mace",
    "heavy mace": "Heavy Mace",
    "mace": "Mace",
    "1h mace": "Mace",
    "dane": "Dane Axe",
    "dane axe": "Dane Axe",
    "exe axe": "Executioner's Axe",
    "exec axe": "Executioner's Axe",
    "executioner axe": "Executioner's Axe",
    "executioners axe": "Executioner's Axe",
    "baxe": "Battle Axe",
    "battle axe": "Battle Axe",
    "gs": "Greatsword",
    "greatsword": "Greatsword",
    "mstar": "Morning Star",
    "morning star": "Morning Star",
    "qs": "Quarterstaff",
    "quarterstaff": "Quarterstaff",
    "halberd": "Halberd",
    "glaive": "Glaive",
    "spear": "Spear",
    "dagger": "Dagger",
    "knife": "Knife",
    "hatchet": "Hatchet",
    "katars": "Katars",
    "falchion": "Falchion",
    "rapier": "Rapier",
    "sword": "Sword",
    "short sword": "Short Sword",
    "war axe": "War Axe",
    "pole axe": "Pole Axe",
    "poleaxe": "Pole Axe",
    "polehammer": "Polehammer",
    "maul": "Maul",
    "war club": "War Club",
    "shovel": "Shovel",
    "pick axe": "Pick Axe",
    "pickaxe": "Pick Axe",
    "mallet": "Mallet",
    "sledge": "Sledge Hammer",
    "sledgehammer": "Sledge Hammer",
    "sledge hammer": "Sledge Hammer",
    "highland sword": "Highland Sword",
    "warhammer": "Warhammer",
    "war hammer": "Warhammer",
    "goedendag": "Goedendag",
    "cudgel": "Cudgel",
    "healing horn": "Healing Horn",
    "fist": "Fist and Shield",
    "fist and shield": "Fist and Shield",
    "heavy cavalry sword": "Heavy Cavalry Sword",
    "hcs": "Heavy Cavalry Sword",
    "one handed spear": "One-Handed Spear",
    "1h spear": "One-Handed Spear",
    "two handed hammer": "Two-Handed Hammer",
    "2h hammer": "Two-Handed Hammer",
    "bow": "Bow",
    "war bow": "War Bow",
    "crossbow": "Crossbow",
    "siege crossbow": "Siege Crossbow",
    "javelin": "Javelin",
    "throwing axe": "Throwing Axe",
}

SUBCLASS_ALIASES = {
    "knight": "Knight",
    "vanguard": "Vanguard",
    "van": "Vanguard",
    "footman": "Footman",
    "archer": "Archer",
    "devastator": "Devastator",
    "dev": "Devastator",
    "crusader": "Crusader",
    "guardian": "Guardian",
    "raider": "Raider",
    "ambusher": "Ambusher",
    "poleman": "Poleman",
    "man at arms": "Man-at-Arms",
    "man-at-arms": "Man-at-Arms",
    "maa": "Man-at-Arms",
    "field engineer": "Field Engineer",
    "engineer": "Field Engineer",
    "eng": "Field Engineer",
    "officer": "Officer",
    "longbowman": "Longbowman",
    "crossbowman": "Crossbowman",
    "skirmisher": "Skirmisher",
}

# Parent class -> list of subclasses
PARENT_TO_SUBCLASSES = {
    "Knight": ["Officer", "Guardian", "Crusader"],
    "Vanguard": ["Devastator", "Raider", "Ambusher"],
    "Footman": ["Poleman", "Man-at-Arms", "Field Engineer"],
    "Archer": ["Crossbowman", "Longbowman", "Skirmisher"],
}

def parse_submission_text(text):
    """Parse message caption for weapon and subclass hints.
    Returns (weapon, subclass) — either may be None if not detected."""
    text_lower = text.lower().strip()

    detected_weapon = None
    detected_subclass = None

    # Check weapon aliases (longest match first to avoid 'mace' matching before 'heavy mace')
    for alias in sorted(WEAPON_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            detected_weapon = WEAPON_ALIASES[alias]
            break

    # Check subclass/class aliases
    detected_parent = None
    for alias in sorted(SUBCLASS_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            raw = SUBCLASS_ALIASES[alias]
            if raw in PARENT_TO_SUBCLASSES:
                # Parent class detected — try to resolve via weapon cross-reference
                detected_parent = raw
            else:
                detected_subclass = raw
            break

    # Cross-reference: if we have a parent class + weapon, resolve to exact subclass
    if detected_parent and detected_weapon:
        subs = PARENT_TO_SUBCLASSES[detected_parent]
        candidates = [s for s in subs if detected_weapon in CLASS_WEAPON_MAP.get(s, [])]
        if len(candidates) == 1:
            detected_subclass = candidates[0]
        # else ambiguous even with weapon — leave None

    return detected_weapon, detected_subclass

# ---------------------------------------------------------------------------
# Registry / Player Card System
# ---------------------------------------------------------------------------

REGISTRY_FORUM_CHANNEL_ID = 1519127645286170654

# Weapon lists per subclass (feat weapons excluded)
REGISTRY_WEAPON_MAP = {
    # Knight
    "Officer":       ["Greatsword", "Heavy Mace", "Longsword", "Mace", "Pole Axe", "War Axe"],
    "Guardian":      ["Axe", "Falchion", "Heavy Cavalry Sword", "One-Handed Spear", "Warhammer"],
    "Crusader":      ["Battle Axe", "Executioner's Axe", "Messer", "Morning Star", "Quarterstaff", "Two-Handed Hammer"],
    # Vanguard
    "Devastator":    ["Battle Axe", "Executioner's Axe", "Greatsword", "Highland Sword", "Maul", "War Club"],
    "Raider":        ["Dane Axe", "Glaive", "Messer", "Two-Handed Hammer"],
    "Ambusher":      ["Cudgel", "Dagger", "Hatchet", "Katars", "Knife", "Short Sword"],
    # Footman
    "Poleman":       ["Glaive", "Goedendag", "Halberd", "Polehammer", "Quarterstaff", "Spear"],
    "Man-at-Arms":   ["Falchion", "Heavy Cavalry Sword", "Mace", "Morning Star", "One-Handed Spear", "Rapier", "Sword"],
    "Field Engineer":["Goedendag", "Pick Axe", "Shovel", "Sledge Hammer"],
    # Archer
    "Longbowman":    ["Bow", "War Bow"],
    "Crossbowman":   ["Crossbow", "Siege Crossbow"],
    "Skirmisher":    ["Javelin", "Throwing Axe"],
}

REGISTRY_CLASS_MAP = {
    "Knight":   ["Officer", "Guardian", "Crusader"],
    "Vanguard": ["Devastator", "Raider", "Ambusher"],
    "Footman":  ["Poleman", "Man-at-Arms", "Field Engineer"],
    "Archer":   ["Longbowman", "Crossbowman", "Skirmisher"],
}

# ---------------------------------------------------------------------------
# Registry emoji maps
# ---------------------------------------------------------------------------
WEAPON_RANK_EMOJIS = {
    "Unranked":        "<:level0_0:1361479473375219832>",
    "Bronze":          "<:level1_1:1361419350665461820>",
    "Silver":          "<:level2_3:1361419398841106442>",
    "Gold":            "<:level3_6:1361419489635209396>",
    "Emerald":         "<:level4_9:1368656036784771212>",
    "Diamond":         "<:level5_12:1368656100764942432>",
    "Crimson":         "<:level6_15:1430203489757302924>",
    "Prestige Bronze": "<:level7_20:1430216503919120537>",
    "Prestige Silver": "<:level8_30:1430216636006137876>",
    "Prestige Gold":   "<:level9_40:1430216748329599046>",
    "Prestige Emerald":"<:level10_55:1430216819787956265>",
    "Prestige Diamond":"<:level11_70:1430217739586240624>",
    "Prestige Crimson":"<:level12_85:1430217099648962651>",
    "Iridescent":      "<:level13_100:1459253823481712895>",
}

SUBCLASS_RANK_EMOJIS = {
    "Initiate":    "<:subclass0:1361423009256308808>",
    "Veteran":     "<:veteran2:1430199755094360194>",
    "Master":      "<:master3:1430199983675670619>",
    "Grandmaster": "<:grandmaster4:1430199858635210752>",
    "Champion":    "<:champion5:1430199893363789934>",
    "Paragon":     "<:paragon6:1430199955385094235>",
    "Apex":        "<:apex7:1430199916126408754>",
}

CLASS_RANK_EMOJIS = {
    "Sworn":     "<:class0_0:1446622044698443969>",
    "Trusted":   "<:class1_3:1446620360186269726>",
    "Proven":    "<:class2_6:1446620614096846988>",
    "Honored":   "<:class3_9:1446620700189266182>",
    "Esteemed":  "<:class4_12:1446620991777407128>",
    "Exalted":   "<:class5_15:1446621127605620826>",
    "Ascended":  "<:class6_18:1446621258430025791>",
}

FEAT_EMOJIS = {
    "200 Takedowns": "<a:200tkd:1363648828414230538>",
    "100 Kills":     "<a:100kill:1361412390339608686>",
    "Triple":        "<a:triple:1365532698260668466>",
    "Predator":      "<a:predator:1366794896081555567>",
    "Flawless":      "<a:flawless:1360358300834599062>",
}

SPECIAL_OPS_EMOJIS = {
    "Fist and Shield": "<a:captain_america:1366801668041211934>",
    "Healing Horn":    "<a:passive:1365531248268673086>",
    "Mallet":          "<a:predator:1366794896081555567>",
    "Knife":           "<a:100kill:1361412390339608686>",
}

WEAPON_RANK_THRESHOLDS = [
    (1,   "Bronze"),
    (5,   "Silver"),
    (12,  "Gold"),
    (25,  "Emerald"),
    (40,  "Diamond"),
    (60,  "Crimson"),
    (80,  "Prestige Bronze"),
    (100, "Prestige Silver"),
    (115, "Prestige Gold"),
    (125, "Prestige Emerald"),
    (133, "Prestige Diamond"),
    (141, "Prestige Crimson"),
    (150, "Iridescent"),
]

# Prestige thresholds past Iridescent (exponential)
PRESTIGE_THRESHOLDS = [175, 210, 260, 335, 460]

SUBCLASS_RANKS = ["Initiate", "Veteran", "Master", "Grandmaster", "Champion", "Paragon", "Apex"]
CLASS_RANKS    = ["Sworn", "Trusted", "Proven", "Honored", "Esteemed", "Exalted", "Ascended"]
PLAYER_TITLES  = ["Unbound", "Proven", "Respected", "Distinguished", "Renowned", "Illustrious", "Exemplar", "Legend"]

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

def calculate_weapon_marks_for_player(discord_id):
    """
    Count weapon marks per weapon for a player from Submissions sheet.
    1 mark per submission + 1 bonus for 200 Takedowns feat + 1 for 100 Kills + 1 for Triple.
    Returns dict: weapon_name -> total_marks
    """
    subs = submissions_ws.get_all_values()[1:]
    discord_id_str = str(discord_id)
    weapon_marks = {}

    for row in subs:
        if len(row) < 13:
            continue
        row_discord_id = row[2].strip() if len(row) > 2 else ''
        if row_discord_id != discord_id_str:
            continue
        weapon = row[3].strip() if len(row) > 3 else ''
        feats_str = row[11].strip() if len(row) > 11 else ''
        feats = [f.strip() for f in feats_str.split(',')] if feats_str and feats_str != 'None' else []

        if not weapon or weapon == 'Other':
            continue

        marks = 1  # base mark per submission
        if '200 Takedowns' in feats:
            marks += 1
        if '100 Kills' in feats:
            marks += 1
        if 'Triple' in feats:
            marks += 1

        weapon_marks[weapon] = weapon_marks.get(weapon, 0) + marks

    # Merge with legacy marks from LegacyMarks sheet
    try:
        legacy_ws = sheet.worksheet('LegacyMarks')
        legacy_rows = legacy_ws.get_all_values()[1:]
        # Find player name from discord_id
        player_rows = players_ws.get_all_values()[1:]
        player_name = None
        for row in player_rows:
            if row and row[0].strip() == discord_id_str:
                player_name = row[1].strip() if len(row) > 1 else None
                break
        if player_name:
            for row in legacy_rows:
                if len(row) < 4 or row[0].strip().lower() != player_name.lower():
                    continue
                weapon = row[1].strip()
                try:
                    marks = int(row[3])
                except ValueError:
                    continue
                weapon_marks[weapon] = weapon_marks.get(weapon, 0) + marks
    except Exception:
        pass  # LegacyMarks sheet may not exist yet

    return weapon_marks

def calculate_registry_stats(discord_id):
    """Calculate all progression stats for a player."""
    weapon_marks = calculate_weapon_marks_for_player(discord_id)

    class_stats = {}
    for cls, subclasses in REGISTRY_CLASS_MAP.items():
        subclass_stats = {}
        class_marks_total = 0

        for subclass in subclasses:
            weapons = REGISTRY_WEAPON_MAP.get(subclass, [])
            num_weapons = len(weapons)

            # Count subclass marks = sum of weapon rank-ups across all weapons in subclass
            subclass_marks = 0
            weapon_details = {}
            for w in weapons:
                marks = weapon_marks.get(w, 0)
                rank_name, _, _ = get_weapon_rank(marks) if marks > 0 else ("Unranked", 0, 1)
                # Count how many rank tiers this weapon has achieved
                tiers_achieved = sum(1 for threshold, _ in WEAPON_RANK_THRESHOLDS if marks >= threshold)
                subclass_marks += tiers_achieved
                weapon_details[w] = {'marks': marks, 'rank': rank_name, 'tiers': tiers_achieved}

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

def get_player_bounties_completed(discord_id):
    """Count distinct bounties completed by player."""
    try:
        rows = bounty_players_ws.get_all_values()[1:]
        discord_id_str = str(discord_id)
        completed = set()
        for row in rows:
            if len(row) < 5:
                continue
            if row[1].strip() == discord_id_str:
                progress_str = row[4].strip() if len(row) > 4 else '{}'
                try:
                    progress = json.loads(progress_str)
                    # Count as completed if any weapon hit its target
                    if any(v >= 1 for v in progress.values()):
                        completed.add(row[0].strip())
                except Exception:
                    pass
        return len(completed)
    except Exception:
        return 0

def get_butler_titles_for_player(discord_id, stats):
    """Return list of Butler's Favourites titles held by this player."""
    discord_id_str = str(discord_id)
    titles = []
    title_checks = [
        ('grand_marshal', '🏆 Grand Marshal'),
        ('weapons_master', '⚔️ Weapons Master'),
        ('campaign_master', '🗺️ Campaign Master'),
        ('headhunter', '💀 Headhunter'),
        ('butcher', '🩸 Butcher'),
    ]
    # stats dict uses display names not IDs — match by display name via players sheet
    rows = players_ws.get_all_values()[1:]
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

def get_special_ops_for_player(discord_id):
    """Find qualifying Special Ops submissions (feat weapons with 100+ TD)."""
    subs = submissions_ws.get_all_values()[1:]
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
    return special_ops

def get_feats_for_player(discord_id):
    """Get all feat submissions (200TD, 100K, Triple, Predator, Flawless) with links."""
    subs = submissions_ws.get_all_values()[1:]
    discord_id_str = str(discord_id)
    feats = []  # list of (feat_combo_emojis, link)
    named_feats = set()  # track named feats like Hundred-Handed

    # Check for Hundred-Handed (200TD + 100K + Triple + Flawless + no deaths)
    hundred_handed = False
    for row in subs:
        if len(row) < 13 or row[2].strip() != discord_id_str:
            continue
        feats_str = row[11].strip() if len(row) > 11 else ''
        row_feats = [f.strip() for f in feats_str.split(',')] if feats_str and feats_str != 'None' else []
        if all(f in row_feats for f in ['200 Takedowns', '100 Kills', 'Triple', 'Flawless']):
            hundred_handed = True
            break

    if hundred_handed:
        named_feats.add('hhanded')

    # Collect feat submissions
    for row in subs:
        if len(row) < 13 or row[2].strip() != discord_id_str:
            continue
        feats_str = row[11].strip() if len(row) > 11 else ''
        row_feats = [f.strip() for f in feats_str.split(',')] if feats_str and feats_str != 'None' else []
        link = row[12].strip() if len(row) > 12 else ''
        feat_emojis = ''.join(FEAT_EMOJIS[f] for f in ['200 Takedowns', '100 Kills', 'Triple', 'Predator', 'Flawless'] if f in row_feats)
        if feat_emojis:
            feats.append((feat_emojis, link))

    return named_feats, feats[:10]  # cap at 10 entries

def get_mastered_weapons_for_player(discord_id):
    """Weapons with 100+ submissions with 100+ takedowns."""
    subs = submissions_ws.get_all_values()[1:]
    discord_id_str = str(discord_id)
    weapon_counts = {}
    for row in subs:
        if len(row) < 9 or row[2].strip() != discord_id_str:
            continue
        weapon = row[3].strip()
        try:
            td = int(row[7])
        except (ValueError, IndexError):
            continue
        if td >= 100:
            weapon_counts[weapon] = weapon_counts.get(weapon, 0) + 1
    return [w for w, c in weapon_counts.items() if c >= 100]

def get_bounty_completions_for_player(discord_id):
    """Return list of (bounty_name, emoji, is_first) tuples."""
    try:
        rows = bounty_players_ws.get_all_values()[1:]
        discord_id_str = str(discord_id)
        completions = []
        # Get all bounty data to check #1 placement
        bounty_rows = bounty_ws.get_all_values()[1:] if bounty_ws else []
        for row in rows:
            if len(row) < 5 or row[1].strip() != discord_id_str:
                continue
            bounty_title = row[0].strip()
            progress_str = row[4].strip() if len(row) > 4 else '{}'
            try:
                progress = json.loads(progress_str)
                if any(v >= 1 for v in progress.values()):
                    completions.append(bounty_title)
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


def build_registry_messages(player_name, discord_id):
    """Build list of message strings for a player's registry card (one per class + header)."""
    class_stats, weapon_marks = calculate_registry_stats(discord_id)
    bounties_done = get_bounty_completions_for_player(discord_id)
    player_title = get_player_title(len(bounties_done))
    mastered = get_mastered_weapons_for_player(discord_id)
    named_feats, feat_submissions = get_feats_for_player(discord_id)
    special_ops = get_special_ops_for_player(discord_id)

    try:
        butler_stats = calculate_butler_stats()
        butler_titles = get_butler_titles_for_player(discord_id, butler_stats)
    except Exception:
        butler_titles = []

    messages = []

    # --- Message 1: Header card ---
    lines = []
    lines.append(f"🏅 *{player_title}*")
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
        for b in bounties_done:
            lines.append(f"• {b}")
        lines.append("")

    if named_feats or feat_submissions:
        lines.append("**Feats of Legend:**")
        if 'hhanded' in named_feats:
            lines.append(f"• <:hhanded:1430199468246044772> The Hundred-Handed")
        for emojis, link in feat_submissions:
            lines.append(f"• {emojis} —[Link]({link})" if link else f"• {emojis}")
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

            # Subclass meter: one block per weapon, filled when weapon has ≥1 mark
            weapons_with_marks = sum(1 for wdata in sdata['weapons'].values() if wdata['marks'] > 0)
            meter = '▰' * weapons_with_marks + '▱' * (num_weapons - weapons_with_marks)
            lines.append(f"**{sub_emoji} {subclass}: {sdata['rank']}** `[{meter}]`")

            for w, wdata in sdata['weapons'].items():
                w_emoji = WEAPON_RANK_EMOJIS.get(wdata['rank'], WEAPON_RANK_EMOJIS['Unranked'])
                mark_str = format_weapon_marks(wdata['marks'])
                lines.append(f"• {w_emoji} {w} — {mark_str}")
            lines.append("")

        messages.append("\n".join(lines))

    return messages

def get_registry_thread_id(discord_id):
    """Get existing forum thread ID for player, or None."""
    try:
        rows = registry_ws.get_all_values()[1:]
        discord_id_str = str(discord_id)
        for row in rows:
            if row and row[0] == discord_id_str:
                return int(row[2]) if len(row) > 2 and row[2] else None
    except Exception:
        return None
    return None

def save_registry_thread_id(discord_id, player_name, thread_id):
    """Save or update the thread ID in RegistryCards sheet."""
    try:
        rows = registry_ws.get_all_values()
        discord_id_str = str(discord_id)
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == discord_id_str:
                registry_ws.update_cell(i, 2, player_name)
                registry_ws.update_cell(i, 3, str(thread_id))
                return
        registry_ws.append_row([discord_id_str, player_name, str(thread_id)])
    except Exception as e:
        print(f"Registry sheet save error: {e}")

async def create_or_update_registry_card(guild, discord_id, player_name):
    """Create or update a player's registry card in the butlers-archive forum."""
    import os
    try:
        forum = guild.get_channel(REGISTRY_FORUM_CHANNEL_ID)
        if not forum:
            print(f"Registry forum channel not found: {REGISTRY_FORUM_CHANNEL_ID}")
            return

        messages = build_registry_messages(player_name, discord_id)
        thread_id = get_registry_thread_id(discord_id)

        top_path = os.path.join(os.path.dirname(__file__), 'WMMR_Spacer_Top.png')
        bot_path = os.path.join(os.path.dirname(__file__), 'WMMR_Spacer_Bottom.png')

        if thread_id:
            # Edit existing messages in order
            try:
                thread = guild.get_thread(thread_id)
                if not thread:
                    thread = await guild.fetch_channel(thread_id)
                existing = []
                async for msg in thread.history(limit=20, oldest_first=True):
                    existing.append(msg)

                # Update each message in order (skip image-only messages)
                text_msgs = [m for m in existing if m.content]
                for i, (text, msg) in enumerate(zip(messages, text_msgs)):
                    await msg.edit(content=text)
                print(f"Registry card updated for {player_name}")
                return
            except Exception as e:
                print(f"Registry thread edit error for {player_name}: {e}")

        # Create new thread — 🗂️ emoji as first post (clean preview)
        thread_with_msg = await forum.create_thread(
            name=player_name,
            content='🗂️',
        )
        thread = thread_with_msg.thread

        has_top = os.path.exists(top_path)
        has_bot = os.path.exists(bot_path)

        # Top spacer
        if has_top:
            await thread.send(file=discord.File(top_path))

        # Header accolades
        await thread.send(messages[0])

        # Each class: top spacer, class message, bottom spacer
        for msg_text in messages[1:]:
            if has_top:
                await thread.send(file=discord.File(top_path))
            await thread.send(msg_text)
            if has_bot:
                await thread.send(file=discord.File(bot_path))

        save_registry_thread_id(discord_id, player_name, thread.id)
        print(f"Registry card created for {player_name}")

    except Exception as e:
        print(f"Registry card error for {player_name}: {e}")


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

def upsert_player(discord_id, discord_name):
    try:
        rows = players_ws.get_all_values()
        discord_id_str = str(discord_id)
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == discord_id_str:
                # Update name if changed
                if len(row) < 2 or row[1] != discord_name:
                    players_ws.update_cell(i, 2, discord_name)
                return
        # Not found — append new row
        players_ws.append_row([discord_id_str, discord_name, ""])
    except Exception as e:
        print(f"Player upsert error: {e}")

def log_submission(discord_name, discord_id, weapon, cls, map_name, faction, takedowns, kills, deaths, vip, feats, message_link):
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    vip_str = "Yes" if vip else "No"
    feats_str = ", ".join(feats) if feats else "None"
    submissions_ws.append_row([
        timestamp, discord_name, str(discord_id), weapon, cls,
        map_name, faction, takedowns, kills, deaths, vip_str, feats_str, message_link
    ])
    upsert_player(discord_id, discord_name)

GUILD_ID = 1324379304544567356

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    print(f'Logged in as {bot.user}')


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Middle finger at the bot = middle finger back
    if bot.user in message.mentions and '\U0001f595' in message.content:
        await message.channel.send('\U0001f595')
        return

    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')

    # Check if this is an art post in the active bounty channel
    bounty = get_active_bounty()
    if bounty and message.channel.id == bounty['channel_id']:
        has_image = any(
            att.filename.lower().endswith(image_extensions)
            for att in message.attachments
        )
        if has_image and not bounty['completions_msg_id'] and not bounty['bonus_msg_id']:
            # Post placeholder completions and bonus boards
            completions_placeholder = (
                f"```\n"
                f"╭──────────────────────────────╮\n"
                f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}\n"
                f"╰──────────────────────────────╯\n"
                f"No completions yet.\n"
                f"```"
            )
            bonus_placeholder = (
                f"```\n"
                f"╭──────────────────────────────╮\n"
                f"  {bounty['theme_emoji']} BONUS COMPLETIONS {bounty['theme_emoji']}\n"
                f"╰──────────────────────────────╯\n"
                f"No bonus completions yet.\n"
                f"```"
            )
            try:
                comp_msg = await message.channel.send(completions_placeholder)
                bonus_msg = await message.channel.send(bonus_placeholder)
                # Save message IDs to sheet (cols 12 & 13)
                bounty_ws.update_cell(bounty['row'], 12, str(comp_msg.id))
                bounty_ws.update_cell(bounty['row'], 13, str(bonus_msg.id))
            except Exception as e:
                print(f"Bounty placeholder post error: {e}")
        return

    if message.channel.id != SUBMISSIONS_CHANNEL_ID:
        return
    if not message.attachments:
        return

    has_image = any(
        att.filename.lower().endswith(image_extensions)
        for att in message.attachments
    )
    if not has_image:
        return

    prompt_msg = await message.reply("📋 Splendid! Please submit this run.", mention_author=False)
    view = SubmitView(message, prompt_msg)
    await prompt_msg.edit(view=view)

class SubmitView(discord.ui.View):
    def __init__(self, original_message, prompt_msg):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg

    async def on_timeout(self):
        try:
            await self.prompt_msg.delete()
        except Exception:
            pass
        self.stop()


    @discord.ui.button(label='Submit Run', style=discord.ButtonStyle.green, emoji='⚔️')
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        caption = self.original_message.content.strip()
        detected_weapon, detected_subclass = parse_submission_text(caption) if caption else (None, None)
        if detected_weapon or detected_subclass:
            view = ParseConfirmView(self.original_message, self.prompt_msg, detected_weapon, detected_subclass)
            hints = []
            if detected_weapon:
                hints.append(f"Weapon: `{detected_weapon}`")
            if detected_subclass:
                hints.append(f"Class: `{detected_subclass}`")
            await interaction.response.send_message(
                content="\U0001f4cb I noticed the following in your caption \u2014 does this look right?\n" + "  |  ".join(hints),
                view=view,
                ephemeral=True
            )
        else:
            view = WeaponTypeView(self.original_message, self.prompt_msg)
            await interaction.response.send_message(
                content="**Step 1 of 6:** What type of weapon did you use?",
                view=view,
                ephemeral=True
            )

    @discord.ui.button(label='Dismiss', style=discord.ButtonStyle.grey, emoji='✖️')
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self.prompt_msg.delete()
        await interaction.response.defer()


class ParseConfirmView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, detected_weapon, detected_subclass):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.detected_weapon = detected_weapon
        self.detected_subclass = detected_subclass

    async def on_timeout(self):
        try:
            await self.prompt_msg.delete()
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label='Confirm', style=discord.ButtonStyle.green, emoji='✅')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        weapon = self.detected_weapon
        subclass = self.detected_subclass

        # If we have both weapon and subclass, skip straight to map
        if weapon and subclass:
            # Determine category from weapon
            category = "2h" if weapon in WEAPONS_2H else "1h"
            view = MapSelectView(self.original_message, self.prompt_msg, subclass, weapon)
            await interaction.response.edit_message(
                content=f"**Step 4 of 6:** Class: `{subclass}` | Weapon: `{weapon}`\nWhich map were you on?",
                view=view
            )
        elif weapon:
            # Have weapon, still need class — pass weapon so class select skips weapon step
            category = "2h" if weapon in WEAPONS_2H else "1h"
            classes = get_classes_for_category(category)
            view = ClassSelectView(self.original_message, self.prompt_msg, category, classes, pre_detected_weapon=weapon)
            await interaction.response.edit_message(
                content=f"**Step 2 of 6:** Weapon: `{weapon}`\nWhich class were you playing?",
                view=view
            )
        elif subclass:
            # Have class, still need weapon
            view = WeaponTypeView(self.original_message, self.prompt_msg)
            await interaction.response.edit_message(
                content=f"**Step 1 of 6:** Class: `{subclass}`\nWhat type of weapon did you use?",
                view=view
            )

    @discord.ui.button(label='Change', style=discord.ButtonStyle.grey, emoji='🔄')
    async def change(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        view = WeaponTypeView(self.original_message, self.prompt_msg)
        await interaction.response.edit_message(
            content="**Step 1 of 6:** What type of weapon did you use?",
            view=view
        )

class WeaponTypeView(discord.ui.View):
    def __init__(self, original_message, prompt_msg):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg

    @discord.ui.button(label='Two-Handed', style=discord.ButtonStyle.blurple, emoji='⚔️')
    async def two_handed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        classes = get_classes_for_category("2h")
        view = ClassSelectView(self.original_message, self.prompt_msg, "2h", classes)
        await interaction.response.edit_message(
            content="**Step 2 of 6:** Which class were you playing?",
            view=view
        )

    @discord.ui.button(label='One-Handed', style=discord.ButtonStyle.blurple, emoji='🗡️')
    async def one_handed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        classes = get_classes_for_category("1h")
        view = ClassSelectView(self.original_message, self.prompt_msg, "1h", classes)
        await interaction.response.edit_message(
            content="**Step 2 of 6:** Which class were you playing?",
            view=view
        )

    @discord.ui.button(label='Ranged', style=discord.ButtonStyle.blurple)
    async def ranged(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        view = MarksmanSubclassView(self.original_message, self.prompt_msg)
        await interaction.response.edit_message(
            content="**Step 2 of 6:** Class: `Marksman`\nWhich subclass were you playing?",
            view=view
        )

class MarksmanSubclassView(discord.ui.View):
    def __init__(self, original_message, prompt_msg):
        super().__init__(timeout=300)
        self.add_item(MarksmanSubclassSelect(original_message, prompt_msg))

class MarksmanSubclassSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        options = [discord.SelectOption(label=s, description=SUBCLASS_PARENT.get(s)) for s in MARKSMAN_SUBCLASSES.keys()]
        super().__init__(placeholder="Choose your subclass...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        subclass = self.values[0]
        weapons = sorted(MARKSMAN_SUBCLASSES[subclass])
        view = RangedWeaponSelectView(self.original_message, self.prompt_msg, subclass, weapons)
        await interaction.response.edit_message(
            content=f"**Step 3 of 6:** Class: `Marksman` | Subclass: `{subclass}`\nWhich weapon did you use?",
            view=view
        )

class RangedWeaponSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, subclass, weapons):
        super().__init__(timeout=300)
        self.add_item(RangedWeaponSelect(original_message, prompt_msg, subclass, weapons))

class RangedWeaponSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, subclass, weapons):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.subclass = subclass
        options = [discord.SelectOption(label=w) for w in weapons]
        super().__init__(placeholder="Choose your weapon...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_weapon = self.values[0]
        view = MapSelectView(self.original_message, self.prompt_msg, f"Marksman ({self.subclass})", selected_weapon)
        await interaction.response.edit_message(
            content=f"**Step 4 of 6:** Class: `Marksman ({self.subclass})` | Weapon: `{selected_weapon}`\nWhich map were you on?",
            view=view
        )


class ClassSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, category, classes, pre_detected_weapon=None):
        super().__init__(timeout=300)
        self.add_item(ClassSelect(original_message, prompt_msg, category, classes, pre_detected_weapon))

class ClassSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, category, classes, pre_detected_weapon=None):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.category = category
        self.pre_detected_weapon = pre_detected_weapon
        CLASS_ORDER = ["Knight", "Vanguard", "Footman", "Archer"]
        sorted_classes = sorted(classes, key=lambda c: (CLASS_ORDER.index(SUBCLASS_PARENT.get(c, "")) if SUBCLASS_PARENT.get(c) in CLASS_ORDER else 99, c))
        options = [discord.SelectOption(label=c, description=SUBCLASS_PARENT.get(c)) for c in sorted_classes]
        super().__init__(placeholder="Choose your class...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_class = self.values[0]
        if self.pre_detected_weapon:
            # Weapon already confirmed — skip straight to map
            view = MapSelectView(self.original_message, self.prompt_msg, selected_class, self.pre_detected_weapon)
            await interaction.response.edit_message(
                content=f"**Step 4 of 6:** Class: `{selected_class}` | Weapon: `{self.pre_detected_weapon}`\nWhich map were you on?",
                view=view
            )
        else:
            weapons = get_weapons_for_class_and_category(selected_class, self.category)
            view = WeaponSelectView(self.original_message, self.prompt_msg, selected_class, weapons)
            await interaction.response.edit_message(
                content=f"**Step 3 of 6:** Class: `{selected_class}`\nWhich weapon did you use?",
                view=view
            )

class WeaponSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, weapons):
        super().__init__(timeout=300)
        self.add_item(WeaponSelect(original_message, prompt_msg, selected_class, weapons))

class WeaponSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, weapons):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        options = [discord.SelectOption(label=w) for w in weapons]
        super().__init__(placeholder="Choose your weapon...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_weapon = self.values[0]
        view = MapSelectView(self.original_message, self.prompt_msg, self.selected_class, selected_weapon)
        await interaction.response.edit_message(
            content=f"**Step 4 of 6:** Class: `{self.selected_class}` | Weapon: `{selected_weapon}`\nWhich map were you on?",
            view=view
        )

class MapSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon):
        super().__init__(timeout=300)
        self.add_item(MapSelect(original_message, prompt_msg, selected_class, selected_weapon))

class MapSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        options = [discord.SelectOption(label=m) for m in MAPS]
        super().__init__(placeholder="Choose your map...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_map = self.values[0]
        view = FactionSelectView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, selected_map)
        await interaction.response.edit_message(
            content=f"**Step 5 of 6:** Class: `{self.selected_class}` | Weapon: `{self.selected_weapon}` | Map: `{selected_map}`\nWhich faction were you playing as?",
            view=view
        )

class FactionSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map):
        super().__init__(timeout=300)
        self.add_item(FactionSelect(original_message, prompt_msg, selected_class, selected_weapon, selected_map))

class FactionSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        options = [discord.SelectOption(label=f) for f in MAP_FACTIONS.get(selected_map, ["Agatha", "Mason", "Tenosia"])]
        super().__init__(placeholder="Choose your faction...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_faction = self.values[0]
        await interaction.response.send_modal(
            StatsModal(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, selected_faction)
        )

class RetryStatsView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, error_msg):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction
        self.error_msg = error_msg


    @discord.ui.button(label='Try Again', style=discord.ButtonStyle.blurple, emoji='🔄')
    async def try_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await interaction.response.send_modal(
            StatsModal(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction)
        )

class StatsModal(discord.ui.Modal, title="Enter Your Run Statistics"):
    takedowns = discord.ui.TextInput(label="Takedowns", placeholder="e.g. 215", required=True)
    kills = discord.ui.TextInput(label="Kills", placeholder="e.g. 104", required=True)
    deaths = discord.ui.TextInput(label="Deaths", placeholder="e.g. 0", required=True)

    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction):
        super().__init__()
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction

    async def on_submit(self, interaction: discord.Interaction):
        try:
            takedowns = int(self.takedowns.value)
            kills = int(self.kills.value)
            deaths = int(self.deaths.value)
        except ValueError:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "invalid")
            await interaction.response.send_message(
                "❌ Takedowns, Kills, and Deaths must be whole numbers. Please try again.",
                view=view,
                ephemeral=True
            )
            return

        # Sanity checks
        if takedowns < 0 or kills < 0 or deaths < 0:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "negative")
            await interaction.response.send_message(
                "❌ Takedowns, Kills, and Deaths cannot be negative. Please try again.",
                view=view,
                ephemeral=True
            )
            return

        if kills > takedowns:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "kills>td")
            await interaction.response.send_message(
                f"❌ Kills ({kills}) cannot exceed Takedowns ({takedowns}) — takedowns include kills plus assists. Please try again.",
                view=view,
                ephemeral=True
            )
            return

        view = VIPView(
            self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
            self.selected_map, self.faction, takedowns, kills, deaths
        )
        await interaction.response.send_message(
            "**Almost done!** Were you playing as VIP?",
            view=view,
            ephemeral=True
        )

class VIPView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction
        self.takedowns = takedowns
        self.kills = kills
        self.deaths = deaths


    @discord.ui.button(label='Yes', style=discord.ButtonStyle.red)
    async def vip_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self.handle_vip(interaction, True)

    @discord.ui.button(label='No', style=discord.ButtonStyle.green)
    async def vip_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self.handle_vip(interaction, False)

    async def handle_vip(self, interaction, vip):
        if self.takedowns >= 150 and self.kills >= 100:
            view = TripleCheckView(
                self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
                self.selected_map, self.faction, self.takedowns, self.kills, self.deaths, vip
            )
            await interaction.response.edit_message(
                content="Was your score over 20,000 points?",
                view=view
            )
        else:
            await finalise_submission(
                interaction, self.original_message, self.prompt_msg, self.selected_class,
                self.selected_weapon, self.selected_map, self.faction,
                self.takedowns, self.kills, self.deaths, vip, False
            )

class TripleCheckView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction
        self.takedowns = takedowns
        self.kills = kills
        self.deaths = deaths
        self.vip = vip


    @discord.ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def score_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await finalise_submission(
            interaction, self.original_message, self.prompt_msg, self.selected_class,
            self.selected_weapon, self.selected_map, self.faction,
            self.takedowns, self.kills, self.deaths, self.vip, True
        )

    @discord.ui.button(label='No', style=discord.ButtonStyle.red)
    async def score_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await finalise_submission(
            interaction, self.original_message, self.prompt_msg, self.selected_class,
            self.selected_weapon, self.selected_map, self.faction,
            self.takedowns, self.kills, self.deaths, self.vip, False
        )


class EditSubmissionView(discord.ui.View):
    def __init__(self, original_message, author, submission_row,
                 weapon, cls, map_name, faction, takedowns, kills, deaths, vip, feats, message_link):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.author = author
        self.submission_row = submission_row
        self.weapon = weapon
        self.cls = cls
        self.map_name = map_name
        self.faction = faction
        self.takedowns = takedowns
        self.kills = kills
        self.deaths = deaths
        self.vip = vip
        self.feats = feats
        self.message_link = message_link

    async def on_timeout(self):
        try:
            # Remove the edit button but keep the summary message
            await self._message.edit(view=None)
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label='✏️ Edit', style=discord.ButtonStyle.grey)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Only the person who submitted can edit this.", ephemeral=True)
            return
        view = EditFieldSelectView(self)
        await interaction.response.send_message(
            content="**Which field would you like to correct?**",
            view=view,
            ephemeral=True
        )


class EditFieldSelectView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.edit_view = edit_view
        self.add_item(EditFieldSelect(edit_view))


class EditFieldSelect(discord.ui.Select):
    def __init__(self, edit_view):
        self.edit_view = edit_view
        options = [
            discord.SelectOption(label="Weapon / Class", value="weapon"),
            discord.SelectOption(label="Map", value="map"),
            discord.SelectOption(label="Faction", value="faction"),
            discord.SelectOption(label="Stats (TD/K/D)", value="stats"),
            discord.SelectOption(label="VIP", value="vip"),
        ]
        super().__init__(placeholder="Choose a field to edit...", options=options)

    async def callback(self, interaction: discord.Interaction):
        field = self.values[0]
        ev = self.edit_view

        if field == "weapon":
            view = WeaponTypeView(ev.original_message, None, edit_view=ev)
            await interaction.response.edit_message(
                content="**Step 1:** What type of weapon did you use?",
                view=view
            )
        elif field == "map":
            view = EditMapSelectView(ev)
            await interaction.response.edit_message(
                content="**Edit Map:** Which map were you on?",
                view=view
            )
        elif field == "faction":
            view = EditFactionSelectView(ev)
            await interaction.response.edit_message(
                content="**Edit Faction:** Which faction were you playing?",
                view=view
            )
        elif field == "stats":
            await interaction.response.send_modal(EditStatsModal(ev))
        elif field == "vip":
            view = EditVIPView(ev)
            await interaction.response.edit_message(
                content="**Edit VIP:** Were you a VIP?",
                view=view
            )


class EditMapSelectView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.add_item(EditMapSelect(edit_view))

class EditMapSelect(discord.ui.Select):
    def __init__(self, edit_view):
        self.edit_view = edit_view
        options = [discord.SelectOption(label=m) for m in sorted(MAPS)]
        super().__init__(placeholder="Choose map...", options=options[:25])
    async def callback(self, interaction: discord.Interaction):
        ev = self.edit_view
        ev.map_name = self.values[0]
        await _apply_edit(interaction, ev)

class EditFactionSelectView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.add_item(EditFactionSelect(edit_view))

class EditFactionSelect(discord.ui.Select):
    def __init__(self, edit_view):
        self.edit_view = edit_view
        factions = MAP_FACTIONS.get(edit_view.map_name, {})
        options = [discord.SelectOption(label=f) for f in factions.keys()] if factions else [
            discord.SelectOption(label="Agatha"),
            discord.SelectOption(label="Mason"),
            discord.SelectOption(label="Tenosia"),
        ]
        super().__init__(placeholder="Choose faction...", options=options)
    async def callback(self, interaction: discord.Interaction):
        ev = self.edit_view
        ev.faction = self.values[0]
        await _apply_edit(interaction, ev)

class EditStatsModal(discord.ui.Modal, title="Edit Stats"):
    def __init__(self, edit_view):
        super().__init__()
        self.edit_view = edit_view
        self.td = discord.ui.TextInput(label="Takedowns", default=str(edit_view.takedowns), required=True)
        self.k = discord.ui.TextInput(label="Kills", default=str(edit_view.kills), required=True)
        self.d = discord.ui.TextInput(label="Deaths", default=str(edit_view.deaths), required=True)
        self.add_item(self.td)
        self.add_item(self.k)
        self.add_item(self.d)
    async def on_submit(self, interaction: discord.Interaction):
        ev = self.edit_view
        try:
            ev.takedowns = int(self.td.value)
            ev.kills = int(self.k.value)
            ev.deaths = int(self.d.value)
        except ValueError:
            await interaction.response.send_message("Invalid numbers.", ephemeral=True)
            return
        await _apply_edit(interaction, ev)

class EditVIPView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.edit_view = edit_view
    @discord.ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.edit_view.vip = True
        await _apply_edit(interaction, self.edit_view)
    @discord.ui.button(label='No', style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.edit_view.vip = False
        await _apply_edit(interaction, self.edit_view)


async def _apply_edit(interaction, ev):
    """Write the updated submission back to the sheet and update the summary message."""
    try:
        if ev.submission_row:
            vip_str = "Yes" if ev.vip else "No"
            feats_str = ", ".join(ev.feats) if ev.feats else "None"
            submissions_ws.update_cell(ev.submission_row, 4, ev.weapon)
            submissions_ws.update_cell(ev.submission_row, 5, ev.cls)
            submissions_ws.update_cell(ev.submission_row, 6, ev.map_name)
            submissions_ws.update_cell(ev.submission_row, 7, ev.faction)
            submissions_ws.update_cell(ev.submission_row, 8, ev.takedowns)
            submissions_ws.update_cell(ev.submission_row, 9, ev.kills)
            submissions_ws.update_cell(ev.submission_row, 10, ev.deaths)
            submissions_ws.update_cell(ev.submission_row, 11, vip_str)
            submissions_ws.update_cell(ev.submission_row, 12, feats_str)
    except Exception as e:
        print(f"Edit sheet update error: {e}")

    # Rebuild summary
    new_summary = (
        f"⚔️ **Run Submitted** *(edited)*\n"
        f"{ev.author.display_name}\n"
        f"{ev.weapon} • {ev.cls}\n"
        f"{ev.map_name} — {ev.faction}\n"
        f"{ev.takedowns} TD / {ev.kills} K / {ev.deaths} D\n"
        f"VIP: {'Yes' if ev.vip else 'No'}"
    )
    if ev.feats:
        new_summary += f"\n{', '.join(ev.feats)}"

    try:
        await ev._message.edit(content=new_summary, view=None)
    except Exception:
        pass

    await interaction.response.send_message("✅ Submission updated!", ephemeral=True)


async def finalise_submission(interaction, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip, score_over_20k):
    feats = []
    if kills >= 100:
        feats.append("100 Kills")
    if takedowns >= 200:
        feats.append("200 Takedowns")
    if deaths == 0:
        feats.append("Flawless")
    if takedowns >= 150 and deaths == 0:
        feats.append("Predator")
    if takedowns >= 150 and kills >= 100 and score_over_20k:
        feats.append("Triple")
    if selected_weapon in FEAT_WEAPONS and kills >= 100:
        feats.append(selected_weapon)

    vip_str = "Yes" if vip else "No"
    feats_str = ", ".join(feats) if feats else None

    summary = (
        f"⚔️ **Run Submitted**\n"
        f"{interaction.user.display_name}\n"
        f"{selected_weapon} • {selected_class}\n"
        f"{selected_map} — {faction}\n"
        f"{takedowns} TD / {kills} K / {deaths} D\n"
        f"VIP: {vip_str}"
    )
    if feats_str:
        summary += f"\n{feats_str}"

    message_link = f"https://discord.com/channels/{original_message.guild.id}/{original_message.channel.id}/{original_message.id}"

    await interaction.response.edit_message(content="✅ Most impressive! Your run has been recorded.", view=None)

    # Log to Google Sheets first so we get the row index
    submission_row = None
    try:
        log_submission(
            interaction.user.display_name,
            interaction.user.id,
            selected_weapon,
            selected_class,
            selected_map,
            faction,
            takedowns,
            kills,
            deaths,
            vip,
            feats,
            message_link
        )
        # Row index is last row in submissions sheet
        submission_row = len(submissions_ws.get_all_values())
    except Exception as e:
        print(f"Sheet logging error: {e}")

    # Post summary with Edit button
    edit_view = EditSubmissionView(
        original_message, interaction.user,
        submission_row, selected_weapon, selected_class,
        selected_map, faction, takedowns, kills, deaths, vip, feats, message_link
    )
    summary_reply = await original_message.reply(summary, mention_author=False, view=edit_view)
    edit_view._message = summary_reply

    await asyncio.sleep(1)
    try:
        await prompt_msg.delete()
    except discord.NotFound:
        pass

    # React to the original screenshot
    await original_message.add_reaction("<:cigar:1444893851427803298>")
    if deaths == 0:
        await original_message.add_reaction("<a:flawless:1360358300834599062>")
    if kills >= 100:
        await original_message.add_reaction("<a:100kill:1361412390339608686>")
    if takedowns >= 200:
        await original_message.add_reaction("<a:200tkd:1363648828414230538>")
    if takedowns >= 150 and deaths == 0:
        await original_message.add_reaction("<a:predator:1366794896081555567>")
    if takedowns >= 150 and kills >= 100 and score_over_20k:
        await original_message.add_reaction("<a:triple:1365532698260668466>")

    is_ranged = selected_class.startswith("Marksman")

    # weapon_hs — only if score qualifies for the weapon leaderboard (not VIP, not ranged)
    # and beats the player's own existing score on that board
    if not vip and not is_ranged:
        all_values = leaderboard_data_ws.get_all_values()
        weapon_entries = [row for row in all_values[1:] if row[0] == selected_weapon]
        scores = sorted(
            [int(row[3]) for row in weapon_entries if len(row) > 3 and row[3]],
            reverse=True
        )
        qualifies_board = len(scores) < 10 or takedowns > scores[9]
        # Check if player already has a higher score on this board
        discord_id_str = str(interaction.user.id)
        player_existing = [
            int(row[3]) for row in weapon_entries
            if len(row) > 3 and row[3] and len(row) > 2 and row[2] == discord_id_str
        ]
        beats_personal_best = not player_existing or takedowns > max(player_existing)
        if qualifies_board and beats_personal_best:
            await original_message.add_reaction("<:weapon_hs:1350656128635375698>")

    # Update leaderboards (skip for ranged submissions)
    any_updated = False
    placements = []
    if not is_ranged:
        try:
            any_updated, placements = await update_leaderboards(
                interaction, selected_weapon, selected_map, faction,
                takedowns, kills, deaths, vip, feats,
                interaction.user.display_name, message_link
            )
        except Exception as e:
            print(f"Leaderboard update error: {e}")

    if any_updated:
        await original_message.add_reaction("<a:highscore:1360312918545269057>")

    # Bounty check (skip for ranged submissions)
    if not is_ranged:
        try:
            bounty_hit = await update_bounty(
                interaction.guild, selected_weapon,
                interaction.user.display_name, interaction.user.id, takedowns
            )
            print(f"[BOUNTY] bounty_hit={bounty_hit} weapon={selected_weapon} takedowns={takedowns}")
            if bounty_hit:
                await original_message.add_reaction("🐱")
        except Exception as e:
            import traceback
            print(f"Bounty update error: {e}")
            traceback.print_exc()

    # Edit the summary reply to include placements
    if placements:
        placement_lines = "\n".join(f"🏆 {lb} — #{pos}" for lb, pos in placements)
        try:
            # Find the reply we sent and edit it
            async for msg in original_message.channel.history(limit=10, after=original_message):
                if msg.author == original_message.guild.me and msg.reference and msg.reference.message_id == original_message.id:
                    await msg.edit(content=msg.content + f"\n{placement_lines}")
                    break
        except Exception as e:
            print(f"Placement edit error: {e}")

    # Silently update Butler's Favourites pinned message
    try:
        if BUTLERS_FAVOURITES_CHANNEL_ID:
            fav_channel = interaction.guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
            if fav_channel:
                stats = calculate_butler_stats()
                embed_text = build_favourites_embed(stats)
                async for msg in fav_channel.history(limit=5):
                    if msg.author == interaction.guild.me:
                        await msg.edit(content=embed_text)
                        break
                else:
                    await fav_channel.send(embed_text)
                await update_title_roles(interaction.guild, stats)
    except Exception as e:
        print(f"Butler favourites update error: {e}")

    # Update registry card
    try:
        await create_or_update_registry_card(
            interaction.guild, interaction.user.id, interaction.user.display_name
        )
    except Exception as e:
        print(f"Registry card update error: {e}")

async def update_leaderboards(interaction, selected_weapon, selected_map, faction,
                              takedowns, kills, deaths, vip, feats,
                              player_name, message_link):
    guild = interaction.guild
    discord_id = str(interaction.user.id)
    any_updated = False
    placements = []  # list of (lb_name, position)

    # (lb_name, score, top_10, personal_best, unlimited_top50)
    updates = []

    # Weapon board — exclude VIP, top 10
    if not vip:
        updates.append((selected_weapon, takedowns, True, True, False))

    # Map board — top 10
    map_lb_name = f"{selected_map} - {faction}"
    updates.append((map_lb_name, takedowns, True, True, False))

    # Feat boards
    if "Flawless" in feats:
        updates.append(("Flawless", takedowns, False, True, False))
    if "100 Kills" in feats:
        updates.append(("100 Kills", kills, False, False, True))
    if "200 Takedowns" in feats:
        updates.append(("200 Takedowns", takedowns, False, False, True))
    if selected_weapon == "Mallet" and kills >= 100:
        updates.append(("Mallet", takedowns, True, True, False))
    if selected_weapon == "Knife" and kills >= 100:
        updates.append(("Knife", takedowns, True, True, False))
    if selected_weapon == "Healing Horn" and kills >= 100:
        updates.append(("Healing Horn", kills, False, True, False))

    # Columns: A=Leaderboard Name, B=Player, C=Discord ID, D=Score, E=Message Link
    all_values = leaderboard_data_ws.get_all_values()
    all_lb_rows = leaderboards_ws.get_all_records()

    for lb_name, score, top_10, personal_best, unlimited_top50 in updates:
        existing_sheet_row = None
        existing_score = None
        for i, row in enumerate(all_values[1:], start=2):
            row_lb = row[0] if len(row) > 0 else ''
            row_discord_id = row[2] if len(row) > 2 else ''
            row_score = row[3] if len(row) > 3 else ''
            if row_lb == lb_name and row_discord_id == discord_id:
                existing_sheet_row = i
                existing_score = int(row_score) if row_score else 0
                break

        if unlimited_top50:
            # Always append, no cap, no personal best check
            leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link, selected_weapon])
            any_updated = True
            # Find position after append
            all_board = [int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]]
            all_board.append(score)
            all_board.sort(reverse=True)
            pos = all_board.index(score) + 1
            placements.append((lb_name, pos))
        elif personal_best:
            if existing_sheet_row is not None:
                if score > existing_score:
                    leaderboard_data_ws.update_cell(existing_sheet_row, 2, player_name)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 4, score)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 5, message_link)
                    leaderboard_data_ws.update_cell(existing_sheet_row, 6, selected_weapon)
                    any_updated = True
                    # Find position
                    board_scores = sorted([int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
                    # Replace old score with new
                    board_scores = [s for s in board_scores if s != existing_score]
                    board_scores.append(score)
                    board_scores.sort(reverse=True)
                    pos = board_scores.index(score) + 1
                    placements.append((lb_name, pos))
                else:
                    continue
            else:
                if top_10:
                    board_entries = [row for row in all_values[1:] if row[0] == lb_name]
                    board_entries_sorted = sorted(
                        board_entries, key=lambda x: int(x[3]) if len(x) > 3 and x[3] else 0, reverse=True
                    )
                    if len(board_entries_sorted) >= 10:
                        lowest_score = int(board_entries_sorted[9][3]) if board_entries_sorted[9][3] else 0
                        if score <= lowest_score:
                            continue
                        tenth_discord_id = board_entries_sorted[9][2] if len(board_entries_sorted[9]) > 2 else ''
                        for i, row in enumerate(all_values[1:], start=2):
                            if row[0] == lb_name and (row[2] if len(row) > 2 else '') == tenth_discord_id:
                                leaderboard_data_ws.delete_rows(i)
                                all_values = leaderboard_data_ws.get_all_values()  # reload after delete
                                break
                leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link, selected_weapon])
                any_updated = True
                board_scores = sorted([int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
                board_scores.append(score)
                board_scores.sort(reverse=True)
                pos = board_scores.index(score) + 1
                placements.append((lb_name, pos))
        else:
            leaderboard_data_ws.append_row([lb_name, player_name, discord_id, score, message_link, selected_weapon])
            any_updated = True
            board_scores = sorted([int(r[3]) for r in all_values[1:] if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
            board_scores.append(score)
            board_scores.sort(reverse=True)
            pos = board_scores.index(score) + 1
            placements.append((lb_name, pos))

        # Reload and update Discord message
        updated_values = leaderboard_data_ws.get_all_values()
        entries = []
        for row in updated_values[1:]:
            if row[0] == lb_name:
                entries.append({
                    'player': row[1] if len(row) > 1 else '',
                    'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                    'link': row[4] if len(row) > 4 else ''
                })
        entries = sorted(entries, key=lambda x: x['score'], reverse=True)

        # Cap 100 Kills / 200 Takedowns display at top 50
        if lb_name in ("100 Kills", "200 Takedowns"):
            display_entries = entries[:50]
            overflow = len(entries) - 50
        else:
            display_entries = entries
            overflow = 0

        chunks = format_leaderboard_text(display_entries, overflow, show_weapon=(lb_name in ("100 Kills", "200 Takedowns")))

        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
        if not lb_row:
            print(f"No Leaderboards sheet entry found for: {lb_name}")
            continue

        thread_id = int(lb_row['Thread ID'])
        message_ids = [int(mid.strip()) for mid in str(lb_row['Message ID']).split(',') if mid.strip()]

        try:
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)

            # Pack all chunks into existing messages — never post new ones (would appear after decoration)
            packed = pack_chunks_into_slots(chunks, len(message_ids))

            for idx, mid in enumerate(message_ids):
                try:
                    msg = await thread.fetch_message(mid)
                    await msg.edit(content=packed[idx])
                except Exception as e:
                    print(f"Discord edit error for {lb_name} msg {mid}: {e}")

        except Exception as e:
            print(f"Discord update error for {lb_name}: {e}")

    return any_updated, placements

FACTION_EMOJIS = {
    "Mason": "<:mason:1350669458863292426>",
    "Agatha": "<:agatha:1350669712593260554>",
    "Tenosia": "<:tenosia:1350669567269273682>",
}

MAP_ATTACK_DEFENSE = {
    "Lionspire": {"attack": "Mason", "defense": "Agatha"},
    "Galencourt": {"attack": "Mason", "defense": "Agatha"},
    "Aberfell": {"attack": "Agatha", "defense": "Mason"},
    "Coxwell": {"attack": "Mason", "defense": "Agatha"},
    "Darkforest": {"attack": "Mason", "defense": "Agatha"},
    "Baudwyn": {"attack": "Tenosia", "defense": "Mason"},
    "Rudhelm": {"attack": "Agatha", "defense": "Mason"},
    "Trayan Citadel": {"attack": "Agatha", "defense": "Mason"},
    "Montcrux": {"attack": "Agatha", "defense": "Tenosia"},
    "Bridgetown": {"attack": "Tenosia", "defense": "Agatha"},
    "Thayic Stronghold": {"attack": "Mason", "defense": "Agatha"},
    "Falmire": {"attack": "Agatha", "defense": "Mason"},
    "Askandir": {"attack": "Mason", "defense": "Tenosia"},
}

def get_leaderboard_entries(name):
    rows = leaderboard_data_ws.get_all_values()
    entries = []
    for row in rows[1:]:  # skip header
        if row[0] == name:
            entries.append({
                'player': row[1] if len(row) > 1 else '',
                'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                'link': row[4] if len(row) > 4 else '',
                'weapon': row[5] if len(row) > 5 else ''
            })
    return sorted(entries, key=lambda x: x['score'], reverse=True)

def pack_chunks_into_slots(chunks, num_slots):
    """Pack chunks into exactly num_slots messages.
    If chunks > slots, concatenate overflow into the last slot (up to 1900 chars).
    If chunks < slots, fill remaining slots with zero-width space.
    """
    if num_slots == 0:
        return []

    if len(chunks) <= num_slots:
        packed = list(chunks)
        while len(packed) < num_slots:
            packed.append("\u200b")
        return packed

    # More chunks than slots — merge excess into last slot
    packed = list(chunks[:num_slots - 1])
    last = chunks[num_slots - 1]
    for extra in chunks[num_slots:]:
        candidate = last + "\n" + extra
        if len(candidate) <= 1900:
            last = candidate
        else:
            # Truncate with overflow note
            last = last + "\n*...continued*"
            break
    packed.append(last)
    return packed


def format_leaderboard_text(entries, overflow=0, show_weapon=False):
    if not entries:
        return ["No entries yet."]

    lines = []
    for e in entries:
        weapon_str = f" — *{e['weapon']}*" if show_weapon and e.get('weapon') else ""
        if e['link']:
            lines.append(f"• {e['player']} — [{e['score']}]({e['link']}){weapon_str}")
        else:
            lines.append(f"• {e['player']} — {e['score']}{weapon_str}")

    if overflow > 0:
        lines.append(f"*...and {overflow} more entries*")

    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 1900:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)

    return chunks

@bot.tree.command(name="setup", description="Set up a bot-owned leaderboard in this thread")
@discord.app_commands.describe(
    name="Name of the leaderboard e.g. War Axe",
    type="Type: weapon, feat, or map"
)
async def setup_leaderboard(interaction: discord.Interaction, name: str, type: str):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    await interaction.response.send_message("Setting up leaderboard...", ephemeral=True)
    thread = interaction.channel

    if type == "map":
        map_info = MAP_ATTACK_DEFENSE.get(name)
        if not map_info:
            await interaction.edit_original_response(content=f"No attack/defense info found for map: {name}")
            return

        attack_faction = map_info["attack"]
        defense_faction = map_info["defense"]
        attack_emoji = FACTION_EMOJIS[attack_faction]
        defense_emoji = FACTION_EMOJIS[defense_faction]

        attack_name = f"{name} - {attack_faction}"
        defense_name = f"{name} - {defense_faction}"

        attack_entries = get_leaderboard_entries(attack_name)
        defense_entries = get_leaderboard_entries(defense_name)

        attack_chunks = format_leaderboard_text(attack_entries)
        defense_chunks = format_leaderboard_text(defense_entries)

        attack_header = f"{attack_emoji} **{name} {attack_faction}** <:weapon_hs:1350656128635375698>"
        defense_header = f"{defense_emoji} **{name} {defense_faction}** 🛡️"

        await thread.send(file=discord.File(DECORATION_TOP))
        await thread.send(attack_header)
        attack_msg_ids = []
        for chunk in attack_chunks:
            attack_msg = await thread.send(chunk)
            attack_msg_ids.append(str(attack_msg.id))
        await thread.send(file=discord.File(DECORATION_BOTTOM))
        await thread.send(defense_header)
        defense_msg_ids = []
        for chunk in defense_chunks:
            defense_msg = await thread.send(chunk)
            defense_msg_ids.append(str(defense_msg.id))
        await thread.send(file=discord.File(DECORATION_BOTTOM))

        leaderboards_ws.append_row([attack_name, str(thread.id), ",".join(attack_msg_ids), "map"])
        leaderboards_ws.append_row([defense_name, str(thread.id), ",".join(defense_msg_ids), "map"])

        await interaction.edit_original_response(content=f"✅ Map leaderboard for **{name}** set up with both factions.")

    else:
        entries = get_leaderboard_entries(name)
        chunks = format_leaderboard_text(entries, show_weapon=(name in ("100 Kills", "200 Takedowns")))
        await thread.send(file=discord.File(DECORATION_TOP))
        msg_ids = []
        for chunk in chunks:
            lb_msg = await thread.send(chunk)
            msg_ids.append(str(lb_msg.id))
        await thread.send(file=discord.File(DECORATION_BOTTOM))

        leaderboards_ws.append_row([name, str(thread.id), ",".join(msg_ids), type])

        await interaction.edit_original_response(content=f"✅ Leaderboard for **{name}** set up successfully.")

@bot.tree.command(name="refresh", description="Refresh the leaderboard in this thread, or specify a name")
@discord.app_commands.describe(name="Optional: exact leaderboard name. Leave blank to auto-detect from this channel.")
async def refresh_leaderboard(interaction: discord.Interaction, name: str = None):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    all_lb_rows = leaderboards_ws.get_all_records()

    if name is None:
        # Auto-detect by current channel/thread ID
        channel_id = str(interaction.channel.id)
        matching = [r for r in all_lb_rows if str(r['Thread ID']) == channel_id]
        if not matching:
            await interaction.response.send_message("❌ No leaderboard found for this channel. Try specifying the name manually.", ephemeral=True)
            return
        # If multiple (e.g. map boards with attack + defense), refresh all
        names_to_refresh = [r['Leaderboard Name'] for r in matching]
    else:
        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == name), None)
        if not lb_row:
            await interaction.response.send_message(f"❌ No leaderboard found with name: `{name}`", ephemeral=True)
            return
        names_to_refresh = [name]

    await interaction.response.send_message(f"Refreshing **{', '.join(names_to_refresh)}**...", ephemeral=True)

    for lb_name in names_to_refresh:
        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
        if not lb_row:
            continue

        entries = get_leaderboard_entries(lb_name)
        entries = sorted(entries, key=lambda x: x['score'], reverse=True)

        if lb_name in ("100 Kills", "200 Takedowns"):
            overflow = max(0, len(entries) - 50)
            display_entries = entries[:50]
        else:
            overflow = 0
            display_entries = entries

        chunks = format_leaderboard_text(display_entries, overflow, show_weapon=(lb_name in ("100 Kills", "200 Takedowns")))

        thread_id = int(lb_row['Thread ID'])
        message_ids = [int(mid.strip()) for mid in str(lb_row['Message ID']).split(',') if mid.strip()]

        try:
            guild = interaction.guild
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)

            # Pack all chunks into existing messages — never post new ones (would appear after decoration)
            packed = pack_chunks_into_slots(chunks, len(message_ids))

            for idx, mid in enumerate(message_ids):
                try:
                    msg = await thread.fetch_message(mid)
                    await msg.edit(content=packed[idx])
                except Exception as e:
                    print(f"Refresh edit error for {lb_name} msg {mid}: {e}")

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Error refreshing {lb_name}: {e}")
            return

    await interaction.edit_original_response(content=f"✅ **{', '.join(names_to_refresh)}** refreshed successfully.")

# ── BOUNTY HELPERS ────────────────────────────────────────────────────────────

def get_active_bounty():
    """Return the active bounty row as a dict, or None."""
    rows = bounty_ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 9 and row[8] == 'TRUE':
            return {
                'row': i,
                'title': row[0],
                'channel_id': int(row[1]) if row[1] else None,
                'message_id': int(row[2]) if row[2] else None,
                'theme_emoji': row[3],
                'weapons': json.loads(row[4]) if row[4] else {},
                'special_challenge': row[5],
                'special_done': row[6] == '1',
                'completions': json.loads(row[7]) if row[7] else [],
                'role_id': int(row[9]) if len(row) > 9 and row[9] else None,
                'forum_channel_id': int(row[10]) if len(row) > 10 and row[10] else None,
                'completions_msg_id': int(row[11]) if len(row) > 11 and row[11] else None,
                'bonus_msg_id': int(row[12]) if len(row) > 12 and row[12] else None,
            }
    return None

def build_bounty_card(title, theme_emoji, weapons, special_challenge, special_done, completions):
    """
    weapons: dict of { display_name: {"current": int, "total": int} }
    completions: list of {"name": str, "date": str}
    """
    lines = []
    lines.append("╭──────────────────────────────╮")
    lines.append(f"     😼 {title} ◈")
    lines.append("╰──────────────────────────────╯")

    for weapon, data in weapons.items():
        cur = data['current']
        tot = data['total']
        label = f"~~{weapon}~~" if cur >= tot else weapon
        progress = f"{cur}/{tot}"
        lines.append(f"▸ {label:<22} {progress:>4}")

    lines.append("╭──────────────────────────────╮")
    lines.append(f"      {theme_emoji} SPECIAL CHALLENGE {theme_emoji}")
    lines.append("╰──────────────────────────────╯")
    sc_progress = "1/1" if special_done else "0/1"
    lines.append(f"▸ {special_challenge:<22} {sc_progress:>4}")

    if completions:
        lines.append("")
        lines.append("🏆 **Completions**")
        for idx, c in enumerate(completions, 1):
            lines.append(f"{idx}. {c['name']} — {c['date']}")

    return "```\n" + "\n".join(lines) + "\n```"

def save_bounty_state(row_idx, weapons, special_done, completions, message_id=None):
    bounty_ws.update_cell(row_idx, 5, json.dumps(weapons))
    bounty_ws.update_cell(row_idx, 7, '1' if special_done else '0')
    bounty_ws.update_cell(row_idx, 8, json.dumps(completions))
    if message_id:
        bounty_ws.update_cell(row_idx, 3, str(message_id))

async def check_bounty_completion(guild, bounty, player_name, player_id):
    """Check if player just completed the full bounty. Returns True if newly completed."""
    weapons = bounty['weapons']
    # All weapons maxed out
    all_weapons_done = all(w['current'] >= w['total'] for w in weapons.values())
    if not all_weapons_done:
        return False
    # Check they're not already in completions
    completions = bounty['completions']
    already = any(str(c.get('id')) == str(player_id) for c in completions)
    if already:
        return False
    return True

# ── BOUNTY COMMANDS ───────────────────────────────────────────────────────────

@bot.tree.command(name="bounty_create", description="Create a new monthly bounty (mod only)")
@discord.app_commands.describe(
    title="Bounty title e.g. Meowy's Birthday Bounty",
    channel_name="Channel name e.g. meowys-birthday-bounty",
    theme_emoji="Emoji pair for special challenge header e.g. 🐾",
    weapon1="Weapon slot 1 — e.g. Messer or Messer:9 for custom total (default 3)",
    weapon2="Weapon slot 2 — e.g. Dane Axe or Dane Axe:6",
    weapon3="Weapon slot 3", weapon4="Weapon slot 4",
    weapon5="Weapon slot 5", weapon6="Weapon slot 6",
    weapon7="Weapon slot 7 (optional)",
    special_challenge="Special challenge description e.g. 100 Takedowns on Cat Claws (Katars)"
)
async def bounty_create(
    interaction: discord.Interaction,
    title: str,
    channel_name: str,
    theme_emoji: str,
    weapon1: str, weapon2: str, weapon3: str,
    weapon4: str, weapon5: str, weapon6: str,
    special_challenge: str,
    weapon7: str = None,
):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    await interaction.response.send_message("Creating bounty...", ephemeral=True)

    # Deactivate any existing active bounty
    rows = bounty_ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 9 and row[8] == 'TRUE':
            bounty_ws.update_cell(i, 9, 'FALSE')

    # Parse weapons — supports "WeaponName" (default 3) or "WeaponName:9" (custom total)
    def parse_weapon(raw):
        if raw is None:
            return None
        raw = raw.strip()
        if ':' in raw:
            parts = raw.rsplit(':', 1)
            name = parts[0].strip()
            try:
                total = int(parts[1].strip())
            except ValueError:
                total = 3
        else:
            name = raw
            total = 3
        return name, total

    raw_weapons = [weapon1, weapon2, weapon3, weapon4, weapon5, weapon6]
    if weapon7:
        raw_weapons.append(weapon7)

    # Build weapons dict: name → {current, total}
    weapons = {}
    for raw in raw_weapons:
        parsed = parse_weapon(raw)
        if parsed:
            name, total = parsed
            weapons[name] = {"current": 0, "total": total}

    guild = interaction.guild

    # Format channel name with cat emoji prefix
    formatted_channel_name = f"🐱 ┃{channel_name}"

    # Create the text channel under The Bulletin Board category
    bulletin_board = guild.get_channel(BULLETIN_BOARD_CATEGORY_ID)
    channel = await guild.create_text_channel(formatted_channel_name, category=bulletin_board)

    # Create the forum channel under The Ledger category
    ledger = guild.get_channel(LEDGER_CATEGORY_ID)
    forum_channel = None
    forum_error = None
    if not ledger:
        forum_error = f"Ledger category not found (ID: {LEDGER_CATEGORY_ID})"
    else:
        try:
            forum_channel = await guild.create_forum(formatted_channel_name, category=ledger)
        except Exception as e:
            forum_error = str(e)
            print(f"Forum channel create error: {e}")

    # Create the bounty role — lavender colour, cat emoji icon
    lavender = discord.Colour(0xB57EDC)
    bounty_role = await guild.create_role(
        name=title,
        colour=lavender,
        mentionable=True,
        reason=f"Bounty role for: {title}"
    )
    # Set the role icon to the cat emoji (requires server with role icons feature)
    try:
        await bounty_role.edit(unicode_emoji="🐱")
    except Exception:
        pass  # Server may not support role icons — silently skip

    # Save to sheet (col 10 = RoleID, col 11 = ForumChannelID, cols 12-13 = msg IDs set later)
    bounty_ws.append_row([
        title,
        str(channel.id),
        '',
        theme_emoji,
        json.dumps(weapons),
        special_challenge,
        '0',
        json.dumps([]),
        'TRUE',
        str(bounty_role.id),
        str(forum_channel.id) if forum_channel else '',
        '',
        ''
    ])

    forum_mention = forum_channel.mention if forum_channel else f"*(forum creation failed: {forum_error})*"
    msg = (
        f"✅ Bounty **{title}** created!\n"
        f"📋 Bulletin Board: {channel.mention} — post your art there to activate the leaderboards\n"
        f"📖 Ledger: {forum_mention}\n"
        f"🎭 Role: {bounty_role.mention}"
    )
    await interaction.edit_original_response(content=msg)


@bot.tree.command(name="bounty_end", description="End the active bounty with a 24hr grace period (mod only)")
async def bounty_end(interaction: discord.Interaction):
    if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
        return

    bounty = get_active_bounty()
    if not bounty:
        await interaction.response.send_message("No active bounty found.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"⏳ Grace period started for **{bounty['title']}**. Channel will be deleted in 24 hours.",
        ephemeral=False
    )

    # Mark inactive immediately so no new completions count
    bounty_ws.update_cell(bounty['row'], 9, 'FALSE')

    # Wait 24 hours then delete the channel and role
    await asyncio.sleep(86400)
    guild = interaction.guild
    channel = guild.get_channel(bounty['channel_id'])
    if channel:
        await channel.delete(reason=f"Bounty ended: {bounty['title']}")
    if bounty['role_id']:
        role = guild.get_role(bounty['role_id'])
        if role:
            await role.delete(reason=f"Bounty ended: {bounty['title']}")


@bot.tree.command(name="bounty_status", description="Show the current active bounty card")
async def bounty_status(interaction: discord.Interaction):
    bounty = get_active_bounty()
    if not bounty:
        await interaction.response.send_message("No active bounty right now.", ephemeral=True)
        return
    card = build_bounty_card(
        bounty['title'], bounty['theme_emoji'], bounty['weapons'],
        bounty['special_challenge'], bounty['special_done'], bounty['completions']
    )
    await interaction.response.send_message(card, ephemeral=True)



def get_player_bounty_progress(bounty_title, discord_id):
    """Get a player's row from BountyPlayers sheet, or None."""
    rows = bounty_players_ws.get_all_values()
    discord_id_str = str(discord_id)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and row[0] == bounty_title and row[1] == discord_id_str:
            return {
                'row': i,
                'player_name': row[2] if len(row) > 2 else '',
                'forum_post_id': int(row[3]) if len(row) > 3 and row[3] else None,
                'progress': json.loads(row[4]) if len(row) > 4 and row[4] else {}
            }
    return None

def save_player_bounty_progress(row_idx, player_name, forum_post_id, progress):
    bounty_players_ws.update_cell(row_idx, 3, player_name)
    bounty_players_ws.update_cell(row_idx, 4, str(forum_post_id) if forum_post_id else '')
    bounty_players_ws.update_cell(row_idx, 5, json.dumps(progress))

def build_player_bounty_card(bounty, player_progress):
    """Build a personal bounty card for a player showing only their own progress."""
    weapons = bounty['weapons']
    lines = []
    lines.append("╭──────────────────────────────╮")
    lines.append(f"     😼 {bounty['title']} ◈")
    lines.append("╰──────────────────────────────╯")

    for weapon, data in weapons.items():
        tot = data['total']
        raw = player_progress.get(weapon, 0)
        cur = raw['current'] if isinstance(raw, dict) else int(raw)
        label = f"~~{weapon}~~" if cur >= tot else weapon
        progress = f"{cur}/{tot}"
        lines.append(f"▸ {label:<22} {progress:>4}")

    lines.append("╭──────────────────────────────╮")
    lines.append(f"      {bounty['theme_emoji']} SPECIAL CHALLENGE {bounty['theme_emoji']}")
    lines.append("╰──────────────────────────────╯")
    sc_cur = player_progress.get('__special__', 0)
    sc_progress = f"{sc_cur}/1"
    lines.append(f"▸ {bounty['special_challenge']:<22} {sc_progress:>4}")

    return "```\n" + "\n".join(lines) + "\n```"

async def update_bounty(guild, weapon, player_name, player_id, takedowns):
    """Called from finalise_submission. Updates bounty progress if weapon qualifies. Returns True if weapon matched."""
    if takedowns < 100:
        return False

    bounty = get_active_bounty()
    if not bounty:
        return False

    weapons = bounty['weapons']

    # Normalize weapon name for matching (case-insensitive)
    matched_key = next((k for k in weapons if k.lower() == weapon.lower()), None)
    if not matched_key:
        return False  # Weapon not on this bounty

    # Increment global participation counter (informational only — no cap)
    w = weapons[matched_key]
    w['current'] += 1
    weapons[matched_key] = w

    # Assign the bounty role to the player if not already assigned
    bounty_channel = guild.get_channel(bounty['channel_id'])
    bounty_role = guild.get_role(bounty['role_id']) if bounty['role_id'] else None
    member = guild.get_member(player_id)
    if member and bounty_role and bounty_role not in member.roles:
        try:
            await member.add_roles(bounty_role, reason="Bounty participant")
        except Exception as e:
            print(f"Bounty role assign error: {e}")

    # ── PLAYER PROGRESS ───────────────────────────────────────────────────────
    player_row = get_player_bounty_progress(bounty['title'], str(player_id))
    if player_row:
        player_progress = player_row['progress']
        forum_post_id = player_row['forum_post_id']
    else:
        player_progress = {}
        forum_post_id = None

    # Increment player's personal count for this weapon
    raw = player_progress.get(matched_key, 0)
    cur = raw['current'] if isinstance(raw, dict) else int(raw)
    player_progress[matched_key] = cur + 1

    # Get or create the player's forum post
    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if forum_channel and isinstance(forum_channel, discord.ForumChannel):
        if forum_post_id:
            # Edit the card message (second message, after the theme emoji)
            try:
                forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                messages = []
                async for msg in forum_thread.history(limit=5, oldest_first=True):
                    messages.append(msg)
                bot_messages = [m for m in messages if m.author.bot]
                card_text = build_player_bounty_card(bounty, player_progress)
                if bot_messages:
                    await bot_messages[-1].edit(content=card_text)
                else:
                    await forum_thread.send(card_text)
            except Exception as e:
                print(f"Forum post update error: {e}")
                forum_post_id = None

        if not forum_post_id:
            # Create new forum post for this player
            # First message is the theme emoji, bot then posts the bounty card
            try:
                new_thread, first_msg = await forum_channel.create_thread(
                    name=player_name,
                    content=bounty['theme_emoji']
                )
                card_text = build_player_bounty_card(bounty, player_progress)
                await new_thread.send(card_text)
                forum_post_id = new_thread.id
            except Exception as e:
                print(f"Forum post create error: {e}")

    # Save player progress
    if player_row:
        save_player_bounty_progress(player_row['row'], player_name, forum_post_id, player_progress)
    else:
        bounty_players_ws.append_row([
            bounty['title'], str(player_id), player_name,
            str(forum_post_id) if forum_post_id else '', json.dumps(player_progress)
        ])

    # ── COMPLETIONS & BONUS BOARDS ───────────────────────────────────────────
    completions = bounty['completions']
    newly_completed = await check_bounty_completion(guild, bounty, player_name, player_id)
    if newly_completed:
        date_str = datetime.now(timezone.utc).strftime('%b %d')
        completions.append({"id": str(player_id), "name": player_name, "date": date_str})
        # Ping the bounty role in the bounty channel
        if bounty_channel and bounty_role:
            try:
                await bounty_channel.send(
                    f"{bounty_role.mention} 🏆 **{player_name}** has completed the **{bounty['title']}**!"
                )
            except Exception as e:
                print(f"Bounty completion ping error: {e}")

    # Save updated state
    save_bounty_state(bounty['row'], weapons, bounty['special_done'], completions)

    # Update completions board in Bulletin Board channel
    if bounty_channel and bounty.get('completions_msg_id'):
        try:
            if completions:
                lines = [f"```"]
                lines.append(f"╭──────────────────────────────╮")
                lines.append(f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}")
                lines.append(f"╰──────────────────────────────╯")
                for idx, c in enumerate(completions, 1):
                    lines.append(f"{idx}. {c['name']}  {c['date']}")
                lines.append("```")
                comp_text = "\n".join(lines)
            else:
                comp_text = (
                    f"```\n╭──────────────────────────────╮\n"
                    f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}\n"
                    f"╰──────────────────────────────╯\n"
                    f"No completions yet.\n```"
                )
            comp_msg = await bounty_channel.fetch_message(bounty['completions_msg_id'])
            await comp_msg.edit(content=comp_text)
        except Exception as e:
            print(f"Completions board update error: {e}")

    return True


@bot.tree.command(name="bounty_add_card", description="Manually create a bounty forum card for a player (mod only)")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(member="The player to create a card for")
async def bounty_add_card(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)

    bounty = get_active_bounty()
    if not bounty:
        await interaction.followup.send("No active bounty found.", ephemeral=True)
        return

    guild = interaction.guild
    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if not forum_channel:
        await interaction.followup.send("❌ Ledger forum channel not found.", ephemeral=True)
        return

    player_name = member.nick if member.nick else member.display_name
    player_id = member.id

    # Check if player already has a card
    player_row = get_player_bounty_progress(bounty['title'], str(player_id))
    if player_row and player_row.get('forum_post_id'):
        await interaction.followup.send(f"⚠️ {player_name} already has a forum card.", ephemeral=True)
        return

    # Build progress from existing BountyPlayers data or empty
    if player_row:
        player_progress = player_row['progress']
        row_idx = player_row['row']
    else:
        player_progress = {w: {"current": 0, "total": bounty['weapons'][w]['total']} for w in bounty['weapons']}
        row_idx = None

    # Create forum post
    try:
        new_thread, _ = await forum_channel.create_thread(
            name=player_name,
            content=bounty['theme_emoji']
        )
        card_text = build_player_bounty_card(bounty, player_progress)
        await new_thread.send(card_text)
        forum_post_id = new_thread.id

        # Save to BountyPlayers sheet
        if row_idx:
            save_player_bounty_progress(row_idx, player_name, forum_post_id, player_progress)
        else:
            bounty_players_ws.append_row([
                bounty['title'],
                str(player_id),
                player_name,
                str(forum_post_id),
                json.dumps(player_progress)
            ])

        await interaction.followup.send(f"✅ Created bounty card for **{player_name}**.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="seed_players", description="Seed the Players tab from a Discord role (admin only)")
@discord.app_commands.checks.has_permissions(administrator=True)
async def seed_players(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        role = guild.get_role(1433215577173786758)

        if not role:
            await interaction.followup.send("❌ Role not found.", ephemeral=True)
            return

        existing_rows = players_ws.get_all_values()
        existing_ids = set(row[0] for row in existing_rows[1:] if row)

        rows_to_add = []
        skipped = 0

        for member in role.members:
            discord_id = str(member.id)
            display_name = member.nick if member.nick else member.display_name

            if discord_id in existing_ids:
                skipped += 1
                continue

            rows_to_add.append([discord_id, display_name, ""])

        if rows_to_add:
            players_ws.append_rows(rows_to_add, value_input_option="RAW")

        await interaction.followup.send(
            f"✅ Seeded **{len(rows_to_add)}** players from role.\n"
            f"⏭️ Skipped **{skipped}** already in the sheet.",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)



@bot.tree.command(name="patch_notes", description="Post patch notes to the current channel (mod only)")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(version="Version number e.g. v1.3.0", notes="What changed — use | to separate bullet points")
async def patch_notes(interaction: discord.Interaction, version: str, notes: str):
    await interaction.response.defer(ephemeral=True)

    bullets = [f"• {n.strip()}" for n in notes.split("|")]
    bullet_text = "\n".join(bullets)

    msg = (
        f"📝 **Cigar Lounge Butler {version}**\n"
        f"──────────────────────\n"
        f"{bullet_text}"
    )

    await interaction.channel.send(msg)
    await interaction.followup.send(f"✅ Patch notes posted for {version}.", ephemeral=True)

@bot.tree.command(name="bounty_refresh_card", description="Refresh a player's bounty forum card (mod only)")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(member="The player whose card to refresh")
async def bounty_refresh_card(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)

    bounty = get_active_bounty()
    if not bounty:
        await interaction.followup.send("No active bounty found.", ephemeral=True)
        return

    guild = interaction.guild
    player_name = member.nick if member.nick else member.display_name
    player_id = str(member.id)

    player_row = get_player_bounty_progress(bounty['title'], player_id)
    if not player_row:
        await interaction.followup.send(f"❌ No bounty data found for {player_name}.", ephemeral=True)
        return

    forum_post_id = player_row.get('forum_post_id')
    if not forum_post_id:
        await interaction.followup.send(f"❌ No forum card found for {player_name}. Use /bounty_add_card instead.", ephemeral=True)
        return

    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if not forum_channel:
        await interaction.followup.send("❌ Ledger forum channel not found.", ephemeral=True)
        return

    try:
        forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
        player_progress = player_row['progress']
        print(f"[REFRESH] player_progress={json.dumps(player_progress)}")
        card_text = build_player_bounty_card(bounty, player_progress)
        messages = []
        async for msg in forum_thread.history(limit=5, oldest_first=True):
            messages.append(msg)
        # Find the last bot message to edit
        bot_messages = [m for m in messages if m.author.bot]
        if bot_messages:
            await bot_messages[-1].edit(content=card_text)
        else:
            await forum_thread.send(card_text)
        await interaction.followup.send(f"✅ Refreshed bounty card for **{player_name}**.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


def calculate_butler_stats():
    """Pull stats from Submissions and LeaderboardData sheets."""
    subs = submissions_ws.get_all_values()[1:]
    ld = leaderboard_data_ws.get_all_values()[1:]

    # Submission stats
    player_counts = {}
    weapon_counts = {}
    map_counts = {}
    top_td = (0, "")
    top_kills = (0, "")
    td_scores_sub = {}
    kills_scores_sub = {}
    players_set = set()
    lethal_ratios = {}    # player -> [kills/td ratios] — High Lethality
    dominant_ratios = {} # player -> [td/kills ratios] — Low Lethality

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
        # Track lethality ratios
        if kills > 0 and td > 0:
            lethal_ratios.setdefault(player, []).append(kills / td)   # kills/td — High Lethality
            dominant_ratios.setdefault(player, []).append(td / kills) # td/kills — Low Lethality

    most_active = max(player_counts, key=player_counts.get) if player_counts else "N/A"
    top_weapons = sorted(weapon_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_maps = sorted(map_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_busiest = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_td_list = sorted(td_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]
    top_kills_list = sorted(kills_scores_sub.items(), key=lambda x: x[1], reverse=True)[:5]

    # High Lethality — pure avg kills/td ratio, min 5 (fewer subs tiebreak)
    qualified_lethal = {p: v for p, v in lethal_ratios.items() if len(v) >= 5}
    lethal_ranked = sorted(qualified_lethal.keys(),
        key=lambda p: (-sum(qualified_lethal[p]) / len(qualified_lethal[p]), len(qualified_lethal[p])))
    high_lethality = [f"{p} ({sum(qualified_lethal[p])/len(qualified_lethal[p]):.2f})" for p in lethal_ranked[:5]]

    # Low Lethality — pure avg td/kills ratio, min 5 (fewer subs tiebreak)
    qualified_dominant = {p: v for p, v in dominant_ratios.items() if len(v) >= 5}
    dominant_ranked = sorted(qualified_dominant.keys(),
        key=lambda p: (-sum(qualified_dominant[p]) / len(qualified_dominant[p]), len(qualified_dominant[p])))
    low_lethality = [f"{p} ({sum(qualified_dominant[p])/len(qualified_dominant[p]):.2f})" for p in dominant_ranked[:5]]
    most_lethal_top5 = high_lethality  # keep for return dict compat

    # Backfill run counts and best scores from LeaderboardData for legacy entries
    ld_player_boards = {}  # player -> set of board names they appear on (to count unique runs)
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
        """Return player with best placement title.
        breadth_first=True: most boards wins, avg placement as tiebreaker.
        breadth_first=False: best avg wins, most boards as tiebreaker.
        min_boards: minimum boards required to qualify.
        """
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
        """Return player with best weighted score: avg * log(count+1)."""
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
        'high_lethality': high_lethality if high_lethality else ["N/A"],
        'low_lethality': low_lethality if low_lethality else ["N/A"],
    }


def build_favourites_embed(stats):
    def fmt_list(items, suffix):
        return "\n".join(f"{i+1}. {name} — {val} {suffix}" for i, (name, val) in enumerate(items))

    return (
        f"**📋 The Butler's Favourites** | {stats['total_runs']} runs · {stats['total_players']} players\n"
        f"\n"
        f"**Busiest**\n" + fmt_list(stats['top_busiest'], "runs") + "\n"
        f"\n"
        f"**Highest Takedowns**\n" + fmt_list(stats['top_td_list'], "TD") + "\n"
        f"\n"
        f"**Most Kills**\n" + fmt_list(stats['top_kills_list'], "K") + "\n"
        f"\n"
        f"**Top Weapons**\n" + fmt_list(stats['top_weapons'], "runs") + "\n"
        f"\n"
        f"**Top Maps**\n" + fmt_list(stats['top_maps'], "runs") + "\n"
        f"\n"
        f"─────────────────────\n"
        f"🏆 **Grand Marshal** — {stats['grand_marshal']}\n"
        f"⚔️ **Weapons Master** — {stats['weapons_master']}\n"
        f"🗺️ **Campaign Master** — {stats['campaign_master']}\n"
        f"💀 **Headhunter** — {stats['headhunter']}\n"
        f"🩸 **Butcher** — {stats['butcher']}\n"
        f"\n"
        f"**High Lethality** *(kills/td)*\n" + "\n".join(f"{i+1}. {p}" for i, p in enumerate(stats['high_lethality'])) +
        f"\n\n**Low Lethality** *(td/kills)*\n" + "\n".join(f"{i+1}. {p}" for i, p in enumerate(stats['low_lethality']))
    )


async def update_title_roles(guild, stats):
    """Assign title roles and announce changes in #main."""
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


@bot.tree.command(name="butlers_report", description="Summon the Butler's Favourites report")
async def butlers_report(interaction: discord.Interaction):
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
        stats = calculate_butler_stats()
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



@bot.tree.command(name="purge_archive", description="Delete all threads in butlers-archive (admin only).")
@discord.app_commands.checks.has_permissions(administrator=True)
async def purge_archive(interaction: discord.Interaction):
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

        await interaction.followup.send(f"Purge complete — deleted {deleted} threads.", ephemeral=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"Purge error: {e}", ephemeral=True)


@bot.tree.command(name="import_registry", description="Import old registry cards from the-registry into butlers-archive (admin only).")
@discord.app_commands.checks.has_permissions(administrator=True)
async def import_registry(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        old_forum = interaction.guild.get_channel(1362435483061195022)  # the-registry
        if not old_forum:
            await interaction.followup.send("Could not find the-registry channel.", ephemeral=True)
            return

        # Build set of player names who have at least one submission
        subs = submissions_ws.get_all_values()[1:]
        players_with_subs = set()
        player_rows = players_ws.get_all_values()[1:]
        id_to_name = {row[0].strip(): row[1].strip() for row in player_rows if len(row) > 1}
        for row in subs:
            discord_id = row[2].strip() if len(row) > 2 else ''
            if discord_id and discord_id in id_to_name:
                players_with_subs.add(id_to_name[discord_id].lower())

        imported = 0
        skipped = 0

        all_threads = list(old_forum.threads)
        async for thread in old_forum.archived_threads(limit=200):
            all_threads.append(thread)

        for thread in all_threads:
            player_name = thread.name.strip()
            if player_name.lower() in players_with_subs:
                await _process_registry_thread(interaction.guild, thread)
                imported += 1
            else:
                skipped += 1
                print(f"Skipping {player_name} — no submissions")

        await interaction.followup.send(f"Import complete — {imported} cards created, {skipped} skipped (no submissions).", ephemeral=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"Import error: {e}", ephemeral=True)


async def _process_registry_thread(guild, thread):
    """Parse an old registry thread and extract weapon marks into LegacyMarks sheet."""
    import re
    player_name = thread.name.strip()

    # Read all messages in the thread
    messages = []
    async for msg in thread.history(limit=50, oldest_first=True):
        if msg.content:
            messages.append(msg.content)

    full_text = "\n".join(messages)

    # Parse weapon marks from lines like:
    # • :level3_6: Battle Axe: [✦✦✧]
    # The emoji encodes the current rank threshold: level{tier}_{threshold}
    # total marks = threshold + count of ✦ in bracket
    legacy_marks = {}  # weapon_name -> marks

    current_subclass = None

    for line in full_text.split("\n"):
        line = line.strip()

        # Detect subclass header: "Devastator: Grandmaster [▰▰▰▱▱▱]"
        for subclass in REGISTRY_WEAPON_MAP.keys():
            if re.search(rf'\b{re.escape(subclass)}\s*:', line) and any(
                r in line for r in ["Initiate", "Veteran", "Master", "Grandmaster", "Champion", "Paragon", "Apex", "Novice"]
            ):
                current_subclass = subclass
                break

        if not current_subclass:
            continue

        # Detect weapon line: • :levelX_N: WeaponName: [✦✦✧]
        emoji_match = re.search(r':level\d+_(\d+):', line)
        bracket_match = re.search(r'\[([✦✧]+)\]', line)

        if emoji_match and bracket_match:
            current_threshold = int(emoji_match.group(1))
            inner = bracket_match.group(1)
            filled = inner.count('✦')
            total_marks = current_threshold + filled

            # Extract weapon name between emoji and colon before bracket
            name_match = re.search(r':level\d+_\d+:\s*(.+?):\s*\[', line)
            if name_match:
                weapon_raw = name_match.group(1).strip()
                # Match to known weapon names
                for w in REGISTRY_WEAPON_MAP.get(current_subclass, []):
                    if w.lower() in weapon_raw.lower() or weapon_raw.lower() in w.lower():
                        if total_marks > 0:
                            legacy_marks[w] = max(legacy_marks.get(w, 0), total_marks)
                        break

    if not legacy_marks:
        print(f"No legacy marks found for {player_name}, skipping")
        return

    # Store in LegacyMarks sheet (flat: weapon -> marks, subclass left blank)
    await _save_legacy_marks(player_name, guild, legacy_marks)

    # Find discord ID from Players sheet
    discord_id = None
    rows = players_ws.get_all_values()[1:]
    for row in rows:
        if len(row) > 1 and row[1].strip().lower() == player_name.lower():
            try:
                discord_id = int(row[0].strip())
            except ValueError:
                pass
            break

    if discord_id:
        await create_or_update_registry_card(guild, discord_id, player_name)
        print(f"Registry card created for {player_name} (discord_id={discord_id})")
    else:
        print(f"No Discord ID found for {player_name}, skipping card creation")


async def _save_legacy_marks(player_name, guild, legacy_marks):
    """Save legacy weapon marks to LegacyMarks sheet, avoiding duplicates."""
    try:
        try:
            legacy_ws = sheet.worksheet('LegacyMarks')
        except Exception:
            legacy_ws = sheet.add_worksheet(title='LegacyMarks', rows=1000, cols=4)
            legacy_ws.append_row(['PlayerName', 'Weapon', 'Subclass', 'Marks'])

        existing = legacy_ws.get_all_values()[1:]
        existing_keys = {(r[0].strip(), r[1].strip()) for r in existing if len(r) >= 2}

        for weapon, marks in legacy_marks.items():
            key = (player_name, weapon)
            if key not in existing_keys:
                legacy_ws.append_row([player_name, weapon, '', marks])
    except Exception as e:
        print(f"Legacy marks save error for {player_name}: {e}")
    except Exception as e:
        print(f"Legacy marks save error for {player_name}: {e}")

@bot.tree.command(name="create_card", description="Create or refresh a player's registry card (admin only).")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(member="The player to create/refresh a card for")
async def create_card(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    try:
        await create_or_update_registry_card(interaction.guild, member.id, member.display_name)
        await interaction.followup.send(f"Registry card created/updated for {member.display_name}.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="title_guide", description="Post the Butler's Favourites title guide to the favourites channel (mod only).")
@discord.app_commands.checks.has_permissions(administrator=True)
async def title_guide(interaction: discord.Interaction):
    channel = bot.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message("Could not find the Butler's Favourites channel.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Butler's Favourites — Title Guide",
        description="Prestige titles awarded to the Lounge's top performers. Titles are recalculated automatically after every submission.",
        color=discord.Color.from_str("#c8a45a")
    )
    embed.add_field(
        name="🏆 Grand Marshal",
        value="Appears on 15+ leaderboards across all categories, ranked by average placement.",
        inline=False
    )
    embed.add_field(
        name="⚔️ Weapons Master",
        value="Appears on 9+ weapon leaderboards, ranked by average placement.",
        inline=False
    )
    embed.add_field(
        name="🗺️ Campaign Master",
        value="Appears on 6+ map leaderboards, ranked by average placement.",
        inline=False
    )
    embed.add_field(
        name="💀 Headhunter",
        value="Held by the #1 player on the 100 Kills board. Hit 100+ kills in a single match and submit your scoreboard to enter. Ranked by average kills score, weighted by number of submissions.",
        inline=False
    )
    embed.add_field(
        name="🩸 Butcher",
        value="Held by the #1 player on the 200 Takedowns board. Hit 200+ takedowns in a single match and submit your scoreboard to enter. Ranked by average takedowns score, weighted by number of submissions.",
        inline=False
    )
    embed.set_footer(text="Only one player holds each title at a time.")

    await channel.send(embed=embed)
    await interaction.response.send_message("Title guide posted.", ephemeral=True)


import traceback
try:
    bot.run(TOKEN)
except Exception as e:
    traceback.print_exc()
    input("Press Enter to exit...")