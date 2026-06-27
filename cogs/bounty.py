"""
cogs/bounty.py — Bounty system: helpers, progress boards, and bounty slash commands.
"""
import json
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta

import config
from utils.sheets import (
    _sheet_cache, bounty_ws, bounty_players_ws, players_ws,
    cached_bounty_ws, cached_bounty_players,
)

MOD_ROLE_ID             = config.MOD_ROLE_ID
BOUNTY_FORUM_CHANNEL_ID = config.BOUNTY_FORUM_CHANNEL_ID
DECORATION_TOP          = config.DECORATION_TOP
DECORATION_BOTTOM       = config.DECORATION_BOTTOM

def get_active_bounty():
    """Return the active bounty row as a dict, or None."""
    if not bounty_ws:
        return None
    rows = cached_bounty_ws()  # data rows only (header stripped by cache)
    for i, row in enumerate(rows, start=2):
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
                'progress_msg_id': int(row[13]) if len(row) > 13 and row[13] else None,
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
    _sheet_cache.invalidate(bounty_ws)
    if message_id:
        bounty_ws.update_cell(row_idx, 3, str(message_id))

async def check_bounty_completion(guild, bounty, player_name, player_id):
    """Check if player just completed the full bounty. Returns True if newly completed."""
    # Check player's personal progress against per-weapon targets (not global counter)
    player_row = get_player_bounty_progress(bounty['title'], str(player_id))
    if not player_row:
        return False
    player_progress = player_row['progress']
    weapons = bounty['weapons']
    for weapon, data in weapons.items():
        target = data['total']
        raw = player_progress.get(weapon, 0)
        cur = raw['current'] if isinstance(raw, dict) else int(raw)
        if cur < target:
            return False
    # All weapons met — check not already in completions
    completions = bounty['completions']
    already = any(str(c.get('id')) == str(player_id) for c in completions)
    if already:
        return False
    return True

# ── BOUNTY COMMANDS ───────────────────────────────────────────────────────────


def build_progress_board(bounty, top_n=10):
    """Build a top-N hunters board from BountyPlayers, excluding completed players."""
    completed_ids = {str(c['id']) for c in bounty['completions']}
    rows = bounty_players_ws.get_all_values()

    # Calculate total target runs across all weapons
    total_target = sum(
        v.get('total', 0) if isinstance(v, dict) else 0
        for v in bounty['weapons'].values()
    )

    entries = []
    for row in rows[1:]:
        if len(row) < 5 or row[0] != bounty['title']:
            continue
        discord_id = row[1]
        if discord_id in completed_ids:
            continue
        player_name = row[2]
        progress = json.loads(row[4]) if row[4] else {}
        total_submissions = sum(
            (v['current'] if isinstance(v, dict) else int(v))
            for k, v in progress.items() if k != '__special__'
        )
        if total_submissions > 0:
            entries.append((player_name, total_submissions))
    entries.sort(key=lambda x: x[1], reverse=True)
    top = entries[:top_n]

    emoji = bounty['theme_emoji']
    lines = [f"```"]
    lines.append(f"╭────────────────────────────────╮")
    lines.append(f"  {emoji} LIVE SCOREBOARD {emoji}")
    lines.append(f"╰────────────────────────────────╯")
    if top:
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, count) in enumerate(top):
            if i < 3:
                medal = medals[i]
            else:
                medal = f"{i+1}. "
            suffix = f"/ {total_target}" if total_target else ""
            lines.append(f"{medal} {name:<20} {count} {suffix}")
    else:
        lines.append("  No active hunters yet.")
    lines.append("```")
    return "\n".join(lines)


async def update_progress_board(bounty, bounty_channel):
    """Edit the TOP HUNTERS message in the bounty channel."""
    if not bounty.get('progress_msg_id'):
        print(f"[PROGRESS_BOARD] Skipped — no progress_msg_id in bounty row")
        return
    if not bounty_channel:
        print(f"[PROGRESS_BOARD] bounty_channel was None — skipped")
        return
    try:
        msg = await bounty_channel.fetch_message(bounty['progress_msg_id'])
        await msg.edit(content=build_progress_board(bounty))
        print(f"[PROGRESS_BOARD] Updated successfully")
    except Exception as e:
        print(f"[PROGRESS_BOARD] Update error: {e}")



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
    _sheet_cache.invalidate(bounty_players_ws)

def build_player_bounty_card(bounty, player_progress):
    """Build a personal bounty card. Uses plain text so Discord strikethrough renders."""
    weapons = bounty['weapons']
    lines = []
    lines.append(f"```")
    lines.append(f"  {bounty['theme_emoji']} {bounty['title']}")
    lines.append(f"```")

    for weapon, data in weapons.items():
        tot = data['total']
        raw = player_progress.get(weapon, 0)
        cur = raw['current'] if isinstance(raw, dict) else int(raw)
        progress = f"{cur}/{tot}"
        if cur >= tot:
            lines.append(f"~~`▸ {weapon:<22} {progress:>4}`~~")
        else:
            lines.append(f"`▸ {weapon:<22} {progress:>4}`")

    sc_cur = player_progress.get('__special__', 0)
    sc_progress = f"{sc_cur}/1"
    lines.append(f"```")
    lines.append(f"  {bounty['theme_emoji']} SPECIAL CHALLENGE")
    lines.append(f"```")
    if sc_cur >= 1:
        lines.append(f"~~`▸ {bounty['special_challenge']:<22} {sc_progress:>4}`~~")
    else:
        lines.append(f"`▸ {bounty['special_challenge']:<22} {sc_progress:>4}`")

    return "\n".join(lines)



async def update_bounty(guild, weapon, player_name, player_id, takedowns):
    """Called from finalise_submission. Updates bounty progress if weapon qualifies. Returns True if weapon matched."""
    if takedowns < 100:
        return False

    bounty = get_active_bounty()
    if not bounty:
        return False

    if not weapon:
        return False

    if not weapon:
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
    if not bounty_channel and bounty['channel_id']:
        try:
            bounty_channel = await guild.fetch_channel(bounty['channel_id'])
        except Exception as e:
            print(f"[BOUNTY] Could not fetch bounty channel: {e}")
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

    # Update top hunters progress board
    await update_progress_board(bounty, bounty_channel)

    return True


class BountyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="bounty_create", description="Create a new monthly bounty (mod only)")
    @app_commands.describe(
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
        self, interaction: discord.Interaction,
        title: str,
        channel_name: str,
        theme_emoji: str,
        weapon1: str, weapon2: str, weapon3: str,
        weapon4: str, weapon5: str, weapon6: str,
        special_challenge: str,
        weapon7: str = None,
    ):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.send_message("Working on it.", ephemeral=True)

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
            '',
            '',
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        ])

        forum_mention = forum_channel.mention if forum_channel else f"*(forum creation failed: {forum_error})*"
        msg = (
            f"✅ Bounty **{title}** created!\n"
            f"📋 Bulletin Board: {channel.mention} — post your art there to activate the leaderboards\n"
            f"📖 Ledger: {forum_mention}\n"
            f"🎭 Role: {bounty_role.mention}"
        )
        await interaction.edit_original_response(content=msg)

    @app_commands.command(name="bounty_end", description="End the active bounty with a 24hr grace period (mod only)")
    async def bounty_end(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        bounty = get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"⏳ Grace period started for **{bounty['title']}**. Channel will be deleted in 24 hours.",
            ephemeral=False
        )

        # Mark inactive immediately so no new completions count
        bounty_ws.update_cell(bounty['row'], 9, 'FALSE')

        guild = interaction.guild
        closed_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        completed_ids = {str(c['id']) for c in bounty['completions']}

        # ── ARCHIVE SNAPSHOT ─────────────────────────────────────────────────────
        try:
            try:
                archive_ws = sheet.worksheet('BountyArchive')
            except Exception:
                archive_ws = sheet.add_worksheet(title='BountyArchive', rows=1000, cols=6)
                gspread_retry(archive_ws.append_row, ['BountyTitle', 'PlayerID', 'PlayerName', 'Progress', 'Completed', 'ClosedDate'])

            player_rows = gspread_retry(bounty_players_ws.get_all_values)[1:]
            for row in player_rows:
                if not row or len(row) < 5:
                    continue
                if row[0].strip() != bounty['title']:
                    continue
                player_id  = row[1].strip()
                player_name = row[2].strip()
                progress   = row[4].strip() if len(row) > 4 else '{}'
                completed  = 'TRUE' if player_id in completed_ids else 'FALSE'
                gspread_retry(archive_ws.append_row, [
                    bounty['title'], player_id, player_name, progress, completed, closed_date
                ])
            print(f"BountyArchive: snapshot saved for {bounty['title']}")
        except Exception as e:
            print(f"BountyArchive snapshot error: {e}")

        # ── STAMP FORUM CARD THREADS AS CLOSED ───────────────────────────────────
        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        try:
            forum_channel = guild.get_channel(forum_channel_id)
            if not forum_channel:
                forum_channel = await guild.fetch_channel(forum_channel_id)
            if forum_channel:
                threads = list(forum_channel.threads)
                async for t in forum_channel.archived_threads(limit=None):
                    threads.append(t)
                for thread in threads:
                    try:
                        msgs = []
                        async for msg in thread.history(limit=1, oldest_first=True):
                            msgs.append(msg)
                        if msgs:
                            original = msgs[0].content or ''
                            if '🔒 CLOSED' not in original:
                                stamp = f"🔒 **CLOSED — {bounty['title']}**"
                                new_content = f"{stamp}\n\n{original}".strip()
                                await msgs[0].edit(content=new_content)
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        print(f"Bounty card stamp error ({thread.name}): {e}")
            print(f"Bounty cards stamped CLOSED for {bounty['title']}")
        except Exception as e:
            print(f"Bounty card stamp error: {e}")

        # Wait 24 hours then delete the channel and role
        await asyncio.sleep(86400)
        channel = guild.get_channel(bounty['channel_id'])
        if channel:
            await channel.delete(reason=f"Bounty ended: {bounty['title']}")
        if bounty['role_id']:
            role = guild.get_role(bounty['role_id'])
            if role:
                await role.delete(reason=f"Bounty ended: {bounty['title']}")

    @app_commands.command(name="bounty_post_progress", description="Post or repost the live TOP HUNTERS board in the bounty channel (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def bounty_post_progress(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            bounty = get_active_bounty()
            if not bounty:
                await interaction.followup.send("No bounty is running.", ephemeral=True)
                return

            bounty_channel = interaction.guild.get_channel(bounty['channel_id'])
            if not bounty_channel:
                await interaction.followup.send("Bounty channel not found.", ephemeral=True)
                return

            # Delete old progress message if it exists
            if bounty.get('progress_msg_id'):
                try:
                    old_msg = await bounty_channel.fetch_message(bounty['progress_msg_id'])
                    await old_msg.delete()
                except Exception:
                    pass

            # Post fresh progress board
            content = build_progress_board(bounty, top_n=10)
            msg = await bounty_channel.send(content)

            # Save new message ID to Bounty sheet
            bounty_ws.update_cell(bounty['row'], 14, str(msg.id))
            await interaction.followup.send("Done.", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_status", description="Show the current active bounty card")
    async def bounty_status(self, interaction: discord.Interaction):
        bounty = get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        card = build_bounty_card(
            bounty['title'], bounty['theme_emoji'], bounty['weapons'],
            bounty['special_challenge'], bounty['special_done'], bounty['completions']
        )
        await interaction.response.send_message(card, ephemeral=True)

    @app_commands.command(name="bounty_hunt", description="Show the top 5 hunters for the active bounty")
    async def bounty_hunt(self, interaction: discord.Interaction):
        bounty = get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        board = build_progress_board(bounty, top_n=10)
        await interaction.response.send_message(board)

    @app_commands.command(name="my_bounty", description="Show your personal progress on the active bounty")
    async def my_bounty(self, interaction: discord.Interaction):
        bounty = get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        player_row = get_player_bounty_progress(bounty['title'], str(interaction.user.id))
        if not player_row:
            await interaction.response.send_message("No submissions recorded for this bounty.", ephemeral=True)
            return
        card = build_player_bounty_card(bounty, player_row['progress'])
        await interaction.response.send_message(card)

    @app_commands.command(name="bounty_add_card", description="Manually create a bounty forum card for a player (mod only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The player to create a card for")
    async def bounty_add_card(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        bounty = get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
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

            await interaction.followup.send(f"Bounty card created for {player_name}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_refresh_card", description="Refresh a player's bounty forum card (mod only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The player whose card to refresh")
    async def bounty_refresh_card(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        bounty = get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
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
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_set_bonus", description="Mark a player's bounty special challenge as complete (mod only).")
    @app_commands.describe(member="The player to mark bonus complete for")
    async def bounty_set_bonus(self, interaction: discord.Interaction, member: discord.Member):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        bounty = get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        guild = interaction.guild
        player_name = member.nick if member.nick else member.display_name
        player_id = str(member.id)

        player_row = get_player_bounty_progress(bounty['title'], player_id)
        if not player_row:
            await interaction.followup.send(f"No bounty data found for **{player_name}**. Use /bounty_add_card first.", ephemeral=True)
            return

        player_progress = player_row['progress']

        if player_progress.get('__special__', 0) >= 1:
            await interaction.followup.send(f"**{player_name}** has already completed the bonus.", ephemeral=True)
            return

        player_progress['__special__'] = 1

        # Update their forum card
        forum_post_id = player_row.get('forum_post_id')
        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        forum_channel = guild.get_channel(forum_channel_id)

        if forum_channel and forum_post_id:
            try:
                forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                card_text = build_player_bounty_card(bounty, player_progress)
                messages = []
                async for msg in forum_thread.history(limit=5, oldest_first=True):
                    messages.append(msg)
                bot_messages = [m for m in messages if m.author.bot]
                if bot_messages:
                    await bot_messages[-1].edit(content=card_text)
                else:
                    await forum_thread.send(card_text)
            except Exception as e:
                print(f"bounty_set_bonus card update error: {e}")

        # Save updated progress
        save_player_bounty_progress(player_row['row'], player_name, forum_post_id, player_progress)

        await interaction.followup.send(f"⚜️ Bonus marked complete for **{player_name}**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(BountyCog(bot))
