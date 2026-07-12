from datetime import datetime, timezone
# Leaderboard read/write, Discord thread management, and the index builder.
# update_leaderboards() is the main entry point — called after every submission.
import asyncio
import os
import re as _re
import discord
import random
import unicodedata
from discord import app_commands
from discord.ext import commands

import config
import utils.db as _db
from utils.helpers import nerve_log_error


async def _rank_name_ac(interaction: discord.Interaction, current: str):
    """Autocomplete /rank with real board names (weapons, feats, maps). Matches on
    normalized text too, so 'pickaxe' surfaces 'Pick Axe', 'onehanded' -> 'One-Handed Spear'."""
    cur = current.lower()
    curn = _re.sub(r'[^a-z0-9]', '', cur)
    try:
        recs = await _get_lb_records()
        boards = sorted({r['Leaderboard Name'].strip() for r in recs if r.get('Leaderboard Name')})
    except Exception:
        boards = []
    def _hit(b):
        bl = b.lower()
        return cur in bl or (curn and curn in _re.sub(r'[^a-z0-9]', '', bl))
    return [app_commands.Choice(name=b, value=b) for b in boards if _hit(b)][:25]

MOD_ROLE_ID       = config.MOD_ROLE_ID
_ASSETS_DIR       = os.path.join(os.path.dirname(__file__), '..', 'assets')
DECORATION_TOP    = os.path.join(_ASSETS_DIR, 'WMMR_Spacer_Top.png')
DECORATION_BOTTOM = os.path.join(_ASSETS_DIR, 'WMMR_Spacer_Bottom.png')
_SUBCLASS_PRIMARIES = config._SUBCLASS_PRIMARIES
FACTION_EMOJIS     = config.FACTION_EMOJIS
MAP_ATTACK_DEFENSE = config.MAP_ATTACK_DEFENSE

WEAPON_FORUM_1H          = config.WEAPONS_1H_FORUM_ID
WEAPON_FORUM_2H          = config.WEAPONS_2H_FORUM_ID
MAP_RECORDS_FORUM_ID     = config.MAP_RECORDS_FORUM_ID
FEATS_FORUM_ID           = config.FEATS_FORUM_ID
BOUNTY_CARDS_FORUM_ID    = config.BOUNTY_CARDS_FORUM_ID
REGISTRY_FORUM_ID        = config.REGISTRY_FORUM_CHANNEL_ID
LEDGER_ENTRANCE_CHANNEL_ID  = config.LEDGER_ENTRANCE_CHANNEL_ID
REGISTRY_INDEX_THREAD_ID    = config.REGISTRY_INDEX_THREAD_ID
INDEX_THREAD_2H             = config.INDEX_THREAD_2H
INDEX_THREAD_1H             = config.INDEX_THREAD_1H
INDEX_THREAD_FEATS          = config.INDEX_THREAD_FEATS

_WEAPONS_2H = {
    "Greatsword", "Maul", "War Club", "Battle Axe", "Executioner's Axe",
    "Highland Sword", "Dane Axe", "Glaive", "Two-Handed Hammer", "Halberd",
    "Polehammer", "Spear", "Quarterstaff", "Goedendag", "Pole Axe",
    "War Bow", "Crossbow", "Siege Crossbow", "Sledge Hammer", "Shovel",
}
_WEAPONS_1H = {
    "Longsword", "War Axe", "Warhammer", "Falchion", "Heavy Cavalry Sword",
    "Axe", "One-Handed Spear", "Messer", "Rapier", "Morning Star", "Sword",
    "Dagger", "Hatchet", "Cudgel", "Katars", "Short Sword", "Mace",
    "Javelin", "Throwing Axe", "Pick Axe", "Bow",
}

def _weapon_forum_id(weapon):
    if weapon in _WEAPONS_2H:
        return WEAPON_FORUM_2H
    return WEAPON_FORUM_1H

# Persists the entrance message IDs so Butler edits in-place rather than reposting.
_entrance_message_ids: dict = {}


def _lb_rows_to_records(rows):
    """Convert DB leaderboard rows [[name, thread_id, msg_ids, type], ...] to dict format."""
    return [
        {
            'Leaderboard Name': r[0],
            'Thread ID': r[1],
            'Message ID': r[2],
            'Type': r[3] if len(r) > 3 else '',
        }
        for r in rows
    ]


async def _get_lb_records():
    """Fetch all leaderboard rows as dicts."""
    return _lb_rows_to_records(await _db.get_all_leaderboards())


async def _find_index_thread(guild, forum_channel_id: int, index_label: str):
    """Return the index thread object for a forum, or None if not found yet."""
    try:
        forum = guild.get_channel(forum_channel_id)
        if not forum:
            forum = await guild.fetch_channel(forum_channel_id)
        target_name = f"📋 {index_label} Index"
        for t in forum.threads:
            if t.name == target_name:
                return t
        async for t in forum.archived_threads(limit=None):
            if t.name == target_name:
                return t
    except Exception as e:
        print(f"_find_index_thread error ({index_label}): {e}")
    return None


_ENTRANCE_GREETINGS = [
    "The Ledger is open. Mind the ash, and mind your standings.",
    "Welcome back to the lounge. Your betters are already on the boards.",
    "Records don't keep themselves. Fortunately, I do.",
    "Every mark tells a story. Most of them are cautionary tales.",
    "The cigars are lit and the leaderboards are merciless. As it should be.",
    "Another day, another chance to be politely humiliated on the boards.",
    "I have tallied everything. I always tally everything.",
    "Step in, sign the Ledger, and try to leave a mark worth remembering.",
    "The Hall of Fame has standards. The rest of you have potential.",
    "Glory is fleeting. The Ledger is forever.",
]


def _champ(v):
    """Extract a display name from a champion value that may be a str, 'N/A',
    None, or a (name, score) tuple/list."""
    if not v:
        return None
    if isinstance(v, (list, tuple)):
        return str(v[0]).strip() if v else None
    v = str(v).strip()
    return None if v in ('', 'N/A') else v


def _champion_lines(stats, keys=None):
    te = getattr(config, "TITLE_EMOJIS", {})
    rows = {
        'grand_marshal':      (te.get('Grand Marshal', '\U0001f396\ufe0f'),   'Grand Marshal'),
        'weapons_master':     (te.get('Weapons Master', '\u2694\ufe0f'),       'Weapons Master'),
        'campaign_master':    (te.get('Campaign Master', '\U0001f5fa\ufe0f'),  'Campaign Master'),
        'apex':               (te.get('apex_title', '\U0001f480'),              'Apex'),
        'frenzied':           (te.get('frenzied_title', '\U0001fa93'),          'Frenzied'),
        'most_lethal_player': (te.get('Lethality', '\U0001f9ea'),               'Kill Share'),
        'warlord_player':     (te.get('Warlord', '\U0001f6e1\ufe0f'),          'Warlord'),
    }
    order = keys or ['grand_marshal', 'weapons_master', 'campaign_master',
                     'apex', 'frenzied', 'most_lethal_player', 'warlord_player']
    out = []
    for key in order:
        emoji, label = rows[key]
        name = _champ(stats.get(key))
        if name:
            out.append(f"{emoji} **{label}** \u2014 {name}")
    return out


class EntranceView(discord.ui.View):
    """Persistent interactive buttons on the Ledger entrance dashboard."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Grab a Report", emoji="📋",
                       style=discord.ButtonStyle.secondary, custom_id="entrance:mycard")
    async def my_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            from cogs.registry import get_registry_thread_id
            tid = await get_registry_thread_id(str(interaction.user.id))
            if tid:
                url = f"https://discord.com/channels/{interaction.guild.id}/{tid}"
                await interaction.response.send_message(f"📋 Your report: {url}", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "You don't have a registry card yet — submit a run and the Butler will draw one up.",
                    ephemeral=True)
        except Exception:
            await interaction.response.send_message("Couldn't pull your card just now. Try again shortly.", ephemeral=True)

    @discord.ui.button(label="Who's Winning", emoji="👑",
                       style=discord.ButtonStyle.secondary, custom_id="entrance:winning")
    async def whos_winning(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            from cogs.favourites import calculate_butler_stats
            from datetime import datetime, timezone
            season = await _db.get_current_season()
            now = datetime.now(timezone.utc)
            if season:
                s = await calculate_butler_stats(week_start=season['started_at'].timestamp(), week_end=now.timestamp())
            else:
                s = await calculate_butler_stats()
            lines = _champion_lines(s)
            body = "\n".join(lines) if lines else "No champions crowned yet this season."
            await interaction.followup.send("👑 **Reigning champions**\n" + body, ephemeral=True)
        except Exception:
            await interaction.followup.send("Couldn't fetch the standings just now.", ephemeral=True)


_ENTRANCE_LOCK = asyncio.Lock()
_entrance_last_sig = "__init__"


async def build_ledger_entrance(guild, stats=None, force=False):
    """Serialized + change-guarded entry point. Only rebuilds when the active
    bounty changed (or when forced / first run this session), and never
    concurrently \u2014 so the entrance stops re-posting on every submission and
    can't duplicate itself from two rebuilds racing."""
    global _entrance_last_sig
    sig = None
    try:
        for b in await _db.get_all_bounties():
            if len(b) > 8 and b[8] == 'TRUE':
                sig = str(b[1]) if len(b) > 1 else 'active'
                break
    except Exception:
        pass
    async with _ENTRANCE_LOCK:
        if not force and sig == _entrance_last_sig and _entrance_message_ids:
            return
        await _build_ledger_entrance_impl(guild, stats)
        _entrance_last_sig = sig


async def _build_ledger_entrance_impl(guild, stats=None):
    """
    Post or refresh the ledger entrance in LEDGER_ENTRANCE_CHANNEL_ID.
    Mirrors the Discord sidebar structure top-to-bottom with bold hyperlinks.
    """
    try:
        channel = guild.get_channel(LEDGER_ENTRANCE_CHANNEL_ID)
        if not channel:
            channel = await guild.fetch_channel(LEDGER_ENTRANCE_CHANNEL_ID)

        guild_id = guild.id

        # Index threads
        idx_maps  = await _find_index_thread(guild, MAP_RECORDS_FORUM_ID, "Map Records")

        # Active bounty from DB
        bounty_label = "Active Bounty"
        bounty_emoji = "🎯"
        bounty_channel_id = None
        try:
            all_bounties = await _db.get_all_bounties()
            for b in all_bounties:
                if b[8] == 'TRUE':
                    bounty_label = b[0] or "Active Bounty"
                    bounty_emoji = b[3] or "🎯"
                    if b[1]:
                        bounty_channel_id = int(b[1])
                    break
        except Exception as be:
            nerve_log_error("Ledger bounty lookup", be)

        def ch_url(channel_id):
            return f"https://discord.com/channels/{guild.id}/{channel_id}"

        def make_view(*btns):
            """Build a View from (label, channel_id) pairs."""
            v = discord.ui.View(timeout=None)
            for label, cid in btns:
                if cid:
                    v.add_item(discord.ui.Button(
                        label=label, url=ch_url(cid),
                        style=discord.ButtonStyle.link,
                    ))
            return v

        # Each tuple is one message: list of (label, channel_id) buttons
        message_groups = [
            [("⚖️ Information Center",         1460713024082935930)],
            [("🗂️ Member Profiles",          REGISTRY_INDEX_THREAD_ID)],
            [("🏆 Map Records",             idx_maps.id if idx_maps else None),
             ("⚔️ 2H Weapons",             INDEX_THREAD_2H),
             ("🗡️ 1H Weapons",             INDEX_THREAD_1H)],
            [("🏛️ Feats of War",           INDEX_THREAD_FEATS)],
            [("🗄️ Hall of Fame",            config.HALL_OF_FAME_FORUM_ID)],
        ]

        # Delete all previous entrance messages then resend fresh
        bot_id = guild.me.id
        try:
            old_msgs = []
            async for msg in channel.history(limit=30, oldest_first=True):
                if msg.author.id == bot_id:
                    old_msgs.append(msg)
            for om in old_msgs:
                try:
                    await om.delete()
                except Exception:
                    pass
        except Exception as de:
            print(f"Entrance cleanup error: {de}")

        # Themed header so the entrance reads as a designed landing page, not bare buttons.
        header = discord.Embed(
            title="📜  The Archives",
            description="*" + random.choice(_ENTRANCE_GREETINGS) + "*",
            colour=discord.Colour.from_str("#C9A24B"),
        )
        _hbanner = getattr(config, 'LEDGER_ENTRANCE_BANNER_URL', '') or ''
        if _hbanner:
            header.set_image(url=_hbanner)

        _entrance_message_ids.clear()
        try:
            _hs = await channel.send(embed=header)
            _entrance_message_ids['entrance_header'] = _hs.id
        except Exception as _he:
            print(f"Entrance header send error: {_he}")
        for i, group in enumerate(message_groups):
            view = make_view(*group)
            sent = await channel.send(content="​", view=view)
            _entrance_message_ids[f'entrance_{i}'] = sent.id

        print("Ledger entrance updated.")

    except Exception as e:
        print(f"build_ledger_entrance error: {e}")


async def update_leaderboard_index(guild, forum_channel_id: int, index_label: str, blurb: str = None):
    """Rebuild the pinned index thread for a leaderboard forum using embeds."""
    try:
        import config as _cfg
        forum = guild.get_channel(forum_channel_id)
        if not forum:
            print(f"Leaderboard index: forum {forum_channel_id} not found")
            return

        index_thread_name = f"📋 {index_label} Index"

        seen_ids = set()
        threads = []
        try:
            active = await guild._state.http.get_active_threads(guild.id)
            for t_data in active.get('threads', []):
                if int(t_data['parent_id']) == forum_channel_id and t_data['name'] != index_thread_name:
                    t_obj = forum.get_thread(int(t_data['id']))
                    if not t_obj:
                        t_obj = await guild.fetch_channel(int(t_data['id']))
                    threads.append(t_obj)
                    seen_ids.add(int(t_data['id']))
        except Exception as e:
            print(f"Active threads fetch error: {e}")
            for t in forum.threads:
                if t.name != index_thread_name:
                    threads.append(t)
                    seen_ids.add(t.id)
        async for thread in forum.archived_threads(limit=None):
            if thread.name != index_thread_name and thread.id not in seen_ids:
                threads.append(thread)

        seen_base = set()
        deduped = []
        for t in sorted(threads, key=lambda t: t.name.lower()):
            base = t.name.split(' - ')[0].strip() if ' - ' in t.name else t.name
            if base not in seen_base:
                seen_base.add(base)
                deduped.append((base, t))
        deduped.sort(key=lambda x: x[0].lower())

        def make_links(items):
            return ' • '.join(
                f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                for name, t in items
            )

        def _split_field(field_name, items, max_chars=1000):
            fields = []
            current_name = field_name
            current = []
            for item in items:
                candidate = make_links(current + [item])
                if len(candidate) > max_chars and current:
                    fields.append((current_name, make_links(current)))
                    current_name = f"{field_name} (cont.)"
                    current = [item]
                else:
                    current.append(item)
            if current:
                fields.append((current_name, make_links(current)))
            return fields

        embed_fields = []

        is_weapon_index = index_label in ("1H Weapons", "2H Weapons")
        is_map_index    = index_label in ("Map Records",)

        if is_weapon_index:
            CLASS_GROUPS = [
                ("⚔️ Knight",   ["Officer", "Guardian", "Crusader"]),
                ("🗡️ Vanguard", ["Devastator", "Raider", "Ambusher"]),
                ("🛡️ Footman",  ["Poleman", "Man-at-Arms", "Field Engineer"]),
                ("🏹 Archer",   ["Longbowman", "Crossbowman", "Skirmisher"]),
            ]
            archer_weapons = set()
            for ws in _cfg.MARKSMAN_SUBCLASSES.values():
                archer_weapons.update(ws)

            placed = set()
            for group_label, subclasses in CLASS_GROUPS:
                group_weapons = archer_weapons if group_label.startswith("🏹") else set()
                for sc in subclasses:
                    group_weapons.update(_cfg.CLASS_WEAPON_MAP.get(sc, []))
                group_items = [(n, t) for n, t in deduped if n in group_weapons and n not in placed]
                if not group_items:
                    continue
                group_items.sort(key=lambda x: x[0])
                placed.update(n for n, _ in group_items)
                # Newline-separated links, one weapon per line
                val = "\n".join(
                    f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                    for name, t in group_items
                )
                embed_fields.append((group_label, val))
            remainder = [(n, t) for n, t in deduped if n not in placed]
            if remainder:
                val = "\n".join(
                    f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                    for name, t in sorted(remainder, key=lambda x: x[0])
                )
                embed_fields.append(("Other", val))

        elif is_map_index:
            # Alphabetical groups, one map per line
            alpha_groups = [
                ("A – F", "A", "F"),
                ("G – M", "G", "M"),
                ("N – Z", "N", "Z"),
            ]
            placed_maps = set()
            for gname, start, end in alpha_groups:
                grp = [(n, t) for n, t in deduped if n and start[0] <= n[0].upper() <= end[0]]
                if grp:
                    val = "\n".join(
                        f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                        for name, t in grp
                    )
                    embed_fields.append((gname, val))
                    placed_maps.update(n for n, _ in grp)
            other_maps = [(n, t) for n, t in deduped if n not in placed_maps]
            if other_maps:
                val = "\n".join(
                    f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                    for name, t in other_maps
                )
                embed_fields.append(("Other", val))

        else:
            # Feats of War — alphabetical groups, one feat per line
            groups = [('A – D', 'A', 'D'), ('E – K', 'E', 'K'), ('L – R', 'L', 'R'), ('S – Z', 'S', 'Z')]
            for group_name, start, end in groups:
                grp = [(n, t) for n, t in deduped if n and start[0] <= n[0].upper() <= end[0]]
                if grp:
                    val = "\n".join(
                        f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                        for name, t in grp
                    )
                    embed_fields.append((group_name, val))
            other = [(n, t) for n, t in deduped if not n or not n[0].upper().isalpha()]
            if other:
                val = "\n".join(
                    f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                    for name, t in other
                )
                embed_fields.append(('#', val))

        def _build_embeds(fields):
            embeds = []
            for i in range(0, max(len(fields), 1), 25):
                chunk = fields[i:i + 25]
                if is_map_index:
                    colour = discord.Colour.from_str("#2b2d31")
                elif is_weapon_index:
                    colour = discord.Colour.from_str("#2b2d31")
                else:
                    colour = discord.Colour.from_str("#2b2d31")
                if is_map_index:
                    _title_icon = "🗺️"
                elif is_weapon_index:
                    _title_icon = "⚔️"
                else:
                    _title_icon = "📋"
                e = discord.Embed(
                    title=f"{_title_icon} {index_label} Index",
                    description=blurb if (i == 0 and blurb) else ("Jump to a board below" if i == 0 else None),
                    colour=colour,
                )
                for fname, fval in chunk:
                    e.add_field(name=fname, value=fval, inline=False)
                embeds.append(e)
            return embeds

        def _safe_fields(fields):
            # Discord rejects an embed (400 / 50035) if any field value is empty or
            # >1024 chars. Split long link-lists on line boundaries; drop empties.
            out = []
            for fname, fval in fields:
                fval = (fval or "").strip()
                if not fval:
                    continue
                fname = (str(fname).strip() or "\u200b")[:256]
                if len(fval) <= 1024:
                    out.append((fname, fval[:1024]))
                    continue
                cur = ""
                first = True
                for ln in fval.split("\n"):
                    add = ln if not cur else "\n" + ln
                    if len(cur) + len(add) > 1024:
                        if cur:
                            out.append((fname if first else "\u200b", cur[:1024]))
                            first = False
                        cur = ln[:1024]
                    else:
                        cur += add
                if cur:
                    out.append((fname if first else "\u200b", cur[:1024]))
            return out or [("No boards yet", "*Nothing here yet.*")]

        if not embed_fields:
            embed_fields = [("No boards yet", "*Nothing here yet.*")]
        embeds = _build_embeds(_safe_fields(embed_fields))

        _known_index_ids = {
            "1H Weapons":  INDEX_THREAD_1H,
            "2H Weapons":  INDEX_THREAD_2H,
            "Feats of War": INDEX_THREAD_FEATS,
        }
        index_thread = None
        if index_label in _known_index_ids:
            try:
                index_thread = guild.get_channel(_known_index_ids[index_label]) or \
                               await guild.fetch_channel(_known_index_ids[index_label])
            except Exception:
                pass
        if not index_thread:
            for t in forum.threads:
                if t.name == index_thread_name:
                    index_thread = t
                    break
        if not index_thread:
            async for t in forum.archived_threads(limit=None):
                if t.name == index_thread_name:
                    index_thread = t
                    break

        if index_thread:
            msgs = []
            async for msg in index_thread.history(limit=50, oldest_first=True):
                msgs.append(msg)
            for msg in msgs[1:]:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
            for embed in embeds:
                await asyncio.sleep(0.5)
                await index_thread.send(embed=embed)
            print(f"Leaderboard index updated: {index_label}")
        else:
            result = await forum.create_thread(name=index_thread_name, content="**➜ INDEX**")
            await asyncio.sleep(0.5)
            for embed in embeds:
                await asyncio.sleep(0.5)
                await result.thread.send(embed=embed)
            print(f"Leaderboard index created: {index_label}")

    except Exception as e:
        print(f"Leaderboard index error ({index_label}): {e}")


async def _sync_board_messages(thread, embeds, message_ids, msg_content=""):
    """Edit each board message in place; on edit failure, delete the orphaned
    original (best-effort) and post a fresh message instead of leaving a stale
    duplicate behind. If anything had to be recreated, also repost a fresh
    DECORATION_BOTTOM so the new message doesn't end up sitting outside the
    board's decorative frame (the top/bottom spacer images are only posted once,
    by /setup_leaderboard — none of the refresh paths ever touched them, so a
    recreated message looked like a bare, undecorated leaderboard post). Returns
    the new list of message IDs, same length/order as embeds.

    Consolidated from update_leaderboards / refresh_leaderboard /
    refresh_all_leaderboards, which each had this loop duplicated with the same
    orphan-on-failure bug (Glaive board duplicate, found 2026-06-30).
    """
    new_ids = []
    recreated = False
    for i, emb in enumerate(embeds):
        if i < len(message_ids):
            edited = False
            try:
                msg = await thread.fetch_message(message_ids[i])
                await msg.edit(content=msg_content, embed=emb)
                new_ids.append(message_ids[i])
                edited = True
            except Exception as edit_err:
                print(f"Leaderboard edit failed for msg {message_ids[i]} in #{thread.id}, posting fresh: {edit_err}")
            if not edited:
                try:
                    old_msg = await thread.fetch_message(message_ids[i])
                    await old_msg.delete()
                except Exception:
                    pass
                msg = await thread.send(content=msg_content, embed=emb)
                new_ids.append(msg.id)
                recreated = True
        else:
            msg = await thread.send(content=msg_content, embed=emb)
            new_ids.append(msg.id)
            recreated = True

    if recreated:
        try:
            await thread.send(file=discord.File(DECORATION_BOTTOM))
        except Exception as deco_err:
            print(f"Decoration repost failed in #{thread.id}: {deco_err}")

    # If the tracked message_ids list was longer than the number of embeds we
    # actually have (leftover from an older posting scheme that tracked more
    # messages per board than it should have), the leftover IDs were never
    # touched by the loop above and would sit in the thread forever as an
    # orphan no one ever edits or deletes again — found 2026-06-30 on map
    # boards as a duplicate plain-text header sitting above the real embed.
    for extra_id in message_ids[len(embeds):]:
        try:
            extra_msg = await thread.fetch_message(extra_id)
            await extra_msg.delete()
        except Exception:
            pass

    return new_ids


async def update_leaderboards(interaction, selected_weapon, selected_map, faction,
                              takedowns, kills, deaths, vip, feats,
                              player_name, message_link, bot_user=None, second_place_td=None, score=None):
    guild = interaction.guild
    discord_id = str(interaction.user.id)
    any_updated = False  # True only when player beats their own score on a weapon/feat board (not map boards)
    placements = []

    updates = []

    # A pacifist run = no kills and at most a handful of takedowns (objective / support
    # play). These earn NO weapon marks and stay off the weapon/map/takedown boards —
    # they only land on the Pacifist board (below). Defined independent of score so the
    # exclusion is consistent even when vision misses the score number.
    is_pacifist = (kills == 0 and takedowns <= 10)

    # Guard against junk boards: never create a board for a missing/None weapon or
    # map (that's what produced "None - Agatha" and blank weapon boards).
    if (not vip and selected_weapon and str(selected_weapon).strip()
            and str(selected_weapon).strip().lower() != 'none' and takedowns > 0
            and not is_pacifist):
        updates.append((selected_weapon, takedowns, True, True, False))

    map_lb_name = f"{selected_map} - {faction}"
    if (selected_map and str(selected_map).strip() and str(selected_map).strip().lower() != 'none'
            and faction and str(faction).strip() and takedowns > 0
            and not is_pacifist):
        updates.append((map_lb_name, takedowns, True, True, False))

    if "Flawless" in feats:
        updates.append(("Flawless", takedowns, False, True, False))
    # Board placement uses raw stats — independent of feat mark counting
    # Triples also qualify for 100 Kills / 200 Takedowns boards if stats meet threshold
    if kills >= 100:
        updates.append(("100 Kills", kills, False, False, True))
    if takedowns >= 200:
        updates.append(("200 Takedowns", takedowns, False, False, True))
    if "Triple" in feats:
        updates.append(("Triple", takedowns, False, False, True))
    if selected_weapon == "Mallet" and kills >= 100:
        updates.append(("Mallet", takedowns, True, True, False))
    if selected_weapon == "Knife" and kills >= 100:
        updates.append(("Knife", takedowns, True, True, False))
    if selected_weapon == "Healing Horn" and kills >= 100:
        updates.append(("Healing Horn", kills, False, True, False))
    if second_place_td is not None and kills is not None:
        tuff_gap = kills - second_place_td
        if tuff_gap > 0:
            updates.append(("TUFF", tuff_gap, False, False, True))

    # Pacifist: highest scoreboard SCORE with 0 kills and <=10 takedowns (objective / support play).
    if is_pacifist and score and score > 0:
        updates.append(("Pacifist", score, False, False, True))

    # Board setup rows (small) fetched once; each board's ENTRIES are read targeted
    # inside the loop via the indexed get_leaderboard_by_board — no full-table scan.
    all_lb_rows = await _get_lb_records()

    for lb_name, score, top_10, personal_best, unlimited_top50 in updates:
        board_values = await _db.get_leaderboard_by_board(lb_name)
        # Find existing entry for this player on this board
        existing_score = None
        for row in board_values:
            if row[2] == discord_id:
                existing_score = int(row[3]) if row[3] else 0
                break
        existing_entry = existing_score is not None

        if lb_name == "Pacifist":
            # Per-player top 10, ranked fewest-takedowns-then-score. Skip if this exact
            # run is already on the board; add it, then prune everyone to their best 10.
            if any(r[2] == discord_id and (r[4] if len(r) > 4 else '') == (message_link or '')
                   for r in board_values):
                continue
            await _db.add_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
            await _prune_pacifist_board()
            any_updated = True
            continue

        if unlimited_top50:
            # No cap — but skip if this exact submission link already on the board
            already_exists = any(
                r[2] == discord_id
                and (r[4] if len(r) > 4 else '') == (message_link or '')
                for r in board_values
            )
            if already_exists:
                continue
            await _db.add_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
            any_updated = True
            all_board = [int(r[3]) for r in board_values if len(r) > 3 and r[3]]
            all_board.append(score)
            all_board.sort(reverse=True)
            pos = all_board.index(score) + 1
            placements.append((lb_name, pos))
        elif personal_best:
            if existing_entry:
                if score > existing_score:
                    await _db.upsert_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
                    _all = sorted([int(r[3]) for r in board_values if len(r) > 3 and r[3]], reverse=True)
                    board_scores = [s for s in _all if s != existing_score]
                    board_scores.append(score)
                    board_scores.sort(reverse=True)
                    pos = board_scores.index(score) + 1
                    old_pos = (_all.index(existing_score) + 1) if existing_score in _all else pos + 1
                    # High Score fires only when the run IMPROVES the player's board
                    # placement (climbs at least one spot) — NOT when they merely beat their
                    # own score in the same slot. (Making the board for the first time is the
                    # new-entry branch below, which already registers it.)
                    if pos < old_pos:
                        any_updated = True
                        placements.append((lb_name, pos))
                else:
                    continue
            else:
                if top_10:
                    board_entries = list(board_values)
                    board_entries_sorted = sorted(
                        board_entries, key=lambda x: int(x[3]) if len(x) > 3 and x[3] else 0, reverse=True
                    )
                    if len(board_entries_sorted) >= 10:
                        lowest_score = int(board_entries_sorted[9][3]) if board_entries_sorted[9][3] else 0
                        if score <= lowest_score:
                            continue
                        # Evict the actual lowest-scoring row by identity — NOT by
                        # discord_id. Legacy entries have blank discord_ids, and
                        # deleting by ''+oldest nuked arbitrary high legacy rows.
                        await _db.delete_lowest_leaderboard_entry(lb_name)
                        board_values = await _db.get_leaderboard_by_board(lb_name)
                await _db.upsert_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
                any_updated = True  # New entry on a board counts as a PB
                board_scores = sorted([int(r[3]) for r in board_values if len(r) > 3 and r[3]], reverse=True)
                board_scores.append(score)
                board_scores.sort(reverse=True)
                pos = board_scores.index(score) + 1
                placements.append((lb_name, pos))
        else:
            await _db.add_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
            any_updated = True
            board_scores = sorted([int(r[3]) for r in board_values if len(r) > 3 and r[3]], reverse=True)
            board_scores.append(score)
            board_scores.sort(reverse=True)
            pos = board_scores.index(score) + 1
            placements.append((lb_name, pos))

        # Reload just this board (indexed) instead of scanning the whole table
        board_rows = await _db.get_leaderboard_by_board(lb_name)
        entries = []
        for row in board_rows:
            entries.append({
                'player': row[1] if len(row) > 1 else '',
                'did': row[2] if len(row) > 2 else '',
                'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                'link': row[4] if len(row) > 4 else '',
                'weapon': row[5] if len(row) > 5 else '',
            })
        entries = sorted(entries, key=lambda x: x['score'], reverse=True)

        show_weapon = lb_name in ("100 Kills", "200 Takedowns")
        score_prefix = "+" if lb_name == "TUFF" else ""
        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
        if not lb_row:
            print(f"No leaderboards DB entry found for: {lb_name}")
            continue
        is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
        embeds = await _rated_embeds(lb_name, entries, is_map, None, 0, show_weapon, score_prefix, not is_map)
        header_content = _map_header(lb_name) if is_map else ""

        thread_id = int(lb_row['Thread ID'])
        message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(lb_row['Message ID']))]

        try:
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
            new_ids = await _sync_board_messages(thread, embeds, message_ids, msg_content=header_content)
            if new_ids != message_ids:
                await _db.update_leaderboard_messages(lb_name, '|'.join(str(m) for m in new_ids))
        except Exception as e:
            print(f"Discord update error for {lb_name}: {e}")

    return any_updated, placements


# Boards that have their own qualifying rules / are unlimited — handled by
# /backfill_feat_boards, NOT by the weapon/map rebuild below.
_FEAT_BOARD_NAMES = {
    "100 Kills", "200 Takedowns", "Triple", "TUFF",
    "Flawless", "Mallet", "Knife", "Healing Horn", "Pacifist",
}


def _classify_board(name, board_type):
    """Return 'map', 'feat', or 'weapon' for a board."""
    t = (board_type or '').strip().lower()
    if t == 'map' or (' - ' in name and name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE):
        return 'map'
    if name in _FEAT_BOARD_NAMES:
        return 'feat'
    return 'weapon'


def _safe_int(v, default=0):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return default


async def _sort_board_entries(lb_name, entries):
    """Sort a board's entry dicts for display. Pacifist shows ONE row per player
    (their best run), ranked by score descending — ties broken by fewest takedowns;
    takedowns are pulled from each entry's linked submission and stashed on 'td' for
    the '{td} TD · {score}' display. Every other board ranks by score descending.
    Shared by _render_board and the /refresh commands so ordering can't drift."""
    if lb_name != "Pacifist":
        return sorted(entries, key=lambda x: x['score'], reverse=True)
    subs = await _db.get_all_submissions()
    tdl = {}
    for s in subs:
        if len(s) > 12 and s[12].strip():
            try:
                tdl[s[12].strip()] = int(s[7])
            except (ValueError, TypeError):
                pass
    for en in entries:
        en['td'] = tdl.get((en.get('link') or '').strip())
    def _rank(en):
        return (-en['score'], en['td'] if en['td'] is not None else 999)
    best = {}
    for en in entries:
        pid = (en.get('did') or '').strip() or ('name:' + (en.get('player') or '').strip().lower())
        if pid not in best or _rank(en) < _rank(best[pid]):
            best[pid] = en
    return sorted(best.values(), key=_rank)


async def _prune_pacifist_board():
    """Pacifist board keeps ONE row per player — their highest-scoring run (ties
    broken by fewest takedowns) — so a specialist can't crowd it with duplicates.
    Takedowns are read from each entry's linked submission (board rows store only
    score, so ranking is derived on the fly — no schema change / migration needed)."""
    rows = await _db.get_leaderboard_by_board("Pacifist")
    subs = await _db.get_all_submissions()
    td_by_link = {}
    for s in subs:
        if len(s) > 12 and s[12].strip():
            try:
                td_by_link[s[12].strip()] = int(s[7])
            except (ValueError, TypeError):
                pass
    def _key(r):
        lnk = (r[4] if len(r) > 4 else '').strip()
        td = td_by_link.get(lnk, 999)
        sc = int(r[3]) if len(r) > 3 and r[3] else 0
        return (-sc, td)                        # best score first, then fewest takedowns
    by_player = {}
    for r in rows:
        pid = (r[2] or '').strip() or ('name:' + (r[1] or '').strip().lower())
        by_player.setdefault(pid, []).append(r)
    deleted = 0
    for _pid, plist in by_player.items():
        plist.sort(key=_key)
        for extra in plist[1:]:
            lnk = (extra[4] if len(extra) > 4 else '').strip()
            if lnk:
                await _db.delete_leaderboard_entry_by_link("Pacifist", lnk)
                deleted += 1
    return deleted


async def _render_board(guild, lb_row, lb_name):
    """Re-render a single board's Discord messages from its current DB rows."""
    # A board with no thread/message ids was never set up in Discord — skip it
    # rather than crashing the whole rebuild on int('').
    thread_raw = str(lb_row.get('Thread ID') or '').strip()
    msg_raw = str(lb_row.get('Message ID') or '').strip()
    if not thread_raw or not msg_raw:
        print(f"[REBUILD] Skipping render for '{lb_name}' — no thread/message id.")
        return
    board_rows = await _db.get_leaderboard_by_board(lb_name)
    entries = []
    for row in board_rows:
        entries.append({
            'player': row[1] if len(row) > 1 else '',
            'did': row[2] if len(row) > 2 else '',
            'score': _safe_int(row[3]) if len(row) > 3 else 0,
            'link': row[4] if len(row) > 4 else '',
            'weapon': row[5] if len(row) > 5 else '',
        })
    entries = await _sort_board_entries(lb_name, entries)
    show_weapon = lb_name in ("100 Kills", "200 Takedowns")
    score_prefix = "+" if lb_name == "TUFF" else ""
    is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
    embeds = await _rated_embeds(lb_name, entries, is_map, None, 0, show_weapon, score_prefix, not is_map)
    header_content = _map_header(lb_name) if is_map else ""
    thread_id = int(thread_raw)
    message_ids = [int(m) for m in _re.findall(r'\d{17,20}', msg_raw)]
    if not message_ids:
        print(f"[REBUILD] Skipping render for '{lb_name}' — no valid message ids.")
        return
    try:
        thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
        new_ids = await _sync_board_messages(thread, embeds, message_ids, msg_content=header_content)
        if new_ids != message_ids:
            await _db.update_leaderboard_messages(lb_name, '|'.join(str(m) for m in new_ids))
    except Exception as e:
        print(f"Discord update error for {lb_name}: {e}")


async def rebuild_score_boards(guild, board_names=None, only_player=None, render=True):
    """Rebuild weapon + map boards from the full submission history.

    Additive by design: recovers each player's best qualifying score per board
    (weapon boards exclude VIP runs, map boards include them), merges it with
    whatever is already on the board (keeping the higher score so true legacy
    entries with no matching submission are preserved), then re-caps to top-10.

    board_names — restrict to these boards (None = every weapon + map board).
    only_player — restrict the submission scan to one discord_id (used by edits).
    """
    all_lb_records = await _get_lb_records()
    all_subs = await _db.get_all_submissions()
    summary = {'boards': 0, 'added': 0, 'updated': 0, 'evicted': 0}

    for rec in all_lb_records:
        nm = rec['Leaderboard Name']
        kind = _classify_board(nm, rec.get('Type', ''))
        if kind not in ('weapon', 'map'):
            continue
        if board_names is not None and nm not in board_names:
            continue

        # 1. Best qualifying submission per player for this board.
        best = {}  # discord_id -> (score, player_name, link, weapon)
        for s in all_subs:
            if len(s) < 13:
                continue
            did = s[2] or ''
            if only_player is not None and did != str(only_player):
                continue
            pname_s = (s[1] or '').strip()
            # Legacy submissions have blank discord_ids. Key them by name (synthetic
            # "legacy:<name>" id) so they still land on boards AND re-runs stay
            # idempotent (upsert on the synthetic id updates in place).
            key = did if did else (f"legacy:{pname_s.lower()}" if pname_s else '')
            try:
                td = int(s[7]) if s[7] else 0
            except (ValueError, TypeError):
                td = 0
            if kind == 'weapon':
                if s[3] != nm:
                    continue
                if (s[10] or '').strip().lower() == 'yes':  # VIP excluded from weapon boards
                    continue
                score = td
            else:  # map board: "{map} - {faction}"
                if f"{s[5]} - {s[6]}" != nm:
                    continue
                score = td
            if score <= 0 or not key:
                continue
            cur = best.get(key)
            if cur is None or score > cur[0]:
                best[key] = (score, s[1] or '', s[12] or '', s[3] or '')

        # 2. Merge additively with existing entries (keep the higher score).
        existing_rows = await _db.get_leaderboard_by_board(nm)
        existing_by_id = {}
        for r in existing_rows:
            eid = (r[2] if len(r) > 2 else '') or ''
            ename = (r[1] if len(r) > 1 else '').strip()
            ekey = eid if eid else (f"legacy:{ename.lower()}" if ename else '')
            esc = _safe_int(r[3]) if len(r) > 3 else 0
            if ekey and (ekey not in existing_by_id or esc > existing_by_id[ekey]):
                existing_by_id[ekey] = esc
        for key, (score, pname, link, wpn) in best.items():
            ex = existing_by_id.get(key)
            if ex is not None and score <= ex:
                continue
            # For name-keyed legacy entries, clear any stale blank-id row for that
            # name first so the synthetic-id upsert doesn't leave a duplicate.
            if key.startswith('legacy:'):
                await _db.delete_blank_id_entries_by_name(nm, pname)
            await _db.upsert_leaderboard_entry(nm, pname, key, score, link, wpn)
            if ex is None:
                summary['added'] += 1
            else:
                summary['updated'] += 1

        # 3. Cap to top-10 (weapon + map boards are top-10 boards). Trim by
        # deleting the true lowest row each time — origin-agnostic, so a low
        # submission-backed entry goes before an equal/higher legacy one.
        rows = await _db.get_leaderboard_by_board(nm)
        for _ in range(max(0, len(rows) - 10)):
            await _db.delete_lowest_leaderboard_entry(nm)
            summary['evicted'] += 1

        summary['boards'] += 1
        if render:
            await _render_board(guild, rec, nm)

    return summary


async def post_scorecard_to_threads(guild, lb_names, original_message):
    """Re-upload scorecard image to each leaderboard thread."""
    if not original_message.attachments:
        return
    attachment = original_message.attachments[0]
    if not (attachment.content_type or "").startswith("image/"):
        return
    try:
        import aiohttp, io as _io
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    return
                image_bytes = await resp.read()
    except Exception as e:
        print(f"[SCORECARD_UPLOAD] Fetch failed: {e}")
        return

    all_lb_rows = await _get_lb_records()
    posted = set()
    for lb_name in lb_names:
        lb_row = next((r for r in all_lb_rows if r["Leaderboard Name"] == lb_name), None)
        if not lb_row:
            continue
        thread_id = int(lb_row["Thread ID"])
        if thread_id in posted:
            continue
        try:
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
            import io as _io2
            await thread.send(file=discord.File(_io2.BytesIO(image_bytes), filename=attachment.filename))
            posted.add(thread_id)
            print(f"[SCORECARD_UPLOAD] Posted to {lb_name} thread {thread_id}")
        except Exception as e:
            print(f"[SCORECARD_UPLOAD] Failed for {lb_name}: {e}")


async def get_leaderboard_entries(name):
    rows = await _db.get_all_leaderboard_data()
    entries = []
    for row in rows:
        if row[0] == name:
            entries.append({
                'player': row[1] if len(row) > 1 else '',
                'did': row[2] if len(row) > 2 else '',
                'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                'link': row[4] if len(row) > 4 else '',
                'weapon': row[5] if len(row) > 5 else ''
            })
    return sorted(entries, key=lambda x: x['score'], reverse=True)


def pack_chunks_into_slots(chunks, num_slots):
    if num_slots == 0:
        return []

    if len(chunks) <= num_slots:
        packed = list(chunks)
        while len(packed) < num_slots:
            packed.append("​")
        return packed

    packed = list(chunks[:num_slots - 1])
    last = chunks[num_slots - 1]
    for extra in chunks[num_slots:]:
        candidate = last + "\n" + extra
        if len(candidate) <= 1900:
            last = candidate
        else:
            last = last + "\n*...continued*"
            break
    packed.append(last)
    return packed


def format_leaderboard_text(entries, overflow=0, show_weapon=False, score_prefix=""):
    if not entries:
        return ["No entries yet."]

    lines = []
    for idx, e in enumerate(entries, 1):
        weapon_str = f" — *{e['weapon']}*" if show_weapon and e.get('weapon') else ""
        score_str = f"{score_prefix}{e['score']}"
        if e['link']:
            lines.append(f"{idx}. **{e['player']}** — [{score_str}]({e['link']}){weapon_str}")
        else:
            lines.append(f"{idx}. **{e['player']}** — {score_str}{weapon_str}")

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


EMBED_GOLD = 0xC8952C
_FACTION_COLOUR = {
    "Mason":   0xC0392B,   # red
    "Agatha":  0x2471A3,   # blue
    "Tenosia": 0xD4AC0D,   # gold/yellow
}

def _embed_colour(lb_name):
    """Return faction colour for map boards, gold otherwise."""
    if ' - ' in lb_name:
        faction = lb_name.split(' - ', 1)[1]
        return _FACTION_COLOUR.get(faction, EMBED_GOLD)
    return EMBED_GOLD
EMBED_DESC_LIMIT = 3800  # leave headroom below Discord's 4096 limit

from utils.ranks import HH_ARCHER as _HH_ARCHER, HH_PRIMARIES as _HH_PRIMARIES, HH_TOTAL
_HH_LEGACY_COMPLETERS = [
    "Godfather", "UFO", "Ascension", "UrAMoran", "Kwazievil",
    "Flymolo", "SteezyPilgor", "Bald Female", "Teapho", "Roam",
    "C10H15N", "BallsMajoney"
]


def _map_header(lb_name: str) -> str:
    """Return the text CONTENT header for a map board message, e.g.
    '[icon] Falmire Agatha [icon]' — sent as the message's content alongside
    the embed, not as the embed's own title (the title renders inside the
    bordered/colored box; this is meant to sit visibly outside it, matching
    how these boards originally looked). MAP_ATTACK_DEFENSE[map] is
    (attack_faction, defense_faction) — used here to pick the closing icon.
    """
    if ' - ' not in lb_name:
        return lb_name
    map_name, faction = lb_name.split(' - ', 1)
    emoji = FACTION_EMOJIS.get(faction, '⚔️')
    map_info = config.MAP_ATTACK_DEFENSE.get(map_name)
    is_attack = bool(map_info) and map_info[0] == faction
    suffix = "<:weapon_hs:1350656128635375698>" if is_attack else "🛡️"
    return f"{emoji} **{map_name} {faction}** {suffix}"

_LB_EMOJI = {
    "TUFF":             "<a:TUFF2:1520779243879927898>",
    "Pacifist":         "<a:passive:1365531248268673086>",
    "200 Takedowns":    "<a:200tkd:1363648828414230538>",
    "100 Kills":        "<a:100kill:1361412390339608686>",
    "Triple":           "<a:triple:1365532698260668466>",
    "Flawless":         "<a:flawless:1360358300834599062>",
    "The Hundred Handed": "<:hhanded:1430199468246044772>",
    "Knife":            "\U0001f5e1\ufe0f",
    "Mallet":           "\U0001f528",
}

def _lb_title(lb_name, show_title, cont=False):
    """Embed title for a board (weapon/feat emoji lookup). Map boards never use
    this for their header — that's _map_header(), sent as separate message
    content above the bordered embed, not as the embed's own title field (user
    preference, 2026-06-30: header should sit outside the embed border)."""
    if not show_title:
        return None
    emoji = _LB_EMOJI.get(lb_name)
    base = emoji if emoji else lb_name
    return f"{base} (cont.)" if cont else base

async def compute_board_ratings(lb_name, is_map=False, all_subs=None, map_totals=None, window_start=None):
    """Peak best-5-consecutive-game Lethality (kills/TD) and Warlord (takedowns as a share of your team's
    total kills) for a weapon or map board. Rating never drops \u2014 it is the best 5-game
    window a player has ever posted with that weapon/map. Minimum 5 games for
    weapons; for maps the minimum scales with the map's popularity vs the busiest
    map (rare maps need fewer). Weapon boards exclude VIP; map boards allow it.
    Returns (lethality_rows, warlord_rows, min_games) with rows = sorted [(player, score)]."""
    subs = all_subs if all_subs is not None else await _db.get_all_submissions()

    # Monthly ratings only: drop resubmissions (feats contains "Resubmit") and,
    # when window_start (a UTC timestamp) is given, anything before that instant.
    def _rk(r):
        if len(r) > 11 and r[11] and 'Resubmit' in str(r[11]):
            return False
        if window_start is not None:
            try:
                _t = datetime.strptime(str(r[0]).strip()[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
                if _t < window_start:
                    return False
            except Exception:
                return False
        return True
    subs = [r for r in subs if _rk(r)]

    if is_map:
        if map_totals is None:
            map_totals = {}
            for r in subs:
                if len(r) > 6 and r[5].strip() and r[6].strip():
                    k = f"{r[5].strip()} - {r[6].strip()}"
                    map_totals[k] = map_totals.get(k, 0) + 1
        busiest = max(map_totals.values()) if map_totals else 1
        this_total = map_totals.get(lb_name, 0)
        min_games = max(1, min(5, round(5 * this_total / busiest))) if busiest else 5
    else:
        # Scale the game minimum by weapon popularity (same idea as maps): the busiest
        # weapon needs a full 5-game sample; off-hand 1H weapons need as few as 2, so their
        # Lethality/Warlord ratings actually show instead of being blank.
        weapon_totals = {}
        for _r in subs:
            _w = _r[3].strip() if len(_r) > 3 and _r[3] else ''
            if _w:
                weapon_totals[_w] = weapon_totals.get(_w, 0) + 1
        _busiest_w = max(weapon_totals.values()) if weapon_totals else 1
        _this_w = weapon_totals.get(lb_name, 0)
        min_games = max(2, min(5, round(5 * _this_w / _busiest_w))) if _busiest_w else 5

    # Resolve discord_id -> current display name (Players sheet is source of truth).
    # One person can submit under several display names; bucket by stable id so they
    # collapse into a single rating row instead of appearing as duplicates. Legacy
    # rows have blank discord_ids -> key them by name (matching rebuild_score_boards).
    id_to_name = {}
    try:
        for prow in await _db.get_all_players():
            if prow and len(prow) > 1 and (prow[0] or '').strip():
                id_to_name[str(prow[0]).strip()] = (prow[1] or '').strip()
    except Exception:
        pass

    leth, warl = {}, {}
    names = {}  # key -> display name to show
    for row in subs:
        if len(row) < 9:
            continue
        if is_map:
            m = row[5].strip() if len(row) > 5 else ''
            fac = row[6].strip() if len(row) > 6 else ''
            if not m or not fac or f"{m} - {fac}" != lb_name:
                continue
        else:
            if (row[3].strip() if len(row) > 3 else '') != lb_name:
                continue
            _vip = str(row[10]).strip().upper() in ('TRUE', '1', 'YES') if len(row) > 10 and row[10] else False
            if _vip:
                continue
        player = row[1].strip()
        did = row[2].strip() if len(row) > 2 and row[2] else ''
        key = did if did else (f"legacy:{player.lower()}" if player else '')
        if not key:
            continue
        # Prefer the current Players-sheet name for real ids; else the submission name.
        names[key] = _lb_display_name(id_to_name.get(did) or names.get(key) or player, did)
        ts = row[0].strip()
        try:
            td = int(row[7]); kills = int(row[8])
        except (ValueError, IndexError):
            td = kills = 0
        if is_map:
            # Map boards: Kill Share (kills / team total kills) + Warlord (takedowns / team total kills).
            # team_total_kills = kills / kill-share, so TD/team_kills reduces to td * tks / kills.
            try:
                _tks = float(row[20]) if len(row) > 20 and row[20] else None
            except (ValueError, TypeError):
                _tks = None
            if _tks and 0 < _tks <= 100:
                leth.setdefault(key, []).append((ts, _tks))                     # Kill Share %
                if kills > 0 and td > 0:
                    warl.setdefault(key, []).append((ts, td * _tks / kills))    # Warlord % (TD/team kills)
        else:
            # Weapon boards: Lethality (kills/TD) + Warlord (takedowns / team total kills),
            # unified with map boards + the season title. team_total_kills = kills / kill-share,
            # so TD/team_kills reduces to td * tks / kills.
            if td > 0 and kills > 0:
                leth.setdefault(key, []).append((ts, kills / td))
            try:
                _tks = float(row[20]) if len(row) > 20 and row[20] else None
            except (ValueError, TypeError):
                _tks = None
            if _tks and 0 < _tks <= 100 and kills > 0 and td > 0:
                warl.setdefault(key, []).append((ts, td * _tks / kills))

    def _peak(dct):
        out = []
        for k, arr in dct.items():
            if len(arr) < min_games:
                continue
            vals = [v for _, v in sorted(arr)]
            w = min(5, len(vals))
            best = max(sum(vals[i:i + w]) / w for i in range(len(vals) - w + 1))
            out.append((names.get(k, k), best))
        out.sort(key=lambda t: -t[1])
        return out

    return _peak(leth), _peak(warl), min_games


async def _rated_embeds(lb_name, entries, is_map, all_subs=None, overflow=0, show_weapon=False, score_prefix="", show_title=True):
    """Takedown board embeds WITH live rating fields appended: weapon boards show
    Lethality (kills/TD) + Warlord (takedowns/team kills); map boards show
    Kill Share (kills/team kills) + Warlord (takedowns/team kills). All-time best
    5-game streak, so a rating never drops for a bad game."""
    lr = wr = None
    rmin = 5
    try:
        lr, wr, rmin = await compute_board_ratings(lb_name, is_map, all_subs)
    except Exception as e:
        print(f"[BOARD] rating compute error for {lb_name}: {e}")
    return format_leaderboard_embeds(lb_name, entries, overflow, show_weapon, score_prefix, show_title,
                                     lethality_rows=lr, warlord_rows=wr, rating_min=rmin, is_map=is_map)


def _append_rating_fields(embeds, lethality_rows, warlord_rows, rating_min, is_map=False):
    if not embeds or (not lethality_rows and not warlord_rows):
        return
    te = getattr(config, 'TITLE_EMOJIS', {})
    def _fld(rows, fmt):
        out = []
        for i, (p, sc) in enumerate((rows or [])[:5], 1):
            out.append(f"`{i}.` `{p}` \u2014 {fmt(sc)}")
        return "\n".join(out) if out else "*Not enough games yet.*"
    tail = embeds[-1]
    _le = te.get('Lethality', '🧪')
    _we = te.get('Warlord', '🛡️')
    if lethality_rows is not None:
        if is_map:
            # Map boards: Kill Share (kills / team kills), value already a %.
            tail.add_field(name=f"{_le} Kill Share",
                           value=_fld(lethality_rows, lambda s: f"{s:.0f}%"), inline=False)
        else:
            # Weapon boards: Lethality (kills / TD), value is a 0-1 ratio.
            tail.add_field(name=f"{_le} Lethality",
                           value=_fld(lethality_rows, lambda s: f"{s * 100:.0f}%"), inline=False)
    if warlord_rows is not None:
        tail.add_field(name=f"{_we} Warlord",
                       value=_fld(warlord_rows, lambda s: f"{s:.0f}%"), inline=False)
    _min_txt = f"{rating_min}+ games"
    tail.add_field(
        name="\u200b",
        value=(f"*These rank everyone with {_min_txt} — separate from the takedown order "
               "above, so you don't need the takedown top 10. Your score is the best "
               "5-games-in-a-row average you've posted, and it never drops.*"),
        inline=False,
    )


def format_leaderboard_embeds(lb_name, entries, overflow=0, show_weapon=False, score_prefix="", show_title=True, lethality_rows=None, warlord_rows=None, rating_min=5, is_map=False):
    """Return a list of discord.Embeds for a leaderboard board, splitting if description is too long."""
    colour = _embed_colour(lb_name)
    if not entries:
        e = discord.Embed(title=_lb_title(lb_name, show_title), description="*No entries yet.*", colour=colour)
        e.set_footer(text="Last updated")
        e.timestamp = datetime.now(timezone.utc)
        _append_rating_fields([e], lethality_rows, warlord_rows, rating_min, is_map=is_map)
        return [e]

    lines = []
    for idx, e in enumerate(entries, 1):
        weapon_str = f" *{e['weapon']}*" if show_weapon and e.get('weapon') else ""
        if lb_name == "Pacifist" and e.get('td') is not None:
            score_str = f"{e['td']} TD · {e['score']}"
        else:
            score_str = f"{score_prefix}{e['score']}"
        if e['link']:
            lines.append(f"│ {idx}. `{_lb_display_name(e['player'], e.get('did', ''))}` — [{score_str}]({e['link']}){weapon_str}")
        else:
            lines.append(f"│ {idx}. `{_lb_display_name(e['player'], e.get('did', ''))}` — {score_str}{weapon_str}")
    if overflow > 0:
        lines.append(f"*...and {overflow} more*")

    embeds = []
    current_lines = []
    current_len = 0
    for line in lines:
        cost = len(line) + 1
        if current_lines and current_len + cost > EMBED_DESC_LIMIT:
            _e = discord.Embed(title=_lb_title(lb_name, show_title, cont=bool(embeds)), description="\n".join(current_lines), colour=colour)
            _e.set_footer(text="Last updated")
            _e.timestamp = datetime.now(timezone.utc)
            embeds.append(_e)
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += cost
    if current_lines:
        _e = discord.Embed(title=_lb_title(lb_name, show_title, cont=bool(embeds)), description="\n".join(current_lines), colour=colour)
        _e.set_footer(text="Last updated")
        _e.timestamp = datetime.now(timezone.utc)
        embeds.append(_e)
    _append_rating_fields(embeds, lethality_rows, warlord_rows, rating_min, is_map=is_map)
    return embeds


async def archive_and_reset_boards(guild):
    """Snapshot top 3 of every weapon and map board into a compact Hall of Fame
    thread, then clear those boards. Feat boards, marks, ranks and mastery are
    untouched. Boards are only cleared AFTER a successful archive.
    Returns (weapon_boards, map_boards, rows_cleared, thread_url|None)."""
    _FEAT = {"100 Kills", "200 Takedowns", "Flawless", "Healing Horn", "Triple", "TUFF", "Pacifist"}
    ld = await _db.get_all_leaderboard_data()
    boards = {}
    for row in ld:
        if len(row) < 4:
            continue
        b = (row[0] or '').strip()
        if not b or b in _FEAT:
            continue
        try:
            sc = int(row[3])
        except (ValueError, TypeError):
            continue
        boards.setdefault(b, []).append((sc, (row[1] or '').strip(), (row[2] or '').strip()))
    if not boards:
        return 0, 0, 0, None
    weapon_boards = sorted(b for b in boards if ' - ' not in b)
    map_boards = sorted(b for b in boards if ' - ' in b)

    def _top3(b):
        top = sorted(boards[b], key=lambda t: -t[0])[:3]
        return " \u00b7 ".join(f"{i}. {p} {s}" for i, (s, p, *_r) in enumerate(top, 1))

    first = not any((pp[0] if isinstance(pp, (list, tuple)) else pp) == 'board_records_done'
                    for pp in await _db.get_all_index_posts())
    if first:
        title = "Pre-Season Legacy \u2014 Board Records"
    else:
        season = await _db.get_current_season()
        title = f"{(season.get('label') if season else None) or 'Season'} \u2014 Board Records"

    forum = guild.get_channel(config.HALL_OF_FAME_FORUM_ID) or await guild.fetch_channel(config.HALL_OF_FAME_FORUM_ID)
    if not forum:
        print("[SEASON RESET] Hall of Fame forum not found \u2014 aborting (no clear).")
        return len(weapon_boards), len(map_boards), 0, None
    try:
        res = await forum.create_thread(
            name=f"\U0001f5c3\ufe0f {title}"[:100],
            content=f"**{title}**\nTop 3 on every weapon and map board, preserved before the reset.")
        tobj = res.thread
        thread_url = f"https://discord.com/channels/{guild.id}/{tobj.id}"

        async def _post(header, blist):
            if not blist:
                return
            buf = f"__{header}__\n"
            for b in blist:
                ln = f"**{b}** \u2014 {_top3(b)}\n"
                if len(buf) + len(ln) > 1900:
                    await tobj.send(buf)
                    buf = ""
                buf += ln
            if buf.strip():
                await tobj.send(buf)
        await _post("Weapon Boards", weapon_boards)
        await _post("Map Boards", map_boards)
        if first:
            await _db.upsert_index_post('board_records_done', str(tobj.id), '1')
    except Exception as e:
        print(f"[SEASON RESET] HoF archive failed, boards NOT cleared: {e}")
        return len(weapon_boards), len(map_boards), 0, None

    # Merge every board's scores into the permanent all-time top-10 (never resets).
    for _b, _entries in boards.items():
        try:
            await _db.merge_alltime_records(_b, [(p, did, s) for (s, p, did) in _entries])
        except Exception as _ae:
            print(f"[ALLTIME] merge error ({_b}): {_ae}")

    # Takedown boards are permanent (all-time) and are never cleared. The
    # month-end reset only archives a snapshot; the boards stay up across seasons.
    return len(weapon_boards), len(map_boards), 0, thread_url


def _alltime_lines(records):
    lines = []
    for i, rec in enumerate(records, 1):
        pn = rec[0] if len(rec) > 0 else ""
        sc = rec[2] if len(rec) > 2 else 0
        lines.append(f"`{i:>2}.` **{pn}** - {sc}")
    return "\n".join(lines) if lines else "*No records yet.*"


def _alltime_weapon_embed(weapon, records):
    e = discord.Embed(
        title=f"{weapon} - All-Time",
        description=_alltime_lines(records),
        colour=discord.Colour.from_str("#C9A24B"),
    )
    e.set_footer(text="All-Time Top 10 \u00b7 best scores ever set, across every season")
    return e


def _alltime_map_embed(map_name, faction_records):
    """faction_records: list of (faction_label, records). Both factions share one thread."""
    e = discord.Embed(
        title=f"{map_name} - All-Time",
        colour=discord.Colour.from_str("#C9A24B"),
    )
    any_field = False
    for fac, recs in faction_records:
        if not recs:
            continue
        e.add_field(name=fac, value=_alltime_lines(recs)[:1024], inline=False)
        any_field = True
    if not any_field:
        e.description = "*No records yet.*"
    e.set_footer(text="All-Time Top 10 \u00b7 both factions \u00b7 across every season")
    return e


def _alltime_category(board_name):
    if board_name in config.WEAPONS_2H:
        return "2H"
    if board_name in config.WEAPONS_1H:
        return "1H"
    return "Archer"


async def _alltime_index(guild, forum, index_name, units):
    """Rebuild the pinned index: grouped Maps / 2H / 1H / Archer, formatted like
    the other forum indexes. units = list of (category, label, thread)."""
    groups = [
        ("\U0001f5fa\ufe0f Maps",        "Map"),
        ("\u2694\ufe0f 2H Weapons",       "2H"),
        ("\U0001f5e1\ufe0f 1H Weapons",   "1H"),
        ("\U0001f3f9 Archer",             "Archer"),
    ]
    embed = discord.Embed(
        title="\U0001f4cb All-Time Records Index",
        description="The permanent record - the ten best scores ever set on each board, "
                    "carried across every season. Jump to a board below.",
        colour=discord.Colour.from_str("#2b2d31"),
    )
    for glabel, gkey in groups:
        items = sorted([(lbl, th) for cat, lbl, th in units if cat == gkey and th],
                       key=lambda x: x[0].lower())
        if not items:
            continue
        links = [f"[{lbl}](https://discord.com/channels/{guild.id}/{th.id})" for lbl, th in items]
        chunk = ""
        first = True
        for ln in links:
            add = ln if not chunk else "\n" + ln
            if len(chunk) + len(add) > 1024:
                embed.add_field(name=(glabel if first else "\u200b"), value=chunk, inline=False)
                first = False
                chunk = ln
            else:
                chunk += add
        if chunk:
            embed.add_field(name=(glabel if first else "\u200b"), value=chunk, inline=False)
    if not embed.fields:
        embed.add_field(name="No boards yet", value="*Nothing here yet.*", inline=False)

    index_thread = None
    for t in forum.threads:
        if t.name == index_name:
            index_thread = t
            break
    if not index_thread:
        try:
            async for t in forum.archived_threads(limit=None):
                if t.name == index_name:
                    index_thread = t
                    break
        except Exception:
            pass
    if index_thread:
        msgs = []
        async for msg in index_thread.history(limit=50, oldest_first=True):
            msgs.append(msg)
        if msgs:
            await msgs[0].edit(embed=embed)
            for msg in msgs[1:]:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
        else:
            await index_thread.send(embed=embed)
    else:
        await forum.create_thread(name=index_name, embed=embed)


async def render_alltime_boards(guild):
    """Post/refresh the permanent all-time top-10 boards into the consolidated
    All-Time Records forum: one thread per weapon, one thread per map (both
    factions together), plus a grouped pinned index (Maps / 2H / 1H / Archer)."""
    fid = getattr(config, 'ALLTIME_RECORDS_FORUM_ID', 0) or 0
    if not fid:
        print("[ALLTIME] ALLTIME_RECORDS_FORUM_ID not set \u2014 skipping render.")
        return 0
    forum = guild.get_channel(fid) or await guild.fetch_channel(fid)
    if not forum:
        print(f"[ALLTIME] forum {fid} not found.")
        return 0
    board_names = await _db.get_all_alltime_boards()
    if not board_names:
        print("[ALLTIME] no all-time records yet.")
        return 0

    index_name = "\U0001f4cb All-Time Records Index"
    existing = {}
    try:
        active = await guild._state.http.get_active_threads(guild.id)
        for t in active.get('threads', []):
            if int(t['parent_id']) == fid and t['name'] != index_name:
                obj = forum.get_thread(int(t['id'])) or await guild.fetch_channel(int(t['id']))
                existing[t['name']] = obj
    except Exception as e:
        print(f"[ALLTIME] active thread fetch: {e}")
        for t in forum.threads:
            if t.name != index_name:
                existing[t.name] = t
    try:
        async for t in forum.archived_threads(limit=None):
            if t.name != index_name and t.name not in existing:
                existing[t.name] = t
    except Exception as e:
        print(f"[ALLTIME] archived thread fetch: {e}")

    # Split boards: weapons (no ' - ') vs maps ('Map - Faction'), grouping map factions.
    weapons = sorted(b for b in board_names if ' - ' not in b)
    maps = {}
    for b in board_names:
        if ' - ' in b:
            base, fac = b.split(' - ', 1)
            maps.setdefault(base.strip(), []).append((fac.strip(), b))

    async def _post(tname, embed):
        thread = existing.get(tname)
        if thread:
            starter = None
            try:
                starter = thread.starter_message or await thread.fetch_message(thread.id)
            except Exception:
                starter = None
            if starter:
                await starter.edit(embed=embed)
            else:
                await thread.send(embed=embed)
            return thread
        res = await forum.create_thread(name=tname, embed=embed)
        return res.thread

    units = []
    keep_names = {index_name}
    for w in weapons:
        try:
            recs = await _db.get_alltime_records(w)
            tname = f"\U0001f3c5 {w}"[:100]
            th = await _post(tname, _alltime_weapon_embed(w, recs))
            keep_names.add(tname)
            units.append((_alltime_category(w), w, th))
            await asyncio.sleep(0.4)
        except Exception as e:
            print(f"[ALLTIME] render weapon {w}: {e}")
    for m in sorted(maps):
        try:
            fr = [(fac, await _db.get_alltime_records(bname)) for fac, bname in sorted(maps[m])]
            tname = f"\U0001f3c5 {m}"[:100]
            th = await _post(tname, _alltime_map_embed(m, fr))
            keep_names.add(tname)
            units.append(("Map", m, th))
            await asyncio.sleep(0.4)
        except Exception as e:
            print(f"[ALLTIME] render map {m}: {e}")

    # Remove stale bot threads (e.g. old per-faction map threads) no longer used.
    for tname, thread in existing.items():
        if tname not in keep_names and tname.startswith("\U0001f3c5"):
            try:
                await thread.delete()
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[ALLTIME] stale delete {tname}: {e}")

    try:
        await _alltime_index(guild, forum, index_name, units)
    except Exception as e:
        print(f"[ALLTIME] index: {e}")
    return len(units)


_LOOKALIKE = str.maketrans({
    'Υ':'Y','Λ':'A','Β':'B','Ε':'E','Ζ':'Z','Η':'H','Ι':'I','Κ':'K','Μ':'M','Ν':'N',
    'Ο':'O','Ρ':'P','Τ':'T','Χ':'X','Α':'A','Σ':'E','Δ':'D','Θ':'O','Ø':'O','ø':'o',
    'Я':'R','А':'A','В':'B','Е':'E','К':'K','М':'M','Н':'H','О':'O','Р':'P','С':'C',
    'Т':'T','У':'Y','Х':'X','Ѕ':'S','і':'i','ѕ':'s',
})


def _fold_name(name):
    """Fold unicode lookalikes + accents to plain lowercase ASCII-ish for matching."""
    s = unicodedata.normalize('NFKD', name or '').translate(_LOOKALIKE)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def _lb_display_name(name, did=''):
    """Apply leaderboard display-name overrides (discord_id, exact name, or folded
    substring rules) so messy names render cleanly on the boards."""
    ov = getattr(config, 'LEADERBOARD_NAME_OVERRIDES', {}) or {}
    if did and str(did) in ov:
        return ov[str(did)]
    if name in ov:
        return ov[name]
    folded = _fold_name(name)
    for subs, repl in getattr(config, 'LEADERBOARD_NAME_CONTAINS', []) or []:
        if all(str(sub).lower() in folded for sub in subs):
            return repl
    return name


def _monthly_rating_lines(rows, fmt):
    if not rows:
        return "*Not enough games yet.*"
    return "\n".join(f"│ {i}. `{p}` — {fmt(s)}" for i, (p, s) in enumerate(rows[:5], 1))


def _monthly_weapon_embed(weapon, lr, wr):
    te = getattr(config, 'TITLE_EMOJIS', {})
    le = te.get('Lethality', '🧪')
    we = te.get('Warlord', '🛡️')
    e = discord.Embed(title=f"{weapon} — This Month", colour=_embed_colour(weapon))
    e.add_field(name=f"{le} Lethality", value=_monthly_rating_lines(lr, lambda s: f"{s * 100:.0f}%"), inline=False)
    e.add_field(name=f"{we} Warlord", value=_monthly_rating_lines(wr, lambda s: f"{s:.0f}%"), inline=False)
    e.set_footer(text="Monthly · Lethality (kills/TD) + Warlord (takedowns/team kills) · top 5 · resets each month")
    return e


def _monthly_faction_embed(map_name, faction, lr, wr):
    """One vertical faction board, coloured like the original map scoreboards."""
    te = getattr(config, 'TITLE_EMOJIS', {})
    le = te.get('Lethality', '🧪')
    we = te.get('Warlord', '🛡️')
    e = discord.Embed(title=f"{map_name} · {faction} — This Month", colour=_embed_colour(f"{map_name} - {faction}"))
    e.add_field(name=f"{le} Kill Share", value=_monthly_rating_lines(lr, lambda s: f"{s:.0f}%"), inline=False)
    e.add_field(name=f"{we} Warlord", value=_monthly_rating_lines(wr, lambda s: f"{s:.0f}%"), inline=False)
    e.set_footer(text="Monthly · Kill Share (kills/team kills) + Warlord (takedowns/team kills) · top 5 · resets each month")
    return e


def _monthly_window_start():
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


async def _current_window_start():
    season = None
    try:
        season = await _db.get_current_season()
    except Exception:
        season = None
    if season and season.get('started_at'):
        return season['started_at'].timestamp(), (season.get('label') or None)
    return _monthly_window_start(), None


def _boards_in_window(all_subs, window_start):
    weapons, maps = set(), {}
    for r in all_subs:
        if len(r) > 11 and r[11] and 'Resubmit' in str(r[11]):
            continue
        try:
            _t = datetime.strptime(str(r[0]).strip()[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            continue
        if _t < window_start:
            continue
        w = (r[3].strip() if len(r) > 3 and r[3] else '')
        if w:
            weapons.add(w)
        m = (r[5].strip() if len(r) > 5 and r[5] else '')
        fac = (r[6].strip() if len(r) > 6 and r[6] else '')
        if m and fac:
            maps.setdefault(m, set()).add(fac)
    return weapons, maps


async def _monthly_index(guild, forum, index_name, units):
    """Rebuild + pin the Monthly Report index. One embed per category (Maps / 2H /
    1H / Archer) with the board links in the description, so long lists don't get
    the field-split blank-line gaps."""
    groups = [
        ("🗺️ Maps",        "Map"),
        ("⚔️ 2H Weapons",   "2H"),
        ("🗡️ 1H Weapons",   "1H"),
        ("🏹 Archer",        "Archer"),
    ]
    colour = discord.Colour.from_str("#C9A24B")
    embeds = [discord.Embed(
        title="📋 Monthly Report — Index",
        description="Weapon boards rank Lethality (kills/TD) and Warlord (takedowns as a share of your team's total kills). "
                    "Map boards rank Kill Share (share of your team's kills) and Warlord (takedowns vs your "
                    "team's kills). Top 5 per board, current season — resubmissions don't count. Jump to a board below.",
        colour=colour,
    )]
    for glabel, gkey in groups:
        items = sorted([(lbl, th) for cat, lbl, th in units if cat == gkey and th],
                       key=lambda x: x[0].lower())
        if not items:
            continue
        links = [f"[{lbl}](https://discord.com/channels/{guild.id}/{th.id})" for lbl, th in items]
        # Split into <=4000-char descriptions (a second embed only if a category is huge).
        chunks, cur = [], ""
        for ln in links:
            add = ln if not cur else "\n" + ln
            if len(cur) + len(add) > 4000:
                chunks.append(cur)
                cur = ln
            else:
                cur += add
        if cur:
            chunks.append(cur)
        for i, ch in enumerate(chunks):
            embeds.append(discord.Embed(
                title=glabel if i == 0 else f"{glabel} (cont.)",
                description=ch, colour=colour))
    if len(embeds) == 1:
        embeds[0].description += "\n\n*No boards yet — post a run to populate them.*"
    embeds = embeds[:10]  # Discord hard cap: 10 embeds per message

    index_thread = None
    for t in forum.threads:
        if t.name == index_name:
            index_thread = t
            break
    if not index_thread:
        try:
            async for t in forum.archived_threads(limit=None):
                if t.name == index_name:
                    index_thread = t
                    break
        except Exception:
            pass
    if index_thread:
        msgs = []
        async for msg in index_thread.history(limit=50, oldest_first=True):
            msgs.append(msg)
        if msgs:
            await msgs[0].edit(embeds=embeds)
            for msg in msgs[1:]:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
        else:
            await index_thread.send(embeds=embeds)
    else:
        res = await forum.create_thread(name=index_name, embeds=embeds)
        index_thread = res.thread
    try:
        await index_thread.edit(pinned=True)
    except Exception as e:
        print(f"[MONTHLY] index pin: {e}")


async def render_monthly_boards(guild, only_boards=None):
    """Live monthly Lethality/Warlord top-5 boards rendered into the repurposed
    Monthly Report forum (ALLTIME_RECORDS_FORUM_ID). Scoped to the current season
    window; resubmissions excluded. only_boards limits the refresh to given boards."""
    # Monthly Report RETIRED: the season Lethality / Warlord / Kill Share ratings now live
    # on the butler-season-board (season-scoped). This per-board forum report is no longer
    # rendered; kept as a no-op so season_reset + the all-time seed still do their other work.
    return 0
    fid = getattr(config, 'ALLTIME_RECORDS_FORUM_ID', 0) or 0
    if not fid:
        print("[MONTHLY] ALLTIME_RECORDS_FORUM_ID not set - skipping render.")
        return 0
    forum = guild.get_channel(fid) or await guild.fetch_channel(fid)
    if not forum:
        print(f"[MONTHLY] forum {fid} not found.")
        return 0

    window_start, _ = await _current_window_start()
    all_subs = await _db.get_all_submissions()
    weapons, maps = _boards_in_window(all_subs, window_start)

    if only_boards is not None:
        ob = set(only_boards)
        weapons = {w for w in weapons if w in ob}
        maps = {m: fs for m, fs in maps.items() if any(f"{m} - {f}" in ob for f in fs)}

    index_name = "📋 Monthly Report Index"
    existing = {}
    try:
        active = await guild._state.http.get_active_threads(guild.id)
        for t in active.get('threads', []):
            if int(t['parent_id']) == fid and t['name'] != index_name:
                obj = forum.get_thread(int(t['id'])) or await guild.fetch_channel(int(t['id']))
                existing[t['name']] = obj
    except Exception as e:
        print(f"[MONTHLY] active thread fetch: {e}")
        for t in forum.threads:
            if t.name != index_name:
                existing[t.name] = t
    try:
        async for t in forum.archived_threads(limit=None):
            if t.name != index_name and t.name not in existing:
                existing[t.name] = t
    except Exception as e:
        print(f"[MONTHLY] archived thread fetch: {e}")

    async def _post(tname, embeds):
        thread = existing.get(tname)
        if thread:
            starter = None
            try:
                starter = thread.starter_message or await thread.fetch_message(thread.id)
            except Exception:
                starter = None
            if starter:
                await starter.edit(embeds=embeds)
            else:
                await thread.send(embeds=embeds)
            return thread
        res = await forum.create_thread(name=tname, embeds=embeds)
        return res.thread

    units = []
    for w in sorted(weapons):
        try:
            lr, wr, _ = await compute_board_ratings(w, is_map=False, all_subs=all_subs, window_start=window_start)
            tname = f"🗓️ {w}"[:100]
            th = await _post(tname, [_monthly_weapon_embed(w, lr, wr)])
            units.append((_alltime_category(w), w, th))
            await asyncio.sleep(0.4)
        except Exception as e:
            print(f"[MONTHLY] render weapon {w}: {e}")
    for m in sorted(maps):
        try:
            m_embeds = []
            for fac in sorted(maps[m]):
                lr, wr, _ = await compute_board_ratings(f"{m} - {fac}", is_map=True, all_subs=all_subs, window_start=window_start)
                m_embeds.append(_monthly_faction_embed(m, fac, lr, wr))
            if not m_embeds:
                m_embeds = [discord.Embed(title=f"{m} — This Month", description="*No games yet this month.*", colour=_embed_colour(m))]
            tname = f"🗓️ {m}"[:100]
            th = await _post(tname, m_embeds)
            units.append(("Map", m, th))
            await asyncio.sleep(0.4)
        except Exception as e:
            print(f"[MONTHLY] render map {m}: {e}")

    # Full render (not a per-submission touch): rebuild + pin the index.
    if only_boards is None:
        try:
            await _monthly_index(guild, forum, index_name, units)
        except Exception as e:
            print(f"[MONTHLY] index: {e}")
    return len(units)


async def snapshot_monthly_to_hof(guild):
    """Month-end: snapshot monthly Lethality/Warlord top-5 for every weapon and map
    board into a Butler Hall of Fame thread. Non-destructive. Returns (n, url)."""
    fid = config.HALL_OF_FAME_FORUM_ID
    forum = guild.get_channel(fid) or await guild.fetch_channel(fid)
    if not forum:
        print("[MONTHLY HOF] Hall of Fame forum not found.")
        return 0, None
    window_start, label = await _current_window_start()
    label = label or datetime.now(timezone.utc).strftime('%B %Y')
    all_subs = await _db.get_all_submissions()
    weapons, maps = _boards_in_window(all_subs, window_start)

    def _top(rows, fmt):
        return " · ".join(f"{i}. {p} {fmt(s)}" for i, (p, s) in enumerate((rows or [])[:5], 1)) or "—"

    lines = []
    for w in sorted(weapons):
        lr, wr, _ = await compute_board_ratings(w, is_map=False, all_subs=all_subs, window_start=window_start)
        if lr or wr:
            lines.append(f"**{w}**\n· Lethality: {_top(lr, lambda s: f'{s*100:.0f}%')}\n· Warlord: {_top(wr, lambda s: f'{s:.0f}%')}")
    for m in sorted(maps):
        for fac in sorted(maps[m]):
            lr, wr, _ = await compute_board_ratings(f"{m} - {fac}", is_map=True, all_subs=all_subs, window_start=window_start)
            if lr or wr:
                lines.append(f"**{m} — {fac}**\n· Kill Share: {_top(lr, lambda s: f'{s:.0f}%')}\n· Warlord: {_top(wr, lambda s: f'{s:.0f}%')}")
    if not lines:
        return 0, None

    title = f"🗄️ {label} — Monthly Report"[:100]
    res = await forum.create_thread(name=title, content=f"**{label} — Monthly Report**\nLethality + Warlord top 5 per board, preserved at month-end.")
    tobj = res.thread
    url = f"https://discord.com/channels/{guild.id}/{tobj.id}"
    buf = ""
    for ln in lines:
        add = ln + "\n\n"
        if len(buf) + len(add) > 1900:
            await tobj.send(buf)
            buf = ""
        buf += add
    if buf.strip():
        await tobj.send(buf)
    return len(lines), url


async def check_and_merge_alltime(board_name, player, discord_id, score):
    """Merge one fresh score into the permanent all-time top-10 (live) and report
    whether it newly placed. Returns {'rank': int|None, 'record': bool}: rank is
    the 1-based all-time position if this score newly reached the top 10 AND
    improved this player's own all-time best; record=True when it's the new #1."""
    try:
        score = int(score)
    except (ValueError, TypeError):
        return {'rank': None, 'record': False}
    board_name = (board_name or '').strip()
    player = (player or '').strip()
    if not board_name or not player or score <= 0:
        return {'rank': None, 'record': False}
    before = await _db.get_alltime_records(board_name)
    prev_best = max((r[2] for r in before if r[0] == player), default=0)
    prev_top = before[0][2] if before else 0
    await _db.merge_alltime_records(board_name, [(player, discord_id, score)])
    after = await _db.get_alltime_records(board_name)
    rank = None
    for i, r in enumerate(after, 1):
        if r[0] == player and r[2] == score:
            rank = i
            break
    if rank is None or score <= prev_best:
        return {'rank': None, 'record': False}
    return {'rank': rank, 'record': (rank == 1 and score > prev_top)}


async def seed_alltime_from_current(guild):
    """Merge the CURRENT seasonal board scores into the all-time top-10 WITHOUT
    clearing anything, then render. Safe to run repeatedly \u2014 keeps each
    player's best score. Used to populate/preview all-time before any reset."""
    _FEAT = {"100 Kills", "200 Takedowns", "Flawless", "Healing Horn", "Triple", "TUFF", "Pacifist"}
    ld = await _db.get_all_leaderboard_data()
    boards = {}
    for row in ld:
        if len(row) < 4:
            continue
        b = (row[0] or '').strip()
        if not b or b in _FEAT:
            continue
        try:
            sc = int(row[3])
        except (ValueError, TypeError):
            continue
        pn = (row[1] or '').strip()
        did = (row[2] or '').strip()
        if pn:
            boards.setdefault(b, []).append((pn, did, sc))
    for b, entries in boards.items():
        try:
            await _db.merge_alltime_records(b, entries)
        except Exception as e:
            print(f"[ALLTIME] seed merge error ({b}): {e}")
    await render_monthly_boards(guild)
    return len(boards)


class LeaderboardsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="season_reset", description="Snapshot this month's Lethality/Warlord boards to the Hall of Fame (admin only). Non-destructive.")
    @app_commands.checks.has_permissions(administrator=True)
    async def season_reset(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            n, url = await snapshot_monthly_to_hof(interaction.guild)
        except Exception as e:
            await interaction.followup.send(f"❌ Snapshot failed: {e}", ephemeral=True)
            return
        loc = f" ({url})" if url else ""
        try:
            await render_monthly_boards(interaction.guild)
        except Exception as _re2:
            print(f"[MONTHLY] post-snapshot render error: {_re2}")
        if n == 0:
            await interaction.followup.send("Nothing to snapshot — no rated games in this month's window yet.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Snapshotted **{n}** boards' monthly Lethality/Warlord top 5 to the Hall of Fame{loc}.\n"
            f"Nothing was cleared — takedown boards stay permanent; the Monthly Report resets with the new season window.",
            ephemeral=True)

    @app_commands.command(name="refresh_monthly", description="Rebuild all Monthly Report boards + pinned index now (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def refresh_monthly(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not (getattr(config, 'ALLTIME_RECORDS_FORUM_ID', 0) or 0):
            await interaction.followup.send(
                "❌ The Monthly Report forum (`ALLTIME_RECORDS_FORUM_ID`) isn't set in config.", ephemeral=True)
            return
        try:
            n = await render_monthly_boards(interaction.guild)
        except Exception as e:
            await interaction.followup.send(f"❌ Monthly refresh failed: {e}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Rebuilt **{n}** Monthly Report boards (Lethality + Warlord, top 5) and pinned the index.",
            ephemeral=True)

    @app_commands.command(name="alltime_refresh", description="Merge current board scores into the permanent all-time top-10 and refresh the archive (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def alltime_refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not (getattr(config, 'ALLTIME_RECORDS_FORUM_ID', 0) or 0):
            await interaction.followup.send(
                "\u274c `ALLTIME_RECORDS_FORUM_ID` isn't set in config \u2014 create the All-Time Records forum "
                "and paste its channel ID there first.", ephemeral=True)
            return
        try:
            n = await seed_alltime_from_current(interaction.guild)
        except Exception as e:
            await interaction.followup.send(f"\u274c All-time refresh failed: {e}", ephemeral=True)
            return
        await interaction.followup.send(
            f"\u2705 Merged **{n}** boards into the all-time top-10 and refreshed the archive. "
            f"Nothing was cleared \u2014 this only ever keeps each player's best score.\n"
            f"Pin the **\U0001f4cb All-Time Records Index** thread to the top of the forum.",
            ephemeral=True)

    @app_commands.command(name="setup", description="Set up a bot-owned leaderboard in this thread")
    @app_commands.describe(
        name="Name of the leaderboard e.g. War Axe",
        type="Type: weapon, feat, or map"
    )
    async def setup_leaderboard(self, interaction: discord.Interaction, name: str, type: str):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.send_message("Setting up leaderboard...", ephemeral=True)
        thread = interaction.channel

        if type == "map":
            map_info = MAP_ATTACK_DEFENSE.get(name)
            if not map_info:
                await interaction.edit_original_response(content=f"No attack/defense info found for map: {name}")
                return

            # map_info is (attack_faction, defense_faction) — this used to do
            # map_info["attack"]/["defense"] dict-style access, which would raise
            # TypeError against the actual tuple shape in config.py. Never caught
            # because every map board already existed by the time this drifted out
            # of sync; only would have surfaced on a genuinely new /setup_leaderboard
            # map call. Fixed 2026-06-30 alongside the header-placement fix below.
            attack_faction, defense_faction = map_info[0], map_info[1]
            attack_name = f"{name} - {attack_faction}"
            defense_name = f"{name} - {defense_faction}"

            attack_entries = await get_leaderboard_entries(attack_name)
            defense_entries = await get_leaderboard_entries(defense_name)

            # Headers are message CONTENT, sent alongside the embed — not the
            # embed's own title field, which renders inside the bordered/colored
            # box. _map_header() builds the same "[icon] Map Faction [icon]" text
            # used by every other board-sync path now (update_leaderboards,
            # /refresh, /refresh_all, /migrate_boards).
            attack_header = _map_header(attack_name)
            defense_header = _map_header(defense_name)

            attack_embeds = format_leaderboard_embeds(attack_name, attack_entries, show_title=False)
            defense_embeds = format_leaderboard_embeds(defense_name, defense_entries, show_title=False)

            await thread.send(file=discord.File(DECORATION_TOP))
            attack_ids = []
            for emb in attack_embeds:
                m = await thread.send(content=attack_header, embed=emb)
                attack_ids.append(str(m.id))
            defense_ids = []
            for emb in defense_embeds:
                m = await thread.send(content=defense_header, embed=emb)
                defense_ids.append(str(m.id))
            await thread.send(file=discord.File(DECORATION_BOTTOM))

            await _db.upsert_leaderboard(attack_name, str(thread.id), '|'.join(attack_ids), "map")
            await _db.upsert_leaderboard(defense_name, str(thread.id), '|'.join(defense_ids), "map")

            await interaction.edit_original_response(content=f"✅ Map leaderboard for **{name}** set up with both factions.")

        else:
            entries = await get_leaderboard_entries(name)
            show_weapon = name in ("100 Kills", "200 Takedowns")
            score_prefix = "+" if name == "TUFF" else ""
            embeds = format_leaderboard_embeds(name, entries, 0, show_weapon, score_prefix)
            await thread.send(file=discord.File(DECORATION_TOP))
            msg_ids = []
            for emb in embeds:
                m = await thread.send(embed=emb)
                msg_ids.append(str(m.id))
            await thread.send(file=discord.File(DECORATION_BOTTOM))

            await _db.upsert_leaderboard(name, str(thread.id), '|'.join(msg_ids), type)

            await interaction.edit_original_response(content=f"✅ Leaderboard for **{name}** set up successfully.")

    @app_commands.command(name="refresh", description="Refresh the leaderboard in this thread, or specify a name")
    @app_commands.describe(name="Optional: exact leaderboard name. Leave blank to auto-detect from this channel.")
    async def refresh_leaderboard(self, interaction: discord.Interaction, name: str = None):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        all_lb_rows = await _get_lb_records()

        if name is None:
            channel_id = str(interaction.channel.id)
            matching = [r for r in all_lb_rows if str(r['Thread ID']) == channel_id]
            if not matching:
                await interaction.response.send_message("❌ No leaderboard found for this channel. Try specifying the name manually.", ephemeral=True)
                return
            names_to_refresh = [r['Leaderboard Name'] for r in matching]
        else:
            lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == name), None)
            if not lb_row:
                await interaction.response.send_message(f"❌ No leaderboard found with name: `{name}`", ephemeral=True)
                return
            names_to_refresh = [name]

        await interaction.response.send_message(f"Refreshing **{', '.join(names_to_refresh)}**...", ephemeral=True)

        for lb_name in names_to_refresh:
            if lb_name == "The Hundred Handed":
                # HH has its own renderer (matched-46 completers) — not the generic score board
                await refresh_hundred_handed_board(interaction.guild)
                continue
            lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
            if not lb_row:
                continue

            entries = await get_leaderboard_entries(lb_name)
            entries = await _sort_board_entries(lb_name, entries)

            show_weapon = lb_name in ("100 Kills", "200 Takedowns")
            score_prefix = "+" if lb_name == "TUFF" else ""
            is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
            embeds = await _rated_embeds(lb_name, entries, is_map, None, 0, show_weapon, score_prefix, not is_map)
            header_content = _map_header(lb_name) if is_map else ""

            thread_id = int(lb_row['Thread ID'])
            message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(lb_row['Message ID']))]

            try:
                guild = interaction.guild
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
                new_ids = await _sync_board_messages(thread, embeds, message_ids, msg_content=header_content)
                if new_ids != message_ids:
                    await _db.update_leaderboard_messages(lb_name, '|'.join(str(m) for m in new_ids))

            except Exception as e:
                await interaction.edit_original_response(content=f"❌ Error refreshing {lb_name}: {e}")
                return

        await interaction.edit_original_response(content=f"✅ **{', '.join(names_to_refresh)}** refreshed successfully.")

    @app_commands.command(name="refresh_all", description="Refresh every leaderboard at once (mod only)")
    async def refresh_all_leaderboards(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.send_message("Refreshing all leaderboards...", ephemeral=True)

        all_lb_rows = await _get_lb_records()
        guild = interaction.guild
        done, failed = [], []

        for lb_row in all_lb_rows:
            lb_name = lb_row.get('Leaderboard Name')
            thread_id_raw = lb_row.get('Thread ID')
            msg_id_raw = lb_row.get('Message ID')
            if not lb_name or not thread_id_raw or not msg_id_raw:
                continue

            try:
                entries = await get_leaderboard_entries(lb_name)
                entries = await _sort_board_entries(lb_name, entries)
                show_weapon = lb_name in ("100 Kills", "200 Takedowns")
                score_prefix = "+" if lb_name == "TUFF" else ""
                is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
                embeds = await _rated_embeds(lb_name, entries, is_map, None, 0, show_weapon, score_prefix, not is_map)
                header_content = _map_header(lb_name) if is_map else ""

                thread_id = int(thread_id_raw)
                message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(msg_id_raw))]
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)

                new_ids = await _sync_board_messages(thread, embeds, message_ids, msg_content=header_content)
                if new_ids != message_ids:
                    await _db.update_leaderboard_messages(lb_name, '|'.join(str(m) for m in new_ids))
                done.append(lb_name)
            except Exception as e:
                nerve_log_error(f"Leaderboard refresh {lb_name}", e)
                failed.append(lb_name)

        summary = f"✅ Refreshed {len(done)} boards."
        if failed:
            summary += f"\n❌ Failed: {', '.join(failed)}"
        await interaction.edit_original_response(content=summary)

    @app_commands.command(name="refresh_maps", description="Refresh only the MAP boards (Kill Share + Warlord) at once (mod only).")
    async def refresh_map_boards(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.send_message("Refreshing map boards...", ephemeral=True)
        all_lb_rows = await _get_lb_records()
        guild = interaction.guild
        done, failed = [], []
        for lb_row in all_lb_rows:
            lb_name = lb_row.get('Leaderboard Name')
            thread_id_raw = lb_row.get('Thread ID')
            msg_id_raw = lb_row.get('Message ID')
            if not lb_name or not thread_id_raw or not msg_id_raw:
                continue
            is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
            if not is_map:
                continue
            try:
                entries = await get_leaderboard_entries(lb_name)
                entries = await _sort_board_entries(lb_name, entries)
                embeds = await _rated_embeds(lb_name, entries, True, None, 0, False, "", False)
                header_content = _map_header(lb_name)
                thread_id = int(thread_id_raw)
                message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(msg_id_raw))]
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
                new_ids = await _sync_board_messages(thread, embeds, message_ids, msg_content=header_content)
                if new_ids != message_ids:
                    await _db.update_leaderboard_messages(lb_name, '|'.join(str(m) for m in new_ids))
                done.append(lb_name)
            except Exception as e:
                nerve_log_error(f"Map board refresh {lb_name}", e)
                failed.append(lb_name)
        summary = f"\u2705 Refreshed {len(done)} map boards (Kill Share + Warlord)."
        if failed:
            summary += f"\n\u274c Failed: {', '.join(failed)}"
        await interaction.edit_original_response(content=summary)

    @app_commands.command(name="rank", description="Show the top 10 for a weapon or class leaderboard.")
    @app_commands.describe(name="Weapon or leaderboard name e.g. Messer, Halberd")
    @app_commands.autocomplete(name=_rank_name_ac)
    async def rank_command(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        # Source of truth = SET-UP boards (leaderboards table), not just boards that
        # have entries — so empty boards (e.g. a fresh archer board) still resolve,
        # and junk entry-only names don't get suggested.
        try:
            board_names = {r['Leaderboard Name'].strip()
                           for r in await _get_lb_records() if r.get('Leaderboard Name')}
        except Exception:
            board_names = set()

        _norm = lambda s: _re.sub(r'[^a-z0-9]', '', s.lower())
        _nname = _norm(name)

        match = next((b for b in board_names if b.lower() == name.lower()), None)
        if not match:
            try:
                from utils.parsing import parse_submission_text
                _aw, _ = parse_submission_text(name)
                if _aw:
                    match = next((b for b in board_names if b.lower() == _aw.lower()), None)
            except Exception:
                pass
        if not match and _nname:
            match = next((b for b in board_names if _norm(b) == _nname), None)

        if not match:
            suggestions = [b for b in sorted(board_names)
                           if _nname and (_nname in _norm(b) or _norm(b) in _nname)][:5]
            if not suggestions:
                suggestions = [b for b in sorted(board_names) if name.lower() in b.lower()][:5]
            msg = f"No leaderboard found for **{name}**."
            if suggestions:
                msg += f" Did you mean: {', '.join(f'`{s}`' for s in suggestions)}?"
            await interaction.followup.send(msg, ephemeral=True)
            return

        name = match
        entries = await get_leaderboard_entries(name)
        if not entries:
            await interaction.followup.send(f"**{name}** — no entries on the board yet.")
            return

        top = entries[:10]
        total = len(entries)
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [f"**{name}** — Top {len(top)} of {total}", ""]
        for i, e in enumerate(top, 1):
            medal = medals.get(i, f"`{i}.`")
            prefix = f"{medal} " if i <= 3 else f"{medal}  "
            lines.append(f"{prefix}**{e['player']}** — {e['score']}")

        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="migrate_boards", description="Convert all leaderboard boards from text to embeds (admin only).")
    async def migrate_boards(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        all_lb_rows = await _get_lb_records()
        all_ld = await _db.get_all_leaderboard_data()
        guild = interaction.guild
        done, skipped, failed = [], [], []

        for lb_row in all_lb_rows:
            lb_name = lb_row['Leaderboard Name']
            thread_id_str = lb_row['Thread ID']
            if not thread_id_str:
                skipped.append(lb_name)
                continue
            try:
                thread_id = int(thread_id_str)
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
            except Exception as e:
                failed.append(f"{lb_name}: can't fetch thread ({e})")
                continue

            entries = []
            for row in all_ld:
                if row[0] == lb_name:
                    entries.append({
                        'player': row[1] if len(row) > 1 else '',
                        'did': row[2] if len(row) > 2 else '',
                        'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                        'link': row[4] if len(row) > 4 else '',
                        'weapon': row[5] if len(row) > 5 else '',
                    })
            entries.sort(key=lambda x: x['score'], reverse=True)

            show_weapon = lb_name in ("100 Kills", "200 Takedowns")
            score_prefix = "+" if lb_name == "TUFF" else ""
            is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
            embeds = await _rated_embeds(lb_name, entries, is_map, None, 0, show_weapon, score_prefix, not is_map)
            header_content = _map_header(lb_name) if is_map else ""

            old_ids_str = lb_row['Message ID']
            old_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(old_ids_str))]

            try:
                new_ids = await _sync_board_messages(thread, embeds, old_ids, msg_content=header_content)
                await _db.update_leaderboard_messages(lb_name, '|'.join(str(m) for m in new_ids))
                done.append(lb_name)
                await asyncio.sleep(0.4)
            except Exception as e:
                failed.append(f"{lb_name}: {e}")

        report = f"✅ Migrated {len(done)} boards."
        if skipped:
            report += f"\n⚠️ Skipped (no thread): {len(skipped)}"
        if failed:
            report += f"\n❌ Failed:\n" + "\n".join(failed[:10])
        await interaction.edit_original_response(content=report)

    @app_commands.command(name="create_missing_boards", description="Create leaderboard threads for all primary weapons without a board (admin only).")
    async def create_missing_boards(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        all_primaries = set()
        for weapons in _SUBCLASS_PRIMARIES.values():
            all_primaries.update(weapons)

        existing = set()
        try:
            for row in await _db.get_all_leaderboards():
                if row:
                    existing.add(row[0].strip())
        except Exception as e:
            await interaction.followup.send(f"Failed to read leaderboards: {e}", ephemeral=True)
            return

        missing = sorted(all_primaries - existing)
        if not missing:
            await interaction.followup.send("All primary weapon boards already exist.", ephemeral=True)
            return

        guild = interaction.guild
        created = []
        failed = []

        for weapon in missing:
            try:
                forum_id = _weapon_forum_id(weapon)
                forum = guild.get_channel(forum_id) or await guild.fetch_channel(forum_id)

                thread_with_msg = await forum.create_thread(
                    name=weapon,
                    content="<:cigar:1444893851427803298>"
                )
                thread = thread_with_msg.thread

                entries = await get_leaderboard_entries(weapon)
                chunks = format_leaderboard_text(entries)

                await thread.send(file=discord.File(DECORATION_TOP))
                msg_ids = []
                for chunk in chunks:
                    lb_msg = await thread.send(chunk)
                    msg_ids.append(str(lb_msg.id))
                await thread.send(file=discord.File(DECORATION_BOTTOM))

                await _db.upsert_leaderboard(weapon, str(thread.id), "|".join(msg_ids), "weapon")
                created.append(weapon)
                await asyncio.sleep(1.5)

            except Exception as e:
                print(f"create_missing_boards error for {weapon}: {e}")
                failed.append(weapon)
                await asyncio.sleep(1)

        msg = f"Created {len(created)} boards: {chr(10).join(created)}"
        if failed:
            msg += f"\nFailed: {chr(10).join(failed)}"
        await interaction.followup.send(msg[:1900], ephemeral=True)

    @app_commands.command(name="refresh_entrance", description="Refresh just the ledger entrance channel links (mod only).")
    async def refresh_entrance(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        _entrance_message_ids.clear()
        try:
            await build_ledger_entrance(interaction.guild, force=True)
            await interaction.followup.send("✅ Ledger entrance refreshed.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="ledger_refresh", description="Rebuild the ledger entrance channel and all forum indexes (mod only).")
    async def ledger_refresh(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        _entrance_message_ids.clear()

        try:
            await build_ledger_entrance(guild, force=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Entrance build failed: {e}", ephemeral=True)
            return

        index_targets = [
            (WEAPON_FORUM_1H,    "1H Weapons"),
            (WEAPON_FORUM_2H,    "2H Weapons"),
            (MAP_RECORDS_FORUM_ID, "Map Records"),
            (FEATS_FORUM_ID,     "Feats of War"),
        ]
        for forum_id, label in index_targets:
            try:
                await update_leaderboard_index(guild, forum_id, label)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"ledger_refresh: index error for {label}: {e}")

        await interaction.followup.send("✅ Ledger entrance and all indexes rebuilt.", ephemeral=True)

    @app_commands.command(name="repair_marks", description="Backfill missing High Score marks from leaderboard entries (mod only)")
    async def repair_marks(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        from cogs.registry import create_or_update_registry_card

        FEAT_BOARDS = {"100 Kills", "200 Takedowns", "Flawless"}

        try:
            lb_rows  = await _db.get_all_leaderboard_data()
            sub_rows = await _db.get_all_submissions()
        except Exception as e:
            await interaction.edit_original_response(content=f"DB read failed: {e}")
            return

        # Build index: message_link -> (feats_string) from submissions
        link_to_sub = {}
        for row in sub_rows:
            if len(row) < 13:
                continue
            link = row[12].strip()
            if link:
                link_to_sub[link] = row[11].strip()  # feats at index 11

        patched_rows = []
        affected_players = set()

        for lb_row in lb_rows:
            if len(lb_row) < 5:
                continue
            lb_name    = lb_row[0].strip()
            player     = lb_row[1].strip()
            discord_id = lb_row[2].strip()
            link       = lb_row[4].strip()

            if lb_name in FEAT_BOARDS:
                continue
            if not link or link not in link_to_sub:
                continue

            feats_str = link_to_sub[link]
            feats = [f.strip() for f in feats_str.split(',') if f.strip() and f.strip() != 'None']

            if 'High Score' not in feats:
                patched_rows.append((link, feats_str, player, discord_id, lb_name))

        if not patched_rows:
            await interaction.edit_original_response(content="✅ No missing High Score marks found — all entries look correct.")
            return

        errors = []
        for link, old_feats, player, discord_id, lb_name in patched_rows:
            try:
                if old_feats in ('', 'None', 'none'):
                    new_feats = 'High Score'
                else:
                    new_feats = old_feats.rstrip(', ') + ', High Score'
                await _db.update_submission_feats_by_link(link, new_feats)
                affected_players.add((player, int(discord_id) if discord_id.isdigit() else None))
                await asyncio.sleep(0.1)
            except Exception as e:
                errors.append(f"Link {link[:30]} ({player}): {e}")

        rebuilt = []
        for player_name, player_id in affected_players:
            if not player_id:
                continue
            try:
                await create_or_update_registry_card(interaction.guild, player_id, player_name)
                rebuilt.append(player_name)
                await asyncio.sleep(1.0)
            except Exception as e:
                errors.append(f"Registry rebuild for {player_name}: {e}")
                await asyncio.sleep(1.0)

        summary = (
            f"✅ Backfilled High Score on **{len(patched_rows)}** submission(s) "
            f"across **{len(affected_players)}** player(s).\n"
            f"Registry cards rebuilt: {', '.join(rebuilt) or 'none'}"
        )
        if errors:
            summary += f"\n⚠️ Errors ({len(errors)}):\n" + "\n".join(errors[:5])
        await interaction.edit_original_response(content=summary)

    @app_commands.command(name="scan_leaderboard_duplicates", description="Scan all leaderboard threads for stale duplicate messages (mod only, read-only).")
    async def scan_leaderboard_duplicates(self, interaction: discord.Interaction):
        """Read-only audit: each leaderboard board tracks its current Discord message
        ID(s) in the DB. If a message edit ever fails (rate limit, transient API
        error, etc.), the old code path silently posted a brand-new message and
        moved the DB pointer to it, leaving the original stuck in the thread forever
        as a stale duplicate (found on the Glaive board, 2026-06-30). The edit path
        itself now cleans up after a failed edit going forward, but this command
        finds any duplicates that were already left behind before that fix. Nothing
        is deleted automatically — verify each flagged message before removing it.

        Multiple boards can share one thread (e.g. a map's Attack + Defense entries
        live in the same thread as two separately-tracked messages) — so tracked IDs
        are pooled globally before scanning, and threads are only scanned once each.
        Scanning thread-by-thread per board originally caused board A's tracked
        message to look "untracked" while scanning board B's thread, false-flagging
        legitimate Attack/Defense pairs as duplicates. Fixed 2026-06-30.
        """
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        bot_id = guild.me.id
        lb_rows = await _get_lb_records()

        # Pool ALL tracked message IDs globally, and group board names by thread —
        # several boards can legitimately live in the same thread.
        all_tracked_ids = set()
        threads_by_id = {}  # thread_id -> list of board names in that thread
        for lb_row in lb_rows:
            lb_name = (lb_row.get('Leaderboard Name') or '').strip()
            thread_id_raw = lb_row.get('Thread ID') or ''
            message_id_raw = lb_row.get('Message ID') or ''
            if not lb_name or not thread_id_raw:
                continue
            try:
                thread_id = int(thread_id_raw)
            except ValueError:
                continue
            tracked_ids = set(int(m) for m in _re.findall(r'\d{17,20}', str(message_id_raw)))
            if not tracked_ids:
                continue
            all_tracked_ids.update(tracked_ids)
            threads_by_id.setdefault(thread_id, []).append(lb_name)

        findings = []
        errors = []
        checked = 0

        for thread_id, board_names in threads_by_id.items():
            try:
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
            except Exception as e:
                errors.append(f"{', '.join(board_names)}: thread fetch failed ({e})")
                continue

            try:
                checked += 1
                extra = []
                async for msg in thread.history(limit=50, oldest_first=True):
                    if msg.author.id != bot_id or not msg.embeds:
                        continue
                    if msg.id in all_tracked_ids:
                        continue
                    extra.append(msg)
                if extra:
                    links = ", ".join(f"[msg]({m.jump_url})" for m in extra)
                    label = " / ".join(board_names)
                    findings.append(f"\u2022 **{label}** \u2014 {len(extra)} untracked embed message(s): {links}")
            except Exception as e:
                errors.append(f"{', '.join(board_names)}: history scan failed ({e})")
            await asyncio.sleep(0.2)

        if not findings:
            summary = f"\u2705 Scanned **{checked}** thread(s) \u2014 no stray/duplicate leaderboard messages found."
        else:
            summary = f"\u26a0\ufe0f Found possible duplicates in **{len(findings)}** of {checked} thread(s):\n" + "\n".join(findings[:15])
            if len(findings) > 15:
                summary += f"\n*...and {len(findings) - 15} more*"
            summary += "\n\nThis is read-only \u2014 nothing was deleted. Verify each link manually before removing it."

        if errors:
            summary += f"\n\n\u26a0\ufe0f Errors ({len(errors)}):\n" + "\n".join(errors[:5])

        await interaction.edit_original_response(content=summary[:1900])

    @app_commands.command(name="fix_board_decoration", description="Re-frame a single (non-map) board with fresh top/bottom decoration (mod only).")
    @app_commands.describe(name="Exact leaderboard name, e.g. 'Messer' or 'Glaive'")
    async def fix_board_decoration(self, interaction: discord.Interaction, name: str):
        """Decoration spacer images are only ever posted once, by /setup_leaderboard,
        and Discord has no way to insert a message "before" an existing one — so a
        board whose message was ever silently recreated by the old edit-fallback bug
        ended up sitting outside its original top/bottom frame permanently (Glaive,
        Messer, found 2026-06-30). _sync_board_messages now reposts a bottom
        decoration when IT recreates a message, but that doesn't retroactively fix
        boards already in this state from before that fix existed. This command
        deletes the board's current tracked message(s) and reposts everything fresh
        — DECORATION_TOP, the embed(s), DECORATION_BOTTOM — restoring the frame.
        Single-board (non-map) threads only; map boards share a thread with their
        Attack/Defense counterpart and aren't supported here.
        """
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        all_lb_rows = await _get_lb_records()
        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == name), None)
        if not lb_row:
            await interaction.edit_original_response(content=f"❌ No leaderboard found with name: `{name}`")
            return

        is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in name and name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
        if is_map:
            await interaction.edit_original_response(content=f"❌ `{name}` is a map board (shares a thread with its Attack/Defense counterpart) — not supported by this command yet.")
            return

        try:
            thread_id = int(lb_row['Thread ID'])
            thread = interaction.guild.get_channel(thread_id) or await interaction.guild.fetch_channel(thread_id)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Couldn't fetch thread: {e}")
            return

        old_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(lb_row['Message ID']))]
        for old_id in old_ids:
            try:
                old_msg = await thread.fetch_message(old_id)
                await old_msg.delete()
            except Exception:
                pass

        entries = await get_leaderboard_entries(name)
        show_weapon = name in ("100 Kills", "200 Takedowns")
        score_prefix = "+" if name == "TUFF" else ""
        embeds = format_leaderboard_embeds(name, entries, 0, show_weapon, score_prefix)

        try:
            await thread.send(file=discord.File(DECORATION_TOP))
            new_ids = []
            for emb in embeds:
                m = await thread.send(embed=emb)
                new_ids.append(str(m.id))
            await thread.send(file=discord.File(DECORATION_BOTTOM))
            await _db.update_leaderboard_messages(name, '|'.join(new_ids))
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Re-post failed: {e}")
            return

        await interaction.edit_original_response(content=f"✅ **{name}** re-framed with fresh decoration.")

    @app_commands.command(name="fix_map_duplicates", description="Delete stray duplicate header messages on map boards (mod only).")
    async def fix_map_duplicates(self, interaction: discord.Interaction):
        """One-off cleanup for orphaned header-only messages left behind by an
        older posting scheme that tracked more message IDs per map board than
        format_leaderboard_embeds actually produces. _sync_board_messages only
        ever looped over len(embeds), so any extra tracked ID was never edited,
        never deleted, and — once a /refresh overwrote the DB row with the
        shorter new_ids list — no longer tracked anywhere at all, leaving a
        plain-text "[icon] Map Faction [icon]" message sitting above the real
        embed forever (found 2026-06-30, every map board affected). Going
        forward _sync_board_messages cleans these up itself; this command
        sweeps up the ones that already exist and are no longer in the DB to
        be found by that fix or by /scan_leaderboard_duplicates (which only
        flags untracked messages that have an embed — these don't).

        Scoped tight to avoid touching anything unrelated: only deletes bot
        messages in map-board threads that have NO embed, NO attachment, and
        whose content contains the bold "**Map Faction**" core for some board
        in that same thread (i.e. a duplicate of a real header, not just any
        message with text in it).
        """
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        bot_id = guild.me.id
        all_lb_rows = await _get_lb_records()

        # Group map boards by thread, tracking which message IDs are
        # legitimately current and the "core" header text (map + faction,
        # without the leading/trailing icon) that belongs there. The icon
        # suffix logic has changed across deploys, so a stray message left
        # behind by an older version of this code may not be byte-identical
        # to what _map_header() returns today -- only the bold "**Map
        # Faction**" core is stable across versions, so that's what gets
        # matched, not the full header string.
        threads = {}  # thread_id -> {'tracked': set(ids), 'cores': set(core text)}
        for lb_row in all_lb_rows:
            lb_name = (lb_row.get('Leaderboard Name') or '').strip()
            thread_id_raw = lb_row.get('Thread ID') or ''
            if not lb_name or not thread_id_raw:
                continue
            is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
            if not is_map or ' - ' not in lb_name:
                continue
            try:
                thread_id = int(thread_id_raw)
            except ValueError:
                continue
            map_name, faction = lb_name.split(' - ', 1)
            core = f"**{map_name} {faction}**"
            tracked_ids = set(int(m) for m in _re.findall(r'\d{17,20}', str(lb_row.get('Message ID') or '')))
            entry = threads.setdefault(thread_id, {'tracked': set(), 'cores': set()})
            entry['tracked'].update(tracked_ids)
            entry['cores'].add(core)

        deleted = []
        errors = []
        checked = 0

        for thread_id, info in threads.items():
            try:
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
            except Exception as e:
                errors.append(f"Thread {thread_id}: fetch failed ({e})")
                continue
            try:
                checked += 1
                async for msg in thread.history(limit=50, oldest_first=True):
                    if msg.author.id != bot_id:
                        continue
                    if msg.id in info['tracked']:
                        continue
                    if msg.embeds or msg.attachments:
                        continue
                    content = msg.content.strip()
                    if content and any(core in content for core in info['cores']):
                        try:
                            await msg.delete()
                            deleted.append(f"{msg.content.strip()} ({msg.jump_url})")
                            await asyncio.sleep(0.3)
                        except Exception as de:
                            errors.append(f"Delete failed for {msg.id}: {de}")
            except Exception as e:
                errors.append(f"Thread {thread_id}: scan failed ({e})")

        summary = f"✅ Scanned {checked} map thread(s), deleted {len(deleted)} stray duplicate header(s)."
        if deleted:
            summary += "\n" + "\n".join(deleted[:15])
            if len(deleted) > 15:
                summary += f"\n*...and {len(deleted) - 15} more*"
        if errors:
            summary += "\n⚠️ Errors:\n" + "\n".join(errors[:5])
        await interaction.edit_original_response(content=summary[:1900])

    @app_commands.command(name="cleanup_boards", description="Remove junk board entries with missing map/weapon names (mod only).")
    async def cleanup_boards_cmd(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        n = await _db.delete_junk_leaderboard_rows()
        await interaction.edit_original_response(
            content=f"\u2705 Removed {n} junk board entr{'y' if n == 1 else 'ies'} (missing map/weapon names).")

    @app_commands.command(name="rebuild_boards", description="Rebuild weapon + map boards from full submission history (mod only).")
    @app_commands.describe(name="Optional: only this board (exact name). Blank = every weapon + map board.")
    async def rebuild_boards_cmd(self, interaction: discord.Interaction, name: str = None):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        board_names = [name] if name else None
        try:
            summary = await rebuild_score_boards(interaction.guild, board_names=board_names)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Rebuild failed: {e}")
            return
        await interaction.edit_original_response(content=(
            f"✅ Rebuilt **{summary['boards']}** board(s) from submissions. "
            f"Added {summary['added']}, updated {summary['updated']}, "
            f"evicted {summary['evicted']} beyond top-10."
        ))

    @app_commands.command(name="board_audit", description="Read-only: list submission scores missing from weapon/map boards (mod only).")
    @app_commands.describe(name="Optional: only this board (exact name). Blank = every weapon + map board.")
    @app_commands.autocomplete(name=_rank_name_ac)
    async def board_audit_cmd(self, interaction: discord.Interaction, name: str = None):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        all_lb = await _get_lb_records()
        all_subs = await _db.get_all_submissions()
        lines = []
        total = 0

        for rec in all_lb:
            nm = rec["Leaderboard Name"]
            kind = _classify_board(nm, rec.get("Type", ""))
            if kind not in ("weapon", "map"):
                continue
            if name and nm != name:
                continue

            best = {}
            for s in all_subs:
                if len(s) < 13:
                    continue
                pname_s = (s[1] or "").strip()
                did = s[2] or ""
                key = did if did else (("legacy:" + pname_s.lower()) if pname_s else "")
                td = _safe_int(s[7])
                if kind == "weapon":
                    if s[3] != nm:
                        continue
                    if (s[10] or "").strip().lower() == "yes":
                        continue
                    score = td
                else:
                    if (str(s[5]) + " - " + str(s[6])) != nm:
                        continue
                    score = td
                if score <= 0 or not key:
                    continue
                if key not in best or score > best[key][0]:
                    best[key] = (score, pname_s)

            existing = await _db.get_leaderboard_by_board(nm)
            existing_names = {(r[1] or "").strip().lower() for r in existing}
            existing_scores = sorted((_safe_int(r[3]) for r in existing), reverse=True)
            cap10 = existing_scores[9] if len(existing_scores) >= 10 else 0

            missing = [(sc, pn) for sc, pn in best.values()
                       if pn.lower() not in existing_names and sc > cap10]
            if missing:
                missing.sort(reverse=True)
                total += len(missing)
                lines.append("**" + nm + "** - " + str(len(missing)) + " missing:")
                for sc, pn in missing[:6]:
                    lines.append("  - " + pn + " - " + str(sc))

        if not lines:
            await interaction.edit_original_response(
                content="No submission-backed scores are missing from any board top-10.")
            return

        board_count = sum(1 for l in lines if l.startswith("**"))
        noun = "entry" if total == 1 else "entries"
        header = "**Board audit** - " + str(total) + " " + noun + " missing from top-10 across " + str(board_count) + " board(s):\n\n"
        msg = header + "\n".join(lines)
        if len(msg) > 1950:
            msg = msg[:1900] + "\n... (truncated - run with a board name for detail)"
        await interaction.edit_original_response(content=msg)

    @app_commands.command(name="add_board_score", description="Manually add/restore a single board entry (mod only).")
    @app_commands.describe(board="Exact board name (e.g. War Axe, Heavy Mace, Rudhelm - Mason)",
                           player="Player name as shown on the board",
                           score="Score (takedowns for weapon/map boards)",
                           link="Optional message link")
    @app_commands.autocomplete(board=_rank_name_ac)
    async def add_board_score_cmd(self, interaction: discord.Interaction, board: str,
                                  player: str, score: int, link: str = None):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        board = board.strip()
        player = player.strip()

        try:
            players = await _db.get_all_players()
        except Exception:
            players = []

        # If the mod @mentioned the player, Discord passes it as "<@id>"/"<@!id>".
        # Resolve it to the real discord_id + canonical board name, and remember the
        # junk "legacy:<@id>" key so we can purge a row a mistaken mention-add left.
        discord_id = ''
        stale_keys = []
        _m = _re.match(r'^<@!?(\d+)>$', player)
        if _m:
            mid = _m.group(1)
            discord_id = mid
            stale_keys += [f"legacy:<@{mid}>", f"legacy:<@!{mid}>"]
            canon = next(((p[1] or '').strip() for p in players
                          if p and (p[0] or '').strip() == mid and (p[1] or '').strip()), '')
            if not canon:
                _mem = interaction.guild.get_member(int(mid))
                canon = _mem.display_name if _mem else player
            player = canon
        else:
            for p in players:
                if p and len(p) > 1 and p[1] and p[1].strip().lower() == player.lower():
                    discord_id = (p[0] or '').strip()
                    break
            if discord_id:
                stale_keys += [f"legacy:<@{discord_id}>", f"legacy:<@!{discord_id}>"]

        key = discord_id if discord_id else f"legacy:{player.lower()}"

        kind = _classify_board(board, '')
        weapon = board if kind == 'weapon' else ''
        # Purge stale rows for this person: blank-id legacy rows by name, plus any
        # junk mention-keyed rows from a bad add.
        try:
            await _db.delete_blank_id_entries_by_name(board, player)
        except Exception:
            pass
        for _sk in stale_keys:
            try:
                await _db.delete_leaderboard_entry_by_board_and_player(board, _sk)
            except Exception:
                pass
        await _db.upsert_leaderboard_entry(board, player, key, score, link or '', weapon)

        # Re-cap top-10 for weapon/map boards, then re-render.
        if kind in ('weapon', 'map'):
            rows = await _db.get_leaderboard_by_board(board)
            for _ in range(max(0, len(rows) - 10)):
                await _db.delete_lowest_leaderboard_entry(board)

        rec = next((r for r in await _get_lb_records() if r['Leaderboard Name'] == board), None)
        if rec:
            await _render_board(interaction.guild, rec, board)

        # Report whether it survived the top-10 cap.
        final = sorted(await _db.get_leaderboard_by_board(board),
                       key=lambda r: _safe_int(r[3]) if len(r) > 3 else 0, reverse=True)
        survived = any((r[1] or '').strip().lower() == player.lower()
                       and _safe_int(r[3]) == score for r in final[:10])
        note = "" if survived else " ⚠️ (ranked below top-10, stored but not shown)"
        await interaction.edit_original_response(
            content=f"✅ Set **{player}** = {score} on **{board}**.{note}")

    @app_commands.command(name="remove_board_score", description="Remove a player's entry from a board (mod only).")
    @app_commands.describe(board="Exact board name (e.g. Battle Axe)",
                           player="Player name exactly as shown on the board (or an @mention)")
    @app_commands.autocomplete(board=_rank_name_ac)
    async def remove_board_score_cmd(self, interaction: discord.Interaction, board: str, player: str):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        board = board.strip()
        player = player.strip()

        # Match by the visible name; if they passed an @mention, also resolve it to
        # the player's canonical name so either form works, and keep the raw "<@id>"
        # string too (in case a bad add stored the mention as the name).
        names = {player}
        _m = _re.match(r'^<@!?(\d+)>$', player)
        if _m:
            mid = _m.group(1)
            try:
                for p in await _db.get_all_players():
                    if p and (p[0] or '').strip() == mid and (p[1] or '').strip():
                        names.add((p[1] or '').strip())
                        break
            except Exception:
                pass

        removed = 0
        for nm in names:
            try:
                removed += await _db.delete_leaderboard_entries_by_board_and_name(board, nm)
            except Exception as e:
                print(f"[REMOVE_BOARD] delete error for {nm}: {e}")

        if removed:
            rec = next((r for r in await _get_lb_records() if r['Leaderboard Name'] == board), None)
            if rec:
                await _render_board(interaction.guild, rec, board)
            await interaction.edit_original_response(
                content=f"\u2705 Removed {removed} entr{'y' if removed == 1 else 'ies'} for **{player}** from **{board}**.")
        else:
            await interaction.edit_original_response(
                content=f"\u26a0\ufe0f No entry found for **{player}** on **{board}** \u2014 check the exact name shown on the board.")

    @app_commands.command(name="backfill_feat_boards", description="Scan submissions and add missing 100 Kills / 200 Takedowns / Pacifist entries (mod only).")
    async def backfill_feat_boards(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        FEAT_MAP = {"100 Kills": "kills", "200 Takedowns": "takedowns", "Triple": "takedowns"}
        sub_rows = await _db.get_all_submissions()
        lb_rows  = await _db.get_all_leaderboard_data()

        existing = {(r[0], r[4]) for r in lb_rows if len(r) > 4}

        added = 0
        for row in sub_rows:
            if len(row) < 13:
                continue
            feats_str  = row[11] or ""
            link       = (row[12] or "").strip()
            player     = row[1] or ""
            discord_id = row[2] or ""
            kills      = int(row[8]) if row[8] else 0
            takedowns  = int(row[7]) if row[7] else 0
            weapon     = row[3] or ""
            if not link:
                continue
            # Pacifist: 0-kill run with <=10 takedowns, ranked by raw score. Needs a
            # stored score (older subs from before the score column are NULL -> skip).
            if kills == 0 and takedowns <= 10:
                p_score = 0
                if len(row) > 24 and row[24]:
                    try:
                        p_score = int(str(row[24]).replace(',', '').strip())
                    except (ValueError, TypeError):
                        p_score = 0
                if p_score > 0 and ("Pacifist", link) not in existing:
                    await _db.add_leaderboard_entry("Pacifist", player, discord_id, p_score, link, weapon)
                    existing.add(("Pacifist", link))
                    added += 1
                continue  # a pacifist run qualifies for no other feat board

            is_triple_row = 'Triple' in (feats_str or '')
            for board, stat in FEAT_MAP.items():
                # Qualify by raw stats — catches Triples that didn't get the feat tag
                score = kills if stat == "kills" else takedowns
                if board == "Triple":
                    if not is_triple_row:
                        continue
                else:
                    threshold = 100 if stat == "kills" else 200
                    if score < threshold:
                        continue
                if (board, link) in existing:
                    continue
                await _db.add_leaderboard_entry(board, player, discord_id, score, link, weapon)
                existing.add((board, link))
                added += 1

        await _prune_pacifist_board()
        await interaction.edit_original_response(content=f"\u2705 Added **{added}** missing feat board entries. Run `/refresh` on each board to update Discord.")

    @app_commands.command(name="backfill_legacy_ids", description="Attach registered discord_ids to blank-id legacy board rows (mod only). Preview first.")
    @app_commands.describe(confirm="Leave false to PREVIEW. Set true to actually stamp the ids.")
    async def backfill_legacy_ids(self, interaction: discord.Interaction, confirm: bool = False):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            name_to_id = await _db.get_name_to_id_map()
            ld = await _db.get_all_leaderboard_data()
        except Exception as e:
            await interaction.followup.send(f"\u274c Read failed: {e}", ephemeral=True)
            return
        matched = {}    # name -> [discord_id, row_count]
        unmatched = {}  # name -> row_count
        for row in ld:
            did = (row[2] or '').strip() if len(row) > 2 else ''
            name = (row[1] or '').strip() if len(row) > 1 else ''
            if did or not name:
                continue
            k = name.lower()
            if k in name_to_id:
                matched.setdefault(name, [name_to_id[k], 0])
                matched[name][1] += 1
            else:
                unmatched[name] = unmatched.get(name, 0) + 1
        if not matched and not unmatched:
            await interaction.followup.send("\u2705 No blank-id legacy rows found \u2014 nothing to backfill.", ephemeral=True)
            return
        if not confirm:
            lines = ["**Legacy id backfill \u2014 PREVIEW** (nothing written yet)\n"]
            if matched:
                _rows = sum(c for _, c in matched.values())
                lines.append(f"__Will match {len(matched)} names ({_rows} rows):__")
                for nm in sorted(matched)[:40]:
                    did, cnt = matched[nm]
                    lines.append(f"\u2022 `{nm}` \u2192 <@{did}> ({cnt} row{'s' if cnt != 1 else ''})")
                if len(matched) > 40:
                    lines.append(f"\u2026and {len(matched) - 40} more.")
            if unmatched:
                _urows = sum(unmatched.values())
                lines.append(f"\n__No registered player for {len(unmatched)} names ({_urows} rows) \u2014 left as-is:__")
                for nm in sorted(unmatched)[:25]:
                    lines.append(f"\u2022 `{nm}` ({unmatched[nm]})")
                if len(unmatched) > 25:
                    lines.append(f"\u2026and {len(unmatched) - 25} more.")
            lines.append("\nRun `/backfill_legacy_ids confirm:true` to apply the matches above.")
            await interaction.followup.send("\n".join(lines)[:1990], ephemeral=True)
            return
        updated_rows = 0
        for nm, (did, _cnt) in matched.items():
            try:
                updated_rows += await _db.set_legacy_discord_id(nm, did)
            except Exception as e:
                print(f"[LEGACY_ID] {nm}: {e}")
        await interaction.followup.send(
            f"\u2705 Stamped ids on **{updated_rows}** legacy rows across **{len(matched)}** names. "
            f"{len(unmatched)} names had no registered player and were left untouched. "
            f"Run `/refresh_all` + `/bulk_refresh_cards` to re-render.", ephemeral=True)

    @app_commands.command(name="link_legacy_name", description="Link a legacy board name to a registered player + save it as an alias (mod only).")
    @app_commands.describe(legacy_name="The exact legacy name as it shows on the board, e.g. Steezy",
                           player="The registered player it belongs to")
    async def link_legacy_name(self, interaction: discord.Interaction, legacy_name: str, player: discord.Member):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        legacy_name = legacy_name.strip()
        if not legacy_name:
            await interaction.followup.send("Give me a name to link.", ephemeral=True)
            return
        try:
            n = await _db.set_legacy_discord_id(legacy_name, str(player.id))
        except Exception as e:
            await interaction.followup.send(f"\u274c Failed to stamp rows: {e}", ephemeral=True)
            return
        try:
            await _db.save_player_ign(str(player.id), legacy_name)
        except Exception as _ie:
            print(f"[LINK_LEGACY] ign save for {legacy_name}: {_ie}")
        await interaction.followup.send(
            f"\u2705 Linked `{legacy_name}` \u2192 {player.mention} \u2014 stamped **{n}** board row"
            f"{'s' if n != 1 else ''} and saved it as an alias. Run `/refresh_all` + refresh their card once you've batched them.",
            ephemeral=True)

    @app_commands.command(name="map_stats", description="All-time submission counts per map + faction, as a bar breakdown (mod only).")
    async def map_stats(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer()
        subs = await _db.get_all_submissions()
        counts = {}       # (map, faction) -> count
        map_totals = {}   # map -> total
        for row in subs:
            m = (row[5] or '').strip() if len(row) > 5 else ''
            fac = (row[6] or '').strip() if len(row) > 6 else ''
            if not m or not fac:
                continue
            counts[(m, fac)] = counts.get((m, fac), 0) + 1
            map_totals[m] = map_totals.get(m, 0) + 1
        if not counts:
            await interaction.followup.send("No map submissions found.")
            return
        _max = max(counts.values())
        _grand = sum(counts.values())
        def _bar(n):
            return "\u2588" * max(1, round(n / _max * 12))
        embed = discord.Embed(
            title="\U0001f4ca Submissions by Map & Faction",
            description=f"**{_grand}** map submissions across **{len(map_totals)}** maps \u00b7 all-time",
            colour=0x8b6914,
        )
        for m in sorted(map_totals, key=lambda x: -map_totals[x]):
            facs = sorted([(f, c) for (mm, f), c in counts.items() if mm == m], key=lambda x: -x[1])
            lines = [f"`{_bar(c):<12}` {f} \u2014 **{c}**" for f, c in facs]
            embed.add_field(name=f"{m}  \u00b7  {map_totals[m]}", value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="weapon_stats", description="Per-weapon breakdown: count, lethality, kill share or warlord (mod only).")
    @app_commands.describe(metric="What to rank weapons by (default: submission count).")
    @app_commands.choices(metric=[
        app_commands.Choice(name="Submission count", value="count"),
        app_commands.Choice(name="Lethality (kills/TD)", value="lethality"),
        app_commands.Choice(name="Kill Share", value="kill_share"),
        app_commands.Choice(name="Warlord", value="warlord"),
    ])
    async def weapon_stats(self, interaction: discord.Interaction, metric: app_commands.Choice[str] = None):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer()
        _metric_sel = metric.value if metric else "count"
        subs = await _db.get_all_submissions()
        if _metric_sel in ("lethality", "kill_share", "warlord"):
            def _pnum(x):
                try:
                    return float(str(x).replace(",", "").strip())
                except (ValueError, TypeError, AttributeError):
                    return None
            _agg = {}
            for _row in subs:
                _w = (_row[3] or "").strip() if len(_row) > 3 else ""
                if not _w or _w in ("None", "Other", "Multiple Weapons"):
                    continue
                _ff = (_row[11] if len(_row) > 11 else "") or ""
                if "resubmit" in _ff.lower():
                    continue
                _tdv = _pnum(_row[7]) if len(_row) > 7 else None
                _kv = _pnum(_row[8]) if len(_row) > 8 else None
                _ksv = _pnum(_row[20]) if len(_row) > 20 else None
                if _tdv is None or _kv is None:
                    continue
                if _metric_sel == "lethality":
                    if _tdv <= 0:
                        continue
                    _val = _kv / _tdv * 100
                elif _metric_sel == "kill_share":
                    if _ksv is None:
                        continue
                    _val = _ksv
                else:
                    if _ksv is None or _kv <= 0:
                        continue
                    _val = _tdv * _ksv / _kv
                _e = _agg.setdefault(_w, [0.0, 0]); _e[0] += _val; _e[1] += 1
            _rows2 = [(_w, _e[0] / _e[1], _e[1]) for _w, _e in _agg.items() if _e[1] >= 5]
            if not _rows2:
                await interaction.followup.send("Not enough weapon data for that metric (need 5+ submissions).")
                return
            _maxr = max(_v for _, _v, _ in _rows2) or 1
            def _barr(x):
                return "█" * max(1, round(x / _maxr * 12))
            _ord = sorted(_rows2, key=lambda tpl: -tpl[1])
            _labels = {
                "lethality": ("🩸 Lethality by Weapon", "avg lethality (kills ÷ takedowns)"),
                "kill_share": ("💀 Kill Share by Weapon", "avg kill share (kills ÷ team kills)"),
                "warlord": ("🗡️ Warlord by Weapon", "avg warlord (takedowns ÷ team kills)"),
            }
            _title, _desc = _labels[_metric_sel]
            _hdr = f"{_desc} · weapons with 5+ submissions · all-time"
            _lns = [f"`{_barr(v):<12}` {w} — **{v:.0f}%** ({n})" for w, v, n in _ord]
            _bdy = _hdr + "\n\n" + "\n".join(_lns)
            if len(_bdy) > 4000:
                _keep, _tot = [], len(_hdr) + 2
                for _ln in _lns:
                    if _tot + len(_ln) + 1 > 3900:
                        break
                    _keep.append(_ln); _tot += len(_ln) + 1
                _bdy = _hdr + "\n\n" + "\n".join(_keep) + f"\n…and {len(_lns) - len(_keep)} more."
            await interaction.followup.send(embed=discord.Embed(title=_title, description=_bdy, colour=0x8b6914))
            return
        subs = subs
        counts = {}
        for row in subs:
            w = (row[3] or "").strip() if len(row) > 3 else ""
            if not w or w in ("None", "Other", "Multiple Weapons"):
                continue
            counts[w] = counts.get(w, 0) + 1
        if not counts:
            await interaction.followup.send("No weapon submissions found.")
            return
        _max = max(counts.values())
        _grand = sum(counts.values())
        def _bar(n):
            return "\u2588" * max(1, round(n / _max * 12))
        ordered = sorted(counts.items(), key=lambda x: -x[1])
        header = f"**{_grand}** submissions across **{len(counts)}** weapons \u00b7 all-time"
        body_lines = [f"`{_bar(c):<12}` {w} \u2014 **{c}**" for w, c in ordered]
        body = header + "\n\n" + "\n".join(body_lines)
        if len(body) > 4000:
            keep, total = [], len(header) + 2
            for ln in body_lines:
                if total + len(ln) + 1 > 3900:
                    break
                keep.append(ln); total += len(ln) + 1
            body = header + "\n\n" + "\n".join(keep) + f"\n\u2026and {len(body_lines) - len(keep)} more."
        embed = discord.Embed(title="\U0001f4ca Submissions by Weapon", description=body, colour=0x8b6914)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="dedupe_board", description="Remove exact duplicate entries from an unlimited board (mod only).")
    @app_commands.describe(name="Leaderboard name e.g. '100 Kills'")
    async def dedupe_board(self, interaction: discord.Interaction, name: str):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        all_values = await _db.get_all_leaderboard_data()
        rows = [r for r in all_values if r[0] == name]
        seen = set()
        removed = 0
        for r in rows:
            # Use (discord_id, message_link) as unique key — same link = same game
            key = (r[2], r[4] if len(r) > 4 else '')
            if key in seen:
                await _db.delete_leaderboard_entry_by_link(name, r[4] if len(r) > 4 else '')
                removed += 1
            else:
                seen.add(key)
        await interaction.edit_original_response(content=f"\u2705 Removed **{removed}** duplicate entries from **{name}**. Run `/refresh` to update the board.")


    @app_commands.command(name="refresh_hundred_handed", description="Redraw the Hundred Handed board only — no data or role changes (mod only).")
    async def refresh_hundred_handed(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await refresh_hundred_handed_board(interaction.guild)
            await interaction.followup.send("\u2705 Hundred Handed board redrawn (nothing else touched \u2014 no seeding, no roles).", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"\u274c Refresh failed: {e}", ephemeral=True)

    @app_commands.command(name="backfill_hundred_handed", description="Seed Hundred Handed from submissions + legacy list (mod only).")
    async def backfill_hundred_handed(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        added = 0

        # 1. Seed legacy completers using their real discord_id from players table
        all_players = await _db.get_all_players()
        name_to_id = {}
        for p in all_players:
            if p and len(p) > 1 and p[1]:
                name_to_id[p[1].strip().lower()] = (p[0].strip(), p[1].strip())
        for name in _HH_LEGACY_COMPLETERS:
            match = name_to_id.get(name.lower())
            if match:
                real_id, real_name = match
            else:
                # Never registered / name not in the players table — seed under a
                # stable name-based id so they still show as completers. If they
                # later register, the board (collapse-by-name) and
                # /consolidate_hundred_handed will merge them onto their real id.
                real_id, real_name = f"legacy:{name.strip().lower()}", name
                print(f"[HH] Legacy completer '{name}' not in players table — seeding under {real_id}")
            for subclass, weapons in _HH_PRIMARIES.items():
                for weapon in weapons:
                    is_new = await _db.add_hundred_handed(real_id, real_name, subclass, weapon)
                    if is_new:
                        added += 1

        # 2. Scan submissions — primary non-archer weapons only
        # Row indices: [0]=timestamp [1]=player_name [2]=discord_id [3]=weapon [4]=subclass [7]=takedowns
        all_subs = await _db.get_all_submissions()
        for row in all_subs:
            try:
                discord_id = str(row[2]) if len(row) > 2 and row[2] else None
                player_name = str(row[1]) if len(row) > 1 and row[1] else None
                weapon = str(row[3]).strip() if len(row) > 3 and row[3] else None
                subclass = str(row[4]).strip() if len(row) > 4 and row[4] else None
                takedowns = int(row[7]) if len(row) > 7 and row[7] else 0
                if not discord_id or not weapon or not subclass or takedowns < 100:
                    continue
                if subclass not in _HH_PRIMARIES:
                    continue
                if weapon not in _HH_PRIMARIES[subclass]:
                    continue
                is_new = await _db.add_hundred_handed(discord_id, player_name or '', subclass, weapon)
                if is_new:
                    added += 1
            except Exception:
                continue

        await refresh_hundred_handed_board(interaction.guild)

        # Assign Hundred-Handed role to anyone who qualifies
        hh_role_assigned = []
        hh_role_revoked = []
        try:
            hh_role = interaction.guild.get_role(config.HUNDRED_HANDED_ROLE_ID)
            if hh_role:
                # STRICT: role requires all 46 required (subclass, weapon) primary combos.
                _mc = _hh_matched_counts(await _db.get_all_hundred_handed())
                _qualified = {did for did, (nm, m, _p) in _mc.items() if m >= HH_TOTAL}
                for did in _qualified:
                    try:
                        member = interaction.guild.get_member(int(did)) or await interaction.guild.fetch_member(int(did))
                        if member and hh_role not in member.roles:
                            await member.add_roles(hh_role, reason="Hundred-Handed: all 46 combos complete")
                            hh_role_assigned.append(member.display_name)
                    except Exception:
                        continue
                # NOTE: no auto-revoke — the role is a curated source of truth (some
                # legacy completers were granted it without every combo being logged).
        except Exception as role_e:
            print(f"[HH] Role sync error: {role_e}")

        role_msg = ""
        if hh_role_assigned:
            role_msg += f"\n\U0001f396\ufe0f Role granted: {', '.join(hh_role_assigned)}"
        await interaction.edit_original_response(content=f"\u2705 Seeded **{added}** Hundred Handed entries (12 legacy + submissions scan). Board updated.{role_msg}")

    @app_commands.command(name="consolidate_hundred_handed", description="Merge duplicate Hundred Handed identities into one per player (mod only).")
    @app_commands.describe(confirm="Apply the merge. Leave off for a dry-run preview.")
    async def consolidate_hundred_handed(self, interaction: discord.Interaction, confirm: bool = False):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            res = await _db.consolidate_hundred_handed(dry_run=not confirm)
        except Exception as e:
            await interaction.followup.send(f"\u274c Error: {e}", ephemeral=True)
            return
        if res["players"] == 0:
            await interaction.followup.send("No duplicate Hundred Handed identities found \u2014 nothing to merge.", ephemeral=True)
            return
        detail = "\n".join(res["details"][:15])
        more = f"\n\u2026and {len(res['details']) - 15} more" if len(res["details"]) > 15 else ""
        if confirm:
            await refresh_hundred_handed_board(interaction.guild)
            await interaction.followup.send(
                f"\u2705 Merged **{res['players']}** duplicate identities, removed **{res['removed']}** redundant rows. Board refreshed.\n{detail}{more}",
                ephemeral=True)
        else:
            await interaction.followup.send(
                f"**Dry run** \u2014 would merge **{res['players']}** identities and remove **{res['removed']}** rows:\n{detail}{more}\n\nRun again with `confirm: True` to apply.",
                ephemeral=True)


def _hh_matched_counts(all_pairs):
    """discord_id -> (player_name, matched_count, done_pairs). matched_count counts
    ONLY the 46 required (subclass, weapon) primary combos — secondary/extra combos in
    the table are ignored, so board, role and card all agree on true completion."""
    _req = {(sc, w) for sc, ws in _HH_PRIMARIES.items() for w in ws}
    _by = {}
    for did, name, sc, w in all_pairs:
        did = (did or '').strip(); name = (name or '').strip()
        key = did or ('name:' + name.lower())   # legacy rows have blank id -> group by name
        if not key:
            continue
        ent = _by.setdefault(key, ['', set()])
        ent[1].add((sc, w))
        if name:
            ent[0] = name
    return {key: (nm, len(pairs & _req), pairs) for key, (nm, pairs) in _by.items()}


async def refresh_hundred_handed_board(guild):
    """Rebuild The Hundred Handed embed in its thread."""
    all_lb_rows = await _get_lb_records()
    lb_row = next((r for r in all_lb_rows if r.get('Leaderboard Name') == 'The Hundred Handed'), None)
    if not lb_row:
        print("[HUNDRED_HANDED] No leaderboard row found for 'The Hundred Handed'")
        return

    thread_id = int(lb_row['Thread ID'])
    message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(lb_row['Message ID']))]

    _hh_emoji = "<:hhanded:1430199468246044772>"
    # Board mirrors the Hundred-Handed ROLE holders (the curated source of truth for
    # who has completed it) — not the raw combo count, which can lag behind for
    # players whose historical combos were never fully logged.
    _hh_role = guild.get_role(config.HUNDRED_HANDED_ROLE_ID)
    completers = sorted([m.display_name for m in (_hh_role.members if _hh_role else [])],
                        key=lambda n: n.lower())
    if not completers:
        desc = "*No completions yet.*"
    else:
        desc = "\n".join(f"│ {i}. `{nm}` — {_hh_emoji} {HH_TOTAL}/{HH_TOTAL} \u2713"
                         for i, nm in enumerate(completers, 1))

    embed = discord.Embed(title=_hh_emoji, description=desc, colour=EMBED_GOLD)
    embed.set_footer(text="Last updated")
    embed.timestamp = datetime.now(timezone.utc)

    try:
        thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
        if message_ids:
            try:
                msg = await thread.fetch_message(message_ids[0])
                await msg.edit(content="", embed=embed)
            except Exception:
                msg = await thread.send(embed=embed)
                await _db.update_leaderboard_messages('The Hundred Handed', str(msg.id))
        else:
            msg = await thread.send(embed=embed)
            await _db.update_leaderboard_messages('The Hundred Handed', str(msg.id))
    except Exception as e:
        print(f"[HUNDRED_HANDED] Board refresh error: {e}")


async def setup(bot):
    await bot.add_cog(LeaderboardsCog(bot))
