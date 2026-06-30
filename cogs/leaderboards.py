from datetime import datetime, timezone
# Leaderboard read/write, Discord thread management, and the index builder.
# update_leaderboards() is the main entry point — called after every submission.
import asyncio
import os
import re as _re
import discord
from discord import app_commands
from discord.ext import commands

import config
import utils.db as _db
from utils.helpers import nerve_log_error

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


async def build_ledger_entrance(guild):
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
            [("⚖️ Challenge Rules",         1460713024082935930)],
            [("🗂️ Butler's Archive",        REGISTRY_INDEX_THREAD_ID)],
            [(f"{bounty_emoji} {bounty_label}", bounty_channel_id),
             ("📋 Butler's Favourites",     1518822798116524092)],
            [("🏆 Map Records",             idx_maps.id if idx_maps else None),
             ("⚔️ 2H Weapons",             INDEX_THREAD_2H),
             ("🗡️ 1H Weapons",             INDEX_THREAD_1H)],
            [("🏛️ Feats of War",           INDEX_THREAD_FEATS)],
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

        _entrance_message_ids.clear()
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

        if not embed_fields:
            embed_fields = [("No boards yet", "*Nothing here yet.*")]
        embeds = _build_embeds(embed_fields)

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

    return new_ids


async def update_leaderboards(interaction, selected_weapon, selected_map, faction,
                              takedowns, kills, deaths, vip, feats,
                              player_name, message_link, bot_user=None, second_place_td=None):
    guild = interaction.guild
    discord_id = str(interaction.user.id)
    any_updated = False  # True only when player beats their own score on a weapon/feat board (not map boards)
    placements = []

    updates = []

    if not vip:
        updates.append((selected_weapon, takedowns, True, True, False))

    map_lb_name = f"{selected_map} - {faction}"
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

    # Fetch all data once at the start
    all_values = await _db.get_all_leaderboard_data()
    all_lb_rows = await _get_lb_records()

    for lb_name, score, top_10, personal_best, unlimited_top50 in updates:
        # Find existing entry for this player on this board
        existing_score = None
        for row in all_values:
            if row[0] == lb_name and row[2] == discord_id:
                existing_score = int(row[3]) if row[3] else 0
                break
        existing_entry = existing_score is not None

        if unlimited_top50:
            # No cap — but skip if this exact submission link already on the board
            already_exists = any(
                r[0] == lb_name and r[2] == discord_id
                and (r[4] if len(r) > 4 else '') == (message_link or '')
                for r in all_values
            )
            if already_exists:
                continue
            await _db.add_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
            any_updated = True
            all_board = [int(r[3]) for r in all_values if r[0] == lb_name and len(r) > 3 and r[3]]
            all_board.append(score)
            all_board.sort(reverse=True)
            pos = all_board.index(score) + 1
            placements.append((lb_name, pos))
        elif personal_best:
            if existing_entry:
                if score > existing_score:
                    await _db.upsert_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
                    any_updated = True
                    board_scores = sorted([int(r[3]) for r in all_values if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
                    board_scores = [s for s in board_scores if s != existing_score]
                    board_scores.append(score)
                    board_scores.sort(reverse=True)
                    pos = board_scores.index(score) + 1
                    placements.append((lb_name, pos))
                else:
                    continue
            else:
                if top_10:
                    board_entries = [row for row in all_values if row[0] == lb_name]
                    board_entries_sorted = sorted(
                        board_entries, key=lambda x: int(x[3]) if len(x) > 3 and x[3] else 0, reverse=True
                    )
                    if len(board_entries_sorted) >= 10:
                        lowest_score = int(board_entries_sorted[9][3]) if board_entries_sorted[9][3] else 0
                        if score <= lowest_score:
                            continue
                        tenth_discord_id = board_entries_sorted[9][2] if len(board_entries_sorted[9]) > 2 else ''
                        await _db.delete_leaderboard_entry_by_board_and_player(lb_name, tenth_discord_id)
                        all_values = await _db.get_all_leaderboard_data()
                await _db.upsert_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
                any_updated = True  # New entry on a board counts as a PB
                board_scores = sorted([int(r[3]) for r in all_values if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
                board_scores.append(score)
                board_scores.sort(reverse=True)
                pos = board_scores.index(score) + 1
                placements.append((lb_name, pos))
        else:
            await _db.add_leaderboard_entry(lb_name, player_name, discord_id, score, message_link, selected_weapon)
            any_updated = True
            board_scores = sorted([int(r[3]) for r in all_values if r[0] == lb_name and len(r) > 3 and r[3]], reverse=True)
            board_scores.append(score)
            board_scores.sort(reverse=True)
            pos = board_scores.index(score) + 1
            placements.append((lb_name, pos))

        # Reload and update Discord message
        updated_values = await _db.get_all_leaderboard_data()
        entries = []
        for row in updated_values:
            if row[0] == lb_name:
                entries.append({
                    'player': row[1] if len(row) > 1 else '',
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
        embeds = format_leaderboard_embeds(lb_name, entries, 0, show_weapon, score_prefix, show_title=not is_map)
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

_HH_ARCHER = {'Longbowman', 'Crossbowman', 'Skirmisher'}
_HH_PRIMARIES = {sc: ws for sc, ws in config._SUBCLASS_PRIMARIES.items() if sc not in _HH_ARCHER}
HH_TOTAL = sum(len(v) for v in _HH_PRIMARIES.values())
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

def format_leaderboard_embeds(lb_name, entries, overflow=0, show_weapon=False, score_prefix="", show_title=True):
    """Return a list of discord.Embeds for a leaderboard board, splitting if description is too long."""
    colour = _embed_colour(lb_name)
    if not entries:
        e = discord.Embed(title=_lb_title(lb_name, show_title), description="*No entries yet.*", colour=colour)
        e.set_footer(text="Last updated")
        e.timestamp = datetime.now(timezone.utc)
        return [e]

    lines = []
    for idx, e in enumerate(entries, 1):
        weapon_str = f" *{e['weapon']}*" if show_weapon and e.get('weapon') else ""
        score_str = f"{score_prefix}{e['score']}"
        if e['link']:
            lines.append(f"│ {idx}. `{e['player']}` — [{score_str}]({e['link']}){weapon_str}")
        else:
            lines.append(f"│ {idx}. `{e['player']}` — {score_str}{weapon_str}")
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
    return embeds


class LeaderboardsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
            lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
            if not lb_row:
                continue

            entries = await get_leaderboard_entries(lb_name)
            entries = sorted(entries, key=lambda x: x['score'], reverse=True)

            show_weapon = lb_name in ("100 Kills", "200 Takedowns")
            score_prefix = "+" if lb_name == "TUFF" else ""
            is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
            embeds = format_leaderboard_embeds(lb_name, entries, 0, show_weapon, score_prefix, show_title=not is_map)
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
                entries = sorted(entries, key=lambda x: x['score'], reverse=True)
                show_weapon = lb_name in ("100 Kills", "200 Takedowns")
                score_prefix = "+" if lb_name == "TUFF" else ""
                is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
                embeds = format_leaderboard_embeds(lb_name, entries, 0, show_weapon, score_prefix, show_title=not is_map)
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

    @app_commands.command(name="rank", description="Show the top 10 for a weapon or class leaderboard.")
    @app_commands.describe(name="Weapon or leaderboard name e.g. Messer, Halberd")
    async def rank_command(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        entries = await get_leaderboard_entries(name)
        if not entries:
            # Try case-insensitive match
            all_rows = await _db.get_all_leaderboard_data()
            all_boards = {row[0].strip() for row in all_rows if row}
            match = next((b for b in all_boards if b.lower() == name.lower()), None)
            if match:
                entries = await get_leaderboard_entries(match)
                name = match
            else:
                suggestions = [b for b in sorted(all_boards) if name.lower() in b.lower()][:5]
                msg = f"No leaderboard found for **{name}**."
                if suggestions:
                    msg += f" Did you mean: {', '.join(f'`{s}`' for s in suggestions)}?"
                await interaction.followup.send(msg, ephemeral=True)
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
                        'score': int(row[3]) if len(row) > 3 and row[3] else 0,
                        'link': row[4] if len(row) > 4 else '',
                        'weapon': row[5] if len(row) > 5 else '',
                    })
            entries.sort(key=lambda x: x['score'], reverse=True)

            show_weapon = lb_name in ("100 Kills", "200 Takedowns")
            score_prefix = "+" if lb_name == "TUFF" else ""
            is_map = (lb_row.get('Type', '').strip().lower() == 'map') or (' - ' in lb_name and lb_name.split(' - ')[0] in config.MAP_ATTACK_DEFENSE)
            embeds = format_leaderboard_embeds(lb_name, entries, 0, show_weapon, score_prefix, show_title=not is_map)
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
            await build_ledger_entrance(interaction.guild)
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
            await build_ledger_entrance(guild)
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

    @app_commands.command(name="backfill_feat_boards", description="Scan submissions and add missing 100 Kills / 200 Takedowns entries (mod only).")
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

        await interaction.edit_original_response(content=f"\u2705 Added **{added}** missing feat board entries. Run `/refresh` on each board to update Discord.")

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
            if not match:
                print(f"[HH] Legacy completer '{name}' not found in players table — skipping")
                continue
            real_id, real_name = match
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
        try:
            hh_role = interaction.guild.get_role(config.HUNDRED_HANDED_ROLE_ID)
            if hh_role:
                _all_primaries = {w for sc, ws in _HH_PRIMARIES.items() for w in ws}
                all_subs_for_role = await _db.get_all_submissions()
                player_weapons: dict[str, set] = {}
                for r in all_subs_for_role:
                    if len(r) > 3 and r[2].strip() and r[3].strip():
                        player_weapons.setdefault(r[2].strip(), set()).add(r[3].strip())
                for discord_id_str, weapons in player_weapons.items():
                    if not _all_primaries.issubset(weapons):
                        continue
                    try:
                        member = interaction.guild.get_member(int(discord_id_str)) or await interaction.guild.fetch_member(int(discord_id_str))
                        if hh_role not in member.roles:
                            await member.add_roles(hh_role, reason="Backfill: Hundred-Handed role")
                            hh_role_assigned.append(member.display_name)
                    except Exception:
                        continue
        except Exception as role_e:
            print(f"[HH] Role backfill error: {role_e}")

        role_msg = f"\n\U0001f396\ufe0f Role assigned to: {', '.join(hh_role_assigned)}" if hh_role_assigned else ""
        await interaction.edit_original_response(content=f"\u2705 Seeded **{added}** Hundred Handed entries (12 legacy + submissions scan). Board updated.{role_msg}")


async def refresh_hundred_handed_board(guild):
    """Rebuild The Hundred Handed embed in its thread."""
    all_lb_rows = await _get_lb_records()
    lb_row = next((r for r in all_lb_rows if r.get('Leaderboard Name') == 'The Hundred Handed'), None)
    if not lb_row:
        print("[HUNDRED_HANDED] No leaderboard row found for 'The Hundred Handed'")
        return

    thread_id = int(lb_row['Thread ID'])
    message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(lb_row['Message ID']))]

    rows = await _db.get_hundred_handed_leaderboard()
    _hh_emoji = "<:hhanded:1430199468246044772>"
    if not rows:
        desc = "*No entries yet.*"
    else:
        lines = []
        completers = [(did, name, cnt) for did, name, cnt in rows if cnt >= HH_TOTAL]
        in_progress = [(did, name, cnt) for did, name, cnt in rows if cnt < HH_TOTAL]
        for idx, (discord_id, player_name, count) in enumerate(completers, 1):
            lines.append(f"│ {idx}. `{player_name}` — {_hh_emoji} {count}/{HH_TOTAL} ✓")
        if in_progress:
            if completers:
                lines.append("")
                lines.append("*In Progress*")
            for discord_id, player_name, count in in_progress:
                lines.append(f"│ `{player_name}` — {count}/{HH_TOTAL}")
        desc = "\n".join(lines)

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
