"""
cogs/submissions.py — UI views, submission flow, and submission worker.
"""
import os
import re
import json
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta

import config
from utils.sheets import (
    _sheet_cache, _registry_lock,
    submissions_ws, players_ws, leaderboard_data_ws,
    bounty_ws, bounty_players_ws, registry_ws,
    leaderboards_ws, index_posts_ws,
    _submission_queues, _submission_workers, get_submission_queue,
    cached_submissions, cached_players, cached_leaderboard_data,
    gspread_retry,
)
from utils.helpers import (
    parse_submission_text, format_weapon_marks,
    detect_weapon_milestones, build_milestone_message,
    nerve_log_submission, nerve_log_error, nerve_log_milestone,
    submission_state, butler_quip, vision_parse_scorecard,
)

def _ordinal(n):
    return {1:'st',2:'nd',3:'rd'}.get(n if n < 20 else n % 10, 'th')

MOD_ROLE_ID            = config.MOD_ROLE_ID
_ASSETS_DIR            = os.path.join(os.path.dirname(__file__), '..', 'assets')
DECORATION_TOP         = os.path.join(_ASSETS_DIR, 'WMMR_Spacer_Top.png')
DECORATION_BOTTOM      = os.path.join(_ASSETS_DIR, 'WMMR_Spacer_Bottom.png')
SUBMISSIONS_CHANNEL_ID = config.SUBMISSIONS_CHANNEL_ID
BUTLERS_NOTES_CHANNEL_ID = config.BUTLERS_NOTES_CHANNEL_ID
BUTLERS_FAVOURITES_CHANNEL_ID = config.BUTLERS_FAVOURITES_CHANNEL_ID
BOUNTY_CARDS_FORUM_ID  = config.BOUNTY_CARDS_FORUM_ID
MAIN_CHANNEL_ID        = config.MAIN_CHANNEL_ID
MAPS                   = config.MAPS
VIP_MAPS               = config.VIP_MAPS
MAP_FACTIONS           = config.MAP_FACTIONS
FEAT_WEAPONS           = config.FEAT_WEAPONS
MARKSMAN_SUBCLASSES    = config.MARKSMAN_SUBCLASSES
SUBCLASS_PARENT        = config.SUBCLASS_PARENT
WEAPONS_2H             = config.WEAPONS_2H
WEAPONS_1H             = config.WEAPONS_1H
CLASS_WEAPON_MAP       = config.CLASS_WEAPON_MAP
WEAPON_RANK_THRESHOLDS = config.WEAPON_RANK_THRESHOLDS
PRESTIGE_THRESHOLDS    = config.PRESTIGE_THRESHOLDS
GUILD_ID               = config.GUILD_ID


# ── Player helpers ─────────────────────────────────────────────────────────────
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
    class_weapons = CLASS_WEAPON_MAP.get(selected_class, [])
    return sorted(class_weapons)

def upsert_player(discord_id, discord_name):
    """Returns True if this is a new player."""
    try:
        rows = cached_players()
        discord_id_str = str(discord_id)
        for i, row in enumerate(rows, start=2):
            if row and row[0] == discord_id_str:
                if len(row) < 2 or row[1] != discord_name:
                    players_ws.update_cell(i, 2, discord_name)
                    _sheet_cache.invalidate(players_ws)
                return False
        players_ws.append_row([discord_id_str, discord_name, ""])
        _sheet_cache.invalidate(players_ws)
        return True
    except Exception as e:
        print(f"Player upsert error: {e}")
        return False

def log_submission(discord_name, discord_id, weapon, cls, map_name, faction,
                   takedowns, kills, deaths, vip, feats, message_link,
                   lobby_rank=None, lobby_size=None, kills_rank=None,
                   team_rank=None, team_size=None, total_lobby_kills=None, team_score_ratio=None):
    from datetime import datetime as _dt
    timestamp = _dt.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    vip_str   = "Yes" if vip else "No"
    feats_str = ", ".join(feats) if feats else "None"
    nerve_log_submission(discord_name, weapon)
    submissions_ws.append_row([
        timestamp, discord_name, str(discord_id), weapon, cls,
        map_name, faction, takedowns, kills, deaths, vip_str, feats_str, message_link,
        lobby_rank        if lobby_rank        is not None else '',
        lobby_size        if lobby_size        is not None else '',
        kills_rank        if kills_rank        is not None else '',
        team_rank         if team_rank         is not None else '',
        team_size         if team_size         is not None else '',
        total_lobby_kills if total_lobby_kills is not None else '',
        round(team_score_ratio, 3) if team_score_ratio is not None else '',
    ])
    _sheet_cache.invalidate(submissions_ws)

class SubmitView(discord.ui.View):
    def __init__(self, original_message, prompt_msg=None):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg

    async def on_timeout(self):
        try:
            await self.prompt_msg.edit(
                content="*Submission window expired. Post again to start a new one.*",
                view=None,
            )
        except Exception:
            pass
        self.stop()


    @discord.ui.button(label='Submit Run', style=discord.ButtonStyle.green, emoji='⚔️')
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        # Prevent double-processing if user clicks twice or Discord replays the interaction
        msg_id = self.original_message.id
        if msg_id in _active_vision:
            await interaction.response.send_message("Already processing your submission — please wait.", ephemeral=True)
            return
        _active_vision.add(msg_id)

        # Check for image before deferring — no image = instant response, no loading state
        def _has_image(msg):
            for att in msg.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    return True
                if not att.content_type and any(att.filename.lower().endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    return True
            return False

        has_image = _has_image(self.original_message)

        if not has_image:
            # No image — skip vision entirely, go straight to class select instantly
            _active_vision.discard(msg_id)
            caption = self.original_message.content.strip()
            detected_weapon, detected_subclass = parse_submission_text(caption) if caption else (None, None)
            if detected_weapon or detected_subclass:
                view = ParseConfirmView(self.original_message, self.prompt_msg, detected_weapon, detected_subclass)
                hints = []
                if detected_weapon:   hints.append(f"Weapon: `{detected_weapon}`")
                if detected_subclass: hints.append(f"Class: `{detected_subclass}`")
                await interaction.response.send_message(
                    content="\U0001f4cb I noticed the following in your caption \u2014 does this look right?\n" + "  |  ".join(hints),
                    view=view, ephemeral=True)
            else:
                all_melee_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]])
                view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_melee_classes)
                await interaction.response.send_message(content="Which class were you playing?", view=view, ephemeral=True)
            return

        # Has image — defer so vision API has time to run
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("📋 Reading your scorecard...", ephemeral=True)

        parsed = None
        try:
            print(f"[VISION] Attachments: {[(a.filename, a.content_type) for a in self.original_message.attachments]}")
            for att in self.original_message.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    parsed = await asyncio.to_thread(vision_parse_scorecard, att.url)
                    print(f"[VISION] Raw parsed result: {parsed}")
                    break
                elif not att.content_type:
                    # content_type can be None — fall back to filename extension check
                    if any(att.filename.lower().endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                        parsed = await asyncio.to_thread(vision_parse_scorecard, att.url)
                        print(f"[VISION] Raw parsed result (ext check): {parsed}")
                        break
    
            # Validate parsed fields against known lists and sanity bounds
            if parsed:
                if parsed.get('weapon') not in (list(config.WEAPONS_1H) + list(config.WEAPONS_2H) + list(config.FEAT_WEAPONS)):
                    parsed['weapon'] = None
                if parsed.get('subclass') not in config.CLASS_WEAPON_MAP:
                    parsed['subclass'] = None
                # Normalize vision map names (full display names → our short keys)
                raw_map = parsed.get('map')
                if raw_map and raw_map not in config.MAP_FACTIONS:
                    parsed['map'] = config.MAP_ALIASES.get(raw_map.lower())
                if parsed.get('map') not in config.MAP_FACTIONS:
                    parsed['map'] = None
                if parsed.get('faction') not in ('Agatha', 'Mason', 'Tenosia'):
                    parsed['faction'] = None
                # Sanity bounds on stats — if they look wrong, null them so the modal is blank
                td = parsed.get('takedowns')
                k  = parsed.get('kills')
                d  = parsed.get('deaths')
                if td is not None and (td < 5 or td > 600):
                    parsed['takedowns'] = parsed['kills'] = parsed['deaths'] = None
                elif k is not None and td is not None and k > td:
                    parsed['kills'] = None  # kills can't exceed takedowns
                if d is not None and (d < 0 or d > 100):
                    parsed['deaths'] = None
    
            vision_useful = parsed and any(
                parsed.get(f) is not None
                for f in ('weapon', 'subclass', 'takedowns', 'kills', 'deaths')
            )
    
            if vision_useful:
                view = VisionConfirmView(self.original_message, self.prompt_msg, parsed)
                lines = ["\ud83d\udccb **I read the following from your scorecard:**"]
                if parsed.get('subclass'):              lines.append(f"Class: `{parsed['subclass']}`")
                if parsed.get('weapon'):                lines.append(f"Weapon: `{parsed['weapon']}`")
                if parsed.get('map'):                   lines.append(f"Map: `{parsed['map']}`")
                if parsed.get('faction'):               lines.append(f"Faction: `{parsed['faction']}`")
                if parsed.get('takedowns') is not None: lines.append(f"Takedowns: `{parsed['takedowns']}`")
                if parsed.get('kills') is not None:     lines.append(f"Kills: `{parsed['kills']}`")
                if parsed.get('deaths') is not None:    lines.append(f"Deaths: `{parsed['deaths']}`")
                missing = [f for f in ('subclass', 'weapon', 'map', 'faction', 'takedowns', 'kills', 'deaths') if parsed.get(f) is None]
                if missing:
                    lines.append(f"\n*Could not read: {', '.join(missing)} \u2014 you'll be asked for those next.*")
                await interaction.followup.send(content="\n".join(lines), view=view, ephemeral=True)
            else:
                # Vision got nothing useful \u2014 caption parse then full form
                caption = self.original_message.content.strip()
                detected_weapon, detected_subclass = parse_submission_text(caption) if caption else (None, None)
                if detected_weapon or detected_subclass:
                    view = ParseConfirmView(self.original_message, self.prompt_msg, detected_weapon, detected_subclass)
                    hints = []
                    if detected_weapon:   hints.append(f"Weapon: `{detected_weapon}`")
                    if detected_subclass: hints.append(f"Class: `{detected_subclass}`")
                    await interaction.followup.send(
                        content="\ud83d\udccb I noticed the following in your caption \u2014 does this look right?\n" + "  |  ".join(hints),
                        view=view,
                        ephemeral=True
                    )
                else:
                    all_melee_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]])
                    view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_melee_classes)
                    await interaction.followup.send(content="Which class were you playing?", view=view, ephemeral=True)
        finally:
            _active_vision.discard(msg_id)

    @discord.ui.button(label='Dismiss', style=discord.ButtonStyle.grey, emoji='✖️')
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self.prompt_msg.delete()
        await interaction.response.defer()


class VisionConfirmView(discord.ui.View):
    """
    Shown after a successful vision parse. Confirm sends straight to finalise
    (or the remaining missing-field selects). Each Fix button drops into the
    relevant select for just that field, carrying all other confirmed values.
    """
    def __init__(self, original_message, prompt_msg, parsed: dict):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.parsed = parsed  # keys: weapon, subclass, map, faction, takedowns, kills, deaths, other_scores

    async def on_timeout(self):
        try:
            await self.prompt_msg.edit(
                content="*Submission window expired. Post again to start a new one.*",
                view=None
            )
        except Exception:
            pass
        self.stop()

    def _owner_check(self, interaction):
        return interaction.user.id == self.original_message.author.id

    async def _proceed(self, interaction):
        """Route to whatever is still missing, or straight to finalise."""
        p = self.parsed
        # Work through missing fields in order: subclass → weapon → map → faction → stats
        if not p.get('subclass'):
            all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys()])
            view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_classes,
                                   pre_detected_weapon=p.get('weapon'), vision_data=p)
            await interaction.response.edit_message(content="Which class were you playing?", view=view)
        elif not p.get('weapon'):
            weapons = get_all_weapons_for_class(p['subclass'])
            view = WeaponSelectView(self.original_message, self.prompt_msg, p['subclass'], weapons, vision_data=p)
            await interaction.response.edit_message(content=f"Class: `{p['subclass']}`\nWhich weapon did you use?", view=view)
        elif not p.get('map'):
            view = MapSelectView(self.original_message, self.prompt_msg, p['subclass'], p['weapon'], vision_data=p)
            await interaction.response.edit_message(
                content=f"Class: `{p['subclass']}` | Weapon: `{p['weapon']}`\nWhich map were you on?", view=view)
        elif not p.get('faction'):
            view = FactionSelectView(self.original_message, self.prompt_msg, p['subclass'], p['weapon'], p['map'], vision_data=p)
            await interaction.response.edit_message(
                content=f"Class: `{p['subclass']}` | Weapon: `{p['weapon']}` | Map: `{p['map']}`\nWhich faction?", view=view)
        else:
            # Always show the stats modal as the final step so the player
            # can verify vision's numbers — never auto-submit from vision alone
            await interaction.response.send_modal(
                StatsModal(self.original_message, self.prompt_msg, p['subclass'], p['weapon'], p['map'], p['faction'],
                           prefill_td=p.get('takedowns'), prefill_k=p.get('kills'), prefill_d=p.get('deaths'),
                           vision_data=p)
            )

    @discord.ui.button(label='Confirm', style=discord.ButtonStyle.green, emoji='✅')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_check(interaction):
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self._proceed(interaction)

    @discord.ui.button(label='Fix Class', style=discord.ButtonStyle.grey)
    async def fix_class(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_check(interaction):
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        self.parsed['subclass'] = None
        self.parsed['weapon'] = None  # class change invalidates weapon
        all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys()])
        view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_classes, vision_data=self.parsed)
        await interaction.response.edit_message(content="Which class were you playing?", view=view)

    @discord.ui.button(label='Fix Weapon', style=discord.ButtonStyle.grey)
    async def fix_weapon(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_check(interaction):
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        self.parsed['weapon'] = None
        subclass = self.parsed.get('subclass')
        if subclass:
            weapons = get_all_weapons_for_class(subclass)
            view = WeaponSelectView(self.original_message, self.prompt_msg, subclass, weapons, vision_data=self.parsed)
            await interaction.response.edit_message(
                content=f"Class: `{subclass}`\nWhich weapon did you use?", view=view)
        else:
            all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys()])
            view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_classes, vision_data=self.parsed)
            await interaction.response.edit_message(content="Which class were you playing?", view=view)

    @discord.ui.button(label='Fix Stats', style=discord.ButtonStyle.grey)
    async def fix_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_check(interaction):
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        p = self.parsed
        await interaction.response.send_modal(
            StatsModal(self.original_message, self.prompt_msg,
                       p.get('subclass'), p.get('weapon'), p.get('map'), p.get('faction'),
                       prefill_td=p.get('takedowns'), prefill_k=p.get('kills'), prefill_d=p.get('deaths'),
                       vision_data=p)
        )


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
            view = MapSelectView(self.original_message, self.prompt_msg, subclass, weapon)
            await interaction.response.edit_message(
                content=f"Class: `{subclass}` / Weapon: `{weapon}`. Which map?",
                view=view
            )
        elif weapon:
            # Have weapon, still need class
            category = "2h" if weapon in WEAPONS_2H else "1h"
            classes = get_classes_for_category(category)
            view = ClassSelectView(self.original_message, self.prompt_msg, category, classes, pre_detected_weapon=weapon)
            await interaction.response.edit_message(
                content=f"Weapon: `{weapon}`. Which class were you playing?",
                view=view
            )
        elif subclass:
            # Have class, skip straight to weapon select
            weapons = get_all_weapons_for_class(subclass)
            view = WeaponSelectView(self.original_message, self.prompt_msg, subclass, weapons)
            await interaction.response.edit_message(
                content=f"Class: `{subclass}`. Which weapon?",
                view=view
            )

    @discord.ui.button(label='Change', style=discord.ButtonStyle.grey, emoji='🔄')
    async def change(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        all_melee_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]])
        view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_melee_classes)
        await interaction.response.edit_message(
            content="Which class were you playing?",
            view=view
        )

class WeaponTypeView(discord.ui.View):
    def __init__(self, original_message, prompt_msg):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg

    @discord.ui.button(label='Melee', style=discord.ButtonStyle.blurple, emoji='⚔️')
    async def melee(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        all_melee_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]])
        view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_melee_classes)
        await interaction.response.edit_message(
            content="Which class were you playing?",
            view=view
        )

    @discord.ui.button(label='Ranged', style=discord.ButtonStyle.blurple)
    async def ranged(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        view = MarksmanSubclassView(self.original_message, self.prompt_msg)
        await interaction.response.edit_message(
            content="Class: `Marksman`. Which subclass?",
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
            content=f"Class: `Marksman ({subclass})`. Which weapon?",
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
        options.append(discord.SelectOption(label="Multiple Weapons"))
        super().__init__(placeholder="Choose your weapon...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_weapon = self.values[0]
        view = MapSelectView(self.original_message, self.prompt_msg, f"Marksman ({self.subclass})", selected_weapon)
        await interaction.response.edit_message(
            content=f"Class: `Marksman ({self.subclass})` / Weapon: `{selected_weapon}`. Which map?",
            view=view
        )


def _fuzzy_match(query, options):
    """Return options whose name contains the query (case-insensitive)."""
    q = query.strip().lower()
    return [o for o in options if q in o.lower()]


async def _proceed_weapon(interaction, original_message, prompt_msg, selected_class, selected_weapon, vision_data):
    """Shared logic after a weapon is confirmed."""
    vd = {**vision_data, 'weapon': selected_weapon}
    if vd.get('map') and vd.get('faction'):
        await interaction.response.send_modal(
            StatsModal(original_message, prompt_msg, selected_class, selected_weapon,
                       vd['map'], vd['faction'],
                       prefill_td=vd.get('takedowns'), prefill_k=vd.get('kills'), prefill_d=vd.get('deaths'),
                       vision_data=vd)
        )
    elif vd.get('map'):
        view = FactionSelectView(original_message, prompt_msg, selected_class, selected_weapon, vd['map'], vision_data=vd)
        await interaction.response.edit_message(
            content=f"Class: `{selected_class}` | Weapon: `{selected_weapon}` | Map: `{vd['map']}`. Which faction?",
            view=view
        )
    else:
        view = MapSelectView(original_message, prompt_msg, selected_class, selected_weapon, vision_data=vd)
        await interaction.response.edit_message(
            content=f"Class: `{selected_class}` | Weapon: `{selected_weapon}`. Which map?",
            view=view
        )


class ClassSearchModal(discord.ui.Modal, title="Class Search"):
    query = discord.ui.TextInput(
        label="Type class name",
        placeholder="e.g. Devastator, Long...",
        required=True, max_length=30
    )

    def __init__(self, original_message, prompt_msg, category, classes, pre_detected_weapon=None, vision_data=None):
        super().__init__()
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.category = category
        self.classes = classes
        self.pre_detected_weapon = pre_detected_weapon
        self.vision_data = vision_data or {}

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("Not your submission.", ephemeral=True)
            return
        matches = _fuzzy_match(self.query.value, self.classes)
        if not matches:
            await interaction.response.send_message(
                f"No class matching **{self.query.value}**. Try again.", ephemeral=True)
            return
        if len(matches) == 1:
            selected_class = matches[0]
            vd = {**self.vision_data, 'subclass': selected_class}
            if self.pre_detected_weapon:
                view = MapSelectView(self.original_message, self.prompt_msg, selected_class, self.pre_detected_weapon, vision_data=vd)
                await interaction.response.edit_message(
                    content=f"Class: `{selected_class}` | Weapon: `{self.pre_detected_weapon}`. Which map?", view=view)
            else:
                weapons = get_all_weapons_for_class(selected_class)
                view = WeaponSelectView(self.original_message, self.prompt_msg, selected_class, weapons,
                                        vision_data=vd, all_classes=self.classes, category=self.category)
                await interaction.response.edit_message(
                    content=f"Class: `{selected_class}`. Which weapon?", view=view)
        else:
            view = ClassSelectView(self.original_message, self.prompt_msg, self.category,
                                   matches, self.pre_detected_weapon, self.vision_data)
            await interaction.response.edit_message(
                content=f"Found {len(matches)} matches — pick one:", view=view)


class ClassSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, category, classes, pre_detected_weapon=None, vision_data=None):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.category = category
        self.classes = classes
        self.pre_detected_weapon = pre_detected_weapon
        self.vision_data = vision_data or {}
        if classes:
            CLASS_ORDER = ["Knight", "Vanguard", "Footman", "Archer"]
            sorted_classes = sorted(classes, key=lambda c: (CLASS_ORDER.index(SUBCLASS_PARENT.get(c, "")) if SUBCLASS_PARENT.get(c) in CLASS_ORDER else 99, c))
            options = [discord.SelectOption(label=c, description=SUBCLASS_PARENT.get(c)) for c in sorted_classes[:25]]
            self.add_item(ClassSelect(original_message, prompt_msg, category, classes, pre_detected_weapon, vision_data, options))

    @discord.ui.button(label="Search Class", style=discord.ButtonStyle.blurple, emoji="🔍", row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("Not your submission.", ephemeral=True)
            return
        await interaction.response.send_modal(
            ClassSearchModal(self.original_message, self.prompt_msg, self.category,
                             self.classes, self.pre_detected_weapon, self.vision_data))


class ClassSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, category, classes, pre_detected_weapon=None, vision_data=None, options=None):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.category = category
        self.classes = classes
        self.pre_detected_weapon = pre_detected_weapon
        self.vision_data = vision_data or {}
        if options is None:
            CLASS_ORDER = ["Knight", "Vanguard", "Footman", "Archer"]
            sorted_classes = sorted(classes, key=lambda c: (CLASS_ORDER.index(SUBCLASS_PARENT.get(c, "")) if SUBCLASS_PARENT.get(c) in CLASS_ORDER else 99, c))
            options = [discord.SelectOption(label=c, description=SUBCLASS_PARENT.get(c)) for c in sorted_classes[:25]]
        super().__init__(placeholder="Choose your class...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_class = self.values[0]
        vd = {**self.vision_data, 'subclass': selected_class}
        if self.pre_detected_weapon:
            view = MapSelectView(self.original_message, self.prompt_msg, selected_class, self.pre_detected_weapon, vision_data=vd)
            await interaction.response.edit_message(
                content=f"Class: `{selected_class}` | Weapon: `{self.pre_detected_weapon}`. Which map?", view=view)
        else:
            weapons = get_all_weapons_for_class(selected_class)
            view = WeaponSelectView(self.original_message, self.prompt_msg, selected_class, weapons,
                                    vision_data=vd, all_classes=self.classes, category=self.category)
            await interaction.response.edit_message(
                content=f"Class: `{selected_class}`. Which weapon?", view=view)


class WeaponSearchModal(discord.ui.Modal, title="Weapon Search"):
    query = discord.ui.TextInput(
        label="Type weapon name",
        placeholder="Type any part of the weapon name, e.g. knife, axe...",
        required=True, max_length=30
    )

    def __init__(self, original_message, prompt_msg, selected_class, weapons, vision_data=None, all_classes=None, category="all"):
        super().__init__()
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.weapons = weapons
        self.vision_data = vision_data or {}
        self.all_classes = all_classes or sorted(CLASS_WEAPON_MAP.keys())
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("Not your submission.", ephemeral=True)
            return
        matches = _fuzzy_match(self.query.value, self.weapons)
        if not matches:
            await interaction.response.send_message(
                f"No weapon matching **{self.query.value}**. Try again.", ephemeral=True)
            return
        if len(matches) == 1:
            await _proceed_weapon(interaction, self.original_message, self.prompt_msg,
                                  self.selected_class, matches[0], self.vision_data)
        else:
            view = WeaponSelectView(self.original_message, self.prompt_msg, self.selected_class,
                                    matches, vision_data=self.vision_data,
                                    all_classes=self.all_classes, category=self.category)
            await interaction.response.edit_message(
                content=f"Class: `{self.selected_class}`. Found {len(matches)} matches — pick one:", view=view)


class WeaponSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, weapons, vision_data=None, all_classes=None, category="all"):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.vision_data = vision_data or {}
        self.all_classes = all_classes or sorted(CLASS_WEAPON_MAP.keys())
        self.category = category
        self.weapons = weapons
        if weapons:
            import config as _cfg
            primaries = _cfg._SUBCLASS_PRIMARIES.get(selected_class, set())
            def _opt(w):
                is_secondary = bool(primaries) and w not in primaries
                return discord.SelectOption(label=w, description="⬦ Secondary" if is_secondary else None)
            options = [_opt(w) for w in weapons[:25]]
            self.add_item(WeaponSelect(original_message, prompt_msg, selected_class, weapons, vision_data, options))

    @discord.ui.button(label="Search Weapon", style=discord.ButtonStyle.blurple, emoji="🔍", row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("Not your submission.", ephemeral=True)
            return
        await interaction.response.send_modal(
            WeaponSearchModal(self.original_message, self.prompt_msg, self.selected_class,
                              self.weapons, self.vision_data, self.all_classes, self.category))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey, emoji="◀️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        view = ClassSelectView(self.original_message, self.prompt_msg, self.category, self.all_classes, vision_data=self.vision_data)
        await interaction.response.edit_message(content="Which class were you playing?", view=view)


class WeaponSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, weapons, vision_data=None, options=None):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.vision_data = vision_data or {}
        self.weapons_list = weapons
        if options is None:
            import config as _cfg
            primaries = _cfg._SUBCLASS_PRIMARIES.get(selected_class, set())
            def _opt(w):
                is_secondary = primaries and w not in primaries
                return discord.SelectOption(
                    label=w,
                    description="⬦ Secondary" if is_secondary else None,
                )
            options = [_opt(w) for w in weapons[:25]]
        super().__init__(placeholder="Choose your weapon...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_weapon = self.values[0]
        await _proceed_weapon(interaction, self.original_message, self.prompt_msg,
                              self.selected_class, selected_weapon, self.vision_data)

class MapSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, vision_data=None):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.vision_data = vision_data or {}
        self.add_item(MapSelect(original_message, prompt_msg, selected_class, selected_weapon, vision_data))

    @discord.ui.button(label='Back', style=discord.ButtonStyle.grey, emoji='◀️', row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        weapons = get_all_weapons_for_class(self.selected_class)
        view = WeaponSelectView(self.original_message, self.prompt_msg, self.selected_class, weapons, vision_data=self.vision_data)
        await interaction.response.edit_message(
            content=f"Class: `{self.selected_class}`. Which weapon?",
            view=view
        )

class MapSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, vision_data=None):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.vision_data = vision_data or {}
        options = [discord.SelectOption(label=m) for m in MAPS]
        super().__init__(placeholder="Choose your map...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_map = self.values[0]
        vd = {**self.vision_data, 'map': selected_map}
        # Skip faction step if vision already has it
        if vd.get('faction'):
            await interaction.response.send_modal(
                StatsModal(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
                           selected_map, vd['faction'],
                           prefill_td=vd.get('takedowns'), prefill_k=vd.get('kills'), prefill_d=vd.get('deaths'),
                           vision_data=vd)
            )
        else:
            view = FactionSelectView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, selected_map, vision_data=vd)
            await interaction.response.edit_message(
                content=f"Class: `{self.selected_class}` | Weapon: `{self.selected_weapon}` | Map: `{selected_map}`. Which faction?",
                view=view
            )

class FactionSelectView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, vision_data=None):
        super().__init__(timeout=300)
        self.vision_data = vision_data or {}
        self.add_item(FactionSelect(original_message, prompt_msg, selected_class, selected_weapon, selected_map, vision_data))

class FactionSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, vision_data=None):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.vision_data = vision_data or {}
        options = [discord.SelectOption(label=f) for f in MAP_FACTIONS.get(selected_map, ["Agatha", "Mason", "Tenosia"])]
        super().__init__(placeholder="Choose your faction...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        selected_faction = self.values[0]
        vd = {**self.vision_data, 'faction': selected_faction}
        await interaction.response.send_modal(
            StatsModal(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
                       self.selected_map, selected_faction,
                       prefill_td=vd.get('takedowns'), prefill_k=vd.get('kills'), prefill_d=vd.get('deaths'),
                       vision_data=vd)
        )
        try:
            await interaction.edit_original_response(
                content=f"Class: `{self.selected_class}` | Weapon: `{self.selected_weapon}` | Map: `{self.selected_map}` | Faction: `{selected_faction}`",
                view=None
            )
        except Exception:
            pass

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
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction,
                 prefill_td=None, prefill_k=None, prefill_d=None, vision_data=None):
        super().__init__()
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.selected_class = selected_class
        self.selected_weapon = selected_weapon
        self.selected_map = selected_map
        self.faction = faction
        self.vision_data = vision_data or {}
        self.takedowns = discord.ui.TextInput(
            label="Takedowns", placeholder="e.g. 215", required=True,
            default=str(prefill_td) if prefill_td is not None else discord.utils.MISSING
        )
        self.kills = discord.ui.TextInput(
            label="Kills", placeholder="e.g. 104", required=True,
            default=str(prefill_k) if prefill_k is not None else discord.utils.MISSING
        )
        self.deaths = discord.ui.TextInput(
            label="Deaths", placeholder="e.g. 0", required=True,
            default=str(prefill_d) if prefill_d is not None else discord.utils.MISSING
        )
        self.add_item(self.takedowns)
        self.add_item(self.kills)
        self.add_item(self.deaths)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            takedowns = int(self.takedowns.value)
            kills = int(self.kills.value)
            deaths = int(self.deaths.value)
        except ValueError:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "invalid")
            await interaction.response.send_message(
                "Those aren't numbers. The Butler requires whole numbers.",
                view=view,
                ephemeral=True
            )
            return

        # Sanity checks
        if takedowns < 0 or kills < 0 or deaths < 0:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "negative")
            await interaction.response.send_message(
                "Those numbers aren't possible. Try again.",
                view=view,
                ephemeral=True
            )
            return

        if kills > takedowns:
            view = RetryStatsView(self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon, self.selected_map, self.faction, "kills>td")
            await interaction.response.send_message(
                f"Kills ({kills}) can't exceed takedowns ({takedowns}). Takedowns include kills and assists. Check the scoreboard.",
                view=view,
                ephemeral=True
            )
            return

        # Check 20k score first if potential triple, then VIP if applicable
        needs_vip = (self.selected_map, self.faction) in VIP_MAPS
        if takedowns >= 150 and kills >= 100:
            view = TripleCheckView(
                self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
                self.selected_map, self.faction, takedowns, kills, deaths, needs_vip=needs_vip,
                vision_data=self.vision_data,
            )
            await interaction.response.edit_message(
                content="Score over 20,000 points?",
                view=view
            )
        elif needs_vip:
            view = VIPView(
                self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
                self.selected_map, self.faction, takedowns, kills, deaths,
                vision_data=self.vision_data,
            )
            await interaction.response.edit_message(
                content="Were you VIP this round?",
                view=view
            )
        else:
            await finalise_submission(
                interaction, self.original_message, self.prompt_msg,
                self.selected_class, self.selected_weapon,
                self.selected_map, self.faction, takedowns, kills, deaths, False, False,
                vision_data=self.vision_data,
            )

class VIPView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, score_over_20k=False, vision_data=None):
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
        self.score_over_20k = score_over_20k
        self.vision_data = vision_data or {}

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
        await finalise_submission(
            interaction, self.original_message, self.prompt_msg, self.selected_class,
            self.selected_weapon, self.selected_map, self.faction,
            self.takedowns, self.kills, self.deaths, vip, self.score_over_20k,
            vision_data=self.vision_data,
        )

class TripleCheckView(discord.ui.View):
    def __init__(self, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip=False, needs_vip=False, vision_data=None):
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
        self.needs_vip = needs_vip
        self.vision_data = vision_data or {}

    async def _after_triple_check(self, interaction, score_over_20k):
        if self.needs_vip:
            view = VIPView(
                self.original_message, self.prompt_msg, self.selected_class, self.selected_weapon,
                self.selected_map, self.faction, self.takedowns, self.kills, self.deaths,
                score_over_20k=score_over_20k, vision_data=self.vision_data,
            )
            await interaction.response.edit_message(
                content="Were you VIP this round?",
                view=view
            )
        else:
            await finalise_submission(
                interaction, self.original_message, self.prompt_msg, self.selected_class,
                self.selected_weapon, self.selected_map, self.faction,
                self.takedowns, self.kills, self.deaths, self.vip, score_over_20k,
                vision_data=self.vision_data,
            )

    @discord.ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def score_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self._after_triple_check(interaction, True)

    @discord.ui.button(label='No', style=discord.ButtonStyle.red)
    async def score_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        await self._after_triple_check(interaction, False)


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
            all_melee_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]])
            view = ClassSelectView(ev.original_message, None, "all", all_melee_classes)
            await interaction.response.edit_message(
                content="**Edit weapon:** Which class were you playing?",
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
        f"**Run Submitted** *(edited)*\n"
        f"{ev.author.display_name}\n"
        f"{ev.weapon} • {ev.cls}\n"
        f"{ev.map_name} / {ev.faction}\n"
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


async def _submission_worker(guild_id):
    """Drain the submission queue for a guild, one at a time."""
    queue = get_submission_queue(guild_id)
    while True:
        item = await queue.get()
        interaction = item[0]
        try:
            _, original_message, prompt_msg, args = item
            await asyncio.wait_for(
                _do_finalise_submission(interaction, original_message, prompt_msg, *args),
                timeout=60
            )
        except asyncio.TimeoutError:
            print(f"Submission worker timeout for guild {guild_id}")
            try:
                await interaction.followup.send(
                    "The submission took too long and was dropped. Try again.",
                    ephemeral=True
                )
            except Exception:
                pass
        except Exception as e:
            print(f"Submission worker error: {e}")
        finally:
            _queued_msgs.discard(item[1].id)
            queue.task_done()


async def finalise_submission(interaction, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip, score_over_20k, vision_data=None):
    msg_id = original_message.id
    if msg_id in _queued_msgs:
        await interaction.response.send_message("Already submitting this run — please wait.", ephemeral=True)
        return
    _queued_msgs.add(msg_id)
    guild_id = interaction.guild.id
    queue = get_submission_queue(guild_id)
    vd = vision_data or {}
    args = (selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip, score_over_20k, vd)
    await queue.put((interaction, original_message, prompt_msg, args))
    # Ensure worker is running for this guild
    worker = _submission_workers.get(guild_id)
    if worker is None or worker.done():
        _submission_workers[guild_id] = asyncio.create_task(_submission_worker(guild_id))



async def check_submission_anomaly(guild, player_name, message_link, selected_weapon, selected_map, takedowns, kills):
    """Flag suspicious submissions to butlers-notes if stats exceed 2x any server record."""
    try:
        notes_channel = guild.get_channel(BUTLERS_NOTES_CHANNEL_ID)
        if not notes_channel:
            return

        flags = []

        all_rows = submissions_ws.get_all_values()[1:]

        # Server record: kills
        all_kills = [int(r[8]) for r in all_rows if len(r) > 8 and r[8].strip().lstrip('-').isdigit() and int(r[8]) > 0]
        if all_kills:
            record_kills = max(all_kills)
            if kills > record_kills * 2:
                pct = int(((kills - record_kills) / record_kills) * 100)
                flags.append(f"**Kills:** {kills} — server record is {record_kills} (+{pct}%)")

        # Server record: takedowns
        all_tds = [int(r[7]) for r in all_rows if len(r) > 7 and r[7].strip().lstrip('-').isdigit() and int(r[7]) > 0]
        if all_tds:
            record_tds = max(all_tds)
            if takedowns > record_tds * 2:
                pct = int(((takedowns - record_tds) / record_tds) * 100)
                flags.append(f"**Takedowns:** {takedowns} — server record is {record_tds} (+{pct}%)")

        # Weapon leaderboard: would this be 1st place by 20%+ gap?
        ld_rows = leaderboard_data_ws.get_all_values()[1:]
        weapon_scores = [int(r[3]) for r in ld_rows if r[0] == selected_weapon and len(r) > 3 and r[3].strip().isdigit()]
        if weapon_scores:
            current_best = max(weapon_scores)
            if takedowns > current_best * 1.8:
                pct = int(((takedowns - current_best) / current_best) * 100)
                flags.append(f"**Weapon ({selected_weapon}):** {takedowns} TDs — current #1 is {current_best} (+{pct}%)")

        # Map leaderboard: same check
        map_scores = [int(r[3]) for r in ld_rows if r[0] == selected_map and len(r) > 3 and r[3].strip().isdigit()]
        if map_scores:
            current_best = max(map_scores)
            if takedowns > current_best * 1.8:
                pct = int(((takedowns - current_best) / current_best) * 100)
                flags.append(f"**Map ({selected_map}):** {takedowns} TDs — current #1 is {current_best} (+{pct}%)")

        if flags:
            alert = (
                f"⚠️ **Suspicious submission — {player_name}**\n"
                + "\n".join(flags)
                + f"\n{message_link}"
            )
            await notes_channel.send(alert)

    except Exception as e:
        print(f"Anomaly check error: {e}")


async def _do_finalise_submission(interaction, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip, score_over_20k, vision_data=None):
    # Cross-cog lazy imports to avoid circular dependencies at module load
    from cogs.leaderboards import update_leaderboards, update_leaderboard_index, build_ledger_entrance
    from cogs.bounty import update_bounty, get_active_bounty, check_bounty_completion
    from cogs.registry import (
        create_or_update_registry_card,
        calculate_weapon_marks_for_player,
        update_butlers_archive_row,
        get_weapon_rank,
    )
    from cogs.favourites import calculate_butler_stats, update_title_roles, build_favourites_embed
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

    caption = original_message.content.strip() if original_message.content else ""

    # Compute lobby context from vision team data
    vd = vision_data or {}
    lobby_rank = None
    lobby_size = None
    kills_rank = None
    lobby_line = None

    _team_td = [s for s in vd.get('team_scores', []) if isinstance(s, int) and s > 0]
    _team_k  = [k for k in vd.get('team_kills',  []) if isinstance(k, int) and k > 0]
    _enemy_td = [s for s in vd.get('enemy_scores', []) if isinstance(s, int) and s > 0]
    _enemy_k  = [k for k in vd.get('enemy_kills',  []) if isinstance(k, int) and k > 0]
    _all_td = _team_td + _enemy_td
    _all_k  = _team_k  + _enemy_k

    blurb_parts = []

    # --- Team rank ---
    if _team_td:
        team_rank = sum(1 for s in _team_td if s >= takedowns) + 1
        team_size = len(_team_td) + 1
        if team_rank == 1:
            sorted_team = sorted(_team_td, reverse=True)
            gap = takedowns - sorted_team[0] if sorted_team else 0
            gap_str = f" +{gap} TD" if gap > 0 else ""
            blurb_parts.append(f"1st on team{gap_str}")
        else:
            blurb_parts.append(f"{team_rank}{_ordinal(team_rank)} on team of {team_size}")

    # --- Kill share ---
    total_kills = kills + sum(_all_k) if kills else None
    if total_kills and total_kills > 0 and kills:
        kill_share = round(kills / total_kills * 100, 1)
        blurb_parts.append(f"{kill_share}% kill share")

    # --- Lobby TD rank (for storage + blurb context) ---
    if _all_td:
        lobby_size = len(_all_td) + 1
        lobby_rank = sum(1 for s in _all_td if s >= takedowns) + 1
        pct = round((1 - (lobby_rank - 1) / lobby_size) * 100)
        blurb_parts.append(f"{lobby_rank}{_ordinal(lobby_rank)} of {lobby_size} lobby")

    # --- Kills rank (for storage) ---
    if _all_k and kills:
        kills_rank = sum(1 for k in _all_k if k >= kills) + 1

    # --- Team rank + team score ratio (for Warlord metric) ---
    _team_rank_val = None
    _team_size_val = None
    _total_lobby_kills = None
    _team_score_ratio = None
    if _team_td:
        _team_rank_val = sum(1 for s in _team_td if s >= takedowns) + 1
        _team_size_val = len(_team_td) + 1
        avg_teammate = sum(_team_td) / len(_team_td) if _team_td else None
        if avg_teammate and avg_teammate > 0:
            _team_score_ratio = takedowns / avg_teammate
    if _all_k:
        _total_lobby_kills = (kills or 0) + sum(_all_k)

    if blurb_parts:
        lobby_line = " · ".join(blurb_parts)

    summary = (
        f"**Run Submitted**\n"
        f"{interaction.user.display_name}\n"
        f"{selected_weapon} • {selected_class}\n"
        f"{selected_map} / {faction}\n"
        f"{takedowns} TD / {kills} K / {deaths} D\n"
        f"VIP: {vip_str}"
    )
    if feats_str:
        summary += f"\n{feats_str}"
    if lobby_line:
        summary += f"\n*{lobby_line}*"
    if caption:
        summary += f"\n*{caption}*"

    # Build marks breakdown
    marks_earned = 1
    marks_lines = ["*+1 submission*"]
    if '200 Takedowns' in feats:
        marks_earned += 1
        marks_lines.append(f"*<a:200tkd:1363648828414230538> +1 Takedowns*")
    if '100 Kills' in feats:
        marks_earned += 1
        marks_lines.append(f"*<a:100kill:1361412390339608686> +1 Kills*")
    if 'Triple' in feats:
        marks_earned += 1
        marks_lines.append(f"*<a:triple:1365532698260668466> +1 Triple*")
    marks_summary = f"\n**{marks_earned} mark{'s' if marks_earned != 1 else ''}** on {selected_weapon}\n" + "\n".join(marks_lines)

    message_link = f"https://discord.com/channels/{original_message.guild.id}/{original_message.channel.id}/{original_message.id}"

    await interaction.response.edit_message(content="Noted. The record has been updated.", view=None)

    # Log to Google Sheets first so we get the row index
    submission_row = None
    try:
        is_new_player = log_submission(
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
            message_link,
            lobby_rank=lobby_rank,
            lobby_size=lobby_size,
            kills_rank=kills_rank,
            team_rank=_team_rank_val,
            team_size=_team_size_val,
            total_lobby_kills=_total_lobby_kills,
            team_score_ratio=_team_score_ratio,
        )
        # Row index is last row in submissions sheet
        submission_row = len(submissions_ws.get_all_values())
    except Exception as e:
        is_new_player = False
        print(f"Sheet logging error: {e}")

    # Anomaly check — alert butlers-notes if stats look suspicious
    try:
        await check_submission_anomaly(
            interaction.guild,
            interaction.user.display_name,
            message_link,
            selected_weapon,
            selected_map,
            takedowns,
            kills
        )
    except Exception as e:
        print(f"Anomaly check call error: {e}")

    # Post summary with Edit button
    edit_view = EditSubmissionView(
        original_message, interaction.user,
        submission_row, selected_weapon, selected_class,
        selected_map, faction, takedowns, kills, deaths, vip, feats, message_link
    )
    summary_reply = await original_message.reply(summary + marks_summary, mention_author=False, view=edit_view)
    edit_view._message = summary_reply

    await asyncio.sleep(1)
    try:
        await prompt_msg.delete()
    except discord.NotFound:
        pass

    # React to the original screenshot
    async def safe_react(emoji):
        try:
            await original_message.add_reaction(emoji)
        except Exception as e:
            print(f"Reaction failed ({emoji}): {e}")

    await safe_react("<:cigar:1444893851427803298>")
    if deaths == 0:
        await safe_react("<a:flawless:1360358300834599062>")
    if kills >= 100:
        await safe_react("<a:100kill:1361412390339608686>")
    if takedowns >= 200:
        await safe_react("<a:200tkd:1363648828414230538>")
    if takedowns >= 150 and deaths == 0:
        await safe_react("<a:predator:1366794896081555567>")
    if takedowns >= 150 and kills >= 100 and score_over_20k:
        await safe_react("<a:triple:1365532698260668466>")

    is_ranged = bool(selected_class and selected_class.startswith("Marksman"))

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
            await safe_react("<:weapon_hs:1350656128635375698>")

    # Update leaderboards (skip for ranged submissions)
    any_updated = False
    placements = []
    newly_completed = False
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
        await safe_react("<a:highscore:1360312918545269057>")
        # Write High Score feat back to the Submissions sheet so mark totals count it
        if submission_row:
            try:
                current_feats = submissions_ws.cell(submission_row, 12).value or ''
                if 'High Score' not in current_feats:
                    updated_feats = (current_feats.rstrip(', ') + ', High Score').lstrip(', ')
                    if current_feats in ('', 'None'):
                        updated_feats = 'High Score'
                    submissions_ws.update_cell(submission_row, 12, updated_feats)
                    _sheet_cache.invalidate(submissions_ws)
            except Exception as e:
                print(f"Highscore feat write error: {e}")
        # Edit summary message to show the bonus mark
        try:
            async for msg in original_message.channel.history(limit=10, after=original_message):
                if msg.author == original_message.guild.me and msg.reference and msg.reference.message_id == original_message.id:
                    import re as _re
                    def increment_marks(content):
                        def replacer(m):
                            n = int(m.group(1)) + 1
                            return f"**{n} mark{'s' if n != 1 else ''}**"
                        # Match "**1 mark**" or "**2 marks**" (no + prefix)
                        return _re.sub(r'\*\*(\d+) marks?\*\*', replacer, content)
                    new_content = increment_marks(msg.content) + f"\n<a:highscore:1360312918545269057> +1 High Score"
                    await msg.edit(content=new_content)
                    break
        except Exception as e:
            print(f"Highscore mark edit error: {e}")

    # Bounty check (skip for ranged submissions)
    if not is_ranged:
        try:
            bounty_hit = await update_bounty(
                interaction.guild, selected_weapon,
                interaction.user.display_name, interaction.user.id, takedowns
            )
            print(f"[BOUNTY] bounty_hit={bounty_hit} weapon={selected_weapon} takedowns={takedowns}")
            if bounty_hit:
                await safe_react("🐱")
                # Check if this run completed the bounty
                _bounty = get_active_bounty()
                if _bounty:
                    newly_completed = await check_bounty_completion(
                        interaction.guild, _bounty, interaction.user.display_name, interaction.user.id
                    )
        except Exception as e:
            import traceback
            print(f"Bounty update error: {e}")
            traceback.print_exc()

    # ── BUTLER PERSONALITY HOOKS ─────────────────────────────────────────────
    try:
        main_channel = interaction.guild.get_channel(MAIN_CHANNEL_ID)
        now = datetime.now(timezone.utc)
        player = interaction.user.display_name

        if main_channel:
            # Dry spell — first submission after 4+ hours of silence
            if submission_state['last_submission_time'] and (now - submission_state['last_submission_time']).total_seconds() > 14400:
                line = butler_quip(
                    "The lounge has been dead for hours and someone just submitted a run. "
                    "React as the Butler — one dry line about finally seeing some activity. Vary it each time.",
                    fallback="The lounge stirs. About time."
                )
                await main_channel.send(f"*{line}*")

            # New player first submission
            if is_new_player:
                line = butler_quip(
                    f"A new player named {player} has just submitted their first run. "
                    "Acknowledge them briefly as the Butler — dry, not warm, but not unkind. One sentence.",
                    fallback=f"*A new arrival. The Butler acknowledges you, {player}.*"
                )
                await main_channel.send(line if line.startswith('*') else f"*{line}*")

            # New #1 on any leaderboard
            new_firsts = [lb for lb, pos in placements if pos == 1]
            if new_firsts:
                boards = ", ".join(new_firsts)
                line = butler_quip(
                    f"{player} just took the top spot on the {boards} leaderboard. "
                    "React as the Butler — acknowledge it but add doubt or dry skepticism about how long it lasts. One sentence.",
                    fallback="On top. But for how long."
                )
                await main_channel.send(f"*{line}*")

            # Bounty completion
            if newly_completed:
                line = butler_quip(
                    f"{player} just completed the bounty. React as the Butler — acknowledge it, "
                    "maybe reference the bald woman (Bald Female, a server legend) in comparison. One or two sentences.",
                    fallback=f"The bounty is settled. **{player}** has seen to it."
                )
                await main_channel.send(line)

        # Flawless — reply in submissions channel
        if deaths == 0:
            line = butler_quip(
                f"{player} just submitted a run with 0 deaths on the {selected_weapon}. "
                "React as the Butler — one dry line about a flawless run. Can reference the bald woman's shiny head as a metaphor for perfection. Vary it each time.",
                fallback="*Immaculate. Not a scratch.*"
            )
            await original_message.reply(
                line if line.startswith('*') else f"*{line}*",
                mention_author=False
            )

        submission_state['last_submission_time'] = now
        submission_state['dry_spell_posted'] = False

    except Exception as e:
        print(f"Butler personality error: {e}")

    # Edit the summary reply to include placements
    if placements:
        placement_lines = "\n".join(
            f"{'🏆' if ' - ' in lb else '<:weapon_hs:1350656128635375698>'} {lb} — #{pos}"
            for lb, pos in placements
        )
        try:
            # Find the reply we sent and edit it
            async for msg in original_message.channel.history(limit=10, after=original_message):
                if msg.author == original_message.guild.me and msg.reference and msg.reference.message_id == original_message.id:
                    await msg.edit(content=msg.content + f"\n{placement_lines}")
                    break
        except Exception as e:
            print(f"Placement edit error: {e}")

    # Background tasks — run after confirmation is posted
    _guild = interaction.guild
    _user_id = interaction.user.id
    _user_name = interaction.user.display_name

    async def _bg_tasks():
        # Update registry card
        try:
            await create_or_update_registry_card(_guild, _user_id, _user_name)
        except Exception as e:
            print(f"Registry card update error: {e}")

        # Update bounty cards index
        try:
            bounty = get_active_bounty()
            if bounty:
                bounty_blurb = (
                    f"[{bounty['title']}](https://discord.com/channels/1324379304544567356/1518657579088216217)\n\n"
                    f"A monthly bounty where select weapons qualify toward completion. Submit the required number of runs per weapon to complete the bounty. Often comes with a bonus challenge.\n\n"
                    f"**Weapons & Requirements:**\n" +
                    "\n".join(f"▸ {w}: {d['total']} runs" for w, d in bounty['weapons'].items())
                )
                await update_leaderboard_index(_guild, BOUNTY_CARDS_FORUM_ID, "Bounty Cards", bounty_blurb)
        except Exception as e:
            print(f"Bounty cards index update error: {e}")

        # Refresh ledger entrance after any submission that touched leaderboards
        if any_updated:
            try:
                await build_ledger_entrance(_guild)
            except Exception as e:
                print(f"Ledger entrance refresh error: {e}")

        # Update ButlersArchive summary sheet + milestone detection
        try:
            subs = cached_submissions()
            discord_id_str = str(_user_id)
            player_subs = [r for r in subs if len(r) > 2 and r[2].strip() == discord_id_str]
            submission_count = len(player_subs)
            last_submission = player_subs[-1][0] if player_subs else ''

            # Read OLD weapon marks from Players sheet BEFORE updating — used for milestone diff
            old_flat = {}
            try:
                p_rows = players_ws.get_all_values()
                for p_row in p_rows[1:]:
                    if p_row and p_row[0].strip() == discord_id_str:
                        old_marks_str = p_row[6].strip() if len(p_row) > 6 else ''
                        for part in old_marks_str.split(','):
                            part = part.strip()
                            if ':' in part:
                                w, c = part.rsplit(':', 1)
                                try:
                                    old_flat[w.strip()] = int(c.strip())
                                except ValueError:
                                    pass
                        break
            except Exception as e:
                print(f"Milestone: old marks read error: {e}")

            # Compute new weapon marks
            weapon_marks_data = calculate_weapon_marks_for_player(_user_id)
            flat_marks = {}
            for k, v in weapon_marks_data.items():
                w = k[0] if isinstance(k, tuple) else k
                flat_marks[w] = flat_marks.get(w, 0) + v
            weapon_marks_str = ', '.join(
                f"{w}: {int(v)}" for w, v in sorted(flat_marks.items(), key=lambda x: -x[1]) if v > 0
            ) if flat_marks else ''

            # Class marks summary (count submissions per base class)
            class_counts = {}
            for r in player_subs:
                if len(r) > 4:
                    cls = r[4].strip()
                    base = cls.split('(')[0].strip() if '(' in cls else cls
                    class_counts[base] = class_counts.get(base, 0) + 1
            class_marks_str = ', '.join(f"{c}: {n}" for c, n in sorted(class_counts.items(), key=lambda x: -x[1]))

            total_marks = sum(flat_marks.values()) if flat_marks else 0

            # Thread ID from registry
            reg_rows = registry_ws.get_all_values()[1:]
            thread_id = None
            for r in reg_rows:
                if len(r) > 2 and r[0].strip() == discord_id_str:
                    thread_id = r[2].strip() or None
                    break

            update_butlers_archive_row(
                _user_id, _user_name, thread_id,
                total_marks, submission_count, last_submission,
                weapon_marks_str, class_marks_str
            )

            # ── MILESTONE ANNOUNCEMENTS ───────────────────────────────────
            try:
                is_first_submission = submission_count == 1
                milestones = detect_weapon_milestones(old_flat, flat_marks)
                # Suppress Bronze (threshold 1) unless this is the player's very first submission
                milestones = [(w, t, r) for w, t, r in milestones if t != 1 or is_first_submission]
                if milestones:
                    main_ch = _guild.get_channel(MAIN_CHANNEL_ID) or await _guild.fetch_channel(MAIN_CHANNEL_ID)
                    if main_ch:
                        for weapon, threshold, rank_name in milestones:
                            msg = build_milestone_message(_user_name, weapon, threshold, rank_name)
                            if msg:
                                nerve_log_milestone(_user_name, weapon, rank_name)
                                await main_ch.send(msg)
                                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Milestone announcement error: {e}")

        except Exception as e:
            print(f"ButlersArchive bg update error: {e}")

        # Update Butler's Favourites
        try:
            if BUTLERS_FAVOURITES_CHANNEL_ID:
                fav_channel = _guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
                if fav_channel:
                    _now = datetime.now(timezone.utc)
                    days_since_monday = _now.weekday()
                    week_start_dt = (_now - timedelta(days=days_since_monday)).replace(hour=12, minute=0, second=0, microsecond=0)
                    if week_start_dt > _now:
                        week_start_dt -= timedelta(weeks=1)
                    week_label = f"{week_start_dt.strftime('%b %d')} – {(week_start_dt + timedelta(days=7)).strftime('%b %d')}"
                    stats = calculate_butler_stats(week_start=week_start_dt.timestamp(), week_end=_now.timestamp())
                    stats['week_label'] = week_label
                    embed_text = build_favourites_embed(stats)
                    async for msg in fav_channel.history(limit=5):
                        if msg.author == _guild.me:
                            await msg.edit(content=embed_text)
                            break
                    else:
                        await fav_channel.send(embed_text)
                    await update_title_roles(_guild, stats)
        except Exception as e:
            print(f"Butler favourites update error: {e}")

    asyncio.create_task(_bg_tasks())


_active_vision: set[int] = set()  # prevents double-processing same message
_queued_msgs: set[int] = set()  # prevents same message being finalised twice

class SubmissionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._prompted_messages: set[int] = set()

    @commands.Cog.listener()
    async def on_message(self, message):
        """Trigger submission flow when a player posts an image in the submissions channel."""
        if message.author.bot:
            return
        if message.channel.id != SUBMISSIONS_CHANNEL_ID:
            return
        if message.id in self._prompted_messages:
            return
        self._prompted_messages.add(message.id)
        # Prevent unbounded growth — keep only the last 200 message IDs
        if len(self._prompted_messages) > 200:
            self._prompted_messages = set(list(self._prompted_messages)[-200:])
        # content_type isn't always populated (especially on mobile) — fall back to extension
        _image_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        has_image = any(
            (att.content_type and att.content_type.startswith("image/"))
            or att.filename.lower().endswith(_image_exts)
            for att in message.attachments
        )
        if not has_image:
            return
        view = SubmitView(original_message=message)
        prompt = await message.reply(
            "\U0001f4cb **Submit this run?**",
            view=view,
            mention_author=False,
        )
        view.prompt_msg = prompt


async def setup(bot):
    await bot.add_cog(SubmissionsCog(bot))
