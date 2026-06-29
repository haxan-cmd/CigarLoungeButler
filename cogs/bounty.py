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
import utils.db as _db

MOD_ROLE_ID             = config.MOD_ROLE_ID
BOUNTY_FORUM_CHANNEL_ID = config.BOUNTY_FORUM_CHANNEL_ID
DECORATION_TOP          = config.DECORATION_TOP
DECORATION_BOTTOM       = config.DECORATION_BOTTOM
BULLETIN_BOARD_CATEGORY_ID = config.BULLETIN_BOARD_CATEGORY_ID
LEDGER_CATEGORY_ID         = config.LEDGER_CATEGORY_ID


async def get_active_bounty():
    """Return the active bounty as a dict, or None."""
    rows = await _db.get_all_bounties()
    for row in rows:
        if len(row) >= 9 and row[8] == 'TRUE':
            return {
                'id': int(row[15]),
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
                'bonus_completions': json.loads(row[16]) if len(row) > 16 and row[16] else [],
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


async def save_bounty_state(bounty_id, weapons, special_done, completions, message_id=None):
    await _db.update_bounty_field(bounty_id, 'weapons', json.dumps(weapons))
    await _db.update_bounty_field(bounty_id, 'special_done', bool(special_done))
    await _db.update_bounty_field(bounty_id, 'completions', json.dumps(completions))
    if message_id:
        await _db.update_bounty_field(bounty_id, 'message_id', str(message_id))


async def check_bounty_completion(guild, bounty, player_name, player_id):
    """Check if player just completed the full bounty. Returns True if newly completed."""
    player_row = await get_player_bounty_progress(bounty['title'], str(player_id))
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
    completions = bounty['completions']
    already = any(str(c.get('id')) == str(player_id) for c in completions)
    if already:
        return False
    return True


async def build_progress_board(bounty, top_n=10):
    """Build a top-N hunters board from BountyPlayers, excluding completed players."""
    completed_ids = {str(c['id']) for c in bounty['completions']}
    rows = await _db.get_all_bounty_players()

    total_target = sum(
        v.get('total', 0) if isinstance(v, dict) else 0
        for v in bounty['weapons'].values()
    )

    entries = []
    for row in rows:
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
        content = await build_progress_board(bounty)
        msg = await bounty_channel.fetch_message(bounty['progress_msg_id'])
        await msg.edit(content=content)
        print(f"[PROGRESS_BOARD] Updated successfully")
    except Exception as e:
        print(f"[PROGRESS_BOARD] Update error: {e}")


async def get_player_bounty_progress(bounty_title, discord_id):
    """Get a player's bounty progress from DB, or None."""
    rows = await _db.get_all_bounty_players()
    discord_id_str = str(discord_id)
    for row in rows:
        if len(row) >= 2 and row[0] == bounty_title and row[1] == discord_id_str:
            return {
                'player_name': row[2] if len(row) > 2 else '',
                'forum_post_id': int(row[3]) if len(row) > 3 and row[3] else None,
                'progress': json.loads(row[4]) if len(row) > 4 and row[4] else {}
            }
    return None


async def save_player_bounty_progress(bounty_title, discord_id, player_name, forum_post_id, progress):
    await _db.upsert_bounty_player(
        bounty_title, str(discord_id), player_name,
        str(forum_post_id) if forum_post_id else '',
        json.dumps(progress)
    )


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

    bounty = await get_active_bounty()
    if not bounty:
        print(f"[BOUNTY] No active bounty found — skipping for {player_name} weapon={weapon}")
        return False

    if not weapon:
        return False

    weapons = bounty['weapons']

    matched_key = next((k for k in weapons if k.lower() == weapon.lower()), None)
    if not matched_key:
        print(f"[BOUNTY] Weapon '{weapon}' not in bounty '{bounty['title']}' — keys: {list(weapons.keys())}")
        # Still check special challenge even if weapon isn't a bounty weapon
        if not bounty['special_done'] and bounty.get('special_challenge'):
            import re as _re
            sc = bounty['special_challenge'].lower()
            td_match = _re.search(r'(\d+)\s*takedown', sc)
            sc_min_td = int(td_match.group(1)) if td_match else 100
            if weapon and weapon.lower() in sc and takedowns >= sc_min_td:
                bounty['special_done'] = True
                print(f"[BOUNTY] Special challenge auto-completed by {player_name} — {weapon} {takedowns}TD")
                bounty_channel = guild.get_channel(bounty['channel_id'])
                if not bounty_channel and bounty['channel_id']:
                    try:
                        bounty_channel = await guild.fetch_channel(bounty['channel_id'])
                    except Exception:
                        bounty_channel = None
                if bounty_channel:
                    try:
                        bounty_role = guild.get_role(bounty.get('role_id')) if bounty.get('role_id') else None
                        mention = bounty_role.mention if bounty_role else ''
                        await bounty_channel.send(
                            f"{mention} ⭐ **{player_name}** has completed the special challenge: **{bounty['special_challenge']}**!"
                        )
                    except Exception as e:
                        print(f"[BOUNTY] Special challenge ping error: {e}")
                await save_bounty_state(bounty['id'], weapons, bounty['special_done'], bounty['completions'])
        return False

    # Increment global participation counter
    w = weapons[matched_key]
    w['current'] += 1
    weapons[matched_key] = w

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
    player_row = await get_player_bounty_progress(bounty['title'], str(player_id))
    if player_row:
        player_progress = player_row['progress']
        forum_post_id = player_row['forum_post_id']
    else:
        player_progress = {}
        forum_post_id = None

    raw = player_progress.get(matched_key, 0)
    cur = raw['current'] if isinstance(raw, dict) else int(raw)
    player_progress[matched_key] = cur + 1

    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if forum_channel and isinstance(forum_channel, discord.ForumChannel):
        if forum_post_id:
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

    # Save player progress (upsert handles both new and existing)
    await save_player_bounty_progress(bounty['title'], str(player_id), player_name, forum_post_id, player_progress)

    # ── COMPLETIONS & BONUS BOARDS ───────────────────────────────────────────
    completions = bounty['completions']
    newly_completed = await check_bounty_completion(guild, bounty, player_name, player_id)
    if newly_completed:
        date_str = datetime.now(timezone.utc).strftime('%b %d')
        completions.append({"id": str(player_id), "name": player_name, "date": date_str})
        if bounty_channel and bounty_role:
            try:
                await bounty_channel.send(
                    f"{bounty_role.mention} 🏆 **{player_name}** has completed the **{bounty['title']}**!"
                )
            except Exception as e:
                print(f"Bounty completion ping error: {e}")

    # ── AUTO-CHECK SPECIAL CHALLENGE ─────────────────────────────────────────
    if not bounty['special_done'] and bounty.get('special_challenge'):
        sc = bounty['special_challenge'].lower()
        # Parse minimum TD threshold from challenge text (e.g. "100 Takedowns")
        import re as _re
        td_match = _re.search(r'(\d+)\s*takedown', sc)
        sc_min_td = int(td_match.group(1)) if td_match else 100
        # Check if current weapon appears anywhere in the challenge text
        weapon_in_challenge = weapon and weapon.lower() in sc
        if weapon_in_challenge and takedowns >= sc_min_td:
            bounty['special_done'] = True
            print(f"[BOUNTY] Special challenge auto-completed by {player_name} — {weapon} {takedowns}TD")
            # Append to bonus_completions list
            bonus_completions = bounty.get('bonus_completions', [])
            if not any(str(e.get('id') if isinstance(e, dict) else '') == str(player_id) for e in bonus_completions):
                bonus_completions.append({'id': str(player_id), 'name': player_name})
            bounty['bonus_completions'] = bonus_completions
            await _db.update_bounty_field(bounty['id'], 'bonus_completions', json.dumps(bonus_completions))
            if bounty_channel:
                try:
                    bounty_role = guild.get_role(bounty.get('role_id')) if bounty.get('role_id') else None
                    mention = bounty_role.mention if bounty_role else ''
                    await bounty_channel.send(
                        f"{mention} ⭐ **{player_name}** has completed the special challenge: **{bounty['special_challenge']}**!"
                    )
                except Exception as e:
                    print(f"[BOUNTY] Special challenge ping error: {e}")

    # Save updated state
    await save_bounty_state(bounty['id'], weapons, bounty['special_done'], completions)

    # Update completions board
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

    # Update bonus completions board if special just got done
    if bounty['special_done'] and bounty_channel and bounty.get('bonus_msg_id'):
        try:
            bonus_text = _build_bonus_board_text(bounty)
            bonus_msg = await bounty_channel.fetch_message(bounty['bonus_msg_id'])
            await bonus_msg.edit(content=bonus_text)
        except Exception as e:
            print(f"Bonus board update error: {e}")

    await update_progress_board(bounty, bounty_channel)

    return True


def _build_bonus_board_text(bounty):
    """Build the BONUS COMPLETIONS board text from bounty['bonus_completions'] list."""
    completers = bounty.get('bonus_completions', [])
    lines = [
        "```",
        "╭──────────────────────────────╮",
        f"  {bounty['theme_emoji']} BONUS COMPLETIONS {bounty['theme_emoji']}",
        "╰──────────────────────────────╯",
    ]
    if completers:
        for idx, entry in enumerate(completers, 1):
            name = entry['name'] if isinstance(entry, dict) else entry
            lines.append(f"{idx}. {name}")
    else:
        lines.append("No bonus completions yet.")
    lines.append("```")
    return "\n".join(lines)


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
        existing_bounties = await _db.get_all_bounties()
        for row in existing_bounties:
            if len(row) >= 9 and row[8] == 'TRUE':
                bounty_id = int(row[15])
                await _db.update_bounty_field(bounty_id, 'active', 'FALSE')

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

        weapons = {}
        for raw in raw_weapons:
            parsed = parse_weapon(raw)
            if parsed:
                name, total = parsed
                weapons[name] = {"current": 0, "total": total}

        guild = interaction.guild

        formatted_channel_name = f"🐱 ┃{channel_name}"

        bulletin_board = guild.get_channel(BULLETIN_BOARD_CATEGORY_ID)
        channel = await guild.create_text_channel(formatted_channel_name, category=bulletin_board)

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

        lavender = discord.Colour(0xB57EDC)
        bounty_role = await guild.create_role(
            name=title,
            colour=lavender,
            mentionable=True,
            reason=f"Bounty role for: {title}"
        )
        try:
            await bounty_role.edit(unicode_emoji="🐱")
        except Exception:
            pass

        await _db.add_bounty(
            title=title,
            channel_id=str(channel.id),
            message_id='',
            theme_emoji=theme_emoji,
            weapons=json.dumps(weapons),
            special_challenge=special_challenge,
            active=True,
            role_id=str(bounty_role.id),
            forum_channel_id=str(forum_channel.id) if forum_channel else '',
            start_date=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        )

        forum_mention = forum_channel.mention if forum_channel else f"*(forum creation failed: {forum_error})*"
        msg = (
            f"✅ Bounty **{title}** created!\n"
            f"📋 Bulletin Board: {channel.mention}\n"
            f"📖 Ledger: {forum_mention}\n"
            f"🎭 Role: {bounty_role.mention}"
        )
        await interaction.edit_original_response(content=msg)

    @app_commands.command(name="bounty_end", description="End the active bounty with a 24hr grace period (mod only)")
    async def bounty_end(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"⏳ Grace period started for **{bounty['title']}**. Channel will be deleted in 24 hours.",
            ephemeral=False
        )

        # Mark inactive immediately
        await _db.update_bounty_field(bounty['id'], 'active', 'FALSE')

        guild = interaction.guild
        closed_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        completed_ids = {str(c['id']) for c in bounty['completions']}

        # ── STAMP FORUM CARD THREADS AS CLOSED ───────────────────────────────
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
            bounty = await get_active_bounty()
            if not bounty:
                await interaction.followup.send("No bounty is running.", ephemeral=True)
                return

            bounty_channel = interaction.guild.get_channel(bounty['channel_id'])
            if not bounty_channel:
                await interaction.followup.send("Bounty channel not found.", ephemeral=True)
                return

            if bounty.get('progress_msg_id'):
                try:
                    old_msg = await bounty_channel.fetch_message(bounty['progress_msg_id'])
                    await old_msg.delete()
                except Exception:
                    pass

            content = await build_progress_board(bounty, top_n=10)
            msg = await bounty_channel.send(content)

            await _db.update_bounty_field(bounty['id'], 'progress_msg_id', str(msg.id))
            await interaction.followup.send("Done.", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_status", description="Show the current active bounty card")
    async def bounty_status(self, interaction: discord.Interaction):
        bounty = await get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        card = build_bounty_card(
            bounty['title'], bounty['theme_emoji'], bounty['weapons'],
            bounty['special_challenge'], bounty['special_done'], bounty['completions']
        )
        await interaction.response.send_message(card, ephemeral=True)

    @app_commands.command(name="bounty_hunt", description="Show the top hunters for the active bounty")
    async def bounty_hunt(self, interaction: discord.Interaction):
        bounty = await get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        board = await build_progress_board(bounty, top_n=10)
        await interaction.response.send_message(board)

    @app_commands.command(name="my_bounty", description="Show your personal progress on the active bounty")
    async def my_bounty(self, interaction: discord.Interaction):
        bounty = await get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        player_row = await get_player_bounty_progress(bounty['title'], str(interaction.user.id))
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

        bounty = await get_active_bounty()
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

        player_row = await get_player_bounty_progress(bounty['title'], str(player_id))
        if player_row and player_row.get('forum_post_id'):
            await interaction.followup.send(f"⚠️ {player_name} already has a forum card.", ephemeral=True)
            return

        if player_row:
            player_progress = player_row['progress']
        else:
            player_progress = {w: {"current": 0, "total": bounty['weapons'][w]['total']} for w in bounty['weapons']}

        try:
            new_thread, _ = await forum_channel.create_thread(
                name=player_name,
                content=bounty['theme_emoji']
            )
            card_text = build_player_bounty_card(bounty, player_progress)
            await new_thread.send(card_text)
            forum_post_id = new_thread.id

            await save_player_bounty_progress(bounty['title'], str(player_id), player_name, forum_post_id, player_progress)

            await interaction.followup.send(f"Bounty card created for {player_name}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_refresh_card", description="Refresh a player's bounty forum card (mod only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The player whose card to refresh")
    async def bounty_refresh_card(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        guild = interaction.guild
        player_name = member.nick if member.nick else member.display_name
        player_id = str(member.id)

        player_row = await get_player_bounty_progress(bounty['title'], player_id)
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
            card_text = build_player_bounty_card(bounty, player_progress)
            messages = []
            async for msg in forum_thread.history(limit=5, oldest_first=True):
                messages.append(msg)
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

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        guild = interaction.guild
        player_name = member.nick if member.nick else member.display_name
        player_id = str(member.id)

        player_row = await get_player_bounty_progress(bounty['title'], player_id)
        # Allow even if player has no prior bounty data — create fresh progress
        player_progress = player_row['progress'] if player_row else {}
        forum_post_id = player_row.get('forum_post_id') if player_row else None

        if player_progress.get('__special__', 0) >= 1:
            await interaction.followup.send(f"**{player_name}** has already completed the bonus.", ephemeral=True)
            return

        player_progress['__special__'] = 1

        # Update global bounty special_done flag
        bounty['special_done'] = True

        # Append to bonus_completions list (same pattern as completions)
        bonus_completions = bounty.get('bonus_completions', [])
        if not any(str(e.get('id') if isinstance(e, dict) else '') == str(player_id) for e in bonus_completions):
            bonus_completions.append({'id': str(player_id), 'name': player_name})
        bounty['bonus_completions'] = bonus_completions
        await save_bounty_state(bounty['id'], bounty['weapons'], True, bounty['completions'])
        await _db.update_bounty_field(bounty['id'], 'bonus_completions', json.dumps(bonus_completions))

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

        await save_player_bounty_progress(bounty['title'], player_id, player_name, forum_post_id, player_progress)

        # Update the bonus completions board message
        bounty_channel = guild.get_channel(bounty['channel_id']) if bounty.get('channel_id') else None
        if not bounty_channel and bounty.get('channel_id'):
            try:
                bounty_channel = await guild.fetch_channel(bounty['channel_id'])
            except Exception as e:
                print(f"bounty_set_bonus channel fetch error: {e}")
                bounty_channel = None
        print(f"[BOUNTY_SET_BONUS] channel={bounty_channel} bonus_msg_id={bounty.get('bonus_msg_id')}")
        if bounty_channel and bounty.get('bonus_msg_id'):
            try:
                bonus_text = _build_bonus_board_text(bounty)
                bonus_msg = await bounty_channel.fetch_message(bounty['bonus_msg_id'])
                await bonus_msg.edit(content=bonus_text)
                print(f"[BOUNTY_SET_BONUS] Board updated with {len(bonus_completions)} completers")
            except Exception as e:
                print(f"bounty_set_bonus board update error: {e}")

        await interaction.followup.send(f"⚜️ Bonus marked complete for **{player_name}**.", ephemeral=True)

    @app_commands.command(name="bounty_credit", description="Manually credit a player with a bounty weapon hit (mod only).")
    @app_commands.describe(member="The player to credit", weapon="The bounty weapon to credit them for")
    async def bounty_credit(self, interaction: discord.Interaction, member: discord.Member, weapon: str):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        weapons = bounty['weapons']
        matched_key = next((k for k in weapons if k.lower() == weapon.lower()), None)
        if not matched_key:
            valid = ", ".join(weapons.keys())
            await interaction.followup.send(
                f"❌ `{weapon}` is not in the current bounty.\nValid weapons: {valid}", ephemeral=True)
            return

        guild = interaction.guild
        player_name = member.nick if member.nick else member.display_name
        player_id = str(member.id)

        # Increment global weapon counter
        w = weapons[matched_key]
        w['current'] += 1
        weapons[matched_key] = w

        # Update player progress
        player_row = await get_player_bounty_progress(bounty['title'], player_id)
        if player_row:
            player_progress = player_row['progress']
            forum_post_id = player_row['forum_post_id']
        else:
            player_progress = {}
            forum_post_id = None

        raw = player_progress.get(matched_key, 0)
        cur = raw['current'] if isinstance(raw, dict) else int(raw)
        player_progress[matched_key] = cur + 1

        # Assign bounty role if not already
        bounty_role = guild.get_role(bounty['role_id']) if bounty['role_id'] else None
        if bounty_role and bounty_role not in member.roles:
            try:
                await member.add_roles(bounty_role, reason="Bounty credit (manual)")
            except Exception as e:
                print(f"[BOUNTY_CREDIT] Role assign error: {e}")

        # Update forum card
        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        forum_channel = guild.get_channel(forum_channel_id)
        if forum_channel and isinstance(forum_channel, discord.ForumChannel):
            if forum_post_id:
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
                    print(f"[BOUNTY_CREDIT] Forum card update error: {e}")
                    forum_post_id = None
            if not forum_post_id:
                try:
                    new_thread, first_msg = await forum_channel.create_thread(
                        name=player_name,
                        content=bounty['theme_emoji']
                    )
                    card_text = build_player_bounty_card(bounty, player_progress)
                    await new_thread.send(card_text)
                    forum_post_id = new_thread.id
                except Exception as e:
                    print(f"[BOUNTY_CREDIT] Forum post create error: {e}")

        await save_player_bounty_progress(bounty['title'], str(member.id), player_name, forum_post_id, player_progress)
        await save_bounty_state(bounty['id'], weapons, bounty['special_done'], bounty['completions'])

        await interaction.followup.send(
            f"\u2705 Credited **{player_name}** with 1 hit on **{weapon}** ({new_total}/{w['total']})",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(BountyCog(bot))
