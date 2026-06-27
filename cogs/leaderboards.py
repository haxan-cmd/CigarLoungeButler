# Leaderboard read/write, Discord thread management, and the index builder.
# update_leaderboards() is the main entry point — called after every submission.
import asyncio
import os
import re as _re
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.sheets import (
    _sheet_cache, sheet,
    leaderboards_ws, leaderboard_data_ws,
    gspread_retry, cached_leaderboard_data,
)

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
# { section_key: message_id }  — populated on first post, reused on every refresh.
_entrance_message_ids: dict = {}


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
    Post or refresh the 6-section ledger entrance in LEDGER_ENTRANCE_CHANNEL_ID.
    Each section is one message; Butler edits it in-place on subsequent calls.
    """
    try:
        channel = guild.get_channel(LEDGER_ENTRANCE_CHANNEL_ID)
        if not channel:
            channel = await guild.fetch_channel(LEDGER_ENTRANCE_CHANNEL_ID)

        # Pull all board rows from the sheet once
        try:
            all_lb_rows = leaderboards_ws.get_all_records()
        except Exception as e:
            print(f"Ledger entrance sheet read error: {e}")
            return

        def board_links(names_and_ids, guild_id, max_chars=1600):
            """Turn a list of (display_name, thread_id) into inline bullet links, capped to fit."""
            links = []
            for name, tid in names_and_ids:
                links.append(f"[{name}](https://discord.com/channels/{guild_id}/{tid})")
            result = ' • '.join(links)
            if len(result) <= max_chars:
                return result
            # Truncate: keep as many as fit, add overflow note
            kept = []
            for link in links:
                candidate = ' • '.join(kept + [link])
                if len(candidate) > max_chars - 30:
                    remaining = len(links) - len(kept)
                    kept.append(f"*+{remaining} more*")
                    break
                kept.append(link)
            return ' • '.join(kept)

        guild_id = guild.id

        # ── Gather boards by type ───────────────────────────────────────────
        weapon_1h_boards = sorted(
            [(r['Leaderboard Name'], int(r['Thread ID']))
             for r in all_lb_rows
             if r.get('Type', '').strip().lower() == 'weapon'
             and r['Leaderboard Name'] in _WEAPONS_1H],
            key=lambda x: x[0]
        )
        weapon_2h_boards = sorted(
            [(r['Leaderboard Name'], int(r['Thread ID']))
             for r in all_lb_rows
             if r.get('Type', '').strip().lower() == 'weapon'
             and r['Leaderboard Name'] in _WEAPONS_2H],
            key=lambda x: x[0]
        )
        map_boards_raw = [
            r for r in all_lb_rows
            if r.get('Type', '').strip().lower() == 'map'
        ]
        # Dedupe maps — show base name once, link to whichever faction thread comes first
        seen_maps = {}
        for r in sorted(map_boards_raw, key=lambda x: x['Leaderboard Name']):
            base = r['Leaderboard Name'].split(' - ')[0].strip()
            if base not in seen_maps:
                seen_maps[base] = int(r['Thread ID'])
        map_boards = sorted(seen_maps.items(), key=lambda x: x[0])

        feat_boards = sorted(
            [(r['Leaderboard Name'], int(r['Thread ID']))
             for r in all_lb_rows
             if r.get('Type', '').strip().lower() == 'feat'],
            key=lambda x: x[0]
        )

        # ── Index threads — hardcoded IDs for known existing threads ───────
        _t = lambda tid: type('T', (), {'id': tid})()
        idx_1h     = _t(INDEX_THREAD_1H)
        idx_2h     = _t(INDEX_THREAD_2H)
        idx_maps   = await _find_index_thread(guild, MAP_RECORDS_FORUM_ID,  "Map Records")
        idx_feats  = _t(INDEX_THREAD_FEATS)
        idx_bounty = await _find_index_thread(guild, BOUNTY_CARDS_FORUM_ID, "Bounty Cards")
        idx_reg    = _t(REGISTRY_INDEX_THREAD_ID)

        def index_link(thread, label):
            if thread:
                return f"[→ Full {label} Index](https://discord.com/channels/{guild_id}/{thread.id})"
            return f"*{label} index not yet built*"

        # ── Build section content strings ───────────────────────────────────
        sections = []

        # 1H Weapons
        body_1h = board_links(weapon_1h_boards, guild_id) if weapon_1h_boards else "*No boards yet*"
        sections.append(("1h", (
            f"⚔️  **ONE-HANDED WEAPONS**\n"
            f"Top 10 takedown runs per weapon. One entry per player, personal best only.\n"
            f"{index_link(idx_1h, '1H')}\n\n"
            f"{body_1h}"
        )))

        # 2H Weapons
        body_2h = board_links(weapon_2h_boards, guild_id) if weapon_2h_boards else "*No boards yet*"
        sections.append(("2h", (
            f"🪓  **TWO-HANDED WEAPONS**\n"
            f"Top 10 takedown runs per weapon. One entry per player, personal best only.\n"
            f"{index_link(idx_2h, '2H')}\n\n"
            f"{body_2h}"
        )))

        # Maps
        body_maps = board_links(map_boards, guild_id) if map_boards else "*No boards yet*"
        sections.append(("maps", (
            f"🗺️  **MAP RECORDS**\n"
            f"Top 10 takedown runs per map, tracked by faction.\n"
            f"{index_link(idx_maps, 'Maps')}\n\n"
            f"{body_maps}"
        )))

        # Feats
        body_feats = board_links(feat_boards, guild_id) if feat_boards else "*No boards yet*"
        sections.append(("feats", (
            f"🏅  **FEATS**\n"
            f"Special achievement boards — Flawless runs, 100 Kill games, 200 Takedown games, and weapon-specific challenges.\n"
            f"{index_link(idx_feats, 'Feats')}\n\n"
            f"{body_feats}"
        )))

        # Bounty Cards
        sections.append(("bounty", (
            f"🎯  **BOUNTY CARDS**\n"
            f"Active and completed bounties. Each card tracks progress toward the current target.\n"
            f"{index_link(idx_bounty, 'Bounty Cards')}"
        )))

        # Registry
        sections.append(("registry", (
            f"<:cigar:1444893851427803298>  **BUTLER'S ARCHIVE**\n"
            f"Player registry cards — every registered player's weapon marks, ranks, and submission history.\n"
            f"{index_link(idx_reg, 'Registry')}"
        )))

        # ── Post or edit each section ───────────────────────────────────────
        # Load existing message IDs from channel history on first run if we lost them.
        # Match by content keyword so ordering doesn't matter.
        _KEY_MARKERS = {
            '1h':       'ONE-HANDED WEAPONS',
            '2h':       'TWO-HANDED WEAPONS',
            'maps':     'MAP RECORDS',
            'feats':    'FEATS',
            'bounty':   'BOUNTY CARDS',
            'registry': "BUTLER'S ARCHIVE",
        }
        if not _entrance_message_ids:
            try:
                bot_id = guild.me.id
                async for msg in channel.history(limit=30, oldest_first=True):
                    if msg.author.id == bot_id:
                        for key, marker in _KEY_MARKERS.items():
                            if marker in (msg.content or '') and key not in _entrance_message_ids:
                                _entrance_message_ids[key] = msg.id
                                break
            except Exception:
                pass

        for key, content in sections:
            mid = _entrance_message_ids.get(key)
            if mid:
                try:
                    msg = await channel.fetch_message(mid)
                    await msg.edit(content=content)
                    await asyncio.sleep(0.4)
                    continue
                except discord.NotFound:
                    pass
            # No existing message — post fresh
            new_msg = await channel.send(content)
            _entrance_message_ids[key] = new_msg.id
            await asyncio.sleep(0.4)

        print("Ledger entrance updated.")

    except Exception as e:
        print(f"build_ledger_entrance error: {e}")


async def update_leaderboard_index(guild, forum_channel_id: int, index_label: str, blurb: str = None):
    """Rebuild the pinned index thread for a leaderboard forum using embeds (matches Player Registry style)."""
    try:
        import config as _cfg
        forum = guild.get_channel(forum_channel_id)
        if not forum:
            print(f"Leaderboard index: forum {forum_channel_id} not found")
            return

        index_thread_name = f"📋 {index_label} Index"

        # ── Collect all non-index threads ──────────────────────────────────
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

        # Dedupe (maps come in pairs like "Rudhelm - Mason")
        seen_base = set()
        deduped = []
        for t in sorted(threads, key=lambda t: t.name.lower()):
            base = t.name.split(' - ')[0].strip() if ' - ' in t.name else t.name
            if base not in seen_base:
                seen_base.add(base)
                deduped.append((base, t))
        deduped.sort(key=lambda x: x[0].lower())

        # ── Build embed fields ─────────────────────────────────────────────
        def make_links(items):
            return ' • '.join(
                f"[{name}](https://discord.com/channels/{guild.id}/{t.id})"
                for name, t in items
            )

        def _split_field(field_name, items, max_chars=1000):
            """Split items across multiple fields if value exceeds Discord's 1024-char field limit."""
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

        embed_fields = []  # list of (name, value)

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
                embed_fields.extend(_split_field(group_label, group_items))
            remainder = [(n, t) for n, t in deduped if n not in placed]
            if remainder:
                embed_fields.extend(_split_field("Other", remainder))

        elif is_map_index:
            embed_fields.extend(_split_field("Maps", deduped))

        else:
            # Feats / Bounty / generic — alphabetical groups
            groups = [('A–D', 'A', 'D'), ('E–K', 'E', 'K'), ('L–R', 'L', 'R'), ('S–Z', 'S', 'Z')]
            for group_name, start, end in groups:
                grp = [(n, t) for n, t in deduped if n and start <= n[0].upper() <= end]
                if grp:
                    embed_fields.extend(_split_field(group_name, grp))
            other = [(n, t) for n, t in deduped if not n or not n[0].upper().isalpha()]
            if other:
                embed_fields.extend(_split_field('#', other))

        # ── Build embed(s) — max 25 fields each ───────────────────────────
        def _build_embeds(fields):
            embeds = []
            for i in range(0, max(len(fields), 1), 25):
                chunk = fields[i:i + 25]
                e = discord.Embed(
                    title=f"📋 {index_label} Index",
                    description=blurb if (i == 0 and blurb) else ("Jump to a board below" if i == 0 else None),
                    colour=discord.Colour.from_str("#2b2d31"),
                )
                for fname, fval in chunk:
                    e.add_field(name=fname, value=fval, inline=False)
                embeds.append(e)
            return embeds

        if not embed_fields:
            embed_fields = [("No boards yet", "*Nothing here yet.*")]
        embeds = _build_embeds(embed_fields)

        # ── Find or create index thread ────────────────────────────────────
        _known_index_ids = {
            "1H Weapons":  INDEX_THREAD_1H,
            "2H Weapons":  INDEX_THREAD_2H,
            "Feats of War": INDEX_THREAD_FEATS,
        }
        index_thread = None
        if index_label in _known_index_ids:
            try:
                index_thread = guild.get_channel(_known_index_ids[index_label]) or                                await guild.fetch_channel(_known_index_ids[index_label])
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
            # Delete all non-starter messages
            for msg in msgs[1:]:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
            # Send fresh embeds
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



async def update_leaderboards(interaction, selected_weapon, selected_map, faction,
                              takedowns, kills, deaths, vip, feats,
                              player_name, message_link):
    guild = interaction.guild
    discord_id = str(interaction.user.id)
    any_updated = False
    placements = []  # (lb_name, position) — returned so submissions can show placement in the confirm message

    # Each tuple: (lb_name, score, top_10, personal_best, unlimited_top50)
    # top_10 = board caps at 10 entries, personal_best = one entry per player, unlimited = append always
    updates = []

    # VIP runs don't count toward weapon boards — they use catapult
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

        # 100 Kills / 200 Takedowns always live in a single message — cap at top 50,
        # then pack everything into exactly 1 slot so order never breaks.
        if lb_name in ("100 Kills", "200 Takedowns"):
            display_entries = entries[:50]
            overflow = len(entries) - 50
            chunks = format_leaderboard_text(display_entries, overflow, show_weapon=True)
            packed = pack_chunks_into_slots(chunks, 1)
        else:
            display_entries = entries
            overflow = 0
            chunks = format_leaderboard_text(display_entries, overflow, show_weapon=False)
            packed = None  # use standard multi-slot logic below

        lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
        if not lb_row:
            print(f"No Leaderboards sheet entry found for: {lb_name}")
            continue

        thread_id = int(lb_row['Thread ID'])
        message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(lb_row['Message ID']))]

        try:
            thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)

            if packed is not None:
                # Single-message board — just edit the first slot
                if message_ids:
                    try:
                        msg = await thread.fetch_message(message_ids[0])
                        await msg.edit(content=packed[0])
                    except Exception as e:
                        print(f"Discord edit error for {lb_name} msg {message_ids[0]}: {e}")
            elif len(chunks) <= len(message_ids):
                # Happy path — fits in what we already have, just edit in place
                packed = pack_chunks_into_slots(chunks, len(message_ids))
                for idx, mid in enumerate(message_ids):
                    try:
                        msg = await thread.fetch_message(mid)
                        await msg.edit(content=packed[idx])
                    except Exception as e:
                        print(f"Discord edit error for {lb_name} msg {mid}: {e}")
            else:
                # Board grew past its allocated slots — pull the bottom decoration off,
                # post extra messages, then repost the decoration at the end.
                try:
                    async for old_msg in thread.history(limit=5, oldest_first=False):
                        if old_msg.attachments:
                            await old_msg.delete()
                            break
                except Exception as e:
                    print(f"Decoration delete error for {lb_name}: {e}")

                # Edit existing slots
                for idx, mid in enumerate(message_ids):
                    try:
                        msg = await thread.fetch_message(mid)
                        await msg.edit(content=chunks[idx])
                    except Exception as e:
                        print(f"Discord edit error for {lb_name} msg {mid}: {e}")

                # Post new slots for overflow chunks
                new_msg_ids = list(message_ids)
                for extra_chunk in chunks[len(message_ids):]:
                    new_msg = await thread.send(extra_chunk)
                    new_msg_ids.append(new_msg.id)
                    await asyncio.sleep(0.5)

                # Repost bottom decoration
                try:
                    await thread.send(file=discord.File(DECORATION_BOTTOM))
                except Exception as e:
                    print(f"Decoration repost error for {lb_name}: {e}")

                # Update Leaderboards sheet with new message IDs
                try:
                    all_lb_data = leaderboards_ws.get_all_values()
                    for i, lb_row_data in enumerate(all_lb_data[1:], start=2):
                        if lb_row_data and lb_row_data[0].strip() == lb_name:
                            leaderboards_ws.update_cell(i, 3, '|'.join(str(m) for m in new_msg_ids))
                            break
                except Exception as e:
                    print(f"Leaderboards sheet update error for {lb_name}: {e}")

                print(f"Expanded {lb_name} board to {len(new_msg_ids)} message slots")

        except Exception as e:
            print(f"Discord update error for {lb_name}: {e}")

    return any_updated, placements


async def post_scorecard_to_threads(guild, lb_names, original_message):
    """Re-upload scorecard image to each leaderboard thread so it persists
    even if the original submission message is later deleted."""
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

    all_lb_rows = leaderboards_ws.get_all_records()
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
    # We pre-allocate a fixed number of Discord messages per leaderboard so we
    # can edit them in-place rather than deleting and reposting. This keeps
    # message links stable. If we have fewer chunks than slots, pad with zero-width
    # spaces. If we have more, cram the overflow into the last slot.
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

            leaderboards_ws.append_row([attack_name, str(thread.id), "|".join(attack_msg_ids), "map"])
            leaderboards_ws.append_row([defense_name, str(thread.id), "|".join(defense_msg_ids), "map"])

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

            leaderboards_ws.append_row([name, str(thread.id), "|".join(msg_ids), type])

            await interaction.edit_original_response(content=f"✅ Leaderboard for **{name}** set up successfully.")

    @app_commands.command(name="refresh", description="Refresh the leaderboard in this thread, or specify a name")
    @app_commands.describe(name="Optional: exact leaderboard name. Leave blank to auto-detect from this channel.")

    async def refresh_leaderboard(self, interaction: discord.Interaction, name: str = None):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
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
                chunks = format_leaderboard_text(display_entries, overflow, show_weapon=True)
                refresh_packed = pack_chunks_into_slots(chunks, 1)
            else:
                overflow = 0
                display_entries = entries
                chunks = format_leaderboard_text(display_entries, overflow, show_weapon=False)
                refresh_packed = None

            thread_id = int(lb_row['Thread ID'])
            message_ids = [int(m) for m in _re.findall(r'\d{17,20}', str(lb_row['Message ID']))]

            try:
                guild = interaction.guild
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)

                if refresh_packed is not None:
                    if message_ids:
                        try:
                            msg = await thread.fetch_message(message_ids[0])
                            await msg.edit(content=refresh_packed[0])
                        except Exception as e:
                            print(f"Refresh edit error for {lb_name} msg {message_ids[0]}: {e}")
                elif len(chunks) <= len(message_ids):
                    packed = pack_chunks_into_slots(chunks, len(message_ids))
                    for idx, mid in enumerate(message_ids):
                        try:
                            msg = await thread.fetch_message(mid)
                            await msg.edit(content=packed[idx])
                        except Exception as e:
                            print(f"Refresh edit error for {lb_name} msg {mid}: {e}")
                else:
                    # Need more slots — delete bottom decoration, post new messages, repost decoration
                    try:
                        async for old_msg in thread.history(limit=5, oldest_first=False):
                            if old_msg.attachments:
                                await old_msg.delete()
                                break
                    except Exception as e:
                        print(f"Decoration delete error for {lb_name}: {e}")

                    for idx, mid in enumerate(message_ids):
                        try:
                            msg = await thread.fetch_message(mid)
                            await msg.edit(content=chunks[idx])
                        except Exception as e:
                            print(f"Refresh edit error for {lb_name} msg {mid}: {e}")

                    new_msg_ids = list(message_ids)
                    for extra_chunk in chunks[len(message_ids):]:
                        new_msg = await thread.send(extra_chunk)
                        new_msg_ids.append(new_msg.id)
                        await asyncio.sleep(0.5)

                    try:
                        await thread.send(file=discord.File(DECORATION_BOTTOM))
                    except Exception as e:
                        print(f"Decoration repost error for {lb_name}: {e}")

                    try:
                        all_lb_data = leaderboards_ws.get_all_values()
                        for i, lb_row_data in enumerate(all_lb_data[1:], start=2):
                            if lb_row_data and lb_row_data[0].strip() == lb_name:
                                leaderboards_ws.update_cell(i, 3, '|'.join(str(m) for m in new_msg_ids))
                                break
                    except Exception as e:
                        print(f"Leaderboards sheet update error for {lb_name}: {e}")

                    print(f"Expanded {lb_name} board to {len(new_msg_ids)} message slots")

            except Exception as e:
                await interaction.edit_original_response(content=f"❌ Error refreshing {lb_name}: {e}")
                return

        await interaction.edit_original_response(content=f"✅ **{', '.join(names_to_refresh)}** refreshed successfully.")

    @app_commands.command(name="rank", description="Show the top 10 for a weapon or class leaderboard.")
    @app_commands.describe(name="Weapon or leaderboard name e.g. Messer, Halberd")
    async def rank_command(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        # Try exact match first, then case-insensitive
        entries = get_leaderboard_entries(name)
        if not entries:
            # Try case-insensitive match against all board names
            all_boards = set()
            for row in leaderboard_data_ws.get_all_values()[1:]:
                if row:
                    all_boards.add(row[0].strip())
            match = next((b for b in all_boards if b.lower() == name.lower()), None)
            if match:
                entries = get_leaderboard_entries(match)
                name = match
            else:
                # Suggest close matches
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
            # Pad numbered entries to align with medal width (medal emoji = ~2 chars wide)
            prefix = f"{medal} " if i <= 3 else f"{medal}  "
            lines.append(f"{prefix}**{e['player']}** — {e['score']}")

        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="create_missing_boards", description="Create leaderboard threads for all primary weapons without a board (admin only).")
    async def create_missing_boards(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # All primary weapons across all subclasses
        all_primaries = set()
        for weapons in _SUBCLASS_PRIMARIES.values():
            all_primaries.update(weapons)

        # Existing boards in leaderboards_ws
        existing = set()
        try:
            for row in leaderboards_ws.get_all_values()[1:]:
                if row:
                    existing.add(row[0].strip())
        except Exception as e:
            await interaction.followup.send(f"Failed to read leaderboards sheet: {e}", ephemeral=True)
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

                entries = get_leaderboard_entries(weapon)
                chunks = format_leaderboard_text(entries)

                await thread.send(file=discord.File(DECORATION_TOP))
                msg_ids = []
                for chunk in chunks:
                    lb_msg = await thread.send(chunk)
                    msg_ids.append(str(lb_msg.id))
                await thread.send(file=discord.File(DECORATION_BOTTOM))

                leaderboards_ws.append_row([weapon, str(thread.id), "|".join(msg_ids), "weapon"])
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

    @app_commands.command(name="ledger_refresh", description="Rebuild the ledger entrance channel and all forum indexes (mod only).")
    async def ledger_refresh(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.send_message("Rebuilding the ledger entrance...", ephemeral=True)
        guild = interaction.guild

        # Clear cached message IDs so we post fresh instead of editing stale/wrong messages
        _entrance_message_ids.clear()

        try:
            await build_ledger_entrance(guild)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Entrance build failed: {e}")
            return

        # Rebuild all forum indexes
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

        await interaction.edit_original_response(content="✅ Ledger entrance and all indexes rebuilt.")


async def setup(bot):
    await bot.add_cog(LeaderboardsCog(bot))
