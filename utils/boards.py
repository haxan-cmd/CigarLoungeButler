"""Pure board-name classification — the single source of truth for which boards
are feat boards, which count toward the Weapons Master title, and what unit a
board's stored score is in.

This exists because the same hand-maintained board-name sets were duplicated
across several cogs, and adding the Score board silently broke the copies that
never got updated (season reset nearly wiped it; the Weapons Master title counted
it as a weapon board). Everything routes through here now, and it imports only
config so it can be unit-tested without discord.
"""
import config

# The canonical feat-board set. A feat board is any board that is NOT a per-weapon
# or per-map takedown board. Keep in sync with schema/setup, nothing else.
FEAT_BOARD_NAMES = {
    "100 Kills", "200 Takedowns", "Triple", "TUFF",
    "Flawless", "Mallet", "Knife", "Healing Horn", "Healing Banner", "Pacifist", "Hybrid",
    "Score",                # highest scoreboard points in a match, one row per player
    "The Hundred Handed",   # progress board, not score-based
}

# Feat boards that are weapon-SPECIFIC (a single weapon) — these DO count toward
# the Weapons Master title. Everything else feat is a non-weapon board.
WEAPON_FEAT_BOARDS = {"Mallet", "Knife"}

# Kills/takedown feat boards handled separately (Apex/Frenzied season stats).
_KILLS_OR_TD = {"100 Kills", "200 Takedowns"}
_PROGRESS_BOARDS = {"The Hundred Handed"}

# What unit a board's stored score value represents, for text display. Boards not
# listed here are takedown boards. ("Top Score" is the pre-rename Score alias.)
_BOARD_UNITS = {
    "Score": "points", "Top Score": "points", "Pacifist": "points",
    "100 Kills": "kills", "TUFF": "kill margin",
    # Healing boards store a HEALING total, not takedowns — without this they defaulted
    # to 'TDs' and a player's healing score leaked in as their "highest takedowns" PB.
    "Healing Banner": "healing", "Healing Horn": "healing",
}


def is_kills_board(name):
    """A per-weapon Highest-Kills board ("Messer Kills") — not a feat board."""
    return bool(name) and name.endswith(" Kills") and name not in FEAT_BOARD_NAMES


def is_map_board(name):
    """Map boards are "{Map} - {Faction}" where the map is a real map."""
    if not name or " - " not in name:
        return False
    base = name.split(" - ")[0].strip()
    return bool(base) and base in getattr(config, "MAP_ATTACK_DEFENSE", {})


def is_feat_board(name):
    return name in FEAT_BOARD_NAMES


def non_weapon_feat_boards():
    """Feat boards that must NOT count toward the Weapons Master title
    (Score, TUFF, Pacifist, Triple, Hybrid, Flawless, Healing Horn/Banner). They
    count toward Grand Marshal (most boards) but not weapon breadth. Mallet/Knife
    are weapon-specific and stay OUT of this set (they ARE weapon boards)."""
    return FEAT_BOARD_NAMES - WEAPON_FEAT_BOARDS - _KILLS_OR_TD - _PROGRESS_BOARDS


def archer_weapons():
    """The Archer-class weapons (Bow, Crossbow, Javelin, Throwing Axe, ...), derived
    from config.REGISTRY_CLASS_MAP. Excluded BY POLICY from the melee title placements
    (Weapons Master / Grand Marshal): a ranged board is still ranked on its own, it
    just doesn't count toward those titles."""
    out = set()
    for _sub in getattr(config, "REGISTRY_CLASS_MAP", {}).get("Archer", []):
        out.update(getattr(config, "REGISTRY_WEAPON_MAP", {}).get(_sub, []))
    return out


def is_archer_weapon(name):
    """True if `name` is an Archer-class weapon board (excluded from melee titles)."""
    return bool(name) and name in archer_weapons()


def board_unit(name):
    """Display unit for a board's stored score value ('points'/'kills'/'kill
    margin'/'TDs'). Prevents reporting Score points as takedowns."""
    return _BOARD_UNITS.get(name, "TDs")
