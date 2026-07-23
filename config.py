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
ALLTIME_RECORDS_FORUM_ID    = 0   # retired (Monthly Report removed; season stats live on the butler-season-board)

# Optional banner image shown atop the Ledger entrance dashboard (paste a Discord
# CDN image URL or any public image URL; leave "" to show no banner).
LEDGER_BANNER_URL = ""
# Banner atop the archive-entrance (The Ledger) header embed.
LEDGER_ENTRANCE_BANNER_URL = ""
BOUNTY_COMPLETION_BONUS     = 5   # season GP for FIRST bounty completion (race: 5/4/3, then 2 for later finishers)
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
COUNTING_CHANNEL_ID         = 1510068548775579868  # counting channel: stats tracker + Idiot-role insults
COUNTING_BOT_ID             = 510016054391734273   # the "counting" bot: its ✅ react + RUINED messages are the source of truth
CLOWN_TARGET_USER_ID        = 694099959066132531  # Butler clown-reacts this user often (not every post)

# The "99" channel: people post 90-99 TD games that just missed the 100 cutoff.
# The Butler occasionally pops in to sardonically commiserate — a 🍼 react or a
# dry one-liner. Rare by design (chance + cooldown), so it never spams. Set the
# channel ID (env-overridable) to enable; 0 = off.
import os as _os
NINETY_NINE_CHANNEL_ID   = int(_os.getenv('NINETY_NINE_CHANNEL_ID', '0'))
NINETY_NINE_REACT_CHANCE = float(_os.getenv('NINETY_NINE_CHANCE', '0.30'))
NINETY_NINE_COOLDOWN     = int(_os.getenv('NINETY_NINE_COOLDOWN', '240'))  # sec, per channel
# Weighted toward a 🍼 react; a dry quip fires less often.
NINETY_NINE_QUIPS = [
    "lol",
    "aw, nice try.",
    "so close. anyway.",
    "99. a fine number. not the one that counts, but fine.",
    "the board doesn't grade on effort, sir.",
    "almost is carrying a great deal of weight in that sentence.",
    "one short. how poetic.",
    "tragic. i'll alert the historians.",
    "and yet.",
    "there's always next game. probably.",
]
REACT_BLOCKED_USER_ID       = 694099959066132531  # this user's reactions are auto-removed in main (can still talk)
REGISTRY_INDEX_THREAD_ID    = 1519508672181571798
INDEX_THREAD_2H             = 1519531444064489592
INDEX_THREAD_1H             = 1519531596024119386
INDEX_THREAD_FEATS          = 1519531724881526834

# ── Role IDs ─────────────────────────────────────────────────────────────────
MOD_ROLE_ID             = 1472259982241300611
# The Manager (Bald Female) — nerve-centre digests ping her directly rather than the
# mod role (which renders as a stray "@Null").
MANAGER_ID              = 131581203256967168
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

# Never roll these as a Special Feature. They sit on the 1H/2H lists for board
# ROUTING, but they are personal-best feat boards, not weapons anyone grinds
# takedowns on, so featuring one gives the season a dead objective.
FEATURED_WEAPON_EXCLUDE = set(FEAT_WEAPONS) | {"Healing Banner"}

# A weapon or map needs at least this many logged runs all-time to be eligible
# as a Special Feature. Without a floor the inverse-frequency weighting below
# actively hunts for whatever nobody plays.
FEATURED_MIN_RUNS = 15

# Max masked links the Butler may insert into one reply. Low values keep prose
# readable, but a bulleted list of 8 bounty weapons looked broken when only the
# first 5 (longest names first) got linked.
BUTLER_MAX_LINKS = 14

# Minimum runs before a bar appears on an /explore RATE chart (lethality, kill
# share, warlord, avg TD/kills). At 3, three-run outliers topped the boards --
# a junk "Other" subclass led avg lethality on 3 runs. Volume metrics (run
# count, totals, best run) are unaffected: those are honest at any sample size.
EXPLORE_MIN_RUNS = 8

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

# High-lethality sticker — the bot replies with this sticker when a run's
# lethality (kills / takedowns) is at or above the threshold. Set the NAME to the
# exact sticker name as it appears in the server (Server Settings -> Stickers).
LETHALITY_STICKER_NAME = "lethality"   # exact sticker name in the server ("" to disable)
LETHALITY_STICKER_THRESHOLD = 60

# Submission blurb only shows the "vs weapon avg" lethality note when a run is a
# real OUTLIER — this many points above/below the weapon's average. Inside the
# band (near par) it's noise, so only raw lethality shows. Bigger = fewer notes.
LETHALITY_BLURB_MIN_DELTA = 5.0

# "Died a lot" sticker — the bot replies with this sticker when a run's DEATHS are at or
# above the threshold. Set NAME to the exact sticker name as it appears in the server
# (Server Settings -> Stickers). Leave "" to disable.
DEATHS_STICKER_NAME = "certifiedlounger"   # 30+ deaths -> reply with the Certified Lounger sticker
DEATHS_STICKER_THRESHOLD = 30

# Lobby tilt — PERCENTAGE gap between the two faction banner kill totals,
# relative to the smaller team (so +50% and -50% mean the same imbalance).
# Positive = your team led. Percentage instead of raw diff so long games and
# big lobbies don't read as stomps (Sylveon's suggestion, 2026-07-15). Drives
# the red-to-green marker on the blurb + a 🍼 react/sticker at STOMP or more.
# Calibrated from 94 logged games: ~69% land Even at LEAN=25. STOMP=75 keeps
# the baby bottle for true massacres only (top ~5%; a 600-400 game at +50% is
# a solid win, not a playpen — raised from 50 on 2026-07-16). Max seen: +104%.
# Sticker name as it appears in Server Settings -> Stickers; "" disables.
LOBBY_TILT_STOMP        = 75    # percent
LOBBY_TILT_LEAN         = 25    # percent
STOMP_STICKER_NAME      = "traininggrounds"

# Per-weapon animated Virtuoso emoji shown on the player card (fallback below).
# Use the full custom-emoji token: animated = "<a:name:id>", static = "<:name:id>".
VIRTUOSO_DEFAULT_EMOJI = "\U0001f48e"  # gem, used when a weapon has no custom emoji
VIRTUOSO_WEAPON_EMOJIS = {
    "Executioner's Axe": "<a:executioneraxevirtuoso:1523020043615731812>",
    "Messer": "<a:messervirtuoso:1523020066923352188>",
}

# Per-weapon animated emoji shown on the blurb at 100-mark Mastery (Virtuoso, 250,
# takes precedence when a weapon has both).
MASTERY_WEAPON_EMOJIS = {
    "Halberd": "<a:halberdmastery:1523019767328538765>",
    "Greatsword": "<a:greatswordmastery:1523019414994419863>",
    "Messer": "<a:messermaster:1523878605002899627>",
    "Battle Axe": "<a:battleaxemaster:1524768667974504630>",
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
    "Pacifist":      "<a:passive:1365531248268673086>",
    "Hybrid":        "🔀",
}

SPECIAL_OPS_EMOJIS = {
    "Fist and Shield": "<a:captain_america:1366801668041211934>",
    "Healing Horn":    "<a:passive:1365531248268673086>",
    "Healing Banner":  "🚩",
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

# (attacker, defender) — corrected against in-game banners, 2026-07-16
MAP_ATTACK_DEFENSE = {
    "Aberfell":          ("Agatha", "Mason"),
    "Askandir":          ("Mason",  "Tenosia"),
    "Baudwyn":           ("Tenosia", "Mason"),
    "Bridgetown":        ("Tenosia", "Agatha"),
    "Coxwell":           ("Mason",  "Agatha"),
    "Darkforest":        ("Mason",  "Agatha"),
    "Falmire":           ("Agatha", "Mason"),
    "Galencourt":        ("Mason",  "Agatha"),
    "Lionspire":         ("Mason",  "Agatha"),
    "Montcrux":          ("Agatha", "Tenosia"),
    "Rudhelm":           ("Agatha", "Mason"),
    "Thayic Stronghold": ("Mason",  "Agatha"),
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
# Player titles by TOTAL bounties completed (index = count, capped at the top).
# Cigar-lounge / made-man theme. Assigned manually now, but get_player_title
# still renders this on the registry card from the bounty count.
PLAYER_TITLES  = ["Lounger", "Insider", "Regular", "Made Man", "High Roller", "Kingpin", "Legend"]

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
    "cav sword": "Heavy Cavalry Sword", "cavalry sword": "Heavy Cavalry Sword", "heavy cav sword": "Heavy Cavalry Sword",
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
    ("/help",         "Every command you can run, grouped by what it does."),
    ("/rules",        "Show the Cigar Lounge challenge rules."),
    ("/playerstats",  "Your all-time profile: title, weapon ranks and marks. /playerstats [name] for anyone."),
    ("/season",       "Your season GP: rank, where each point came from, and how far off the next place."),
    ("/refreshcard",  "Refresh your registry card in butlers-archive."),
    ("/top",          "Top 10 for any weapon or class board e.g. /top Messer."),
    ("/standings",    "Live standings for the current season."),
    ("/titles",       "Who leads each all-time title, with the tiebreak shown."),
    ("/report",       "Current-standings snapshot: season champions, records, all-time titles."),
    ("/serverstats",  "Server activity dashboard over 24h / 7d / 30d."),
    ("/explore",      "Any metric grouped any way, filtered by feat or season, as a chart."),
    ("/aliases",      "Who has the most in-game names."),
    ("/bounty status", "The active bounty card and your personal progress."),
]

# Leaderboard display-name overrides. Keys may be a discord_id (all digits) or an
# exact display name -> replacement. LEADERBOARD_NAME_CONTAINS matches messy or
# unicode-lookalike names by folded substrings: (required_substrings, replacement).
LEADERBOARD_NAME_OVERRIDES = {
    "460883781830574091": "Yaboombatron",    # yaboomba (real submission id)
    "833823649676394516": "massive egglant",  # Massive Eggplant (real submission id)
}
LEADERBOARD_NAME_CONTAINS = []
