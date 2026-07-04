"""
config.py — All constants, IDs, emoji maps, weapon lists, and alias tables.
Nothing is imported from other project modules here.
"""
import os
from dotenv import load_dotenv
load_dotenv()

load_dotenv()

# ── Credentials / IDs ────────────────────────────────────────────────────────
TOKEN    = os.getenv('DISCORD_TOKEN')
SHEET_ID = '1aT7MbBa3qZxx9ZyaFvlgmbjvCDe2kkQMt5Qsnq_6lzY'
GUILD_ID = 1324379304544567356

DECORATION_TOP    = os.getenv('DECORATION_TOP',    'WMMR_Spacer_Top.png')
DECORATION_BOTTOM = os.getenv('DECORATION_BOTTOM', 'WMMR_Spacer_Bottom.png')

# ── Channel IDs ───────────────────────────────────────────────────────────────
SUBMISSIONS_CHANNEL_ID      = 1328832440927518920
MAIN_CHANNEL_ID             = 1324447691467526338
REGISTRY_FORUM_CHANNEL_ID   = 1519127645286170654   # butlers-archive
MAP_RECORDS_FORUM_ID        = 1460730790559092888
WEAPONS_2H_FORUM_ID         = 1456639902077812868
WEAPONS_1H_FORUM_ID         = 1486118387800346768
FEATS_FORUM_ID              = 1486143184542105680
BOUNTY_CARDS_FORUM_ID       = 1518657580174676021
HALL_OF_FAME_FORUM_ID       = 1521858440593670235   # season Hall of Fame forum
ALLTIME_RECORDS_FORUM_ID    = 1522630299337490582   # all-time-records forum

# Optional banner image shown atop the Ledger entrance dashboard (paste a Discord
# CDN image URL or any public image URL; leave "" to show no banner).
LEDGER_BANNER_URL = ""
# Banner atop the archive-entrance (The Ledger) header embed.
LEDGER_ENTRANCE_BANNER_URL = ""
BOUNTY_COMPLETION_BONUS     = 5   # season GP points awarded for completing the bounty
BOUNTY_FORUM_CHANNEL_ID     = 1456640264004435978   # Ledger forum for bounty cards
BULLETIN_BOARD_CATEGORY_ID  = 1359537379039252550
LEDGER_CATEGORY_ID          = 1456640264004435978
BUTLERS_NOTES_CHANNEL_ID    = 1518771519075909702
BUTLERS_FAVOURITES_CHANNEL_ID = 1518822798116524092
BUTLERS_MANUAL_CHANNEL_ID   = 1519829042843357274
KOFI_DONATION_CHANNEL_ID    = 1521577105052270694
KOFI_URL                    = "https://ko-fi.com/baldfemale"
KOFI_MONTHLY_GOAL           = 20.00
NERVE_CENTER_CHANNEL_ID     = 1520092706074787870
CHALLENGE_RULES_CHANNEL_ID  = 1460713024082935930
LEDGER_ENTRANCE_CHANNEL_ID  = 1520290658387099648
COUNTING_CHANNEL_ID         = None  # counting channel; set to its ID so the Butler insults whoever earns the Idiot role
CLOWN_TARGET_USER_ID        = 694099959066132531  # Butler clown-reacts this user often (not every post)
REACT_BLOCKED_USER_ID       = 694099959066132531  # this user's reactions are auto-removed in main (can still talk)
REGISTRY_INDEX_THREAD_ID    = 1519508672181571798
INDEX_THREAD_2H             = 1519531444064489592
INDEX_THREAD_1H             = 1519531596024119386
INDEX_THREAD_FEATS          = 1519531724881526834

# ── Role IDs ─────────────────────────────────────────────────────────────────
MOD_ROLE_ID             = 1472259982241300611
GRAND_MARSHAL_ROLE_ID   = 1467680214560674020
WEAPONS_MASTER_ROLE_ID  = 1467679890706010277
CAMPAIGN_MASTER_ROLE_ID = 1518820158821367858
MOST_LETHAL_ROLE_ID     = 1518827472718921819
WARLORD_ROLE_ID         = 1518827620572205097
HUNDRED_HANDED_ROLE_ID  = 1472321853023326361
UNBOUND_ROLE_ID         = 1433215577173786758

# ── Weapon lists ─────────────────────────────────────────────────────────────
WEAPONS_2H = [
    "Battle Axe", "Dane Axe", "Executioner's Axe", "Glaive",
    "Goedendag", "Greatsword", "Halberd", "Highland Sword", "Katars",
    "Longsword", "Maul", "Messer", "Morning Star", "Pole Axe", "Polehammer",
    "Quarterstaff", "Shovel", "Sledge Hammer", "Spear", "Two-Handed Hammer",
    "War Axe", "War Club", "Heavy Mace",
]

WEAPONS_1H = [
    "Axe", "Dagger", "Falchion", "Fist and Shield", "Hatchet", "Healing Horn",
    "Heavy Cavalry Sword", "Knife", "Mace", "Mallet", "One-Handed Spear",
    "Pick Axe", "Rapier", "Short Sword", "Sword", "Warhammer", "Cudgel",
]

CLASS_WEAPON_MAP = {
    "Officer":        ["Axe", "Greatsword", "Heavy Mace", "Longsword", "Mace", "Pole Axe", "Sword", "War Axe"],
    "Guardian":       ["Axe", "Falchion", "Fist and Shield", "Hatchet", "Heavy Cavalry Sword", "Mace", "One-Handed Spear", "Short Sword", "Warhammer"],
    "Crusader":       ["Axe", "Battle Axe", "Executioner's Axe", "Falchion", "Messer", "Morning Star", "Quarterstaff", "Two-Handed Hammer"],
    "Devastator":     ["Battle Axe", "Executioner's Axe", "Greatsword", "Highland Sword", "Knife", "Maul", "War Club"],
    "Raider":         ["Dane Axe", "Glaive", "Messer", "Two-Handed Hammer"],
    "Ambusher":       ["Cudgel", "Dagger", "Hatchet", "Katars", "Short Sword"],
    "Poleman":        ["Cudgel", "Glaive", "Goedendag", "Halberd", "Hatchet", "Polehammer", "Quarterstaff", "Short Sword", "Spear"],
    "Man-at-Arms":    ["Axe", "Falchion", "Fist and Shield", "Healing Horn", "Heavy Cavalry Sword", "Knife", "Mace",
                       "Morning Star", "One-Handed Spear", "Rapier", "Short Sword", "Sword"],
    "Field Engineer": ["Goedendag", "Mallet", "Pick Axe", "Shovel", "Sledge Hammer"],
    "Longbowman":     ["Bow", "Cudgel", "Hatchet", "Knife", "Short Sword", "War Bow"],
    "Crossbowman":    ["Axe", "Crossbow", "Cudgel", "Knife", "Short Sword", "Siege Crossbow"],
    "Skirmisher":     ["Axe", "Falchion", "Javelin", "Knife", "Mace", "Throwing Axe"],
}

SUBCLASS_PARENT = {
    "Officer":      "Knight",  "Guardian":     "Knight",  "Crusader":      "Knight",
    "Devastator":   "Vanguard","Raider":        "Vanguard","Ambusher":      "Vanguard",
    "Poleman":      "Footman", "Man-at-Arms":   "Footman", "Field Engineer":"Footman",
    "Longbowman":   "Archer",  "Crossbowman":   "Archer",  "Skirmisher":    "Archer",
}

PARENT_TO_SUBCLASSES = {
    "Knight":   ["Officer", "Guardian", "Crusader"],
    "Vanguard": ["Devastator", "Raider", "Ambusher"],
    "Footman":  ["Poleman", "Man-at-Arms", "Field Engineer"],
    "Archer":   ["Crossbowman", "Longbowman", "Skirmisher"],
}

MAP_FACTIONS = {
    "Aberfell":         ["Agatha", "Mason"],
    "Askandir":         ["Mason",  "Tenosia"],
    "Baudwyn":          ["Mason",  "Tenosia"],
    "Bridgetown":       ["Agatha", "Tenosia"],
    "Coxwell":          ["Agatha", "Mason"],
    "Darkforest":       ["Agatha", "Mason"],
    "Falmire":          ["Agatha", "Mason"],
    "Galencourt":       ["Agatha", "Mason"],
    "Lionspire":        ["Agatha", "Mason"],
    "Montcrux":         ["Agatha", "Tenosia"],
    "Rudhelm":          ["Agatha", "Mason"],
    "Thayic Stronghold":["Agatha", "Mason"],
    "Trayan Citadel":   ["Agatha", "Mason"],
}
MAPS = sorted(MAP_FACTIONS.keys())

# Vision sometimes returns full in-game display names — normalize to our short keys
MAP_ALIASES = {
    "the battle of darkforest": "Darkforest",
    "the battle of aberfell": "Aberfell",
    "the raid on aberfell": "Aberfell",
    "raid on aberfell": "Aberfell",
    "the siege of coxwell": "Coxwell",
    "the slaughter of coxwell": "Coxwell",
    "slaughter of coxwell": "Coxwell",
    "the battle of galencourt": "Galencourt",
    "the desecration of galencourt": "Galencourt",
    "desecration of galencourt": "Galencourt",
    "the battle of rudhelm": "Rudhelm",
    "the battle of falmire": "Falmire",
    "the siege of lionspire": "Lionspire",
    "the fall of lionspire": "Lionspire",
    "fall of lionspire": "Lionspire",
    "the battle of montcrux": "Montcrux",
    "the reclamation of montcrux": "Montcrux",
    "reclamation of montcrux": "Montcrux",
    "the battle of baudwyn": "Baudwyn",
    "the breach of baudwyn": "Baudwyn",
    "breach of baudwyn": "Baudwyn",
    "the battle of bridgetown": "Bridgetown",
    "sacking of bridgetown": "Bridgetown",
    "the sacking of bridgetown": "Bridgetown",
    "the battle of askandir": "Askandir",
    "the razing of askandir": "Askandir",
    "raiding of askandir": "Askandir",
    "the raiding of askandir": "Askandir",
    "the siege of thayic stronghold": "Thayic Stronghold",
    "the assault on thayic stronghold": "Thayic Stronghold",
    "assault on thayic stronghold": "Thayic Stronghold",
    "the siege of trayan citadel": "Trayan Citadel",
    "regicide at trayan citadel": "Trayan Citadel",
    "the regicide at trayan citadel": "Trayan Citadel",
    "escape from falmire": "Falmire",
    "the escape from falmire": "Falmire",
    "falmire": "Falmire",
    "askandir": "Askandir",
    "aberfell": "Aberfell",
    "baudwyn": "Baudwyn",
    "bridgetown": "Bridgetown",
    "coxwell": "Coxwell",
    "darkforest": "Darkforest",
    "galencourt": "Galencourt",
    "lionspire": "Lionspire",
    "montcrux": "Montcrux",
    "rudhelm": "Rudhelm",
    "thayic stronghold": "Thayic Stronghold",
    "trayan citadel": "Trayan Citadel",
    # Extra variants Gemini may return
    "battle of darkforest": "Darkforest",
    "battle of aberfell": "Aberfell",
    "siege of coxwell": "Coxwell",
    "battle of galencourt": "Galencourt",
    "battle of rudhelm": "Rudhelm",
    "siege of rudhelm": "Rudhelm",
    "the siege of rudhelm": "Rudhelm",
    "battle of falmire": "Falmire",
    "siege of lionspire": "Lionspire",
    "battle of montcrux": "Montcrux",
    "battle of baudwyn": "Baudwyn",
    "battle of bridgetown": "Bridgetown",
    "battle of askandir": "Askandir",
    "razing of askandir": "Askandir",
    "siege of thayic stronghold": "Thayic Stronghold",
    "siege of trayan citadel": "Trayan Citadel",
    "darkforest": "Darkforest",
    "aberfell": "Aberfell",
    "coxwell": "Coxwell",
    "galencourt": "Galencourt",
    "rudhelm": "Rudhelm",
    "lionspire": "Lionspire",
    "montcrux": "Montcrux",
    "baudwyn": "Baudwyn",
    "bridgetown": "Bridgetown",
}

FEAT_WEAPONS = ["Mallet", "Knife", "Healing Horn", "Fist and Shield"]

VIP_MAPS = {
    ("Trayan Citadel",    "Agatha"),
    ("Trayan Citadel",    "Mason"),
    ("Thayic Stronghold", "Agatha"),
    ("Falmire",           "Agatha"),
    ("Rudhelm",           "Mason"),
    ("Darkforest",        "Agatha"),
}

MARKSMAN_SUBCLASSES = {
    "Longbowman":  ["Bow", "War Bow"],
    "Crossbowman": ["Crossbow", "Siege Crossbow"],
    "Skirmisher":  ["Javelin", "Throwing Axe"],
}

# ── Registry weapon / class maps ─────────────────────────────────────────────
REGISTRY_WEAPON_MAP = {
    "Officer":        ["Axe", "Greatsword", "Heavy Mace", "Longsword", "Mace", "Pole Axe", "Sword", "War Axe"],
    "Guardian":       ["Axe", "Falchion", "Heavy Cavalry Sword", "One-Handed Spear", "Warhammer"],
    "Crusader":       ["Axe", "Battle Axe", "Executioner's Axe", "Falchion", "Messer", "Morning Star", "Quarterstaff", "Two-Handed Hammer"],
    "Devastator":     ["Battle Axe", "Executioner's Axe", "Greatsword", "Highland Sword", "Knife", "Maul", "War Club"],
    "Raider":         ["Dane Axe", "Glaive", "Messer", "Two-Handed Hammer"],
    "Ambusher":       ["Cudgel", "Dagger", "Hatchet", "Katars", "Short Sword"],
    "Poleman":        ["Cudgel", "Glaive", "Goedendag", "Halberd", "Hatchet", "Polehammer", "Quarterstaff", "Short Sword", "Spear"],
    "Man-at-Arms":    ["Falchion", "Heavy Cavalry Sword", "Mace", "Morning Star", "One-Handed Spear", "Rapier", "Sword"],
    "Field Engineer": ["Goedendag", "Pick Axe", "Shovel", "Sledge Hammer"],
    "Longbowman":     ["Bow", "War Bow"],
    "Crossbowman":    ["Crossbow", "Siege Crossbow"],
    "Skirmisher":     ["Javelin", "Throwing Axe"],
}

REGISTRY_CLASS_MAP = {
    "Knight":   ["Officer", "Guardian", "Crusader"],
    "Vanguard": ["Devastator", "Raider", "Ambusher"],
    "Footman":  ["Poleman", "Man-at-Arms", "Field Engineer"],
    "Archer":   ["Longbowman", "Crossbowman", "Skirmisher"],
}

MASTERY_THRESHOLD  = 100   # qualifying (100+ TD) primary-weapon runs to master a weapon
VIRTUOSO_THRESHOLD = 250   # runs to reach Virtuoso on a weapon

# Per-weapon animated Virtuoso emoji shown on the player card (fallback below).
# Use the full custom-emoji token: animated = "<a:name:id>", static = "<:name:id>".
VIRTUOSO_DEFAULT_EMOJI = "\U0001f48e"  # gem, used when a weapon has no custom emoji
VIRTUOSO_WEAPON_EMOJIS = {
    "Executioner's Axe": "<a:ExecAxeVirtuoso:1522338416425959624>",
    "Messer": "<a:messervirtuoso:1522715847485952231>",
}

# Per-weapon animated emoji shown on the blurb at 100-mark Mastery (Virtuoso, 250,
# takes precedence when a weapon has both).
MASTERY_WEAPON_EMOJIS = {
    "Halberd": "<a:halberdmastery:1522718086225068215>",
    "Greatsword": "<a:greatswordmastery:1523012710621773836>",
}

# Subclass primaries — only these count toward Mastered Weapon (100 submissions)
_SUBCLASS_PRIMARIES = {
    "Officer":        {"Longsword", "War Axe", "Greatsword", "Pole Axe", "Heavy Mace"},
    "Guardian":       {"Warhammer", "Falchion", "Heavy Cavalry Sword", "Axe", "One-Handed Spear"},
    "Crusader":       {"Messer", "Battle Axe", "Two-Handed Hammer", "Executioner's Axe", "Quarterstaff"},
    "Devastator":     {"Greatsword", "Maul", "War Club", "Battle Axe", "Executioner's Axe", "Highland Sword"},
    "Raider":         {"Dane Axe", "Glaive", "Two-Handed Hammer", "Messer"},
    "Ambusher":       {"Hatchet", "Dagger", "Cudgel", "Katars", "Short Sword"},
    "Poleman":        {"Halberd", "Polehammer", "Spear", "Glaive", "Quarterstaff", "Goedendag"},
    "Man-at-Arms":    {"Sword", "Morning Star", "Falchion", "One-Handed Spear", "Rapier", "Heavy Cavalry Sword"},
    "Field Engineer": {"Goedendag", "Pick Axe", "Sledge Hammer", "Shovel"},
    "Longbowman":     {"War Bow", "Bow"},
    "Crossbowman":    {"Crossbow", "Siege Crossbow"},
    "Skirmisher":     {"Javelin", "Throwing Axe"},
}

# ── Emoji maps ────────────────────────────────────────────────────────────────
WEAPON_RANK_EMOJIS = {
    "Unranked":         "<:level0_0:1361479473375219832>",
    "Bronze":           "<:level1_1:1361419350665461820>",
    "Silver":           "<:level2_3:1361419398841106442>",
    "Gold":             "<:level3_6:1361419489635209396>",
    "Emerald":          "<:level4_9:1368656036784771212>",
    "Diamond":          "<:level5_12:1368656100764942432>",
    "Crimson":          "<:level6_15:1430203489757302924>",
    "Prestige Bronze":  "<:level7_20:1430216503919120537>",
    "Prestige Silver":  "<:level8_30:1430216636006137876>",
    "Prestige Gold":    "<:level9_40:1430216748329599046>",
    "Prestige Emerald": "<:level10_55:1430216819787956265>",
    "Prestige Diamond": "<:level11_70:1430217739586240624>",
    "Prestige Crimson": "<:level12_85:1430217099648962651>",
    "Iridescent":       "<:level13_100:1459253823481712895>",
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
    "Sworn":    "<:class0_0:1446622044698443969>",
    "Trusted":  "<:class1_3:1446620360186269726>",
    "Proven":   "<:class2_6:1446620614096846988>",
    "Honored":  "<:class3_9:1446620700189266182>",
    "Esteemed": "<:class4_12:1446620991777407128>",
    "Exalted":  "<:class5_15:1446621127605620826>",
    "Ascended": "<:class6_18:1446621258430025791>",
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
    "Mallet":          "🔨",
    "Knife":           "🔪",
}

TITLE_EMOJIS = {
    "Grand Marshal":   "<a:grandmarshal:1519928617407348877>",
    "Weapons Master":  "<a:weaponsmaster:1519928521445605488>",
    "Campaign Master": "<a:campaignmaster:1520497947115262083>",
    "apex_title":      "<a:topkill:1360314538364240024>",
    "frenzied_title":  "<a:200tkd:1363648828414230538>",
    "Lethality":       "<a:mostlethal:1520490418817601658>",
    "Warlord":         "<:warlord:1520490364039860347>",
}

FACTION_EMOJIS = {
    "Agatha": "<:agatha:1350669712593260554>",
    "Mason":  "<:mason:1350669458863292426>",
    "Tenosia":"<:tenosia:1350669567269273682>",
}

MAP_ATTACK_DEFENSE = {
    "Aberfell":          ("Agatha", "Mason"),
    "Askandir":          ("Mason",  "Tenosia"),
    "Baudwyn":           ("Mason",  "Tenosia"),
    "Bridgetown":        ("Agatha", "Tenosia"),
    "Coxwell":           ("Agatha", "Mason"),
    "Darkforest":        ("Agatha", "Mason"),
    "Falmire":           ("Agatha", "Mason"),
    "Galencourt":        ("Agatha", "Mason"),
    "Lionspire":         ("Agatha", "Mason"),
    "Montcrux":          ("Agatha", "Tenosia"),
    "Rudhelm":           ("Agatha", "Mason"),
    "Thayic Stronghold": ("Agatha", "Mason"),
    "Trayan Citadel":    ("Agatha", "Mason"),
}

# ── Rank thresholds ───────────────────────────────────────────────────────────
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

PRESTIGE_THRESHOLDS = [175, 210, 260, 335, 460]

SUBCLASS_RANKS = ["Initiate", "Veteran", "Master", "Grandmaster", "Champion", "Paragon", "Apex"]
CLASS_RANKS    = ["Sworn", "Trusted", "Proven", "Honored", "Esteemed", "Exalted", "Ascended"]
PLAYER_TITLES  = ["Unbound", "Proven", "Respected", "Distinguished", "Renowned", "Illustrious", "Exemplar", "Legend"]

SUBCLASS_RANK_THRESHOLDS = list(enumerate(SUBCLASS_RANKS))
CLASS_RANK_THRESHOLDS    = list(enumerate(CLASS_RANKS))

# ── Alias maps ────────────────────────────────────────────────────────────────
WEAPON_ALIASES = {
    "ls": "Longsword", "longsword": "Longsword",
    "hmace": "Heavy Mace", "heavy mace": "Heavy Mace",
    "mace": "Mace", "1h mace": "Mace",
    "dane": "Dane Axe", "dane axe": "Dane Axe",
    "exe axe": "Executioner's Axe", "exec axe": "Executioner's Axe",
    "executioner axe": "Executioner's Axe", "executioners axe": "Executioner's Axe",
    "baxe": "Battle Axe", "battle axe": "Battle Axe",
    "gs": "Greatsword", "greatsword": "Greatsword",
    "mstar": "Morning Star", "morning star": "Morning Star",
    "qs": "Quarterstaff", "quarterstaff": "Quarterstaff",
    "halberd": "Halberd", "glaive": "Glaive", "spear": "Spear",
    "dagger": "Dagger", "knife": "Knife", "hatchet": "Hatchet",
    "katars": "Katars", "falchion": "Falchion", "rapier": "Rapier",
    "sword": "Sword", "short sword": "Short Sword",
    "war axe": "War Axe", "pole axe": "Pole Axe", "poleaxe": "Pole Axe",
    "polehammer": "Polehammer", "maul": "Maul", "war club": "War Club",
    "shovel": "Shovel", "pick axe": "Pick Axe", "pickaxe": "Pick Axe",
    "mallet": "Mallet",
    "messer": "Messer", "axe": "Axe",
    "sledge": "Sledge Hammer", "sledgehammer": "Sledge Hammer", "sledge hammer": "Sledge Hammer",
    "highland sword": "Highland Sword",
    "warhammer": "Warhammer", "war hammer": "Warhammer",
    "goedendag": "Goedendag", "cudgel": "Cudgel",
    "healing horn": "Healing Horn",
    "fist": "Fist and Shield", "fist and shield": "Fist and Shield",
    "heavy cavalry sword": "Heavy Cavalry Sword", "hcs": "Heavy Cavalry Sword",
    "one handed spear": "One-Handed Spear", "one hand spear": "One-Handed Spear",
    "1 hand spear": "One-Handed Spear", "1 handed spear": "One-Handed Spear", "1h spear": "One-Handed Spear",
    "two handed hammer": "Two-Handed Hammer", "2h hammer": "Two-Handed Hammer",
    "bow": "Bow", "war bow": "War Bow",
    "crossbow": "Crossbow", "siege crossbow": "Siege Crossbow",
    "javelin": "Javelin", "throwing axe": "Throwing Axe",
}

SUBCLASS_ALIASES = {
    "knight": "Knight", "vanguard": "Vanguard", "van": "Vanguard",
    "footman": "Footman", "archer": "Archer",
    "devastator": "Devastator", "dev": "Devastator",
    "crusader": "Crusader", "guardian": "Guardian",
    "raider": "Raider", "ambusher": "Ambusher",
    "poleman": "Poleman",
    "man at arms": "Man-at-Arms", "man-at-arms": "Man-at-Arms", "maa": "Man-at-Arms",
    "field engineer": "Field Engineer", "engineer": "Field Engineer", "eng": "Field Engineer",
    "officer": "Officer",
    "longbowman": "Longbowman", "crossbowman": "Crossbowman", "skirmisher": "Skirmisher",
}

# ── Player commands list (for butlers-manual) ─────────────────────────────────
PLAYER_COMMANDS = [
    ("/rules",          "Show the Cigar Lounge challenge rules."),
    ("/rank",           "Show the top 10 for any weapon leaderboard e.g. /rank Messer."),
    ("/stats",          "Show your title standings and weapon rank progress. Use /stats [name] for any player."),
    ("/refresh_card",   "Refresh your registry card in butlers-archive."),
        ("/butlers_report", "Summon the Butler's Favourites report."),
    ("/bounty_status",  "Show the current active bounty card and your personal progress."),
    ("/bounty_hunt",    "Show the top 5 hunters for the active bounty."),
]

# Leaderboard display-name overrides. Keys may be a discord_id (all digits) or an
# exact display name -> replacement. LEADERBOARD_NAME_CONTAINS matches messy or
# unicode-lookalike names by folded substrings: (required_substrings, replacement).
LEADERBOARD_NAME_OVERRIDES = {
    "460883781830574091": "Yaboombatron",    # yaboomba (real submission id)
    "833823649676394516": "massive egglant",  # Massive Eggplant (real submission id)
}
LEADERBOARD_NAME_CONTAINS = []
