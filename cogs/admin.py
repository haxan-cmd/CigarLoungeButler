# Admin and mod commands — rules, challenge rules, patch notes, submission removal, seeding.
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.sheets import (
    _sheet_cache, players_ws, submissions_ws, leaderboard_data_ws,
    registry_ws, index_posts_ws, leaderboards_ws,
    cached_players, cached_submissions, gspread_retry,
)

MOD_ROLE_ID             = config.MOD_ROLE_ID
GUILD_ID                = config.GUILD_ID
CHALLENGE_RULES_CHANNEL_ID = config.CHALLENGE_RULES_CHANNEL_ID
BUTLERS_FAVOURITES_CHANNEL_ID = config.BUTLERS_FAVOURITES_CHANNEL_ID
DECORATION_TOP          = config.DECORATION_TOP
DECORATION_BOTTOM       = config.DECORATION_BOTTOM
PLAYER_TITLES           = config.PLAYER_TITLES
GRAND_MARSHAL_ROLE_ID   = config.GRAND_MARSHAL_ROLE_ID
WEAPONS_MASTER_ROLE_ID  = config.WEAPONS_MASTER_ROLE_ID
CAMPAIGN_MASTER_ROLE_ID = config.CAMPAIGN_MASTER_ROLE_ID
HEADHUNTER_ROLE_ID      = config.HEADHUNTER_ROLE_ID
BUTCHER_ROLE_ID         = config.BUTCHER_ROLE_ID

CHALLENGE_RULES_CONTENT = [
    # 1. Intro + weapon ranks
    """\
<:cigar:1444893851427803298> **CIGAR LOUNGE**
100-bombers come here to grind weapon marks, complete bounties, and settle scores against each other.

One outstanding game is a coincidence.
The lounge is interested in what you do after that.

<:level1_1:1361419350665461820> — **Bronze**
• 1 weapon mark (1 total)
<:level2_3:1361419398841106442> — **Silver**
• +4 weapon marks (5 total)
<:level3_6:1361419489635209396> — **Gold**
• +7 weapon marks (12 total)
<:level4_9:1368656036784771212> — **Emerald**
• +13 weapon marks (25 total)
<:level5_12:1368656100764942432> — **Diamond**
• +15 weapon marks (40 total)
<:level6_15:1430203489757302924> — **Crimson**
• +20 weapon marks (60 total)
<:level7_20:1430216503919120537> — **Prestige Bronze**
• +20 weapon marks (80 total)
<:level8_30:1430216636006137876> — **Prestige Silver**
• +20 weapon marks (100 total)
<:level9_40:1430216748329599046> — **Prestige Gold**
• +15 weapon marks (115 total)
<:level10_55:1430216819787956265> — **Prestige Emerald**
• +10 weapon marks (125 total)
<:level11_70:1430217739586240624> — **Prestige Diamond**
• +8 weapon marks (133 total)
<:level12_85:1430217099648962651> — **Prestige Crimson**
• +8 weapon marks (141 total)
<:level13_100:1459253823481712895> — **Iridescent**
• +9 weapon marks (150 total)""",

    # 2. Earning weapon marks
    """\
🎯 **EARNING WEAPON MARKS**
A weapon mark is earned by completing a **100 takedown game** with the following conditions:

• Same loadout for the entire match
• **No catapult usage**
• Match must be submitted in <#1328832440927518920>

**Submission must include:**
• Class or Subclass
• Weapon used
• VIP used or not

**Bonus marks per submission:**
• <a:200tkd:1363648828414230538> +1 for 200 Takedowns
• <a:100kill:1361412390339608686> +1 for 100 Kills
• <a:triple:1365532698260668466> +1 for Triple
• <:highscore:1360312918545269057> +1 for Leaderboard High Score

**Note:**
Goedendag counts for Polearms and Engineer (Footman).

Weapon marks are recorded on your **Player Card**. The card is created on your first valid submission.""",

    # 3. Subclass & class progression
    """\
🧩 **SUBCLASS & CLASS PROGRESSION**
Each time a weapon badge upgrades, you earn **1 subclass mark**.

Subclasses differ in length — depends how many primary weapons are in them.
Fill the meter and you earn **1 class mark**.""",

    # 4. Subclass ranks
    """\
⚔️ **SUBCLASS RANKS**
<:subclass0:1361423009256308808> — Initiate
<:veteran2:1430199755094360194> — Veteran
<:master3:1430199983675670619> — Master
<:grandmaster4:1430199858635210752> — Grandmaster
<:champion5:1430199893363789934> — Champion
<:paragon6:1430199955385094235> — Paragon
<:apex7:1430199916126408754> — Apex""",

    # 5. Class ranks
    """\
🛡️ **CLASS RANKS**
<:class0_0:1446622044698443969> — Sworn
<:class1_3:1446620360186269726> — Trusted
<:class2_6:1446620614096846988> — Proven
<:class3_9:1446620700189266182> — Honored
<:class4_12:1446620991777407128> — Esteemed
<:class5_15:1446621127605620826> — Exalted
<:class6_18:1446621258430025791> — Ascended""",

    # 6. Overall player titles
    """\
🏆 **OVERALL PLAYER TITLES**
Complete bounties. That's how you rank up.

0 — Unbound
1 — Proven
2 — Respected
3 — Distinguished
4 — Renowned
5 — Illustrious
6 — Exemplar
7 — Legend""",

    # 7. Feats of legend
    """\
💀 **Feats of Legend**
Additional marks may be earned by completing a valid **100 takedown game** plus one of the following:

• <a:100kill:1361412390339608686> — 100 kills
• <a:triple:1365532698260668466> — 150 takedowns, 100 kills, and 20,000 points (**Triple**)
• <a:200tkd:1363648828414230538> — 200 takedowns
• <a:predator:1366794896081555567> — 150 takedowns without dying

Additionally, you can earn <:hhanded:1430199468246044772> **The Hundred-Handed** feat by getting a 100 with every primary weapon (archer excluded)""",

    # 8. Bounties
    """\
🎯 **BOUNTIES**
Monthly objectives tracked on separate bounty cards. Complete them — that's how you rank up. They don't run forever.""",
]


def get_challenge_rules_message_ids():
    # We store the message IDs so /update_challenge_rules can edit in place
    try:
        ws = sheet.worksheet('ChallengeRules')
        rows = ws.get_all_values()[1:]
        return [int(r[0]) for r in rows if r and r[0]]
    except Exception:
        return []

def save_challenge_rules_message_ids(msg_ids):
    try:
        try:
            ws = sheet.worksheet('ChallengeRules')
            ws.clear()
        except Exception:
            ws = sheet.add_worksheet(title='ChallengeRules', rows=20, cols=2)
        ws.append_row(['MessageID', 'Section'])
        labels = ['Intro + Weapon Ranks', 'Earning Marks', 'Subclass & Class Progression',
                  'Subclass Ranks', 'Class Ranks', 'Player Titles', 'Feats of Legend', 'Bounties']
        for msg_id, label in zip(msg_ids, labels):
            ws.append_row([str(msg_id), label])
    except Exception as e:
        print(f"ChallengeRules sheet save error: {e}")




class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="seed_players", description="Seed the Players tab from a Discord role (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def seed_players(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            guild = interaction.guild
            role = guild.get_role(1433215577173786758)

            if not role:
                await interaction.followup.send("❌ Role not found.", ephemeral=True)
                return

            existing_rows = players_ws.get_all_values()
            existing_ids = set(row[0] for row in existing_rows[1:] if row)

            rows_to_add = []
            skipped = 0

            for member in role.members:
                discord_id = str(member.id)
                display_name = member.nick if member.nick else member.display_name

                if discord_id in existing_ids:
                    skipped += 1
                    continue

                rows_to_add.append([discord_id, display_name, ""])

            if rows_to_add:
                players_ws.append_rows(rows_to_add, value_input_option="RAW")

            await interaction.followup.send(
                f"✅ Seeded **{len(rows_to_add)}** players from role.\n"
                f"⏭️ Skipped **{skipped}** already in the sheet.",
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="patch_notes", description="Post patch notes to the current channel (mod only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(version="Version number e.g. v1.3.0", notes="What changed — use | to separate bullet points")
    async def patch_notes(self, interaction: discord.Interaction, version: str, notes: str):
        await interaction.response.defer(ephemeral=True)

        bullets = [f"• {n.strip()}" for n in notes.split("|")]
        bullet_text = "\n".join(bullets)

        msg = (
            f"📝 **Cigar Lounge Butler {version}**\n"
            f"──────────────────────\n"
            f"{bullet_text}"
        )

        await interaction.channel.send(msg)
        await interaction.followup.send(f"✅ Patch notes posted for {version}.", ephemeral=True)

    @app_commands.command(name="post_challenge_rules", description="Post the challenge rules to the challenge-rules channel (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_challenge_rules(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            channel = self.bot.get_channel(CHALLENGE_RULES_CHANNEL_ID)
            if not channel:
                await interaction.followup.send("Could not find challenge-rules channel.", ephemeral=True)
                return

            msg_ids = []
            for i, content in enumerate(CHALLENGE_RULES_CONTENT):
                if i > 0:
                    await channel.send(file=discord.File(DECORATION_BOTTOM))
                    await asyncio.sleep(0.5)
                msg = await channel.send(content)
                msg_ids.append(msg.id)
                await asyncio.sleep(0.5)

            await channel.send(file=discord.File(DECORATION_BOTTOM))
            save_challenge_rules_message_ids(msg_ids)
            await interaction.followup.send(f"Posted {len(msg_ids)} challenge rules messages.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="update_challenge_rules", description="Update the challenge rules channel with current info (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def update_challenge_rules(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            channel = self.bot.get_channel(CHALLENGE_RULES_CHANNEL_ID)
            if not channel:
                await interaction.followup.send("Could not find challenge-rules channel.", ephemeral=True)
                return

            msg_ids = get_challenge_rules_message_ids()
            if not msg_ids:
                await interaction.followup.send("No challenge rules messages found — run /post_challenge_rules first.", ephemeral=True)
                return

            updated = 0
            for msg_id, content in zip(msg_ids, CHALLENGE_RULES_CONTENT):
                try:
                    msg = await channel.fetch_message(msg_id)
                    await msg.edit(content=content)
                    updated += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"Error updating message {msg_id}: {e}")

            await interaction.followup.send(f"Updated {updated}/{len(msg_ids)} challenge rules messages.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="title_guide", description="Post the Butler's Favourites title guide to the favourites channel (mod only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def title_guide(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("Could not find the Butler's Favourites channel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Butler's Favourites — Title Guide",
            description="Prestige titles awarded to the Lounge's top performers. Titles are recalculated automatically after every submission.",
            color=discord.Color.from_str("#c8a45a")
        )
        embed.add_field(
            name="🏆 Grand Marshal",
            value="Appears on 15+ leaderboards across all categories, ranked by average placement.",
            inline=False
        )
        embed.add_field(
            name="⚔️ Weapons Master",
            value="Appears on 9+ weapon leaderboards, ranked by average placement.",
            inline=False
        )
        embed.add_field(
            name="🗺️ Campaign Master",
            value="Appears on 6+ map leaderboards, ranked by average placement.",
            inline=False
        )
        embed.add_field(
            name="💀 Headhunter",
            value="Held by the #1 player on the 100 Kills board. Hit 100+ kills in a single match and submit your scoreboard to enter. Ranked by average kills score, weighted by number of submissions.",
            inline=False
        )
        embed.add_field(
            name="🩸 Butcher",
            value="Held by the #1 player on the 200 Takedowns board. Hit 200+ takedowns in a single match and submit your scoreboard to enter. Ranked by average takedowns score, weighted by number of submissions.",
            inline=False
        )
        embed.set_footer(text="Only one player holds each title at a time.")

        await channel.send(embed=embed)
        await interaction.response.send_message("Title guide posted.", ephemeral=True)

    @app_commands.command(name="remove_submission", description="Remove a fake or erroneous submission and roll back all affected tables (admin only).")
    @app_commands.describe(message_link="The Discord message link to the original submission")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_submission(self, interaction: discord.Interaction, message_link: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        report = []

        try:
            # 1. find and delete the submission row
            sub_rows = submissions_ws.get_all_values()
            sub_row_idx = None
            sub_data = None
            for i, row in enumerate(sub_rows[1:], start=2):
                if len(row) >= 13 and row[12].strip() == message_link.strip():
                    sub_row_idx = i
                    sub_data = row
                    break

            if not sub_data:
                await interaction.followup.send("❌ No submission found with that message link.", ephemeral=True)
                return

            player_name = sub_data[1].strip()
            discord_id  = sub_data[2].strip()
            weapon      = sub_data[3].strip()
            map_name    = sub_data[5].strip()
            try:
                takedowns = int(sub_data[7])
            except Exception:
                takedowns = 0

            submissions_ws.delete_rows(sub_row_idx)
            report.append(f"✅ Submissions: row deleted ({player_name}, {weapon}, {map_name})")

            # 2. strip it from LeaderboardData
            ld_rows = leaderboard_data_ws.get_all_values()
            ld_deleted = 0
            affected_lb_names = set()
            # Iterate in reverse so row deletion doesn't shift indices
            for i in range(len(ld_rows) - 1, 0, -1):
                row = ld_rows[i]
                if len(row) >= 5 and row[4].strip() == message_link.strip():
                    affected_lb_names.add(row[0].strip())
                    leaderboard_data_ws.delete_rows(i + 1)
                    ld_deleted += 1
            report.append(f"✅ LeaderboardData: {ld_deleted} row(s) deleted, affected boards: {', '.join(affected_lb_names) or 'none'}")

            # 3. rebuild any leaderboard threads that had this score in them
            if affected_lb_names:
                all_lb_rows = leaderboards_ws.get_all_records()
                rebuilt = []
                for lb_name in affected_lb_names:
                    lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
                    if not lb_row:
                        continue
                    try:
                        entries = get_leaderboard_entries(lb_name)
                        entries = sorted(entries, key=lambda x: x['score'], reverse=True)
                        overflow = 0
                        if lb_name in ("100 Kills", "200 Takedowns"):
                            overflow = max(0, len(entries) - 50)
                            entries = entries[:50]
                        chunks = format_leaderboard_text(entries, overflow, show_weapon=(lb_name in ("100 Kills", "200 Takedowns")))
                        thread_id = int(lb_row['Thread ID'])
                        message_ids = [int(mid.strip()) for mid in str(lb_row['Message ID']).split(',') if mid.strip()]
                        thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
                        packed = pack_chunks_into_slots(chunks, len(message_ids))
                        for idx, mid in enumerate(message_ids):
                            try:
                                msg = await thread.fetch_message(mid)
                                await msg.edit(content=packed[idx] if idx < len(packed) else "ᅠ")
                            except Exception as e:
                                print(f"Leaderboard msg edit error ({lb_name}): {e}")
                        rebuilt.append(lb_name)
                    except Exception as e:
                        print(f"Leaderboard rebuild error ({lb_name}): {e}")
                report.append(f"✅ Leaderboards rebuilt: {', '.join(rebuilt) or 'none'}")

            # 4. roll back bounty progress if it counted toward an active bounty
            bounty = get_active_bounty()
            if bounty:
                matched_key = next((k for k in bounty['weapons'] if k.lower() == weapon.lower()), None)
                if matched_key and takedowns >= 100:
                    player_row = get_player_bounty_progress(bounty['title'], discord_id)
                    if player_row:
                        progress = player_row['progress']
                        raw = progress.get(matched_key, 0)
                        cur = raw['current'] if isinstance(raw, dict) else int(raw)
                        if cur > 0:
                            progress[matched_key] = cur - 1
                            save_player_bounty_progress(player_row['row'], player_name, player_row['forum_post_id'], progress)
                            # Update bounty card in forum
                            forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
                            forum_channel = guild.get_channel(forum_channel_id)
                            if forum_channel and player_row['forum_post_id']:
                                try:
                                    forum_thread = forum_channel.get_thread(player_row['forum_post_id']) or await guild.fetch_channel(player_row['forum_post_id'])
                                    msgs = []
                                    async for msg in forum_thread.history(limit=5, oldest_first=True):
                                        msgs.append(msg)
                                    bot_msgs = [m for m in msgs if m.author.bot]
                                    if bot_msgs:
                                        await bot_msgs[-1].edit(content=build_player_bounty_card(bounty, progress))
                                except Exception as e:
                                    print(f"Bounty card rollback error: {e}")
                            # Decrement global weapon counter
                            weapons = bounty['weapons']
                            if matched_key in weapons:
                                weapons[matched_key]['current'] = max(0, weapons[matched_key]['current'] - 1)
                                save_bounty_state(bounty['row'], weapons, bounty['special_done'], bounty['completions'])
                            report.append(f"✅ Bounty: decremented {matched_key} for {player_name}")
                        else:
                            report.append(f"⚠️ Bounty: {player_name} already at 0 for {matched_key}, skipped")
                    else:
                        report.append(f"ℹ️ Bounty: no progress row found for {player_name}")
                else:
                    report.append(f"ℹ️ Bounty: weapon {weapon} not on active bounty or TDs < 100, skipped")

            # 5. rebuild their registry card so the mark count reflects the removal
            try:
                discord_id_int = int(discord_id)
                await create_or_update_registry_card(guild, discord_id_int, player_name)
                report.append(f"✅ Registry card refreshed for {player_name}")
            except Exception as e:
                report.append(f"⚠️ Registry card refresh failed: {e}")

            summary = f"**Submission removed — {player_name}**\n" + "\n".join(report)
            await interaction.followup.send(summary, ephemeral=True)

        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"❌ Error during removal: {e}", ephemeral=True)

    @app_commands.command(name="rules", description="Show the Cigar Lounge challenge rules.")
    async def rules_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        for chunk in CHALLENGE_RULES_CONTENT:
            await interaction.followup.send(chunk, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
