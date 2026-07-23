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
import utils.db as _db
import io
import utils.tilt as _tilt_mod

# ── Submission queue / lock (was in utils.sheets, now local) ──────────────────
_submission_queues: dict  = {}
_submission_workers: dict = {}
# registry-card lock lives in cogs/registry.py

def get_submission_queue(guild_id):
    if guild_id not in _submission_queues:
        _submission_queues[guild_id] = asyncio.Queue()
    return _submission_queues[guild_id]
from utils.helpers import (
    parse_submission_text, format_weapon_marks,
    detect_weapon_milestones, build_milestone_message,
    nerve_log_submission, nerve_log_error, nerve_log_milestone,
    submission_state, butler_quip, vision_parse_scorecard,
    submission_start, submission_end, swallow,
)

# Bounty reactions and blurb links follow the ACTIVE bounty's theme emoji.
# These were hardcoded to the Meowy Massacre cat and kept showing it after the
# bounty rolled over.
_BOUNTY_EMOJI_FALLBACK = "\U0001f3af"  # dart, if a bounty has no emoji set


async def _bounty_emoji():
    """Theme emoji of the active bounty, falling back if there isn't one."""
    try:
        from cogs.bounty import get_active_bounty
        _b = await get_active_bounty()
        return (_b or {}).get('theme_emoji') or _BOUNTY_EMOJI_FALLBACK
    except Exception:
        return _BOUNTY_EMOJI_FALLBACK


def _ordinal(n):
    return {1:'st',2:'nd',3:'rd'}.get(n if n < 20 else n % 10, 'th')

# ── Submission blurb embed ────────────────────────────────────────────────────
# The blurb is a gold embed (same gold as the boards/cards), embed-only — no
# plain-content line (an emoji-only content renders as a giant jumbo emoji).
# All post-hoc edits go through _blurb_desc/_blurb_edit so the string surgery
# keeps working on the embed description.
_BLURB_GOLD = 0xC9A24B

def _blurb_embed(desc, edited=False, thumb=None):
    e = discord.Embed(title="Run Submitted" + (" (edited)" if edited else ""),
                      description=desc, colour=_BLURB_GOLD)
    if thumb:
        e.set_thumbnail(url=thumb)
    return e

def _blurb_desc(msg):
    """Blurb text of a summary message: embed description, or plain content for
    pre-embed-era blurbs (an edit upgrades those to the embed format)."""
    if msg.embeds and msg.embeds[0].description:
        return msg.embeds[0].description
    return msg.content or ''

async def _blurb_edit(msg, desc, edited=False, view=None):
    # content='' clears the plain text (also wipes the old-format blurb text
    # when an edit upgrades a pre-embed message)
    # Keep the lethality-charge thumbnail across edits: the attachment stays on
    # the message (we never pass attachments=[]), so re-referencing its URL keeps
    # it visible; a plain _blurb_embed would drop it.
    _thumb = None
    try:
        if msg.embeds and msg.embeds[0].thumbnail:
            _thumb = msg.embeds[0].thumbnail.url
    except Exception:
        _thumb = None
    kwargs = {'content': '', 'embed': _blurb_embed(desc, edited=edited, thumb=_thumb)}
    if view is not None:
        kwargs['view'] = view
    await msg.edit(**kwargs)


def _link_weapon(weapon, guild_id, lb_thread_map):
    """Hyperlink a weapon name to its leaderboard thread, if one exists."""
    tid = lb_thread_map.get(weapon)
    return f"[{weapon}](https://discord.com/channels/{guild_id}/{tid})" if tid and weapon else (weapon or "")

def _link_map_faction(map_name, faction, guild_id, lb_thread_map):
    """Hyperlink the 'Map / Faction' text to its shared map-board thread, if one exists."""
    tid = lb_thread_map.get(f"{map_name} - {faction}")
    plain = f"{map_name} / {faction}"
    return f"[{plain}](https://discord.com/channels/{guild_id}/{tid})" if tid else plain

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

async def upsert_player(discord_id, discord_name):
    """Returns True if this is a new player."""
    try:
        existing = await _db.get_player(str(discord_id))
        if existing:
            if existing[1] != discord_name:
                await _db.upsert_player(discord_id, discord_name,
                    forum_thread_id=existing[2] or None,
                    total_marks=int(existing[3] or 0),
                    submission_count=int(existing[4] or 0),
                    last_submission=existing[5] or None,
                    weapon_marks=existing[6] or None,
                    class_marks=existing[7] or None,
                )
            return False
        await _db.upsert_player(discord_id, discord_name)
        return True
    except Exception as e:
        print(f"Player upsert error: {e}")
        return False

async def log_submission(discord_name, discord_id, weapon, cls, map_name, faction,
                         takedowns, kills, deaths, vip, feats, message_link,
                         lobby_rank=None, lobby_size=None, kills_rank=None,
                         team_rank=None, team_size=None, total_lobby_kills=None, team_score_ratio=None,
                         team_kill_share=None, team_td_share=None, second_place_td=None, score=None,
                         team_total_kills=None, enemy_total_kills=None):
    from datetime import datetime as _dt, timezone as _tz
    # Naive UTC: submitted_at is TIMESTAMP (no tz), asyncpg rejects aware values
    now = _dt.now(_tz.utc).replace(tzinfo=None)

    # Deduplicate: skip if identical run logged in the last 5 minutes
    try:
        dup_weapon = await _db.check_duplicate_submission(
            str(discord_id), takedowns, kills, deaths, map_name, faction
        )
        if dup_weapon is not None:
            print(f"[DEDUP] Skipping duplicate submission for {discord_name} ({takedowns} TD, {kills}K, {deaths}D)")
            return None, dup_weapon
    except Exception as dedup_err:
        print(f"[DEDUP] Check failed (non-fatal): {dedup_err}")

    feats_str = ", ".join(feats) if feats else "None"
    nerve_log_submission(discord_name, weapon)

    row_id = await _db.add_submission(
        now, discord_name, discord_id, weapon, cls, map_name, faction,
        takedowns, kills, deaths, vip, feats_str, message_link,
        lobby_rank=lobby_rank,
        lobby_size=lobby_size,
        kills_rank=kills_rank,
        team_rank=team_rank,
        team_size=team_size,
        total_lobby_kills=total_lobby_kills,
        team_td_ratio=round(team_score_ratio, 3) if team_score_ratio is not None else None,
        team_kill_share=round(team_kill_share, 1) if team_kill_share is not None else None,
        team_td_share=round(team_td_share, 1) if team_td_share is not None else None,
        second_place_td=second_place_td,
        score=score,
        team_total_kills=team_total_kills,
        enemy_total_kills=enemy_total_kills,
    )
    return row_id, None

class HealingScoreModal(discord.ui.Modal, title="Healing Submission"):
    """Manual score entry for a Healing Horn / Healing Banner run — the in-game
    popup screenshot can't go through scorecard vision, so the player types
    the total."""
    def __init__(self, original_message, board_name, prompt_msg=None, default_score=""):
        super().__init__(title=f"{board_name} Submission")
        self.original_message = original_message
        self.board_name = board_name
        self.prompt_msg = prompt_msg
        self.score_input = discord.ui.TextInput(
            label="Total healing (from the HEALING popup)",
            placeholder="e.g. 903",
            default=default_score,
            required=True,
            max_length=7,
        )
        self.add_item(self.score_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.score_input.value).replace(',', '').replace('+', '').strip()
        try:
            score = int(raw)
        except ValueError:
            await interaction.response.send_message(
                "That doesn't look like a number, sir. Try again.", ephemeral=True)
            return
        if not (1 <= score <= 999999):
            await interaction.response.send_message(
                "A healing total between 1 and 999,999, if you please.", ephemeral=True)
            return
        await interaction.response.defer()

        author = self.original_message.author
        discord_id = str(author.id)
        try:
            player_row = await _db.get_player(discord_id)
        except Exception:
            player_row = None
        player_name = (player_row[1].strip() if player_row and len(player_row) > 1 and player_row[1]
                       else author.display_name)

        from cogs.leaderboards import submit_manual_pb_score
        async with _BOARD_LOCK:
            pos, prev = await submit_manual_pb_score(
                interaction.guild, self.board_name, player_name, discord_id, score,
                self.original_message.jump_url)

        emoji = config.SPECIAL_OPS_EMOJIS.get(self.board_name, "")
        if pos is None:
            emb = discord.Embed(
                colour=0x36393f,
                description=f"The {self.board_name} board isn't set up yet. A mod will need to create it first.")
        elif pos == 'not_improved':
            emb = discord.Embed(
                colour=_BLURB_GOLD,
                description=(f"{emoji} **`{player_name}`** — {score} healing noted, but your "
                             f"standing best is **{prev}**. The board stands."))
        else:
            prev_str = f" *(previous best {prev})*" if prev else ""
            emb = discord.Embed(
                colour=_BLURB_GOLD,
                description=(f"{emoji} **`{player_name}`** — **{score}** healing, "
                             f"**#{pos}** on the {self.board_name} board{prev_str}."))
            try:
                await self.original_message.add_reaction(emoji or "\U0001F3BA")
            except Exception:
                pass

        try:
            if self.prompt_msg:
                await self.prompt_msg.delete()
        except Exception:
            pass
        await interaction.followup.send(embed=emb)


class HealingScoreView(discord.ui.View):
    def __init__(self, original_message, board_name, prompt_msg=None):
        super().__init__(timeout=300)
        self.original_message = original_message
        self.board_name = board_name
        self.prompt_msg = prompt_msg

    async def on_timeout(self):
        try:
            expired_embed = discord.Embed(
                title="Window Expired",
                description=f"Post your screenshot again to open a new {self.board_name} submission.",
                color=0x36393f,
            )
            expired_embed.set_footer(text="Cigar Lounge Butler")
            await self.prompt_msg.edit(content=None, embed=expired_embed, view=None)
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label='Submit Healing Score', style=discord.ButtonStyle.green, emoji='\U0001F3BA')
    async def healing_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message(
                "I'm afraid I can only take instruction from the one who posted this engagement, sir.",
                ephemeral=True)
            return
        # Prefill from the caption if a number rode along, e.g. "banner 1894"
        _txt = re.sub(r'healing|horn|banner', '', self.original_message.content or '', flags=re.I)
        _m = re.search(r'\d[\d,]{0,6}', _txt)
        default_score = _m.group(0).replace(',', '') if _m else ""
        await interaction.response.send_modal(
            HealingScoreModal(self.original_message, self.board_name, self.prompt_msg, default_score))


class SubmitView(discord.ui.View):
    def __init__(self, original_message, prompt_msg=None):
        super().__init__(timeout=180)   # 3 min, then the ignored prompt self-deletes
        self.original_message = original_message
        self.prompt_msg = prompt_msg

    async def on_timeout(self):
        # Ephemeral isn't possible for a message-triggered prompt, so the next
        # best thing: an ABANDONED prompt cleans itself up instead of lingering.
        # (A clicked prompt is already deleted in the finalise path.)
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
        # Prevent double-processing if user clicks twice or Discord replays the interaction
        msg_id = self.original_message.id
        if msg_id in _active_vision:
            await interaction.response.send_message("Already processing your submission — please wait.", ephemeral=True)
            return
        _active_vision.add(msg_id)
        # In-flight counter for the SIGTERM drain. Every exit path below must
        # hit submission_end() (no-image early return + the vision finally).
        submission_start()

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
            submission_end()
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
                all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]] + ["Archer"])
                view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_classes)
                await interaction.response.send_message(content="Which class were you playing?", view=view, ephemeral=True)
            return

        # Has image — defer so vision API has time to run
        await interaction.response.defer(ephemeral=True)
        _reading_msg = await interaction.followup.send("📋 Reading your scorecard...", ephemeral=True, wait=True)

        parsed = None
        try:
            print(f"[VISION] Attachments: {[(a.filename, a.content_type) for a in self.original_message.attachments]}")
            player_display_name = self.original_message.author.display_name
            stored_igns = []
            # Use stored IGNs as hint if available (more reliable than Discord name)
            try:
                stored_igns = await _db.get_player_igns(self.original_message.author.id) or []
                if stored_igns:
                    # Pass all known aliases; Discord name appended as last resort
                    vision_name_hint = ', '.join(stored_igns + [player_display_name])
                else:
                    vision_name_hint = player_display_name
            except Exception:
                vision_name_hint = player_display_name
            # Roster of OTHER players' names — lets the vision safety net fire its corrective
            # re-read ONLY on a genuine wrong-row (read name belongs to someone else), not on
            # an unregistered in-game name.
            try:
                _n2id = await _db.get_name_to_id_map()
                _uid = str(self.original_message.author.id)
                vision_other_names = [nm for nm, _i in _n2id.items() if str(_i) != _uid]
            except Exception:
                vision_other_names = []
            for att in self.original_message.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    parsed = await asyncio.to_thread(vision_parse_scorecard, att.url, vision_name_hint, vision_other_names)
                    print(f"[VISION] Raw parsed result: {parsed}")
                    break
                elif not att.content_type:
                    # content_type can be None — fall back to filename extension check
                    if any(att.filename.lower().endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                        parsed = await asyncio.to_thread(vision_parse_scorecard, att.url, vision_name_hint, vision_other_names)
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

                # Self-check: compare the read takedowns against the rest of the
                # lobby (arrays we already parsed). A value far above everyone else
                # is usually an OCR digit error — flag it (never auto-change).
                parsed['_stat_warn'] = None
                try:
                    _others = [s for s in (list(parsed.get('team_scores') or [])
                                           + list(parsed.get('enemy_scores') or []))
                               if isinstance(s, int) and s > 0]
                    _td = parsed.get('takedowns')
                    if _others and _td is not None:
                        _hi = max(_others)
                        if _td > 250 and _td > _hi * 2.5:
                            parsed['_stat_warn'] = (
                                f"Takedowns `{_td}` is far above the rest of the lobby "
                                f"(next highest ~{_hi}) — double-check it's not a misread.")
                except Exception as _e:
                    swallow(_e, "stat-warn anomaly check")

                # Name-match guard: if the identified row's name doesn't match the
                # submitter (Discord name or a known IGN), warn — this is how a
                # shared clan tag lets vision grab a teammate's row.
                parsed['_name_warn'] = None
                try:
                    from difflib import SequenceMatcher as _SM
                    _read = re.sub(r'[^a-z0-9]', '', (parsed.get('name') or '').lower())
                    _known = [re.sub(r'[^a-z0-9]', '', (n or '').lower())
                              for n in ([player_display_name] + list(stored_igns or []))]
                    _known = [k for k in _known if len(k) >= 2]
                    # Substring OR fuzzy match. A new IGN is only learned AFTER this run
                    # finalises, so a first-time IGN can never be in _known — pure substring
                    # matching scolded people for spelling their own name slightly differently
                    # ("Hikuta" vs "xHikura", "Massive Σggplant" vs "Massive Eggplant").
                    # 0.6 separates real variants (>=0.67 observed) from teammate rows (<=0.46).
                    _matched = any(
                        k in _read or _read in k or _SM(None, _read, k).ratio() >= 0.6
                        for k in _known)
                    if _read and _known and not _matched:
                        # Not an accusation: an unrecognised IGN is the NORMAL first
                        # submission for anyone whose in-game name differs from Discord.
                        parsed['_name_warn'] = (
                            f"I don't recognise **{parsed.get('name')}** as one of your names. "
                            f"If that's you, hit Confirm and I'll remember it for next time. "
                            f"If it's a teammate's row, fix it before confirming.")
                except Exception as _ne:
                    print(f"[VISION] name-match guard error: {_ne}")
    
            # Caption keyword prefill: vision usually can't read weapon/subclass, so
            # if the player typed them in the caption (e.g. "Poleman Halberd") use
            # those to fill the gaps. Vision-read values always win; the caption
            # only fills fields vision left blank.
            _caption_text = self.original_message.content.strip()
            if _caption_text and parsed:
                _cap_weapon, _cap_subclass = parse_submission_text(_caption_text)
                if parsed.get('weapon') is None and _cap_weapon:
                    parsed['weapon'] = _cap_weapon
                    print(f"[CAPTION] weapon prefilled from caption: {_cap_weapon}")
                if parsed.get('subclass') is None and _cap_subclass:
                    parsed['subclass'] = _cap_subclass
                    print(f"[CAPTION] subclass prefilled from caption: {_cap_subclass}")

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
                if parsed.get('_name_warn'):
                    lines.append(f"\nℹ️ {parsed['_name_warn']}")
                if parsed.get('_stat_warn'):
                    lines.append(f"\n⚠️ {parsed['_stat_warn']}")
                # Weapon/class are never printed on the scoreboard \u2014 asking for
                # them is the NORMAL next step, not a vision miss. "Could not
                # read" is reserved for fields vision genuinely should have got.
                _real_missing = [f for f in ('map', 'faction', 'takedowns', 'kills', 'deaths')
                                 if parsed.get(f) is None]
                _need_pick = [('class' if f == 'subclass' else f)
                              for f in ('subclass', 'weapon') if parsed.get(f) is None]
                if _real_missing:
                    _suffix = f", along with your {' and '.join(_need_pick)}" if _need_pick else ""
                    lines.append(f"\n*Could not read: {', '.join(_real_missing)} \u2014 "
                                 f"you'll be asked for {'those' if len(_real_missing) > 1 else 'that'} next{_suffix}.*")
                elif _need_pick:
                    lines.append(f"\n*Next: pick your {' and '.join(_need_pick)}.*")
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
                    all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]] + ["Archer"])
                    view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_classes)
                    await interaction.followup.send(content="Which class were you playing?", view=view, ephemeral=True)
        finally:
            # Remove the "Reading your scorecard..." ephemeral now that the result
            # card / picker has been sent — it otherwise lingers on screen.
            try:
                await _reading_msg.delete()
            except Exception:
                pass
            _active_vision.discard(msg_id)
            submission_end()

    @discord.ui.button(label='Dismiss', style=discord.ButtonStyle.grey, emoji='✖️')
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        try:
            await self.prompt_msg.delete()
        except Exception:
            pass
        try:
            await interaction.response.defer()
            await interaction.delete_original_response()
        except Exception:
            try:
                await interaction.response.edit_message(content="​", embed=None, view=None)
            except Exception:
                pass


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
        # A Hybrid run has no single weapon: fill it so the weapon step is skipped.
        if str(p.get('subclass') or '').strip() == 'Hybrid' and not p.get('weapon'):
            p['weapon'] = 'Hybrid'
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
            td = p.get('takedowns')
            kills = p.get('kills')
            deaths = p.get('deaths')
            if td is not None and kills is not None and deaths is not None:
                # Vision already read the stats and user clicked Confirm — route through
                # VIP/triple checks then finalise, same as StatsModal does
                needs_vip = (p['map'], p['faction']) in VIP_MAPS
                if td >= 150 and kills >= 100:
                    view = TripleCheckView(
                        self.original_message, self.prompt_msg, p['subclass'], p['weapon'],
                        p['map'], p['faction'], td, kills, deaths, needs_vip=needs_vip,
                        vision_data=p,
                    )
                    await interaction.response.edit_message(content="Score over 20,000 points?", view=view)
                elif needs_vip:
                    view = VIPView(
                        self.original_message, self.prompt_msg, p['subclass'], p['weapon'],
                        p['map'], p['faction'], td, kills, deaths, vision_data=p,
                    )
                    await interaction.response.edit_message(content="Were you VIP this round?", view=view)
                else:
                    await finalise_submission(
                        interaction, self.original_message, self.prompt_msg,
                        p['subclass'], p['weapon'], p['map'], p['faction'],
                        td, kills, deaths, vip=False, score_over_20k=False, vision_data=p
                    )
            else:
                # Stats missing — show modal so user can enter them
                await interaction.response.send_modal(
                    StatsModal(self.original_message, self.prompt_msg, p['subclass'], p['weapon'], p['map'], p['faction'],
                               prefill_td=td, prefill_k=kills, prefill_d=deaths,
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

    @discord.ui.button(label='Fix Numbers', style=discord.ButtonStyle.grey)
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


    @discord.ui.button(label='Fix Map', style=discord.ButtonStyle.grey, row=1)
    async def fix_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_check(interaction):
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        self.parsed['map'] = None
        self.parsed['faction'] = None  # a map change invalidates the faction
        p = self.parsed
        view = MapSelectView(self.original_message, self.prompt_msg, p.get('subclass'), p.get('weapon'), vision_data=p)
        await interaction.response.edit_message(
            content=f"Class: `{p.get('subclass')}` | Weapon: `{p.get('weapon')}`\nWhich map were you on?", view=view)

    @discord.ui.button(label='Fix Team', style=discord.ButtonStyle.grey, row=1)
    async def fix_faction(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_check(interaction):
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        self.parsed['faction'] = None
        p = self.parsed
        if not p.get('map'):
            view = MapSelectView(self.original_message, self.prompt_msg, p.get('subclass'), p.get('weapon'), vision_data=p)
            await interaction.response.edit_message(content="Which map were you on?", view=view)
            return
        view = FactionSelectView(self.original_message, self.prompt_msg, p.get('subclass'), p.get('weapon'), p['map'], vision_data=p)
        await interaction.response.edit_message(
            content=f"Class: `{p.get('subclass')}` | Weapon: `{p.get('weapon')}` | Map: `{p['map']}`\nWhich team?", view=view)



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
        all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]] + ["Archer"])
        view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_classes)
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
        all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]] + ["Archer"])
        view = ClassSelectView(self.original_message, self.prompt_msg, "all", all_classes)
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
    def __init__(self, original_message, prompt_msg, vision_data=None):
        super().__init__(timeout=300)
        self.add_item(MarksmanSubclassSelect(original_message, prompt_msg, vision_data=vision_data))

class MarksmanSubclassSelect(discord.ui.Select):
    def __init__(self, original_message, prompt_msg, vision_data=None):
        self.original_message = original_message
        self.prompt_msg = prompt_msg
        self.vision_data = vision_data or {}
        options = [discord.SelectOption(label=s, description=SUBCLASS_PARENT.get(s)) for s in MARKSMAN_SUBCLASSES.keys()]
        super().__init__(placeholder="Choose your subclass...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_message.author.id:
            await interaction.response.send_message("I'm afraid I can only take instruction from the one who posted this engagement, sir.", ephemeral=True)
            return
        subclass = self.values[0]
        vd = {**self.vision_data, "subclass": subclass}
        weapons = get_all_weapons_for_class(subclass)
        all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]] + ["Archer"])
        view = WeaponSelectView(self.original_message, self.prompt_msg, subclass, weapons, vision_data=vd, all_classes=all_classes)
        await interaction.response.edit_message(
            content=f"Class: `Archer ({subclass})`. Which weapon?",
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
    vd = {**vision_data, 'subclass': selected_class, 'weapon': selected_weapon}
    if vd.get('map') and vd.get('faction'):
        # All fields confirmed — return to VisionConfirmView so user can review before final submit
        view = VisionConfirmView(original_message, prompt_msg, vd)
        td, k, d = vd.get('takedowns','?'), vd.get('kills','?'), vd.get('deaths','?')
        await interaction.response.edit_message(
            content=f"✅ `{selected_class}` · `{selected_weapon}` · `{vd['map']}` · `{vd['faction']}` · TD:`{td}` K:`{k}` D:`{d}`\nLooks right? Hit **Confirm** to submit.",
            view=view
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
        _pool = list(self.classes)
        if self.category == "all" and not self.pre_detected_weapon and "Hybrid" not in _pool:
            _pool.append("Hybrid")
        matches = _fuzzy_match(self.query.value, _pool)
        if not matches:
            await interaction.response.send_message(
                f"No class matching **{self.query.value}**. Try again.", ephemeral=True)
            return
        if len(matches) == 1:
            selected_class = matches[0]
            vd = {**self.vision_data, 'subclass': selected_class}
            if selected_class == "Hybrid":
                vd['subclass'] = "Hybrid"
                view = MapSelectView(self.original_message, self.prompt_msg, "Hybrid", "Hybrid", vision_data=vd)
                await interaction.response.edit_message(
                    content="Class: `Hybrid` (weapon swap). Which map?", view=view)
                return
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
            options = [discord.SelectOption(label=c, description=SUBCLASS_PARENT.get(c)) for c in sorted_classes[:24]]
            # Hybrid: weapon-swap games. Only on the top-level picker ("all"), and
            # only when a weapon isn't already locked in.
            if category == "all" and not pre_detected_weapon:
                options.append(discord.SelectOption(
                    label="Hybrid", description="Swapped weapons — no single one", emoji="🔀"))
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
        if selected_class == "Hybrid":
            # No weapon to pick — a Hybrid run isn't tied to one. Store weapon and
            # subclass both as "Hybrid" and go straight to the map.
            vd['subclass'] = "Hybrid"
            view = MapSelectView(self.original_message, self.prompt_msg, "Hybrid", "Hybrid", vision_data=vd)
            await interaction.response.edit_message(
                content="Class: `Hybrid` (weapon swap). Which map?", view=view)
            return
        if self.pre_detected_weapon:
            view = MapSelectView(self.original_message, self.prompt_msg, selected_class, self.pre_detected_weapon, vision_data=vd)
            await interaction.response.edit_message(
                content=f"Class: `{selected_class}` | Weapon: `{self.pre_detected_weapon}`. Which map?", view=view)
        else:
            if selected_class == "Archer":
                view = MarksmanSubclassView(self.original_message, self.prompt_msg, vision_data=vd)
                await interaction.response.edit_message(content="Which Archer subclass?", view=view)
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
        # If vision already has faction, return to review screen instead of firing StatsModal directly
        if vd.get('faction'):
            view = VisionConfirmView(self.original_message, self.prompt_msg, vd)
            td, k, d = vd.get('takedowns','?'), vd.get('kills','?'), vd.get('deaths','?')
            await interaction.response.edit_message(
                content=f"✅ `{self.selected_class}` · `{self.selected_weapon}` · `{selected_map}` · `{vd['faction']}` · TD:`{td}` K:`{k}` D:`{d}`\nLooks right? Hit **Confirm** to submit.",
                view=view
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
        view = VisionConfirmView(self.original_message, self.prompt_msg, vd)
        td, k, d = vd.get('takedowns','?'), vd.get('kills','?'), vd.get('deaths','?')
        await interaction.response.edit_message(
            content=f"✅ `{self.selected_class}` · `{self.selected_weapon}` · `{self.selected_map}` · `{selected_faction}` · TD:`{td}` K:`{k}` D:`{d}`\nLooks right? Hit **Confirm** to submit.",
            view=view
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
                 weapon, cls, map_name, faction, takedowns, kills, deaths, vip, feats, message_link,
                 second_place_td=None, score=None):
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
        self.second_place_td = second_place_td
        self.score = score

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
            discord.SelectOption(label="Triple (score 20k+)", value="triple"),
        ]
        super().__init__(placeholder="Choose a field to edit...", options=options)

    async def callback(self, interaction: discord.Interaction):
        field = self.values[0]
        ev = self.edit_view

        if field == "weapon":
            all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]] + ["Archer"])
            view = ClassSelectView(ev.original_message, None, "all", all_classes)
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
        elif field == "triple":
            view = EditTripleView(ev)
            await interaction.response.edit_message(
                content="**Edit Triple:** Was your score over 20,000? (only counts with 150+ TD & 100+ kills)",
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
        # MAP_FACTIONS values are lists
        factions = MAP_FACTIONS.get(edit_view.map_name) or ["Agatha", "Mason", "Tenosia"]
        options = [discord.SelectOption(label=f) for f in factions]
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


def _recompute_triple_feats(ev, score_over_20k):
    """Re-derive Triple / 100 Kills / 200 Takedowns on ev.feats using the SAME rule as a
    fresh submission (Triple = 150+ TD, 100+ kills, and score over 20k). All other feats
    (Predator, Flawless, Pacifist, …) are left untouched."""
    feats = [f for f in (ev.feats or []) if f not in ("Triple", "100 Kills", "200 Takedowns")]
    if ev.takedowns >= 150 and ev.kills >= 100 and score_over_20k:
        feats.append("Triple")
    else:
        if ev.kills >= 100:
            feats.append("100 Kills")
        if ev.takedowns >= 200:
            feats.append("200 Takedowns")
    ev.feats = feats


class EditTripleView(discord.ui.View):
    def __init__(self, edit_view):
        super().__init__(timeout=300)
        self.edit_view = edit_view

    @discord.ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        _recompute_triple_feats(self.edit_view, True)
        await _apply_edit(interaction, self.edit_view)

    @discord.ui.button(label='No', style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        _recompute_triple_feats(self.edit_view, False)
        await _apply_edit(interaction, self.edit_view)




async def _apply_edit(interaction, ev):
    """Write the updated submission back to the DB and update the summary message."""
    # Ack immediately — the board propagation below can take several seconds, which
    # blows past Discord's 3s interaction window and makes the edit show "error".
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass

    # Recompute stat-derived feats from the EDITED numbers. Stats edits used to
    # leave ev.feats frozen at submit-time values, so a corrected 200/100 run
    # kept no feat lines, wrong marks, and a stale DB feats column. Non-stat
    # tags survive; a prior confirmed Triple survives while stats still qualify.
    try:
        _old_f = ev.feats if isinstance(ev.feats, list) else \
            [f.strip() for f in str(ev.feats or '').split(',') if f.strip() and f.strip() != 'None']
        # 'Brutal' is a lobby constant (banner totals), not stat-derived — survives edits
        _KEEP = {'Resubmit', 'Unlisted', 'High Score', 'Brutal', 'Outmatched', 'Uphill'}
        _nf = [f for f in _old_f if f in _KEEP]
        _was_triple = 'Triple' in _old_f
        _sc = ev.score if isinstance(ev.score, int) else None
        _is_triple = (ev.takedowns >= 150 and ev.kills >= 100
                      and (_was_triple or (_sc is not None and _sc >= 20000)))
        if _is_triple:
            _nf.append('Triple')
        else:
            if ev.kills >= 100:
                _nf.append('100 Kills')
            if ev.takedowns >= 200:
                _nf.append('200 Takedowns')
        if ev.deaths == 0 and ev.takedowns > 0 and not (ev.kills == 0 and ev.takedowns <= 10):
            _nf.append('Flawless')
        if ev.takedowns >= 150 and ev.deaths == 0:
            _nf.append('Predator')
        if ev.weapon in FEAT_WEAPONS and ev.kills >= 100:
            _nf.append(ev.weapon)
        ev.feats = _nf
    except Exception as _e_rf:
        print(f"[EDIT] feat recompute error: {_e_rf}")

    # Capture the PRE-EDIT weapon/map before we overwrite the row, so the edit can
    # clear their now-stale board entries below (an edit that changes weapon must
    # drop the old weapon's board row + mark, not just add the new one).
    _old_weapon = None
    _old_map_board = None
    _edit_placements = []
    _team_total = None   # lobby constant, re-derived from old kills / old kill-share
    try:
        _row = await _db.get_submission_by_link(ev.message_link)
        if _row:
            _old_weapon = (_row[0] or '').strip() or None
            _om = (_row[1] or '').strip(); _of = (_row[2] or '').strip()
            _old_map_board = f"{_om} - {_of}" if _om and _of else None
            try:
                _ok, _oks = _row[3], _row[4]
                if _ok and _oks and _oks > 0:
                    _team_total = round(int(_ok) / (_oks / 100.0))
            except (ValueError, TypeError) as _e:
                swallow(_e, "edit team-total re-derive")
    except Exception as _e_old:
        print(f"[EDIT] pre-edit lookup error: {_e_old}")
    try:
        if ev.submission_row:
            feats_str = ", ".join(ev.feats) if ev.feats else "None"
            _new_tks = None
            if _team_total and ev.kills:
                _tks_candidate = round(ev.kills / _team_total * 100, 1)
                if 0 < _tks_candidate <= 100:
                    _new_tks = _tks_candidate
            await _db.update_submission_fields(
                ev.submission_row,
                ev.weapon, ev.cls, ev.map_name, ev.faction,
                ev.takedowns, ev.kills, ev.deaths, ev.vip, feats_str,
                team_kill_share=_new_tks,
            )
    except Exception as e:
        print(f"Edit DB update error: {e}")

    # Propagate the edit to the leaderboards. Previously an edit only rewrote the
    # summary + card, so the boards kept the pre-edit score (e.g. a mis-parsed map
    # left the wrong map board updated and the corrected one untouched).
    # Fix: wipe this run's board entries by link (clears stale weapon/map/feat
    # placements), re-run update_leaderboards with the corrected values, then
    # rebuild the affected weapon/map boards for this player so another of their
    # runs reclaims the slot if this run moved off a board.
    try:
        from cogs.leaderboards import update_leaderboards, rebuild_score_boards
        _edit_guild = ev.original_message.guild
        async with _BOARD_LOCK:
            _old_boards = await _db.delete_leaderboard_entries_by_link(ev.message_link)
            # rebuild_score_boards is additive (never drops a stale row) and delete-by-link
            # can miss if the row's link differs, so ALSO clear this player's entries on the
            # pre-edit weapon/map boards explicitly, keyed by discord_id.
            _extra_old = set()
            _old_kills = f"{_old_weapon} Kills" if (_old_weapon and not ev.vip) else None
            for _ob in ((None if ev.vip else _old_weapon), _old_kills, _old_map_board):
                if _ob:
                    try:
                        await _db.delete_leaderboard_entries_by_board_and_discord(_ob, str(ev.author.id))
                        _extra_old.add(_ob)
                    except Exception as _e_clr:
                        print(f"[EDIT] old-board clear error ({_ob}): {_e_clr}")
            try:
                _edit_any, _edit_placements = await update_leaderboards(
                    interaction, ev.weapon, ev.map_name, ev.faction,
                    ev.takedowns, ev.kills, ev.deaths, ev.vip, (ev.feats or []),
                    ev.author.display_name, ev.message_link,
                    second_place_td=ev.second_place_td, score=ev.score,
                )
            except Exception as _e_upd:
                print(f"[EDIT] update_leaderboards error: {_e_upd}")
            _new_boards = {b for b in (None if ev.vip else ev.weapon,
                                       None if ev.vip else f"{ev.weapon} Kills",
                                       f"{ev.map_name} - {ev.faction}") if b}
            _affected = set(_old_boards) | _new_boards | _extra_old
            if _affected:
                await rebuild_score_boards(
                    _edit_guild, board_names=list(_affected), only_player=str(ev.author.id))
    except Exception as e:
        print(f"[EDIT] board propagation error: {e}")

    # Reconcile the scorecard's reactions with the EDITED stats. They only ever
    # fired at submit time, so a corrected run kept the old stats' reactions and
    # never gained the ones the new stats earn.
    try:
        _msg = ev.original_message
        _pac = (ev.kills == 0 and ev.takedowns <= 10)
        _feats_l = ev.feats if isinstance(ev.feats, list) else []
        _want = {"<:cigar:1444893851427803298>"}
        if ev.deaths == 0 and ev.takedowns > 0 and not _pac:
            _want.add("<a:flawless:1360358300834599062>")
        if "Triple" in _feats_l:
            _want.add("<a:triple:1365532698260668466>")
        if ev.kills >= 100:
            _want.add("<a:100kill:1361412390339608686>")
        if ev.takedowns >= 200:
            _want.add("<a:200tkd:1363648828414230538>")
        if ev.takedowns >= 150 and ev.deaths == 0:
            _want.add("<a:predator:1366794896081555567>")
        if any(lb == "TUFF" for lb, _ in _edit_placements):
            _want.add("<a:TUFF2:1520779243879927898>")
        if any(lb in (ev.weapon, f"{ev.weapon} Kills", f"{ev.map_name} - {ev.faction}")
               for lb, _ in _edit_placements):
            _want.add("<a:highscore:1360312918545269057>")
        if any(lb == "Pacifist" for lb, _ in _edit_placements):
            _want.add("<a:passive:1365531248268673086>")
        # Only stat-driven reacts are ever REMOVED; cigar/bounty/others are safe.
        _removable = {"<a:flawless:1360358300834599062>", "<a:triple:1365532698260668466>",
                      "<a:100kill:1361412390339608686>", "<a:200tkd:1363648828414230538>",
                      "<a:predator:1366794896081555567>"}
        _fresh_msg = await _msg.channel.fetch_message(_msg.id)
        _have = {str(r.emoji) for r in _fresh_msg.reactions if r.me}
        for _e in _want - _have:
            try:
                await _msg.add_reaction(_e)
                await asyncio.sleep(0.25)
            except Exception:
                pass
        for _e in (_have & _removable) - _want:
            try:
                await _msg.remove_reaction(_e, interaction.client.user)
                await asyncio.sleep(0.25)
            except Exception:
                pass
    except Exception as _e_rx:
        print(f"[EDIT] reaction reconcile error: {_e_rx}")

    # Recompute marks + refresh the registry card so the edit actually propagates.
    # Previously the edit only rewrote the summary message, leaving the card and
    # cached mark totals stale (e.g. a class edit didn't move the mark).
    try:
        from cogs.registry import create_or_update_registry_card
        await create_or_update_registry_card(
            ev.original_message.guild, ev.author.id, ev.author.display_name)
    except Exception as e:
        print(f"Edit card refresh error: {e}")

    # Rebuild summary
    _edit_player_row = await _db.get_player(str(ev.author.id))
    _edit_thread_id = _edit_player_row[2] if _edit_player_row and _edit_player_row[2] else None
    _edit_guild_id = ev.original_message.guild.id
    _edit_name = (
        f"[{ev.author.display_name}](https://discord.com/channels/{_edit_guild_id}/{_edit_thread_id})"
        if _edit_thread_id else ev.author.display_name
    )
    _feats = ev.feats if isinstance(ev.feats, list) else ([f.strip() for f in str(ev.feats).split(',')] if ev.feats and str(ev.feats) != 'None' else [])
    # --- Full blurb rebuild: identical to a fresh submission (fields + marks + TUFF + trailer). ---
    _FEAT_EMOJI = {
        "100 Kills": "<a:100kill:1361412390339608686>", "200 Takedowns": "<a:200tkd:1363648828414230538>",
        "Triple": "<a:triple:1365532698260668466>", "TUFF": "<a:TUFF2:1520779243879927898>",
        "Flawless": "<a:flawless:1360358300834599062>", "Mallet": "🔨", "Knife": "🗡️",
        "Hybrid": "🔀",
    }
    _lb_tmap = {}
    try:
        from cogs.leaderboards import _get_lb_records as _lb_gr, _board_jump_path as _bjp2
        _lb_tmap = {r['Leaderboard Name']: _bjp2(r) for r in await _lb_gr() if r.get('Thread ID')}
    except Exception as _e:
        swallow(_e, "edit blurb board-links")
    _gid = ev.original_message.guild.id
    _placed = {lb for lb, _ in _edit_placements}
    def _blink(board, text):
        _tid = _lb_tmap.get(board)
        return f"[{text}](https://discord.com/channels/{_gid}/{_tid})" if _tid else text
    def _rlink(board, pos):
        _tid = _lb_tmap.get(board)
        return f"[#{pos}](https://discord.com/channels/{_gid}/{_tid})" if _tid else f"#{pos}"
    _wpn_disp = _blink(ev.weapon, ev.weapon) if ev.weapon in _placed else ev.weapon
    _mapboard = f"{ev.map_name} - {ev.faction}"
    _mapfac = _blink(_mapboard, f"{ev.map_name} / {ev.faction}") if _mapboard in _placed else f"{ev.map_name} / {ev.faction}"
    # "(edited)" lives in the embed title, not the description
    new_summary = (
        f"│ {_edit_name}\n"
        f"│ {_wpn_disp} • {ev.cls}\n"
        f"│ {_mapfac}\n"
        f"│ {ev.takedowns} TD / {ev.kills} K / {ev.deaths} D\n"
        f"│ VIP: {'Yes' if ev.vip else 'No'}"
    )
    # Rebuild the stats block (it used to vanish on every edit): Kill Share and
    # Warlord recomputed from the re-derived team total, Lethality from the new
    # stats, and the lobby tilt line carried over verbatim from the old blurb
    # (the lobby's kill totals are constants no stat edit can change).
    _stat_lines = []
    try:
        if _team_total and ev.kills and ev.takedowns:
            _ks = round(ev.kills / _team_total * 100, 1)
            _wl = round(ev.takedowns / _team_total * 100, 1)
            if _ks <= 100 and _wl <= 100:
                _stat_lines.append(f"<a:mostlethal:1520490418817601658> {_ks}% Kill Share")
                _stat_lines.append(f"<:warlord:1520490364039860347> {_wl}% Warlord")
        if ev.kills is not None and ev.takedowns:
            _el = round(ev.kills / ev.takedowns * 100, 1)
            _el_line = f"🩸 {_el}% Lethality"
            try:
                _ewavg, _ewn = await _db.get_weapon_avg_lethality(ev.weapon)
                if _ewavg is not None:
                    _ediff = _el - _ewavg
                    if _ediff >= getattr(config, 'LETHALITY_BLURB_MIN_DELTA', 5.0):
                        _el_line += f"  ·  {_ediff:+.1f} vs {ev.weapon} avg"
            except Exception as _ele:
                print(f"[LETHALITY] edit weapon-avg lookup failed: {_ele}")
            _stat_lines.append(_el_line)
        try:
            _cur_msg = await ev._message.channel.fetch_message(ev._message.id)
            _cur_desc = _blurb_desc(_cur_msg)
        except Exception:
            _cur_desc = _blurb_desc(ev._message)
        _tl = re.search(r'\*((?:🍼|🟢|🟡|🟠|🔴)[^*\n]*lobby[^*\n]*)\*', _cur_desc or '')
        if _tl:
            _stat_lines.append(_tl.group(1))
    except Exception as _e_sb:
        print(f"[EDIT] stats block rebuild error: {_e_sb}")
    if _stat_lines:
        new_summary += "\n\n" + "\n".join(f"*{s}*" for s in _stat_lines)

    # Bounty progress line. Rebuilt here rather than carried over, so an edit that
    # moves the run off a bounty weapon (or under the TD floor) correctly drops it.
    # Mirrors the gate in update_bounty: bounty weapon, 100+ TD, not a resubmit.
    try:
        from cogs.bounty import get_active_bounty, get_player_bounty_progress
        _eb = await get_active_bounty()
        _eb_ok = (
            _eb
            and 'Resubmit' not in (_feats or [])
            and (ev.takedowns or 0) >= 100
            and any((ev.weapon or '').strip().lower() == str(k).strip().lower()
                    for k in (_eb.get('weapons') or {}))
        )
        if _eb_ok:
            _epbr = await get_player_bounty_progress(_eb['title'], str(ev.author.id))
            _efp = _epbr.get('forum_post_id') if _epbr else None
            if _efp:
                _eemoji = _eb.get('theme_emoji') or _BOUNTY_EMOJI_FALLBACK
                new_summary += (
                    f"\n\n{_eemoji} [+1 {_eb['title']}]"
                    f"(https://discord.com/channels/{_edit_guild_id}/{_efp})"
                )
    except Exception as _ebe:
        print(f"[EDIT] bounty line rebuild error: {_ebe}")

    _is_pac = (ev.kills == 0 and ev.takedowns <= 10)
    _me = 0 if _is_pac else 1
    _ml = [] if _is_pac else ["<:cigar:1444893851427803298> *+1 Submission*"]
    if '200 Takedowns' in _feats:
        _me += 1
        _tp = next((p for lb, p in _edit_placements if lb == "200 Takedowns"), None)
        _ml.append(f"*<a:200tkd:1363648828414230538> +1{(' — ' + _rlink('200 Takedowns', _tp)) if _tp else ''}*")
    if '100 Kills' in _feats:
        _me += 1
        _kp = next((p for lb, p in _edit_placements if lb == "100 Kills"), None)
        _ml.append(f"*<a:100kill:1361412390339608686> +1{(' — ' + _rlink('100 Kills', _kp)) if _kp else ''}*")
    if 'Triple' in _feats: _me += 1; _ml.append("*<a:triple:1365532698260668466> +1 Triple*")
    for _dlo, _dnm, _dem, _dmk, _dtg in config.TILT_BANDS:
        if _dtg and _dtg in _feats:
            _me += _dmk; _ml.append(f"*{_dem} +{_dmk} {_dnm} lobby*"); break
    if 'High Score' in _feats: _me += 1; _ml.append("<a:highscore:1360312918545269057> +1 High Score")
    if _is_pac:
        new_summary += f"\n\n<a:passive:1365531248268673086> **Pacifist run** on {ev.weapon}."
    else:
        new_summary += f"\n\n**{_me} Mark{'s' if _me != 1 else ''}** on {ev.weapon}\n" + "\n".join(_ml)
    if ev.kills is not None and ev.second_place_td is not None and ev.kills > ev.second_place_td:
        new_summary += f"\n<a:TUFF2:1520779243879927898> **TUFF** +{ev.kills - ev.second_place_td}"
    def _pline(lb, pos):
        _nm = _blink(lb, lb)
        if ' - ' in lb:
            return f"🏆 {_nm} — #{pos}"
        if lb == "TUFF":
            return f"{_FEAT_EMOJI['TUFF']} — #{pos}"
        if lb in _FEAT_EMOJI:
            return f"{_FEAT_EMOJI[lb]} {lb} — #{pos}"
        return f"<:weapon_hs:1350656128635375698> {_nm} — #{pos}"
    _shown = [(lb, pos) for lb, pos in _edit_placements if lb not in _FEAT_EMOJI]
    if _shown:
        new_summary += "\n" + "\n".join(_pline(lb, pos) for lb, pos in _shown)

    try:
        # Keep the SAME edit view attached so the Edit button stays live — users can
        # correct more than one field, one per click (previously view=None killed it
        # after a single edit, so map-then-nothing-else was all you got).
        await _blurb_edit(ev._message, new_summary, edited=True, view=ev)
    except Exception:
        pass

    try:
        await interaction.followup.send("✅ Updated! You can hit **✏️ Edit** again to fix another field.", ephemeral=True)
    except Exception:
        pass


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
            try:
                from utils.helpers import nerve_alert
                await nerve_alert(interaction.client, "submission worker", e)
            except Exception:
                pass
        finally:
            _queued_msgs.discard(item[1].id)
            queue.task_done()


async def finalise_submission(interaction, original_message, prompt_msg, selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip, score_over_20k, vision_data=None):
    msg_id = original_message.id
    if msg_id in _queued_msgs:
        await interaction.response.send_message("Already submitting this run — please wait.", ephemeral=True)
        return
    _queued_msgs.add(msg_id)
    # Acknowledge the interaction immediately so Discord doesn't show "This interaction failed"
    # while the submission worker processes the run (Google Sheets calls can take 2-5 seconds).
    if not interaction.response.is_done():
        try:
            await interaction.response.defer()
        except Exception as _defer_err:
            print(f"[FINALISE] Defer failed (continuing anyway): {_defer_err}")
    guild_id = interaction.guild.id
    queue = get_submission_queue(guild_id)
    vd = vision_data or {}
    args = (selected_class, selected_weapon, selected_map, faction, takedowns, kills, deaths, vip, score_over_20k, vd)
    await queue.put((interaction, original_message, prompt_msg, args))
    # Ensure worker is running for this guild
    worker = _submission_workers.get(guild_id)
    if worker is None or worker.done():
        _submission_workers[guild_id] = asyncio.create_task(_submission_worker(guild_id))



async def check_submission_anomaly(guild, player_name, message_link, selected_weapon, selected_map, faction, takedowns, kills):
    """Flag suspicious submissions to the nerve centre if stats exceed 2x any server record."""
    try:
        notes_channel = guild.get_channel(config.NERVE_CENTER_CHANNEL_ID) or await guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID)
        if not notes_channel:
            return

        flags = []

        # Server records via SQL MAX instead of scanning every submission.
        record_kills, record_tds = await _db.get_submission_record_maxes()

        # Server record: kills
        if record_kills > 0 and kills > record_kills * 2:
            pct = int(((kills - record_kills) / record_kills) * 100)
            flags.append(f"**Kills:** {kills} — server record is {record_kills} (+{pct}%)")

        # Server record: takedowns
        if record_tds > 0 and takedowns > record_tds * 2:
            pct = int(((takedowns - record_tds) / record_tds) * 100)
            flags.append(f"**Takedowns:** {takedowns} — server record is {record_tds} (+{pct}%)")

        # Weapon leaderboard: would this be 1st place by 20%+ gap?
        _wboard = await _db.get_leaderboard_by_board(selected_weapon)
        weapon_scores = [int(r[3]) for r in _wboard if r[0] == selected_weapon and len(r) > 3 and r[3].strip().isdigit()]
        if weapon_scores:
            current_best = max(weapon_scores)
            if takedowns > current_best * 1.8:
                pct = int(((takedowns - current_best) / current_best) * 100)
                flags.append(f"**Weapon ({selected_weapon}):** {takedowns} TDs — current #1 is {current_best} (+{pct}%)")

        # Map leaderboard: same check (map boards are named "{map} - {faction}")
        _map_board = f"{selected_map} - {faction}"
        _mboard = await _db.get_leaderboard_by_board(_map_board)
        map_scores = [int(r[3]) for r in _mboard if len(r) > 3 and r[3].strip().isdigit()]
        if map_scores:
            current_best = max(map_scores)
            if takedowns > current_best * 1.8:
                pct = int(((takedowns - current_best) / current_best) * 100)
                flags.append(f"**Map ({_map_board}):** {takedowns} TDs — current #1 is {current_best} (+{pct}%)")

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
    # Guard: weapon or class is None means the form flow was incomplete (vision failed and user
    # bypassed selection somehow). Abort cleanly rather than logging a None entry to the sheet.
    if not selected_weapon or not selected_class:
        print(f"[FINALISE] Missing weapon/class — routing back to picker for {interaction.user.display_name}")
        try:
            vd = vision_data or {}
            all_classes = sorted([c for c in CLASS_WEAPON_MAP.keys() if c not in ["Longbowman", "Crossbowman", "Skirmisher"]] + ["Archer"])
            if selected_class and not selected_weapon:
                # Have class, need weapon
                weapons = get_all_weapons_for_class(selected_class)
                view = WeaponSelectView(original_message, prompt_msg, selected_class, weapons, vision_data=vd)
                await interaction.edit_original_response(
                    content=f"Class: `{selected_class}` — which weapon were you using?",
                    view=view
                )
            else:
                # Need class (and possibly weapon)
                view = ClassSelectView(original_message, prompt_msg, "all", all_classes, vision_data=vd)
                await interaction.edit_original_response(
                    content="Vision couldn't read your class — which were you playing?",
                    view=view
                )
        except Exception as e:
            print(f"[FINALISE] Picker reroute failed: {e}")
        return
    # Cross-cog lazy imports to avoid circular dependencies at module load
    from cogs.leaderboards import update_leaderboards, update_leaderboard_index, build_ledger_entrance, refresh_hundred_handed_board as _refresh_hundred_handed_board
    from cogs.bounty import update_bounty, get_active_bounty, check_bounty_completion
    from cogs.registry import (
        create_or_update_registry_card,
        calculate_weapon_marks_for_player,
        update_butlers_archive_row,
        get_weapon_rank,
    )
    from cogs.favourites import calculate_butler_stats, update_title_roles, build_favourites_embed
    feats = []
    _score = (vision_data or {}).get('score')
    if not isinstance(_score, int):
        _score = None
    is_triple = takedowns >= 150 and kills >= 100 and (score_over_20k or (_score is not None and _score >= 20000))
    # Flag to nerve centre when a Triple was self-confirmed (manual "20k+?" -> yes) but the
    # scorecard vision read a score UNDER 20k — a possible inflated claim worth a look.
    if is_triple and score_over_20k and _score is not None and _score < 20000:
        try:
            _nc = original_message.guild.get_channel(config.NERVE_CENTER_CHANNEL_ID) \
                  or await original_message.guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID)
            if _nc:
                _mlink = f"https://discord.com/channels/{original_message.guild.id}/{original_message.channel.id}/{original_message.id}"
                await _nc.send(
                    f"\u26a0\ufe0f **Triple score mismatch \u2014 {interaction.user.display_name}**\n"
                    f"Confirmed 20k+ manually, but the scorecard vision read **{_score:,}** "
                    f"({selected_weapon}, {takedowns} TD / {kills} K). Worth a look.\n{_mlink}"
                )
        except Exception as _e_tm:
            print(f"[TRIPLE] score-mismatch flag error: {_e_tm}")

    # Vision-correction feedback: log to nerve centre every field the submitter changed
    # away from what vision originally read. Shows where vision misfires (recurring field
    # misreads) and possible fakery (suspicious number bumps). Only fields vision actually
    # read are compared, so routine manual-fills of blanks don't spam.
    try:
        _vd = vision_data or {}
        _corr = []
        def _txt(label, vis, final):
            if vis is None:
                return
            vs = str(vis).strip()
            if vs and vs.lower() != str(final).strip().lower():
                _corr.append(f"{label} {vs}\u2192{final}")
        _txt("weapon", _vd.get('weapon'), selected_weapon)
        _txt("class", _vd.get('subclass'), selected_class)
        _txt("faction", _vd.get('faction'), faction)
        _txt("TD", _vd.get('takedowns'), takedowns)
        _txt("K", _vd.get('kills'), kills)
        _txt("D", _vd.get('deaths'), deaths)
        _vmap = (_vd.get('map') or '').strip()
        if _vmap:
            _vmap_norm = config.MAP_ALIASES.get(_vmap.lower(), _vmap)
            if selected_map and selected_map.lower() not in _vmap.lower() and _vmap_norm.lower() != selected_map.lower():
                _corr.append(f"map {_vmap}\u2192{selected_map}")
        if _corr:
            print(f"[VISION] correction: {interaction.user.display_name}: " + ", ".join(_corr))
            _ncc = original_message.guild.get_channel(config.NERVE_CENTER_CHANNEL_ID) \
                   or await original_message.guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID)
            if _ncc:
                _mlc = f"https://discord.com/channels/{original_message.guild.id}/{original_message.channel.id}/{original_message.id}"
                await _ncc.send(f"\u270f\ufe0f **Vision corrections \u2014 {interaction.user.display_name}**: "
                                + ", ".join(_corr) + f"\n{_mlc}")
    except Exception as _e_corr:
        print(f"[CORRECTIONS] feedback log error: {_e_corr}")
    if is_triple:
        feats.append("Triple")
    else:
        # Only credit 100 Kills / 200 Takedowns on non-Triple games
        if kills >= 100:
            feats.append("100 Kills")
        if takedowns >= 200:
            feats.append("200 Takedowns")
    if deaths == 0 and takedowns > 0 and not (kills == 0 and takedowns <= 10):
        feats.append("Flawless")
    if takedowns >= 150 and deaths == 0:
        feats.append("Predator")
    if selected_weapon in FEAT_WEAPONS and kills >= 100:
        feats.append(selected_weapon)

    # ── Instant acknowledgment ────────────────────────────────────────────────
    # Fire the stat-based reactions on the scorecard FIRST — before the blurb,
    # any DB write, and all leaderboard/card work — so the player gets immediate
    # feedback. These depend only on the stats already confirmed. safe_react is
    # defined here (outer scope) so the deferred result reactions can reuse it.
    async def safe_react(emoji):
        try:
            await original_message.add_reaction(emoji)
        except Exception as e:
            print(f"Reaction failed ({emoji}): {e}")

    # Every result reaction lands in ONE burst rather than trickling in. Some are
    # known immediately (flawless, triple) and some only after the DB write and
    # board lookups (high score, TUFF, bounty), so the early ones are held until
    # the late ones are decided, then all fire together. The cigar still goes out
    # first and on its own: it is the "received you" signal, not a result.
    _pending_reacts = []
    _react_tasks = []

    def react_later(emoji):
        if emoji and emoji not in _pending_reacts:
            _pending_reacts.append(emoji)

    def flush_reacts():
        if not _pending_reacts:
            return
        _batch = list(_pending_reacts)
        _pending_reacts.clear()
        # gather() schedules immediately and returns a future; do NOT wrap it in
        # create_task (that expects a coroutine and raises TypeError).
        _react_tasks.append(
            asyncio.gather(*(safe_react(e) for e in _batch), return_exceptions=True))

    await safe_react("<:cigar:1444893851427803298>")
    _rest_reacts = []
    if deaths == 0 and takedowns > 0 and not (kills == 0 and takedowns <= 10):
        _rest_reacts.append("<a:flawless:1360358300834599062>")
    if is_triple:
        _rest_reacts.append("<a:triple:1365532698260668466>")
    if kills >= 100:
        _rest_reacts.append("<a:100kill:1361412390339608686>")
    if takedowns >= 200:
        _rest_reacts.append("<a:200tkd:1363648828414230538>")
    if takedowns >= 150 and deaths == 0:
        _rest_reacts.append("<a:predator:1366794896081555567>")
    for _e in _rest_reacts:
        react_later(_e)

    # High-lethality sticker: reply with the configured sticker when kills/TD is exceptional.
    try:
        if kills is not None and takedowns and takedowns > 0 and \
           (kills / takedowns * 100) >= getattr(config, 'LETHALITY_STICKER_THRESHOLD', 60):
            _sname = getattr(config, 'LETHALITY_STICKER_NAME', '') or ''
            if _sname:
                _sg = original_message.guild
                _stk = discord.utils.get(_sg.stickers, name=_sname)
                if _stk is None:
                    try:
                        _stk = discord.utils.get(await _sg.fetch_stickers(), name=_sname)
                    except Exception:
                        _stk = None
                if _stk:
                    await original_message.reply(stickers=[_stk], mention_author=False)
    except Exception as _e_stk:
        print(f"[STICKER] high-lethality sticker error: {_e_stk}")

    # "Died a lot" sticker: reply when a run's deaths reach the configured threshold.
    try:
        if deaths is not None and deaths >= getattr(config, 'DEATHS_STICKER_THRESHOLD', 30):
            _dname = getattr(config, 'DEATHS_STICKER_NAME', '') or ''
            if _dname:
                _dg = original_message.guild
                _dstk = discord.utils.get(_dg.stickers, name=_dname)
                if _dstk is None:
                    try:
                        _dstk = discord.utils.get(await _dg.fetch_stickers(), name=_dname)
                    except Exception:
                        _dstk = None
                if _dstk:
                    await original_message.reply(stickers=[_dstk], mention_author=False)
    except Exception as _e_dstk:
        print(f"[STICKER] high-deaths sticker error: {_e_dstk}")

    # Clear the "Scorecard detected" prompt in the background (never blocks).
    async def _cleanup_prompt():
        try:
            await asyncio.sleep(1)
            await prompt_msg.delete()
        except (discord.NotFound, AttributeError):
            pass
        except Exception as _pe:
            print(f"Prompt delete error: {_pe}")
    if prompt_msg:
        asyncio.create_task(_cleanup_prompt())

    vip_str = "Yes" if vip else "No"
    is_ranged = bool(selected_class and selected_class.startswith("Marksman"))

    caption = original_message.content.strip() if original_message.content else ""

    # Tag resubmissions so they're excluded from weekly stats. Accept common
    # short forms as whole words: resubmit, resub, resubmission, re-sub, re-submit.
    if re.search(r'\bre[-\s]?sub(mit|mission)?\b', caption.lower()):
        feats.append("Resubmit")

    feats_str = ", ".join(feats) if feats else None

    # Compute lobby context from vision team data
    vd = vision_data or {}
    lobby_rank = None
    lobby_size = None
    kills_rank = None
    lobby_line = None

    # Upper bound 600: vision sometimes reads the SCORE column (4-5 digit values)
    # into these arrays; no single-game TD or kill count gets near 600, so bigger
    # values are column bleed and would poison team rank and the TUFF gap.
    _TDMAX = 600
    _team_td = [s for s in vd.get('team_scores', []) if isinstance(s, int) and 0 < s <= _TDMAX]
    # Vision sometimes folds the submitter's OWN row into team_scores. Drop one instance
    # of the submitter's own takedowns so a self-value can't skew team rank, teammate
    # averages, or the TUFF gap (kills - best teammate TD).
    if isinstance(takedowns, int) and takedowns in _team_td:
        _team_td.remove(takedowns)

    def _strip_bleed_spikes(vals, label=""):
        # Column bleed: vision reads a SCORE-column value (e.g. a bottom player's
        # "300") as a takedown. A real bleed is an ISOLATED spike — far above even
        # the next-highest player. Drop the top value only if it exceeds the
        # next-highest by more than 2.5x AND clears 200 (no legit single-game TD
        # sits that high while the runner-up is <2/5 of it). Compare to the NEXT
        # value, NOT the median: scoreboards are right-skewed (a few 80-140 stars,
        # many 0-30 players), so a median comparison flags legit clustered stars as
        # spikes — which invented false TUFFs (C10H15N's 90/88/85 were real).
        vals = sorted(vals, reverse=True)
        while len(vals) >= 2 and vals[0] > 200 and vals[0] > 2.5 * vals[1]:
            _bad = vals.pop(0)
            print(f"[VISION] Dropped {label} bleed spike {_bad} (next-highest {vals[0]})")
        return vals
    _team_td = _strip_bleed_spikes(_team_td, "team_td")
    _team_k  = [k for k in vd.get('team_kills',  []) if isinstance(k, int) and 0 < k <= _TDMAX]
    _enemy_td = [s for s in vd.get('enemy_scores', []) if isinstance(s, int) and 0 < s <= _TDMAX]
    _enemy_k  = [k for k in vd.get('enemy_kills',  []) if isinstance(k, int) and 0 < k <= _TDMAX]
    _all_td = _team_td + _enemy_td
    _all_k  = _team_k  + _enemy_k

    # Team total kills = denominator for Warlord/Kill Share. Prefer the faction's
    # TOTAL kill count read off the top of the scoreboard (robust, and it includes
    # players who left mid-match); fall back to summing the visible teammate rows.
    _vd_team_total = vd.get('team_total_kills')
    if isinstance(_vd_team_total, int) and _vd_team_total > 0:
        total_team_kills = _vd_team_total
    elif _team_k and kills:
        total_team_kills = kills + sum(_team_k)
    else:
        total_team_kills = None
    # Sanity guard: a player's kills and takedowns are both subsets of their
    # team's total kills, so a total below either means the faction banner was
    # cropped or misread (this produced a 171% Kill Share / 368% Warlord blurb).
    # Try the visible-row sum instead; if that's also below the floor, drop the
    # team-share stats for this run rather than post impossible numbers.
    _stat_floor = max(kills or 0, takedowns or 0)
    if total_team_kills is not None and total_team_kills < _stat_floor:
        _row_sum = (kills + sum(_team_k)) if (_team_k and kills) else None
        total_team_kills = _row_sum if (_row_sum and _row_sum >= _stat_floor) else None
        print(f"[TEAMSTATS] banner total below player stats — "
              f"{'using row sum' if total_team_kills else 'dropping team shares'} "
              f"(kills={kills}, td={takedowns})")

    blurb_parts = []

    # --- Team rank (tracked for storage) ---
    if _team_td:
        team_rank = sum(1 for s in _team_td if s >= takedowns) + 1
        team_size = len(_team_td) + 1

    # --- Warlord (takedowns / team total kills) + Kill Share (kills / team total kills), this game ---
    if total_team_kills and kills and takedowns and takedowns > 0:
        _warlord_g = round(takedowns / total_team_kills * 100, 1)
        _exec_g = round(kills / total_team_kills * 100, 1)
        blurb_parts.append(f"<a:mostlethal:1520490418817601658> {_exec_g}% Kill Share")
        blurb_parts.append(f"<:warlord:1520490364039860347> {_warlord_g}% Warlord")

    # --- Lethality (kills / takedowns) — kill conversion, this game (own emoji: Kill Share took the red skull) ---
    # Pacifist runs are support play: a 0.0% Lethality line is noise, not a stat
    _leth_delta = None  # this run's lethality minus the weapon avg; feeds the blurb weapon-charge thumbnail
    if (kills is not None and takedowns and takedowns > 0
            and not (kills == 0 and takedowns <= 10)):
        _leth_g = round(kills / takedowns * 100, 1)
        _leth_line = f"🩸 {_leth_g}% Lethality"
        # Weapon-relative context (Llama's Lethality Score): how this run did vs
        # the weapon's average. Skipped for thin-sample weapons and Hybrid (no
        # single weapon) — get_weapon_avg_lethality returns None there.
        try:
            _wavg, _wn = await _db.get_weapon_avg_lethality(selected_weapon)
            if _wavg is not None:
                _diff = _leth_g - _wavg
                _leth_delta = _diff
                # Only celebrate standout runs — well ABOVE the weapon's average.
                # Below-average and near-average just show raw lethality (no
                # calling people out for an off game).
                if _diff >= getattr(config, 'LETHALITY_BLURB_MIN_DELTA', 5.0):
                    _leth_line += f"  ·  {_diff:+.1f} vs {selected_weapon} avg"
        except Exception as _le:
            print(f"[LETHALITY] weapon-avg lookup failed: {_le}")
        blurb_parts.append(_leth_line)

    # --- Lobby tilt: orientation-adjusted difficulty marker from banner totals ---
    # Raw kill gap conflates lobby balance with your role (attack farms kills,
    # defence doesn't), so we subtract the role baseline before banding. The blurb
    # still shows the raw, verifiable gap; the label + valor come off the adjusted
    # band. utils/tilt.py is the single source both this and the mark calc read.
    _tilt = None            # raw kill-gap %, shown in the blurb
    _tilt_band = None       # adjusted band dict: name / emoji / marks / tag
    _ett = vd.get('enemy_total_kills')
    _raw = _tilt_mod.raw_tilt(_vd_team_total, _ett)
    if _raw is not None:
        _tilt = _raw
        _orient = _tilt_mod.orientation(vd.get('map'), vd.get('faction'))
        _adj = _tilt_mod.adjusted(_raw, vd.get('map'), vd.get('faction'))
        _tilt_band = _tilt_mod.band(_adj)
        _osfx = {'Attack': ' · atk', 'Defense': ' · def'}.get(_orient, '')
        blurb_parts.append(f"{_tilt_band['emoji']} {_tilt_band['name']} lobby ({_tilt:+d}%{_osfx})")
        # Difficulty valor: the hard tail earns tiered marks (Slightly Uphill +1,
        # Outmatched +2, Brutal +3), tagged on the feats column so the mark math
        # and edits see it. Pacifist-ish runs (0 K / <=10 TD) earn nothing.
        _dtag = _tilt_band.get('tag')
        if _dtag and _tilt_band['marks'] > 0 and not (kills == 0 and takedowns <= 10):
            feats.append(_dtag)
            feats_str = ", ".join(feats) if feats else None

    # Tilt reaction/sticker: mock the stomp (a receiving-end valor react was
    # considered and parked — see the 2026-07-15 idea thread if it resurfaces)
    try:
        _tilt_sticker = None
        if _tilt_band is not None and _tilt_band['name'] == 'Training Grounds':
            await safe_react('🍼')
            _tilt_sticker = getattr(config, 'STOMP_STICKER_NAME', '') or ''
        if _tilt_sticker:
            _tg = original_message.guild
            _tstk = discord.utils.get(_tg.stickers, name=_tilt_sticker)
            if _tstk is None:
                try:
                    _tstk = discord.utils.get(await _tg.fetch_stickers(), name=_tilt_sticker)
                except Exception:
                    _tstk = None
            if _tstk:
                await original_message.reply(stickers=[_tstk], mention_author=False)
    except Exception as _e_tilt:
        print(f"[TILT] lobby-tilt react/sticker error: {_e_tilt}")


    # --- Lobby TD rank (tracked for stats, not shown in blurb) ---
    if _all_td:
        lobby_size = len(_all_td) + 1
        lobby_rank = sum(1 for s in _all_td if s >= takedowns) + 1

    # --- Kills rank (for storage) ---
    if _all_k and kills:
        kills_rank = sum(1 for k in _all_k if k >= kills) + 1

    # --- Team rank + team score ratio (for Warlord metric) ---
    _team_rank_val = None
    _team_size_val = None
    _total_lobby_kills = None
    _team_score_ratio = None
    _team_kill_share = None
    _team_td_share = None
    if _team_td:
        _team_rank_val = sum(1 for s in _team_td if s >= takedowns) + 1
        _team_size_val = len(_team_td) + 1
        avg_teammate = sum(_team_td) / len(_team_td) if _team_td else None
        if avg_teammate and avg_teammate > 0:
            _team_score_ratio = takedowns / avg_teammate
        total_team_td = takedowns + sum(_team_td)
        if total_team_td > 0:
            _team_td_share = round(takedowns / total_team_td * 100, 1)
    if _all_k:
        _total_lobby_kills = (kills or 0) + sum(_all_k)
    if total_team_kills and kills:
        _team_kill_share = round(kills / total_team_kills * 100, 1)

    # TUFF: gap between player kills and best teammate's takedowns (kills - best_teammate_TD).
    # Documented rule (challenge-rules embed): "you score TUFF when your kills beat your
    # best teammate's takedowns" — the board tracks the +N margin.
    _second_place_td = None
    if _team_td:
        _second_place_td = sorted(_team_td, reverse=True)[0]
    # Log the computation so TUFF outcomes are visible in the logs — board updates
    # themselves aren't logged, which made "is TUFF working?" impossible to answer.
    if _second_place_td is not None and kills is not None:
        _tuff_gap = kills - _second_place_td
        print(f"[TUFF] {interaction.user.display_name}: kills={kills} "
              f"best_teammate_td={_second_place_td} gap={_tuff_gap:+d} "
              f"-> {'QUALIFIES (+' + str(_tuff_gap) + ')' if _tuff_gap > 0 else 'no TUFF'}")
    else:
        print(f"[TUFF] {interaction.user.display_name}: no teammate TDs read from vision "
              f"(team_td rows={len(_team_td)}) — TUFF cannot be computed")

    # Visibility: vision read the faction banners but returned no roster rows,
    # so team rank and TUFF can't be computed for this run. Flag it so a mod can
    # check the scoreboard and add a missed TUFF with /add_board_score.
    # (Brittany's +6 TUFF was silently skipped this way, 2026-07-13.)
    if not _team_td and isinstance(vd.get('team_total_kills'), int):
        try:
            _ncr = original_message.guild.get_channel(config.NERVE_CENTER_CHANNEL_ID) \
                   or await original_message.guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID)
            if _ncr:
                _mlr = f"https://discord.com/channels/{original_message.guild.id}/{original_message.channel.id}/{original_message.id}"
                await _ncr.send(
                    f"👓 **No teammate takedowns read** on {interaction.user.display_name}'s run "
                    f"({takedowns} TD / {kills} K). Team rank and TUFF not computed — check the "
                    f"scorecard for a missed TUFF (kills vs best teammate TD).\n{_mlr}")
        except Exception as _e_nr:
            print(f"[TEAMSTATS] roster-skip flag error: {_e_nr}")

    if blurb_parts:
        # One stat per line (Kill Share / Warlord / Lethality / lobby marker) —
        # the old dot-joined single line crowded once the tilt marker landed
        lobby_line = "\n".join(f"*{p}*" for p in blurb_parts)

    from cogs.registry import get_registry_thread_id as _grt
    _player_row = await _db.get_player(str(interaction.user.id))
    try:
        _thread_id = await _grt(str(interaction.user.id))
    except Exception:
        _thread_id = None
    if not _thread_id and _player_row and len(_player_row) > 2 and _player_row[2]:
        _thread_id = _player_row[2]
    _guild_id = interaction.guild.id
    _name_display = (
        f"[{interaction.user.display_name}](https://discord.com/channels/{_guild_id}/{_thread_id})"
        if _thread_id else f"`{interaction.user.display_name}`"
    )

    _pac_run = (kills == 0 and takedowns <= 10)
    _score_suffix = f"  ·  {_score:,} score" if (_pac_run and isinstance(_score, int) and _score > 0) else ""
    # "Run Submitted" header lives in the embed TITLE now, not the description
    summary = (
        f"│ {_name_display}\n"
        f"│ {selected_weapon} • {selected_class}\n"
        f"│ {selected_map} / {faction}\n"
        f"│ {takedowns} TD / {kills} K / {deaths} D{_score_suffix}\n"
        f"│ VIP: {vip_str}"
    )
    if feats_str:
        summary += f"\n│ {feats_str}"
    if caption:
        summary += f"\n│ *{caption}*"
    if lobby_line:
        summary += f"\n\n{lobby_line}"

    # Pacifist board thread (for hyperlinking the "lands on the Pacifist board" line)
    _pac_board_link = None
    try:
        from cogs.leaderboards import _get_lb_records as _lb_gr, _board_jump_path as _bjp3
        for _r in await _lb_gr():
            if _r.get('Leaderboard Name') == 'Pacifist' and _r.get('Thread ID'):
                _pac_board_link = f"https://discord.com/channels/{original_message.guild.id}/{_bjp3(_r)}"
                break
    except Exception as _pbe:
        _pac_board_link = None

    # Build marks breakdown. A pacifist run (0 TD / 0 K) earns no weapon mark.
    _is_pacifist = (kills == 0 and takedowns <= 10)
    _is_hybrid = (str(selected_weapon).strip() == "Hybrid")
    marks_earned = 0 if (_is_pacifist or _is_hybrid) else 1
    marks_lines = [] if (_is_pacifist or _is_hybrid) else ["<:cigar:1444893851427803298> *+1 Submission*"]
    if '200 Takedowns' in feats:
        marks_earned += 1
        marks_lines.append(f"*<a:200tkd:1363648828414230538> +1*")
    if '100 Kills' in feats:
        marks_earned += 1
        marks_lines.append(f"*<a:100kill:1361412390339608686> +1*")
    if 'Triple' in feats:
        marks_earned += 1
        marks_lines.append(f"*<a:triple:1365532698260668466> +1 Triple*")
    for _dlo, _dnm, _dem, _dmk, _dtg in config.TILT_BANDS:
        if _dtg and _dtg in feats:
            marks_earned += _dmk
            marks_lines.append(f"*{_dem} +{_dmk} {_dnm} lobby*")
            break
    if _is_hybrid:
        marks_summary = ("\n\n🔀 **Hybrid run** — a weapon-swap game. No weapon marks, "
                         "but it lands on the **Hybrid** board (ranked by takedowns).")
    elif _is_pacifist and marks_earned == 0:
        _pb = f"[Pacifist board]({_pac_board_link})" if _pac_board_link else "Pacifist board"
        marks_summary = f"\n\n<a:passive:1365531248268673086> **Pacifist run** on {selected_weapon} — **+1** feat of legend (no weapon marks), and it lands on the {_pb}."
    else:
        marks_summary = f"\n\n**{marks_earned} Mark{'s' if marks_earned != 1 else ''}** on {selected_weapon}\n" + "\n".join(marks_lines)
    # TUFF (hard carry): kills beat your best teammate's takedowns -> show the margin on the blurb.
    if kills is not None and _second_place_td is not None and kills > _second_place_td:
        marks_summary += f"\n<a:TUFF2:1520779243879927898> **TUFF** +{kills - _second_place_td}"

    message_link = f"https://discord.com/channels/{original_message.guild.id}/{original_message.channel.id}/{original_message.id}"

    try:
        await interaction.delete_original_response()
    except Exception:
        try:
            await interaction.edit_original_response(content="​", view=None)
        except Exception as _edit_err:
            print(f"[FINALISE] edit_original_response failed: {_edit_err}")

    # Delete the "Scorecard detected!" prompt message
    if prompt_msg:
        try:
            await prompt_msg.delete()
        except Exception:
            pass

    # Ensure a players row exists BEFORE anything writes to it. The archive-stats
    # write and IGN learning are plain UPDATEs (silent no-ops without a row), and
    # the Butler's "registered" check reads this table — players who joined after
    # the last /seed_players run were invisible to all three despite submitting.
    try:
        await upsert_player(interaction.user.id, interaction.user.display_name)
    except Exception as _e_up:
        print(f"[PLAYERS] ensure-row error: {_e_up}")

    # Log to Postgres first so we get the row id
    submission_row = None
    try:
        log_result = await log_submission(
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
            team_kill_share=_team_kill_share,
            team_td_share=_team_td_share,
            second_place_td=_second_place_td,
            score=_score,
            team_total_kills=_vd_team_total if isinstance(_vd_team_total, int) else None,
            enemy_total_kills=_ett if isinstance(_ett, int) else None,
        )
        # log_submission returns (row_id, dup_weapon): row_id is the exact row index
        # it wrote to, or None if this was a dedup-skipped repeat — in which case
        # dup_weapon is the weapon already recorded on the matching original.
        submission_row, dup_weapon = log_result
        is_new_player = False  # determined later from submission_count == 1

        # Auto-increment manual feat counts if already set for this player
        discord_id_str = str(interaction.user.id)
        if 'Triple' in feats:
            await _db.increment_manual_feat_count(discord_id_str, 'triple')
        else:
            if '100 Kills' in feats:
                await _db.increment_manual_feat_count(discord_id_str, '100 kills')
            if '200 Takedowns' in feats:
                await _db.increment_manual_feat_count(discord_id_str, '200 takedowns')

        # Hundred-Handed role is granted only by the 46-combo check in _bg_tasks
        # (subclass+weapon combos, same rule as the HH board).
    except Exception as e:
        is_new_player = False
        print(f"Sheet logging error: {e}")

    # Dedup: if this was a duplicate run, only re-check bounty if the weapon was
    # actually corrected from the original attempt (e.g. they picked the wrong
    # weapon the first time and resubmitted). An exact repeat — same stats, same
    # weapon, just double-posted by accident — must NOT increment bounty progress
    # again; it was unconditionally re-counting every accidental resubmission
    # before this, inflating the bounty's aggregate weapon totals. (2026-06-30.)
    if submission_row is None:
        weapon_changed = bool(dup_weapon) and dup_weapon.strip().lower() != (selected_weapon or '').strip().lower()
        if not is_ranged and weapon_changed:
            try:
                from cogs.bounty import update_bounty
                bounty_hit = await update_bounty(
                    interaction.guild, selected_weapon,
                    interaction.user.display_name, interaction.user.id, takedowns
                )
                print(f"[BOUNTY/DEDUP] bounty_hit={bounty_hit} weapon={selected_weapon} (corrected from {dup_weapon})")
                if bounty_hit:
                    await original_message.add_reaction(await _bounty_emoji())
            except Exception as e:
                nerve_log_error("Bounty check", e)
        print(f"[DEDUP] Duplicate submission fully skipped for {interaction.user.display_name}")
        return

    # Anomaly check — alert butlers-notes if stats look suspicious
    try:
        await check_submission_anomaly(
            interaction.guild,
            interaction.user.display_name,
            message_link,
            selected_weapon,
            selected_map,
            faction,
            takedowns,
            kills
        )
    except Exception as e:
        print(f"Anomaly check call error: {e}")

    # Post summary with Edit button
    edit_view = EditSubmissionView(
        original_message, interaction.user,
        submission_row, selected_weapon, selected_class,
        selected_map, faction, takedowns, kills, deaths, vip, feats, message_link,
        _second_place_td, _score
    )
    # Lethality weapon-charge: a grey->green weapon silhouette as the blurb
    # thumbnail, greener the further this run's lethality beat the weapon avg.
    _leth_file = None
    _leth_thumb = None
    try:
        _lmin = getattr(config, 'LETHALITY_BLURB_MIN_DELTA', 5.0)
        if _leth_delta is not None and _leth_delta >= _lmin:
            import utils.charts as _charts
            _lpng = await _charts.render_async(
                _charts.render_lethality_charge, selected_weapon, _leth_delta)
            if _lpng:
                _leth_file = discord.File(io.BytesIO(_lpng), filename="lethality.png")
                _leth_thumb = "attachment://lethality.png"
    except Exception as _lce:
        print(f"[LETHALITY] charge render failed: {_lce}")
    _reply_kwargs = dict(
        embed=_blurb_embed(summary + marks_summary, thumb=_leth_thumb),
        mention_author=False, view=edit_view)
    if _leth_file is not None:
        _reply_kwargs['file'] = _leth_file
    summary_reply = await original_message.reply(**_reply_kwargs)
    edit_view._message = summary_reply

    # The blurb below was edited up to five times in a row, each with its own
    # fetch+edit round-trip, so it visibly mutated several times and every site
    # had to re-fetch to avoid clobbering the previous one (see the comment on the
    # placement block). Hold one cached copy, mutate locally, commit twice at most.
    _blurb_state = {'desc': None, 'dirty': False}

    async def blurb_read():
        if _blurb_state['desc'] is None:
            try:
                _m = await summary_reply.channel.fetch_message(summary_reply.id)
                _blurb_state['desc'] = _blurb_desc(_m)
            except Exception:
                _blurb_state['desc'] = _blurb_desc(summary_reply)
        return _blurb_state['desc']

    def blurb_write(desc):
        _blurb_state['desc'] = desc
        _blurb_state['dirty'] = True

    async def blurb_commit():
        if not _blurb_state['dirty'] or _blurb_state['desc'] is None:
            return
        _blurb_state['dirty'] = False
        try:
            await _blurb_edit(summary_reply, _blurb_state['desc'])
        except Exception as _bce:
            print(f"[BLURB] commit error: {_bce}")

    # Background tasks — run after confirmation is posted
    _guild = interaction.guild
    _user_id = interaction.user.id
    _user_name = interaction.user.display_name

    async def _bg_tasks():
        # is_new_player is (re)computed later in this task's milestone section, which
        # makes it a local — initialize it up front so the butler hooks below can
        # read it without an UnboundLocalError (regression from backgrounding).
        is_new_player = False
        # weapon_hs — only if score qualifies for the weapon leaderboard (not VIP, not ranged)
        # and beats the player's own existing score on that board
        if not vip and not is_ranged:
            # Targeted, indexed read of just this weapon's board — not the whole
            # leaderboard table — so the board-dependent weapon_hs reaction lands
            # as quickly as possible.
            weapon_entries = await _db.get_leaderboard_by_board(selected_weapon)
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
                react_later("<:weapon_hs:1350656128635375698>")

        # Update leaderboards (skip for ranged submissions)
        any_updated = False
        placements = []
        newly_completed = False
        if not is_ranged:
            try:
                async with _BOARD_LOCK:
                    any_updated, placements = await update_leaderboards(
                        interaction, selected_weapon, selected_map, faction,
                        takedowns, kills, deaths, vip, feats,
                        interaction.user.display_name, message_link,
                        bot_user=interaction.client.user,
                        second_place_td=_second_place_td,
                        score=_score,
                    )
            except Exception as e:
                # This except once hid a NameError that silently broke ALL board
                # updates for every submission (2026-07-22). Board failures must
                # be LOUD — surface to the nerve centre, not just stdout.
                import traceback as _tb
                print(f"Leaderboard update error: {e}\n{_tb.format_exc()}")
                try:
                    from utils.helpers import nerve_alert
                    await nerve_alert(interaction.client, "board update", e)
                except Exception:
                    pass

        # A pacifist run only lands on the Pacifist board (an unlimited feat board),
        # which flips any_updated True. That must NOT fire the weapon/map High Score
        # react or mark — pacifist runs never earn a High Score.
        if _is_pacifist:
            any_updated = False

        # Hundred Handed: track subclass+weapon combos (any submission counts)
        if selected_weapon and selected_class and not selected_class.startswith("Marksman"):
            try:
                is_new = await _db.add_hundred_handed(
                    str(interaction.user.id), interaction.user.display_name,
                    selected_class, selected_weapon
                )
                if is_new:
                    print(f"[HUNDRED_HANDED] New combo: {interaction.user.display_name} — {selected_class} / {selected_weapon}")
                    await _refresh_hundred_handed_board(interaction.guild)
                    # Auto-grant the Hundred-Handed role the moment all 46 required combos are done
                    try:
                        from cogs.leaderboards import _hh_matched_counts, HH_TOTAL as _HHT
                        _mine = _hh_matched_counts(await _db.get_all_hundred_handed()).get(str(interaction.user.id))
                        if _mine and _mine[1] >= _HHT:
                            _hhrole = interaction.guild.get_role(config.HUNDRED_HANDED_ROLE_ID)
                            _mem = interaction.guild.get_member(interaction.user.id)
                            if _hhrole and _mem and _hhrole not in _mem.roles:
                                await _mem.add_roles(_hhrole, reason="Hundred-Handed complete (46/46)")
                                print(f"[HUNDRED_HANDED] Granted role to {interaction.user.display_name} (46/46)")
                    except Exception as _hhre:
                        print(f"[HUNDRED_HANDED] auto-role error: {_hhre}")
            except Exception as e:
                nerve_log_error("Hundred-Handed check", e)

        # "High Score" = a personal best on the WEAPON's OWN board — not map or feat
        # boards. any_updated is also flipped by those, which produced phantom High
        # Scores with no weapon placement to show. Gate on the weapon board placing so
        # the High Score react/mark and the weapon hyperlink/placement always agree.
        # High Score = a personal-best placement on the run's WEAPON board or MAP
        # board. The only special rule: VIP runs are barred from weapon boards
        # (inflated kill feed), so a VIP run can only high-score on its map board.
        _weapon_hs = bool(selected_weapon) and any(
            lb in (selected_weapon, f"{selected_weapon} Kills") for lb, _ in placements)
        _map_hs = any(lb == f"{selected_map} - {faction}" for lb, _ in placements)
        if _weapon_hs or _map_hs:
            # Immediate visual feedback FIRST — react + bump the blurb before any
            # bookkeeping, so the user sees the High Score right away.
            react_later("<a:highscore:1360312918545269057>")
            try:
                import re as _re
                def increment_marks(content):
                    def replacer(m):
                        n = int(m.group(1)) + 1
                        return f"**{n} Mark{'s' if n != 1 else ''}**"
                    return _re.sub(r'\*\*(\d+) [Mm]arks?\*\*', replacer, content)
                blurb_write(increment_marks(await blurb_read())
                            + "\n<a:highscore:1360312918545269057> +1 High Score")
            except Exception as e:
                print(f"Highscore mark edit error: {e}")
            # Bookkeeping (lower priority): record the High Score feat so mark totals
            # count it. The player card is refreshed ONCE at the end of _bg_tasks, so we
            # deliberately do NOT refresh it here — that heavy work must never delay the
            # visual feedback above.
            if submission_row:
                try:
                    current_feats = await _db.get_submission_feats(submission_row)
                    if 'High Score' not in current_feats:
                        if current_feats in ('', 'None'):
                            updated_feats = 'High Score'
                        else:
                            updated_feats = (current_feats.rstrip(', ') + ', High Score').lstrip(', ')
                        await _db.update_submission_feats(submission_row, updated_feats)
                except Exception as e:
                    print(f"Highscore feat write error: {e}")
        if any(lb == "TUFF" for lb, _ in placements):
            react_later("<a:TUFF2:1520779243879927898>")
        if any(lb == "Pacifist" for lb, _ in placements):
            react_later("<a:passive:1365531248268673086>")
        if any(lb == "Hybrid" for lb, _ in placements):
            react_later("🔀")   # 🔀 twisted arrows — the Hybrid feat

        # Bounty check (skip for ranged submissions, and for resubmits — an old
        # re-uploaded run shouldn't advance the current monthly bounty or trigger
        # its completion bonus; resubmits still count for all-time boards + card).
        bounty_line = ""  # convenience hyperlink to the player's bounty post, if hit
        if not is_ranged and "Resubmit" not in feats:
            try:
                bounty_hit = await update_bounty(
                    interaction.guild, selected_weapon,
                    interaction.user.display_name, interaction.user.id, takedowns
                )
                print(f"[BOUNTY] bounty_hit={bounty_hit} weapon={selected_weapon} takedowns={takedowns}")
                if bounty_hit:
                    # Check if this run completed the bounty
                    _bounty = await get_active_bounty()
                    react_later((_bounty or {}).get('theme_emoji') or _BOUNTY_EMOJI_FALLBACK)
                    if _bounty:
                        newly_completed = await check_bounty_completion(
                            interaction.guild, _bounty, interaction.user.display_name, interaction.user.id
                        )
                        # Link the player straight to their own bounty progress post.
                        try:
                            from cogs.bounty import get_player_bounty_progress
                            _pbr = await get_player_bounty_progress(_bounty['title'], str(interaction.user.id))
                            _fp = _pbr.get('forum_post_id') if _pbr else None
                            if _fp:
                                _bemoji = _bounty.get('theme_emoji') or _BOUNTY_EMOJI_FALLBACK
                                bounty_line = (
                                    f"{_bemoji} [+1 {_bounty['title']}]"
                                    f"(https://discord.com/channels/{interaction.guild.id}/{_fp})"
                                )
                        except Exception as _blerr:
                            print(f"[BOUNTY] link build error: {_blerr}")
            except Exception as e:
                import traceback
                print(f"Bounty update error: {e}")
                traceback.print_exc()

        # Last reaction is decided by here: send them all as one burst.
        flush_reacts()

        # ── BUTLER PERSONALITY HOOKS ─────────────────────────────────────────────
        try:
            main_channel = interaction.guild.get_channel(MAIN_CHANNEL_ID)
            now = datetime.now(timezone.utc)
            player = interaction.user.display_name
            discord_id_str = str(interaction.user.id)  # bind early: mastery genexpr (~L2079) referenced it before its later assignment

            if main_channel:
                # Dry spell — first submission after 4+ hours of silence
                if submission_state['last_submission_time'] and (now - submission_state['last_submission_time']).total_seconds() > 14400:
                    line = await butler_quip(
                        "The lounge has been dead for hours and someone just submitted a run. "
                        "React as the Butler — one dry line about finally seeing some activity. Vary it each time.",
                        fallback="The lounge stirs. About time."
                    )
                    await main_channel.send(f"*{line}*")

                # New player first submission
                if is_new_player:
                    line = await butler_quip(
                        f"A new player named {player} has just submitted their first run. "
                        "Acknowledge them briefly as the Butler — dry, not warm, but not unkind. One sentence.",
                        fallback=f"*A new arrival. The Butler acknowledges you, {player}.*"
                    )
                    await main_channel.send(line if line.startswith('*') else f"*{line}*")
                    try:
                        unbound_role = interaction.guild.get_role(config.UNBOUND_ROLE_ID)
                        member = interaction.guild.get_member(_user_id) or await interaction.guild.fetch_member(_user_id)
                        if unbound_role and member and unbound_role not in member.roles:
                            await member.add_roles(unbound_role, reason="First blood — first submission")
                            print(f"[UNBOUND] Assigned Unbound role to {player}")
                    except Exception as ub_e:
                        nerve_log_error("Unbound role assign", ub_e)

                # New #1 on any leaderboard — plain factual update (no Butler flavour).
                # "#1" links to the run itself; board and player names get linkified.
                new_firsts = [lb for lb, pos in placements if pos == 1]
                if new_firsts:
                    from cogs.personality import _linkify_reply as _lky
                    boards = ", ".join(f"**{b}**" for b in new_firsts)
                    _first_msg = f"**{player}** took [#1]({message_link}) on {boards}."
                    await main_channel.send(await _lky(_first_msg, _guild))

                # Bounty completion. The season GP is awarded by update_bounty
                # (cogs/bounty.py), which knows the player's FINISH POSITION and pays
                # the race accordingly: 5/4/3, then 2 for everyone after. A second
                # award used to live here paying a flat BOUNTY_COMPLETION_BONUS to
                # everyone; idempotency meant it normally lost the race and did
                # nothing, but if the bounty.py path ever errored it would silently
                # hand 5 GP to a fourth-place finisher. Only the quip belongs here.
                if newly_completed:
                    line = await butler_quip(
                        f"{player} just completed the bounty. React as the Butler — acknowledge it, "
                        "maybe reference the bald woman (Bald Female, a server legend) in comparison. One or two sentences.",
                        fallback=f"The bounty is settled. **{player}** has seen to it."
                    )
                    await main_channel.send(line)

                # Weapon mastery milestone — marks-based, summed across ALL classes
                # (matches the card). Fires once, when this run pushes the weapon's
                # total marks across a threshold.
                _fstr = feats if isinstance(feats, str) else ", ".join(feats or [])
                if not is_ranged and selected_weapon and "Resubmit" not in _fstr:
                    try:
                        _marks = await calculate_weapon_marks_for_player(interaction.user.id)
                        _new = sum(v for k, v in _marks.items()
                                   if (k[0] if isinstance(k, tuple) else k) == selected_weapon)
                        # Badge on the blurb: Virtuoso (250) takes precedence, else Mastery (100).
                        _badge = None
                        if _new >= config.VIRTUOSO_THRESHOLD:
                            _vemoji = config.VIRTUOSO_WEAPON_EMOJIS.get(
                                selected_weapon, getattr(config, 'VIRTUOSO_DEFAULT_EMOJI', '💎'))
                            _badge = (_vemoji, "Virtuoso")
                        elif _new >= config.MASTERY_THRESHOLD:
                            _memoji = getattr(config, 'MASTERY_WEAPON_EMOJIS', {}).get(selected_weapon)
                            if _memoji:
                                _badge = (_memoji, "Master")
                        if _badge:
                            try:
                                # Match the exact badge line, not the bare word:
                                # SUBCLASS_RANKS contains "Master" AND "Grandmaster",
                                # so any caption or rank mentioning either used to
                                # suppress the badge entirely.
                                _vdesc = await blurb_read()
                                _badge_line = f"{_badge[0]} **{_badge[1]}**"
                                if _badge_line not in _vdesc:
                                    blurb_write(_vdesc + f"\n{_badge_line}")
                            except Exception as _vbe:
                                print(f"[BADGE] error: {_vbe}")
                        _rm = 1 + (1 if takedowns >= 200 else 0) + (1 if kills >= 100 else 0)
                        if "Triple" in _fstr: _rm += 1
                        if "High Score" in _fstr: _rm += 1
                        _old = _new - _rm
                        if _old < config.VIRTUOSO_THRESHOLD <= _new:
                            from cogs.personality import _linkify_reply as _lky2
                            await main_channel.send(await _lky2(
                                f"\U0001f48e **{player}** has reached **Virtuoso** on the {selected_weapon} \u2014 {_new} marks across all classes. Exceptional. [The run.]({message_link})", _guild))
                        elif _old < config.MASTERY_THRESHOLD <= _new:
                            from cogs.personality import _linkify_reply as _lky2
                            await main_channel.send(await _lky2(
                                f"\U0001f451 **{player}** has **mastered** the {selected_weapon} \u2014 {_new} marks. The Butler tips his hat. [The run.]({message_link})", _guild))
                    except Exception as _me:
                        print(f"[MASTERY] announce error: {_me}")

            # Flawless — reply in submissions channel
            if deaths == 0:
                line = await butler_quip(
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
            try:
                from utils.helpers import nerve_alert
                await nerve_alert(interaction.client, "submission butler hooks", e)
            except Exception:
                pass

        # Edit the summary reply to include placements, and — only for boards this
        # submission actually placed on — swap the plain weapon/map text for a
        # hyperlink to that board. A submission that doesn't place shouldn't link
        # to a board it didn't make.
        if placements or bounty_line:
            # Each feat board shows its own logo; weapon_hs is reserved for the actual
            # weapon board. Map boards use the trophy.
            _FEAT_EMOJI = {
                "100 Kills":     "<a:100kill:1361412390339608686>",
                "200 Takedowns": "<a:200tkd:1363648828414230538>",
                "Triple":        "<a:triple:1365532698260668466>",
                "TUFF":          "<a:TUFF2:1520779243879927898>",
                "Flawless":      "<a:flawless:1360358300834599062>",
                "Mallet":        "🔨",
                "Knife":         "🗡️",
                "Hybrid":        "🔀",
            }
            # Board thread map — used to hyperlink the board-record line to its board.
            _lb_thread_map = {}
            try:
                from cogs.leaderboards import _get_lb_records as _lb_get_records, _board_jump_path as _bjp
                _lb_rows_for_links = await _lb_get_records()
                # values are "thread/first_message" paths — links land ON the board
                _lb_thread_map = {r['Leaderboard Name']: _bjp(r) for r in _lb_rows_for_links if r.get('Thread ID')}
            except Exception as _tme:
                print(f"[LINK] thread map error: {_tme}")
            def _placement_line(lb, pos):
                _tid = _lb_thread_map.get(lb)
                _name = f"[{lb}](https://discord.com/channels/{_guild_id}/{_tid})" if _tid else lb
                if ' - ' in lb:                       # map board
                    return f"🏆 {_name} — #{pos}"
                if lb == "TUFF":                      # TUFF shows emoji only, no name
                    return f"{_FEAT_EMOJI['TUFF']} — #{pos}"
                if lb in _FEAT_EMOJI:                 # feat boards: own logo + rank
                    return f"{_FEAT_EMOJI[lb]} {lb} — #{pos}"
                # actual weapon board — the only place weapon_hs belongs
                return f"<:weapon_hs:1350656128635375698> {_name} — #{pos}"
            # Feat boards (100 Kills, 200 Takedowns, Triple, TUFF, Flawless…) are already
            # named in the run's feats line above — don't repeat them in the trailer.
            _shown = [(lb, pos) for lb, pos in placements if lb not in _FEAT_EMOJI]
            placement_lines = "\n".join(_placement_line(lb, pos) for lb, pos in _shown)
            trailer = placement_lines
            try:
                placed_boards = {lb for lb, _ in placements}
                map_lb_name = f"{selected_map} - {faction}"
                # Edit the reply directly via our held reference (robust in a busy channel).
                # Re-fetch first so we build on (not clobber) the High Score edit above —
                # it bumped the mark count and appended the "+1 High Score" line, but the
                # stale in-memory copy didn't reflect it, so placing on a board was
                # silently dropping the High Score line and the extra mark.
                new_content = await blurb_read()
                # 100 Kills board rank onto the "+1" line (hyperlinked to the board).
                _kills_pos = next((p for lb, p in placements if lb == "100 Kills"), None)
                if _kills_pos is not None:
                    _ktid = _lb_thread_map.get("100 Kills")
                    _kr = (f"[#{_kills_pos}](https://discord.com/channels/{_guild_id}/{_ktid})"
                           if _ktid else f"#{_kills_pos}")
                    new_content = new_content.replace(
                        "<a:100kill:1361412390339608686> +1*",
                        f"<a:100kill:1361412390339608686> +1 — {_kr}*", 1)
                _td_pos = next((p for lb, p in placements if lb == "200 Takedowns"), None)
                if _td_pos is not None:
                    _ttid = _lb_thread_map.get("200 Takedowns")
                    _tr = (f"[#{_td_pos}](https://discord.com/channels/{_guild_id}/{_ttid})"
                           if _ttid else f"#{_td_pos}")
                    new_content = new_content.replace(
                        "<a:200tkd:1363648828414230538> +1*",
                        f"<a:200tkd:1363648828414230538> +1 — {_tr}*", 1)
                if selected_weapon in placed_boards:
                    weapon_link = _link_weapon(selected_weapon, _guild_id, _lb_thread_map)
                    new_content = new_content.replace(
                        f"│ {selected_weapon} • {selected_class}",
                        f"│ {weapon_link} • {selected_class}",
                        1,
                    )
                if map_lb_name in placed_boards:
                    map_link = _link_map_faction(selected_map, faction, _guild_id, _lb_thread_map)
                    new_content = new_content.replace(
                        f"│ {selected_map} / {faction}",
                        f"│ {map_link}",
                        1,
                    )
                if bounty_line:
                    # Own block, below the stat rows and above the marks rundown.
                    # Bounty progress awards no marks, so sitting it inside the
                    # rundown next to "+1 Submission" read as a second mark.
                    import re as _re2
                    _mblock = _re2.search(
                        r'\n\n(?:\*\*\d+ Marks?\*\* on |<a:passive:\d+> \*\*Pacifist run\*\*)',
                        new_content)
                    if _mblock:
                        new_content = (new_content[:_mblock.start()]
                                       + f"\n\n{bounty_line}"
                                       + new_content[_mblock.start():])
                    else:
                        new_content = f"{new_content}\n\n{bounty_line}"
                blurb_write(new_content + (f"\n{trailer}" if trailer else ""))
            except Exception as e:
                print(f"Placement edit error: {e}")
            # Commit here as well as at the end: if _bg_tasks later times out, the
            # placement/marks content is the part players actually care about.
            await blurb_commit()

        # Auto-learn IGN: if vision read a name from the scoreboard that differs from Discord name, save it
        _vision_name = (vision_data or {}).get('name')
        if _vision_name and _vision_name.strip().lower() != _user_name.strip().lower():
            try:
                # Guard: never learn a name that already belongs to a DIFFERENT player.
                # That is the signature of a wrong-row read (e.g. reading a friend's
                # green-highlighted row) — learning it would poison this player's name
                # hints and make the misread stick.
                _n2id = await _db.get_name_to_id_map()
                _owner = _n2id.get(_vision_name.strip().lower())
                if _owner and str(_owner) != str(_user_id):
                    print(f"[IGN] Skipped '{_vision_name}' for {_user_name} — that name belongs to another player ({_owner}); likely a wrong-row read")
                else:
                    await _db.save_player_ign(_user_id, _vision_name.strip())
                    print(f"[IGN] Saved alias for {_user_name}: '{_vision_name}'")
            except Exception as e:
                print(f"[IGN] Save error: {e}")

        # Pre-fetch once so downstream calls share the same data
        try:
            await _db.get_all_submissions()
            await _db.get_all_players()
        except Exception as _e:
            swallow(_e, "bg pre-fetch")

        # Update registry card
        try:
            await create_or_update_registry_card(_guild, _user_id, _user_name)
        except Exception as e:
            print(f"Registry card update error: {e}")
        # First-time submitters: the card thread didn't exist when the blurb posted, so
        # the name was left as plain code text. Now that the card exists, upgrade the
        # blurb name to a hyperlink to it.
        try:
            from cogs.registry import get_registry_thread_id as _grt2
            try:
                _tid = await _grt2(str(_user_id))
            except Exception:
                _tid = None
            if not _tid:
                _pr = await _db.get_player(str(_user_id))
                _tid = _pr[2] if _pr and len(_pr) > 2 and _pr[2] else None
            # Only link a thread that actually exists — a stale id from a
            # skipped/purged card produced "you don't have access" popups
            if _tid:
                try:
                    _th_ok = _guild.get_thread(int(_tid)) or await _guild.fetch_channel(int(_tid))
                except Exception:
                    _th_ok = None
                if not _th_ok:
                    _tid = None
            if _tid:
                _plain = f"`{_user_name}`"
                _link = f"[{_user_name}](https://discord.com/channels/{_guild.id}/{_tid})"
                _fdesc = await blurb_read()
                if _plain in _fdesc:
                    blurb_write(_fdesc.replace(_plain, _link, 1))
        except Exception as _nle:
            print(f"[NAME LINK] blurb update error: {_nle}")
        await asyncio.sleep(1)

        # Lobbymates: anyone else who submitted this exact match. total_lobby_kills
        # is the same for every player in a lobby, so a matching value + map + a
        # tight time window is a reliable fingerprint. Purely additive to the blurb.
        # Asymmetric by nature: the FIRST person to submit a match can't see mates who
        # haven't uploaded yet — only later submitters get the line. That's fine; the
        # Butler's on-demand context (below) fills it in for anyone who asks afterward.
        try:
            _mates = await _db.get_lobbymates(str(interaction.user.id), message_link)
            if _mates:
                _lines = []
                for _mm in _mates[:3]:
                    if _mm['same_team'] is True:
                        _rel = "alongside"
                    elif _mm['same_team'] is False:
                        _rel = "against"
                    else:
                        _rel = "in a lobby with"
                    _lines.append(f"🎪 Fought {_rel} `{_mm['player_name']}`")
                if _lines:
                    _lm_desc = await blurb_read()
                    blurb_write(_lm_desc + "\n" + "\n".join(f"*{l}*" for l in _lines))
        except Exception as _lme:
            print(f"[LOBBYMATE] blurb update error: {_lme}")
        await blurb_commit()

        # Update bounty cards index. Each bounty has its OWN ledger forum (stored on
        # the bounty row); the static BOUNTY_CARDS_FORUM_ID is the previous one, so
        # refreshing that left the current bounty's index stale every time.
        try:
            bounty = await get_active_bounty()
            if bounty:
                _bfid = bounty.get('forum_channel_id') or BOUNTY_CARDS_FORUM_ID
                _bch = bounty.get('channel_id')
                _blink = (f"[{bounty['title']}](https://discord.com/channels/{_guild.id}/{_bch})"
                          if _bch else f"**{bounty['title']}**")
                def _wtot(d):
                    return d.get('total', 0) if isinstance(d, dict) else d
                bounty_blurb = (
                    f"{_blink}\n\n"
                    f"A monthly bounty where select weapons qualify toward completion. Submit the required number of runs per weapon to complete the bounty. Often comes with a bonus challenge.\n\n"
                    f"**Weapons & Requirements:**\n" +
                    "\n".join(f"▸ {w}: {_wtot(d)} runs" for w, d in bounty['weapons'].items())
                )
                await update_leaderboard_index(_guild, _bfid, "Bounty Cards", bounty_blurb)
        except Exception as e:
            print(f"Bounty cards index update error: {e}")

        # Refresh ledger entrance after any submission that touched leaderboards
        if any_updated:
            try:
                await build_ledger_entrance(_guild)
            except Exception as e:
                print(f"Ledger entrance refresh error: {e}")
            try:
                from cogs.favourites import calculate_butler_stats, update_title_roles
                _now_t = datetime.now(timezone.utc)
                _days_since_mon = _now_t.weekday()
                _week_start = (_now_t - timedelta(days=_days_since_mon)).replace(hour=12, minute=0, second=0, microsecond=0)
                if _week_start > _now_t:
                    _week_start -= timedelta(weeks=1)
                _title_stats = await calculate_butler_stats(week_start=_week_start.timestamp(), week_end=_now_t.timestamp())
                await update_title_roles(_guild, _title_stats, include_weekly=False)
            except Exception as e:
                print(f"Title roles refresh error: {e}")

        # Update ButlersArchive summary sheet + milestone detection
        try:
            subs = await _db.get_all_submissions()
            discord_id_str = str(_user_id)
            player_subs = [r for r in subs if len(r) > 2 and r[2].strip() == discord_id_str]
            submission_count = len(player_subs)
            last_submission = player_subs[-1][0] if player_subs else ''
            is_new_player = submission_count == 1

            # Compute OLD weapon marks as "everything except this brand-new submission",
            # rather than trusting the cached players.weapon_marks column. That cache is
            # only ever written by this same block, so a player whose legacy_marks /
            # leaderboard_data were backfilled (e.g. via /award_marks or an old-registry
            # import) without ever making a live submission before would show old_flat={}
            # here — and since is_first_submission also waives the Bronze/threshold-1
            # suppression below, EVERY backfilled weapon looked like a brand new "first
            # blood" milestone, firing a wall of announcements off a single submission.
            # (Backfilled-player mass "first blood" spam, investigated 2026-06-30.)
            old_flat = {}
            try:
                newest_row = player_subs[-1] if player_subs else None
                subs_excl_new = [r for r in subs if r is not newest_row]
                old_marks_data = await calculate_weapon_marks_for_player(
                    _user_id, cached_data={'submissions': subs_excl_new}
                )
                for k, v in old_marks_data.items():
                    w = k[0] if isinstance(k, tuple) else k
                    old_flat[w] = old_flat.get(w, 0) + v
            except Exception as e:
                print(f"Milestone: old marks read error: {e}")

            # Compute new weapon marks
            weapon_marks_data = await calculate_weapon_marks_for_player(_user_id)
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
            reg_rows = await _db.get_all_registry_cards()
            thread_id = None
            for r in reg_rows:
                if len(r) > 2 and r[0].strip() == discord_id_str:
                    thread_id = r[2].strip() or None
                    break

            await update_butlers_archive_row(
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
                        from cogs.personality import _linkify_reply as _lky3
                        for weapon, threshold, rank_name in milestones:
                            msg = build_milestone_message(_user_name, weapon, threshold, rank_name)
                            if msg:
                                nerve_log_milestone(_user_name, weapon, rank_name)
                                # board/card links + the run that did it
                                msg = await _lky3(msg, _guild) + f" [The run.]({message_link})"
                                await main_ch.send(msg)
                                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Milestone announcement error: {e}")

        except Exception as e:
            print(f"ButlersArchive bg update error: {e}")

        # Update Butler Monthly report
        try:
            # Import here so these names are bound regardless of the any_updated
            # branch above (that branch's local import otherwise makes them
            # function-local and unassigned on the no-new-highscore path).
            from cogs.favourites import calculate_butler_stats, build_favourites_embed, update_title_roles
            if BUTLERS_FAVOURITES_CHANNEL_ID:
                fav_channel = _guild.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
                if fav_channel:
                    _now = datetime.now(timezone.utc)
                    _season = await _db.get_current_season()
                    if _season:
                        stats = await calculate_butler_stats(week_start=_season['started_at'].timestamp(), week_end=_now.timestamp())
                        stats['week_label'] = (_season.get('label') or f"Season {_season['id']}") + " — season so far"
                    else:
                        week_start_dt = (_now - timedelta(days=_now.weekday())).replace(hour=12, minute=0, second=0, microsecond=0)
                        if week_start_dt > _now:
                            week_start_dt -= timedelta(weeks=1)
                        stats = await calculate_butler_stats(week_start=week_start_dt.timestamp(), week_end=_now.timestamp())
                        stats['week_label'] = f"{week_start_dt.strftime('%b %d')} – {(week_start_dt + timedelta(days=7)).strftime('%b %d')}"
                    embed_text = await build_favourites_embed(stats, bot_avatar_url=_guild.me.display_avatar.url if _guild else None)
                    from cogs.favourites import refresh_favourites_message
                    await refresh_favourites_message(_guild, embed_text)
                    await update_title_roles(_guild, stats, include_weekly=False)
        except Exception as e:
            print(f"Butler favourites update error: {e}")

    async def _bg_runner():
        # Backstop so the detached background job can't hang forever. Each block
        # inside _bg_tasks has its own try/except for errors; this bounds total
        # runtime if a Discord/DB call stalls instead of erroring.
        #
        # The semaphore is acquired OUTSIDE the timeout on purpose: queuing for a
        # slot is not the work stalling, and counting it would make every task
        # behind a burst "time out" for doing nothing wrong.
        _wait0 = asyncio.get_running_loop().time()
        async with _BG_SEMAPHORE:
            _waited = asyncio.get_running_loop().time() - _wait0
            if _waited > 5:
                print(f"[BG] waited {_waited:.1f}s for a slot "
                      f"(limit {_BG_LIMIT}) — submissions are bursting")
            await _bg_body()

    async def _bg_body():
        try:
            await asyncio.wait_for(_bg_tasks(), timeout=120)
        except asyncio.TimeoutError:
            print("[BG] background tasks exceeded 120s — aborted (blurb/reactions already sent)")
            try:
                from utils.helpers import nerve_alert
                await nerve_alert(interaction.client, "background tasks", "exceeded 120s timeout")
            except Exception:
                pass
        except Exception as _bge:
            print(f"[BG] background tasks error: {_bge}")
            try:
                from utils.helpers import nerve_alert
                await nerve_alert(interaction.client, "background tasks", _bge)
            except Exception:
                pass
    # Reap the deferred reactions. They have been running concurrently with
    # everything above, so this is almost always already done; awaiting keeps a
    # strong reference so the loop cannot garbage-collect a pending task, and
    # stops exceptions being reported as "never retrieved".
    flush_reacts()   # anything queued after the burst (rare paths)
    if _react_tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*_react_tasks, return_exceptions=True), timeout=15)
        except asyncio.TimeoutError:
            print("[REACT] reactions still pending after 15s")

    _bgt = asyncio.create_task(_bg_runner())
    _bg_task_refs.add(_bgt)
    _bgt.add_done_callback(_bg_task_refs.discard)


# _bg_tasks is detached, so a burst of submissions used to spawn an unbounded
# number of them: each doing full-table scans, opening pool connections and
# queuing on _BOARD_LOCK. Bound it so a burst forms an orderly queue instead of a
# stampede. Sized well under the DB pool so background work can never starve the
# foreground submission path of connections.
_BG_LIMIT = int(os.environ.get('BG_TASK_LIMIT', 6))
_BG_SEMAPHORE = asyncio.Semaphore(_BG_LIMIT)
# asyncio only holds a weak reference to a running task: without this a detached
# task can be garbage-collected mid-flight and silently vanish.
_bg_task_refs: set = set()

_active_vision: set[int] = set()  # prevents double-processing same message
_queued_msgs: set[int] = set()  # prevents same message being finalised twice
# Serializes board read-modify-writes across detached background tasks so two
# concurrent submissions to the same board can't lose an update / dup.
_BOARD_LOCK = asyncio.Lock()

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
        # Only trigger on image attachments
        has_image = any(
            (att.content_type and att.content_type.startswith('image/'))
            or (not att.content_type and att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')))
            for att in message.attachments
        )
        if not has_image:
            return

        self._prompted_messages.add(message.id)
        # Prevent unbounded growth — keep only the last 200 message IDs
        if len(self._prompted_messages) > 200:
            self._prompted_messages = set(list(self._prompted_messages)[-200:])

        # Healing manual flow: a HEALING-popup screenshot captioned "horn" /
        # "healing horn" / "banner" / "healing banner" skips scorecard vision
        # entirely — the player types the total into a modal and it lands on
        # the matching personal-best board.
        _cap = (message.content or '').lower()
        healing_board = None
        if re.search(r'\b(?:healing\s*)?banner\b', _cap):
            healing_board = "Healing Banner"
        elif re.search(r'\b(?:healing\s*)?horn\b', _cap):
            healing_board = "Healing Horn"
        if healing_board:
            hh_view = HealingScoreView(message, healing_board)
            hh_prompt = await message.reply(
                f"\U0001F3BA {healing_board} run detected! Click below to enter your healing total.",
                mention_author=False,
                view=hh_view
            )
            hh_view.prompt_msg = hh_prompt
            return

        view = SubmitView(message)
        prompt = await message.reply(
            "\U0001f4cb Scorecard detected! Click below to submit your run.",
            mention_author=False,
            view=view
        )
        view.prompt_msg = prompt


async def setup(bot):
    await bot.add_cog(SubmissionsCog(bot))
