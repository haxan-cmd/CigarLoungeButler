# Admin and mod commands — rules, challenge rules, patch notes, submission removal, seeding.
import asyncio
import os
import io
import gzip
import json
import datetime as _dt
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import utils.db as _db


def _all_weapons():
    s = set()
    for ws in config.CLASS_WEAPON_MAP.values():
        s.update(ws)
    return sorted(s)

async def _weapon_ac(interaction: discord.Interaction, current: str):
    cur = current.lower()
    return [app_commands.Choice(name=w, value=w) for w in _all_weapons() if cur in w.lower()][:25]

async def _subclass_ac(interaction: discord.Interaction, current: str):
    cur = current.lower()
    subs = sorted(config.CLASS_WEAPON_MAP.keys())
    return [app_commands.Choice(name=s, value=s) for s in subs if cur in s.lower()][:25]

MOD_ROLE_ID             = config.MOD_ROLE_ID
GUILD_ID                = config.GUILD_ID
CHALLENGE_RULES_CHANNEL_ID = config.CHALLENGE_RULES_CHANNEL_ID
BUTLERS_FAVOURITES_CHANNEL_ID = config.BUTLERS_FAVOURITES_CHANNEL_ID
BOUNTY_FORUM_CHANNEL_ID = config.BOUNTY_FORUM_CHANNEL_ID
# Asset paths are relative to the repo root, not the cogs/ subdirectory
_ASSETS_DIR     = os.path.join(os.path.dirname(__file__), '..', 'assets')
DECORATION_TOP  = os.path.join(_ASSETS_DIR, 'WMMR_Spacer_Top.png')
DECORATION_BOTTOM = os.path.join(_ASSETS_DIR, 'WMMR_Spacer_Bottom.png')
PLAYER_TITLES           = config.PLAYER_TITLES
GRAND_MARSHAL_ROLE_ID   = config.GRAND_MARSHAL_ROLE_ID
WEAPONS_MASTER_ROLE_ID  = config.WEAPONS_MASTER_ROLE_ID
CAMPAIGN_MASTER_ROLE_ID = config.CAMPAIGN_MASTER_ROLE_ID

def build_challenge_rules_embeds():
    """Return a list of discord.Embed objects for the challenge rules channel."""
    C = discord.Colour.from_str

    embeds = []

    # 1. Intro
    e = discord.Embed(
        title="<:cigar:1444893851427803298>  Cigar Lounge",
        description=(
            "100-bombers come here to grind weapon marks, complete bounties, and settle scores against each other.\n\n"
            "One outstanding game is a coincidence.\nThe lounge is interested in what you do after that."
        ),
        colour=C("#C9A84C"),
    )
    embeds.append(e)

    # 2. Earning weapon marks
    e = discord.Embed(
        title="🎯  Earning Weapon Marks",
        description="A weapon mark is earned by completing a **100 takedown game** with the following conditions:",
        colour=C("#C9A84C"),
    )
    e.add_field(name="Requirements", value=(
        "• Same loadout for the entire match\n"
        "• No catapult usage\n"
        "• Match must be submitted in <#1328832440927518920>"
    ), inline=False)
    e.add_field(name="Submission must include", value=(
        "• Class or subclass\n• Weapon used\n• VIP used or not"
    ), inline=False)
    e.add_field(name="Bonus marks per submission", value=(
        "<a:200tkd:1363648828414230538> +1 for 200 Takedowns\n"
        "<a:100kill:1361412390339608686> +1 for 100 Kills\n"
        "<a:triple:1365532698260668466> +1 for Triple\n"
        "<a:highscore:1360312918545269057> +1 for Leaderboard High Score\n"
        "🔴 +1 for a Brutal Lobby"
    ), inline=False)
    e.add_field(name="Note", value="Goedendag counts for Polearms **and** Engineer (Footman).", inline=False)
    embeds.append(e)

    # 2b. Lobby difficulty system
    e = discord.Embed(
        title="⚖️  Lobby Difficulty",
        description=(
            "Every submission is graded by the kill gap between the two teams, read "
            "from the scoreboard banners and measured against the smaller team's total. "
            "The marker appears on your submission blurb."
        ),
        colour=C("#992d2d"),
    )
    e.add_field(name="The gradient", value=(
        "🍼 **Training Grounds** — your team up 75% or more. The playpen. Expect mockery.\n"
        "🟢 **Favoured** — up 25–74%\n"
        "🟡 **Even** — within ±25%\n"
        "🟠 **Uphill** — down 25–74%\n"
        "🔴 **Brutal** — down 75% or more. Surviving it pays **+1 mark**. Valor pay."
    ), inline=False)
    embeds.append(e)

    # 3. Weapon ranks
    e = discord.Embed(
        title="⚔️  Weapon Ranks",
        description="Marks accumulate per weapon. Each threshold unlocks the next rank.",
        colour=C("#5865F2"),
    )
    e.add_field(name="Ranks", value=(
        "<:level1_1:1361419350665461820> **Bronze** — 1 mark\n"
        "<:level2_3:1361419398841106442> **Silver** — 5 total\n"
        "<:level3_6:1361419489635209396> **Gold** — 12 total\n"
        "<:level4_9:1368656036784771212> **Emerald** — 25 total\n"
        "<:level5_12:1368656100764942432> **Diamond** — 40 total\n"
        "<:level6_15:1430203489757302924> **Crimson** — 60 total"
    ), inline=True)
    e.add_field(name="Prestige", value=(
        "<:level7_20:1430216503919120537> **Prestige Bronze** — 80\n"
        "<:level8_30:1430216636006137876> **Prestige Silver** — 100\n"
        "<:level9_40:1430216748329599046> **Prestige Gold** — 115\n"
        "<:level10_55:1430216819787956265> **Prestige Emerald** — 125\n"
        "<:level11_70:1430217739586240624> **Prestige Diamond** — 133\n"
        "<:level12_85:1430217099648962651> **Prestige Crimson** — 141\n"
        "<:level13_100:1459253823481712895> **Iridescent** — 150"
    ), inline=True)
    e.add_field(name="👑 Mastery", value=(
        "Past Iridescent, keep grinding the same weapon: **100 qualifying runs = 👑 Mastered**, "
        "**250 = 💎 Virtuoso** (counts across every class that wields it)."
    ), inline=False)
    embeds.append(e)

    # 4. Subclass & class progression
    e = discord.Embed(
        title="🧩  Subclass & Class Progression",
        description=(
            "Each time a weapon badge upgrades, you earn **1 subclass mark**.\n"
            "Fill the subclass meter and earn **1 class mark**. "
            "Subclass length varies by how many primary weapons it contains."
        ),
        colour=C("#534AB7"),
    )
    e.add_field(name="Subclass ranks", value=(
        "<:subclass0:1361423009256308808> Initiate\n"
        "<:veteran2:1430199755094360194> Veteran\n"
        "<:master3:1430199983675670619> Master\n"
        "<:grandmaster4:1430199858635210752> Grandmaster\n"
        "<:champion5:1430199893363789934> Champion\n"
        "<:paragon6:1430199955385094235> Paragon\n"
        "<:apex7:1430199916126408754> Apex"
    ), inline=True)
    e.add_field(name="Class ranks", value=(
        "<:class0_0:1446622044698443969> Sworn\n"
        "<:class1_3:1446620360186269726> Trusted\n"
        "<:class2_6:1446620614096846988> Proven\n"
        "<:class3_9:1446620700189266182> Honored\n"
        "<:class4_12:1446620991777407128> Esteemed\n"
        "<:class5_15:1446621127605620826> Exalted\n"
        "<:class6_18:1446621258430025791> Ascended"
    ), inline=True)
    embeds.append(e)

    # 5. Feats of legend
    e = discord.Embed(
        title="💀  Feats of Legend",
        description="Additional marks earned by completing a valid 100 TD game plus one of the following:",
        colour=C("#C0392B"),
    )
    e.add_field(name="Feats", value=(
        "<a:100kill:1361412390339608686> 100 kills\n"
        "<a:triple:1365532698260668466> 150 takedowns, 100 kills, and 20,000 points **(Triple)**\n"
        "<a:200tkd:1363648828414230538> 200 takedowns\n"
        "<a:predator:1366794896081555567> 150 takedowns without dying **(Predator)**"
    ), inline=False)
    e.add_field(name="<:hhanded:1430199468246044772>  The Hundred-Handed", value=(
        "Get a 100 with every primary weapon across all non-archer subclasses."
    ), inline=False)
    embeds.append(e)

    # 5b. Leaderboards & ratings
    e = discord.Embed(
        title="📊  Leaderboards",
        description="Every weapon and map keeps a live board. Beat your own best and you set a High Score (+1 mark).",
        colour=C("#2B6CB0"),
    )
    e.add_field(name="Boards", value=(
        "• **Weapon boards** — best takedown game per weapon\n"
        "• **Map boards** — best takedown game per map/faction (VIP counts here)\n"
        "• **Feat boards** — 100 Kills, 200 Takedowns, Triple, Flawless, TUFF"
    ), inline=False)
    e.add_field(name="<a:TUFF2:1520779243879927898>  TUFF", value=(
        "A hard-carry board: you score **TUFF** when your **kills** beat your best "
        "teammate's **takedowns**. The board tracks the margin (**+N**) \u2014 how far your "
        "kill count topped the next-highest player on your own team."
    ), inline=False)
    e.add_field(name="<a:mostlethal:1520490418817601658> Board ratings", value=(
        "**Weapon boards** rank <a:mostlethal:1520490418817601658> **Lethality** (kills per takedown) and "
        "<:warlord:1520490364039860347> **Warlord** (your share of your team's takedowns).\n"
        "**Map boards** rank <a:mostlethal:1520490418817601658> **Kill Share** (your share of your team's kills) and "
        "<:warlord:1520490364039860347> **Warlord** (your takedowns vs your team's total kills).\n"
        "Each is your **best 5-game streak ever** on that board, so it never drops for a bad game — keep submitting. "
        "Min 5 games on weapons; rarely-played maps need fewer.\n"
        "Lethality stays weapon-only on purpose: different weapons have different natural kill/takedown ratios, so it "
        "only means something within the same weapon."
    ), inline=False)
    embeds.append(e)

    # 5c. Titles
    e = discord.Embed(
        title="🏅  Titles",
        description="Held by the best across the boards. Some are forever; some reset every month.",
        colour=C("#B57EDC"),
    )
    e.add_field(name="All-time (never reset)", value=(
        "<a:grandmarshal:1519928617407348877> **Grand Marshal** — most boards overall\n"
        "<a:weaponsmaster:1519928521445605488> **Weapons Master** — most weapon boards\n"
        "<a:campaignmaster:1520497947115262083> **Campaign Master** — most map boards"
    ), inline=False)
    e.add_field(name="This season (reset each bounty)", value=(
        "<a:topkill:1360314538364240024> **Apex** — best average kills\n"
        "<a:200tkd:1363648828414230538> **Frenzied** — best average takedowns\n"
        "<a:mostlethal:1520490418817601658> **Kill Share** — biggest share of your team's kills\n"
        "<:warlord:1520490364039860347> **Warlord** — your takedowns vs your team's total kills"
    ), inline=False)
    e.add_field(name="🎯 Bounty", value=(
        "You also carry the **bounty role** while you're taking part in the active monthly bounty."
    ), inline=False)
    embeds.append(e)

    # ── SEASON CHAMPIONSHIP ───────────────────────────────────────────────────
    e = discord.Embed(
        title="🏆  Season Championship",
        description=(
            "Every bounty cycle is a season. Grand Prix points (GP) come from three places. "
            "Highest total takes the crown and a permanent Hall of Fame entry."
        ),
        colour=C("#D4AF37"),
    )
    e.add_field(name="1. Category points  (max 25)", value=(
        "Top 5 in each category score **5 / 4 / 3 / 2 / 1** GP:\n"
        "<a:mostlethal:1520490418817601658> **Kill Share**: your share of your team's kills\n"
        "<:warlord:1520490364039860347> **Warlord**: your takedowns against your team's kills\n"
        "**Total Tally**: every takedown you log this season, added up\n"
        "**Most Kills**: your single best run\n"
        "**Highest Takedowns**: your single best run"
    ), inline=False)
    e.add_field(name="2. Special Features  (max 12)", value=(
        "Four focuses are rolled at random each season: a 1H weapon, a 2H weapon and two maps. "
        "On each one, the highest takedowns in a single run scores **3** GP and the runner-up **1**."
    ), inline=False)
    e.add_field(name="3. Bounty race  (max 5)", value=(
        "Completing the monthly bounty pays by finishing position: "
        "**5** for first, **4** for second, **3** for third, **2** for everyone after."
    ), inline=False)
    e.add_field(name="🎯 The bonus challenge (paid on completion)", value=(
        "The bounty's bonus challenge tallies **while the bounty is live**: every "
        "qualifying run counts toward it as you go. You don't have to save it for last "
        "or do it in any order. But it only **pays out when you finish the main bounty** "
        "— clear the weapon objectives and any bonus progress you've already banked is "
        "credited at that moment. Do it before or after; either way it lands when the "
        "bounty is done."
    ), inline=False)
    e.add_field(name="Why the rate boards reward consistency", value=(
        "Kill Share and Warlord are percentages, so a raw average would let one lucky game win "
        "outright. Both are volume-adjusted: your average is pulled toward the community mean "
        "until you have games behind it, and recent runs count for more than old ones. "
        "Play steadily and it climbs. A single freak scoreline will not carry you."
    ), inline=False)
    e.add_field(name="What does not count", value=(
        "Runs tagged `Resubmit` (an old game uploaded later) or `Unlisted` (pulled by a mod) "
        "are excluded from every season category."
    ), inline=False)
    embeds.append(e)

    # 6. Player titles
    e = discord.Embed(
        title="🏆  Player Titles",
        description="Complete bounties — that's how you rank up.",
        colour=C("#1D9E75"),
    )
    e.add_field(name="Ranks (total bounties completed)", value=(
        "0 — Lounger\n1 — Insider\n2 — Regular\n3 — Made Man\n"
        "4 — High Roller\n5 — Kingpin\n6+ — Legend"
    ), inline=False)
    embeds.append(e)

    # 7. Monthly cycle
    e = discord.Embed(
        title="🗓️  The Monthly Cycle",
        description=(
            "Each month opens a new **bounty** and **season** together. Complete the bounty's "
            "weapon objectives to climb your player title (Lounger → Legend)."
        ),
        colour=C("#C9A84C"),
    )
    e.add_field(name="When the month ends", value=(
        "The season's champions are enshrined in the **Hall of Fame**, and the season titles "
        "(Apex, Frenzied, Most Lethal, Warlord) reset — always up for grabs. Weapon ranks, marks, "
        "and all-time titles carry over forever."
    ), inline=False)
    embeds.append(e)

    return embeds


async def get_challenge_rules_message_ids():
    try:
        return await _db.get_challenge_rule_msg_ids()
    except Exception:
        return []

async def save_challenge_rules_message_ids(msg_ids):
    labels = ['Intro', 'Earning Marks', 'Weapon Ranks', 'Subclass & Class', 'Feats of Legend',
              'Leaderboards', 'Titles', 'Player Titles', 'Monthly Cycle']
    try:
        await _db.save_challenge_rules(msg_ids, labels)
    except Exception as e:
        print(f"ChallengeRules DB save error: {e}")




class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_backup_loop.start()

    def cog_unload(self):
        self.db_backup_loop.cancel()

    async def _run_backup(self, reason="scheduled", force=False):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return None
        ch = (guild.get_channel(config.NERVE_CENTER_CHANNEL_ID)
              or await guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID))
        if not ch:
            return None
        # Skip if a backup was already posted in the last ~20h (unless forced) so
        # frequent redeploys don't spam the channel.
        if not force:
            try:
                cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=20)
                async for m in ch.history(limit=50, after=cutoff):
                    if (m.author.id == self.bot.user.id and m.attachments
                            and any('clb_backup' in (a.filename or '') for a in m.attachments)):
                        return None
            except Exception:
                pass
        data = await _db.dump_database()
        counts = ", ".join(f"{k}:{len(v)}" for k, v in data.items() if isinstance(v, list))
        payload = json.dumps(data, default=str, ensure_ascii=False).encode('utf-8')
        gz = gzip.compress(payload)
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d_%H%M')
        fname = f"clb_backup_{stamp}.json.gz"
        await ch.send(
            f"\U0001f5c4\ufe0f **DB backup** ({reason}) — {len(gz)//1024} KB\n{counts}",
            file=discord.File(io.BytesIO(gz), filename=fname))
        return fname

    @tasks.loop(hours=24)
    async def db_backup_loop(self):
        try:
            await self._run_backup(reason="scheduled")
        except Exception as e:
            print(f"[BACKUP] loop error: {e}")

    @db_backup_loop.before_loop
    async def _before_db_backup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="backup_now", description="Force an immediate DB backup to the nerve centre (mod only).")
    async def backup_now(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            fname = await self._run_backup(reason="manual", force=True)
        except Exception as e:
            await interaction.edit_original_response(content=f"\u274c Backup failed: {e}")
            return
        if fname:
            await interaction.edit_original_response(content=f"\u2705 Backup posted to the nerve centre: `{fname}`")
        else:
            await interaction.edit_original_response(content="\u26a0\ufe0f Backup could not post — nerve centre channel not found.")

    @app_commands.command(name="purge_forum", description="Delete ALL threads in a forum channel (admin only). Irreversible.")
    @app_commands.describe(channel="The forum channel to wipe", confirm="Set True to actually delete — every thread, including the pinned index")
    @app_commands.checks.has_permissions(administrator=True)
    async def purge_forum(self, interaction: discord.Interaction, channel: discord.ForumChannel, confirm: bool = False):
        await interaction.response.defer(ephemeral=True)

        # Gather active + archived threads, de-duplicated.
        threads = list(channel.threads)
        try:
            async for t in channel.archived_threads(limit=None):
                threads.append(t)
        except Exception as e:
            print(f"[PURGE] archived fetch error: {e}")
        seen = set()
        unique = []
        for t in threads:
            if t.id not in seen:
                seen.add(t.id)
                unique.append(t)

        if not confirm:
            await interaction.followup.send(
                f"⚠️ This will permanently delete **{len(unique)}** threads in {channel.mention} "
                f"(including the pinned index). Re-run with `confirm: True` to proceed.",
                ephemeral=True)
            return

        if not unique:
            await interaction.followup.send(f"Nothing to delete in {channel.mention}.", ephemeral=True)
            return

        deleted = failed = 0
        for t in unique:
            try:
                await t.delete()
                deleted += 1
                await asyncio.sleep(0.6)  # stay under Discord's delete rate limit
            except Exception as e:
                failed += 1
                print(f"[PURGE] delete error ({t.name}): {e}")
        note = f" ({failed} could not be deleted)" if failed else ""
        await interaction.followup.send(
            f"🧹 Deleted **{deleted}** threads in {channel.mention}{note}.", ephemeral=True)

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

            existing_rows = await _db.get_all_players()
            existing_ids = set(row[0] for row in existing_rows if row)

            added = 0
            skipped = 0

            for member in role.members:
                discord_id = str(member.id)
                display_name = member.nick if member.nick else member.display_name

                if discord_id in existing_ids:
                    skipped += 1
                    continue

                await _db.upsert_player(discord_id, display_name)
                added += 1

            await interaction.followup.send(
                f"✅ Seeded **{added}** players from role.\n"
                f"⏭️ Skipped **{skipped}** already registered.",
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

            embeds = build_challenge_rules_embeds()
            msg_ids = []
            for embed in embeds:
                msg = await channel.send(embed=embed)
                msg_ids.append(msg.id)
                await asyncio.sleep(0.5)

            await save_challenge_rules_message_ids(msg_ids)
            await interaction.followup.send(f"Posted {len(msg_ids)} challenge rules embeds.", ephemeral=True)
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

            msg_ids = await get_challenge_rules_message_ids()
            if not msg_ids:
                await interaction.followup.send("No challenge rules messages found — run /post_challenge_rules first.", ephemeral=True)
                return

            embeds = build_challenge_rules_embeds()
            updated = 0
            for msg_id, embed in zip(msg_ids, embeds):
                try:
                    msg = await channel.fetch_message(msg_id)
                    await msg.edit(content=None, embed=embed)
                    updated += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"Error updating message {msg_id}: {e}")

            # Embeds added since the original post have no message to edit. Send
            # them and extend the stored id list, so a new section does not
            # require re-posting (and duplicating) the whole channel.
            added = 0
            if len(embeds) > len(msg_ids):
                new_ids = list(msg_ids)
                for embed in embeds[len(msg_ids):]:
                    msg = await channel.send(embed=embed)
                    new_ids.append(msg.id)
                    added += 1
                    await asyncio.sleep(0.5)
                await save_challenge_rules_message_ids(new_ids)

            _tail = f", posted {added} new" if added else ""
            await interaction.followup.send(
                f"Updated {updated}/{len(msg_ids)} challenge rules embeds{_tail}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="title_guide", description="Post the Butler Monthly title guide to the favourites channel (mod only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def title_guide(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(BUTLERS_FAVOURITES_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("Could not find the Butler Monthly channel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Butler Monthly — Title Guide",
            description="Prestige titles awarded to the Lounge's top performers. Titles are recalculated automatically after every submission.",
            color=discord.Color.from_str("#c8a45a")
        )
        embed.add_field(
            name="🏆 Grand Marshal  *(all-time)*",
            value="Appears on 15+ leaderboards across all categories, ranked by average placement.",
            inline=False
        )
        embed.add_field(
            name="⚔️ Weapons Master  *(all-time)*",
            value="Appears on 9+ weapon leaderboards, ranked by average placement.",
            inline=False
        )
        embed.add_field(
            name="🗺️ Campaign Master  *(all-time)*",
            value="Appears on 6+ map leaderboards, ranked by average placement.",
            inline=False
        )
        embed.add_field(
            name="💀 Apex  *(weekly showcase)*",
            value="Each week, awarded to the highest average kills across your 100+ kill runs (minimum 3 that week). A showcase title — no role attached, just bragging rights.",
            inline=False
        )
        embed.add_field(
            name="🩸 Frenzied  *(weekly showcase)*",
            value="Each week, awarded to the highest average takedowns across your 200+ takedown runs (minimum 3 that week). A showcase title — no role attached, just bragging rights.",
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
            from cogs.bounty import (get_active_bounty, get_player_bounty_progress,
                                     save_player_bounty_progress, save_bounty_state,
                                     build_player_bounty_card)
            from cogs.leaderboards import get_leaderboard_entries, format_leaderboard_text, pack_chunks_into_slots, _get_lb_records
            from cogs.registry import create_or_update_registry_card

            # 1. find and delete the submission row
            sub_rows = await _db.get_all_submissions()
            sub_data = None
            for row in sub_rows:
                if len(row) >= 13 and row[12].strip() == message_link.strip():
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

            await _db.delete_submission_by_link(message_link.strip())
            report.append(f"✅ Submissions: row deleted ({player_name}, {weapon}, {map_name})")

            # 2. strip it from LeaderboardData
            affected_lb_names = await _db.delete_leaderboard_entries_by_link(message_link.strip())
            report.append(f"✅ LeaderboardData: deleted entries, affected boards: {', '.join(affected_lb_names) or 'none'}")

            # 3. rebuild any leaderboard threads that had this score in them
            if affected_lb_names:
                all_lb_rows = await _get_lb_records()
                rebuilt = []
                for lb_name in affected_lb_names:
                    lb_row = next((r for r in all_lb_rows if r['Leaderboard Name'] == lb_name), None)
                    if not lb_row:
                        continue
                    try:
                        entries = await get_leaderboard_entries(lb_name)
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
            bounty = await get_active_bounty()
            if bounty:
                matched_key = next((k for k in bounty['weapons'] if k.lower() == weapon.lower()), None)
                if matched_key and takedowns >= 100:
                    player_row = await get_player_bounty_progress(bounty['title'], discord_id)
                    if player_row:
                        progress = player_row['progress']
                        raw = progress.get(matched_key, 0)
                        cur = raw['current'] if isinstance(raw, dict) else int(raw)
                        if cur > 0:
                            progress[matched_key] = cur - 1
                            await save_player_bounty_progress(bounty['title'], discord_id, player_name, player_row['forum_post_id'], progress)
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
                                await save_bounty_state(bounty['id'], weapons, bounty['special_done'], bounty['completions'])
                            report.append(f"✅ Bounty: decremented {matched_key} for {player_name}")
                        else:
                            report.append(f"⚠️ Bounty: {player_name} already at 0 for {matched_key}, skipped")
                    else:
                        report.append(f"ℹ️ Bounty: no progress row found for {player_name}")
                else:
                    report.append(f"ℹ️ Bounty: weapon {weapon} not on active bounty or TDs < 100, skipped")

            # 5. rebuild registry card so mark count reflects the removal
            try:
                from cogs.registry import create_or_update_registry_card
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

    @app_commands.command(name="unlist_submission", description="Toggle a run off/on all boards & records — still counts for marks and bounty (mod only).")
    @app_commands.describe(message_link="Discord message link to the original scorecard post")
    async def unlist_submission(self, interaction: discord.Interaction, message_link: str):
        """Adds/removes an 'Unlisted' tag on the submission's feats. Unlisted runs are
        excluded from board placement, rebuilds, feat-board backfills, and weekly/monthly
        ratings, but keep their marks and bounty progress (those paths ignore the tag).
        For runs that were technically real but outside the spirit of the challenge
        (lopsided lobbies, farm games, etc.)."""
        if not any(r.id == config.MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        link = message_link.strip()

        sub = None
        for row in await _db.get_all_submissions():
            if len(row) >= 13 and (row[12] or '').strip() == link:
                sub = row
                break
        if not sub:
            await interaction.followup.send("❌ No submission found with that message link.", ephemeral=True)
            return

        player_name = (sub[1] or '').strip()
        discord_id  = (sub[2] or '').strip()
        weapon      = (sub[3] or '').strip()
        map_name    = (sub[5] or '').strip()
        faction     = (sub[6] or '').strip()
        vip         = (sub[10] or '').strip().lower() == 'yes'
        feats_str   = (sub[11] or '').strip()
        feats = [f.strip() for f in feats_str.split(',') if f.strip() and f.strip() != 'None']
        currently_unlisted = 'Unlisted' in feats

        def _i(v):
            try:
                return int(str(v).replace(',', '').strip())
            except (ValueError, TypeError):
                return 0
        takedowns = _i(sub[7])
        kills     = _i(sub[8])
        second_td = _i(sub[22]) if len(sub) > 22 and sub[22] else 0
        p_score   = _i(sub[24]) if len(sub) > 24 and sub[24] else 0
        is_pac    = (kills == 0 and takedowns <= 10)
        map_board = f"{map_name} - {faction}" if map_name and faction else None

        from cogs.leaderboards import rebuild_score_boards, _get_lb_records, _render_board, _prune_pacifist_board
        from cogs.submissions import _BOARD_LOCK

        async def _render(boards):
            recs = await _get_lb_records()
            for b in boards:
                rec = next((r for r in recs if r['Leaderboard Name'] == b), None)
                if rec:
                    try:
                        await _render_board(interaction.guild, rec, b)
                    except Exception as e:
                        print(f"[UNLIST] render error ({b}): {e}")

        if not currently_unlisted:
            # ── Unlist: tag it, strip its board rows, rebuild so next-best runs reclaim slots
            feats.append('Unlisted')
            await _db.update_submission_feats_by_link(link, ', '.join(feats))
            async with _BOARD_LOCK:
                affected = set(await _db.delete_leaderboard_entries_by_link(link))
                score_boards = set()
                _kills_board = f"{weapon} Kills" if (weapon and not vip) else None
                for b in ((None if vip else weapon), _kills_board, map_board):
                    if b:
                        await _db.delete_leaderboard_entries_by_board_and_discord(b, discord_id)
                        score_boards.add(b)
                affected |= score_boards
                if score_boards:
                    await rebuild_score_boards(
                        interaction.guild, board_names=list(score_boards), only_player=discord_id)
            # rebuild renders weapon/map itself; re-render any feat boards that lost a row
            await _render(affected - score_boards)
            await interaction.followup.send(
                f"✅ **Unlisted**: {player_name}'s run ({weapon}, {takedowns} TD / {kills} K) is off "
                f"the boards and records. Cleared: {', '.join(sorted(affected)) or 'none'}.\n"
                f"Marks and bounty progress still count. Run the command again to re-list it.",
                ephemeral=True)
        else:
            # ── Re-list: remove the tag, restore feat-board rows from stored stats,
            # rebuild weapon/map so the run competes again.
            feats = [f for f in feats if f != 'Unlisted']
            await _db.update_submission_feats_by_link(link, ', '.join(feats) if feats else 'None')
            async with _BOARD_LOCK:
                readd = []
                if is_pac:
                    if p_score > 0:
                        readd.append(("Pacifist", p_score))
                else:
                    if kills >= 100:
                        readd.append(("100 Kills", kills))
                    if takedowns >= 200:
                        readd.append(("200 Takedowns", takedowns))
                    if 'Triple' in feats:
                        readd.append(("Triple", takedowns))
                    if second_td and kills > second_td:
                        readd.append(("TUFF", kills - second_td))
                existing = {(r[0], (r[4] or '').strip())
                            for r in await _db.get_all_leaderboard_data() if len(r) > 4}
                for b, sc in readd:
                    if (b, link) not in existing:
                        await _db.add_leaderboard_entry(b, player_name, discord_id, sc, link, weapon)
                if is_pac:
                    await _prune_pacifist_board()
                score_boards = {b for b in ((None if vip else weapon),
                                            None if vip else f"{weapon} Kills",
                                            map_board) if b}
                if score_boards:
                    await rebuild_score_boards(
                        interaction.guild, board_names=list(score_boards), only_player=discord_id)
            await _render({b for b, _ in readd})
            _restored = sorted({b for b, _ in readd} | score_boards)
            await interaction.followup.send(
                f"✅ **Re-listed**: {player_name}'s run is back in contention "
                f"({', '.join(_restored) or 'no qualifying boards'}).\n"
                f"Note: personal-best feat boards (Flawless / Mallet / Knife / Healing Horn) "
                f"aren't auto-restored; they'll re-place on the player's next qualifying run.",
                ephemeral=True)

    @app_commands.command(name="rules", description="Show the Cigar Lounge challenge rules.")
    async def rules_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        for embed in build_challenge_rules_embeds():
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="force_poll", description="Manually post a dry Butler question in main right now (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_poll(self, interaction: discord.Interaction):
        """Bypasses the 30%-per-12-hours dice roll in butler_poll_post so a
        poll can be tested/posted on demand instead of waiting on the odds."""
        await interaction.response.defer(ephemeral=True)
        try:
            personality_cog = interaction.client.cogs.get("PersonalityCog")
            if not personality_cog:
                await interaction.followup.send("❌ PersonalityCog not loaded.", ephemeral=True)
                return
            await personality_cog._run_poll_logic()
            await interaction.followup.send("✅ Poll posted in main.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="set_feat_count", description="Manually set a player's 100 Kills / 200 Takedowns / Triple count (mod only).")
    @app_commands.describe(
        player="@ mention or Discord ID of the player",
        feat="Which feat: 100 Kills, 200 Takedowns, or Triple",
        count="Number of times they've achieved this feat"
    )
    @app_commands.choices(feat=[
        app_commands.Choice(name="100 Kills", value="100 Kills"),
        app_commands.Choice(name="200 Takedowns", value="200 Takedowns"),
        app_commands.Choice(name="Triple", value="Triple"),
    ])
    async def set_feat_count(self, interaction: discord.Interaction, player: discord.Member, feat: str, count: int):
        if not any(r.id == config.MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        valid = {'100 kills', '200 takedowns', 'triple'}
        if feat.lower().strip() not in valid:
            await interaction.response.send_message(
                "❌ Feat must be one of: `100 Kills`, `200 Takedowns`, `Triple`", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await _db.set_manual_feat_count(str(player.id), feat, count)
        except Exception as e:
            await interaction.followup.send(f"❌ DB error: {e}", ephemeral=True)
            return
        card_status = "and refreshed their card"
        try:
            from cogs.registry import create_or_update_registry_card
            await create_or_update_registry_card(interaction.guild, str(player.id), _canonical_name)
        except Exception as e:
            card_status = f"but card refresh failed: {e}"
            print(f"[SET_FEAT] card refresh error for {player.display_name}: {e}")
        await interaction.followup.send(
            f"✅ Set **{feat}** count to **{count}** for **{player.display_name}** {card_status}.",
            ephemeral=True
        )


    @app_commands.command(name="award_marks", description="Manually award marks on a weapon to a player (mod only).")
    @app_commands.describe(
        player="@ mention the player",
        weapon="Weapon name (must match exactly)",
        subclass="Subclass (e.g. Knight, Vanguard) — required for shared weapons",
        marks="Number of marks to add"
    )
    @app_commands.autocomplete(weapon=_weapon_ac, subclass=_subclass_ac)
    async def award_marks(self, interaction: discord.Interaction, player: discord.Member, weapon: str, subclass: str, marks: int):
        if not any(r.id == config.MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That\'s not for you.", ephemeral=True)
            return
        if marks < 1:
            await interaction.response.send_message("Marks must be at least 1.", ephemeral=True)
            return

        # Validate weapon name
        all_weapons = set()
        for ws in config.CLASS_WEAPON_MAP.values():
            all_weapons.update(ws)
        if weapon not in all_weapons:
            await interaction.response.send_message(
                f"\u274c Unknown weapon `{weapon}`. Check spelling — must match exactly.", ephemeral=True
            )
            return

        # Normalize subclass through the same alias table used for submission parsing
        # (e.g. "man at arms" / "maa" -> "Man-at-Arms"). Free-text subclass input
        # previously got stored verbatim into legacy_marks, so a mod typing "Man at
        # Arms" (no hyphen) would silently create a row that never matched the
        # canonical "Man-at-Arms" key used everywhere else — the mark looked added
        # but never showed up on the card. (OctoLemon Sword/Man-at-Arms, 2026-06-30.)
        normalized_subclass = config.SUBCLASS_ALIASES.get(subclass.strip().lower(), subclass.strip())
        if normalized_subclass not in config.REGISTRY_WEAPON_MAP:
            await interaction.response.send_message(
                f"\u274c Unknown subclass `{subclass}`. Must be a valid subclass (e.g. `Man-at-Arms`, `Officer`, `Guardian`).",
                ephemeral=True
            )
            return
        subclass = normalized_subclass

        await interaction.response.defer(ephemeral=True)
        # Store under the SAME name the card reads legacy marks by — the Players-table
        # name (set at last submission), not the live Discord display name. Otherwise a
        # clan tag / rename means the mark is written under one name and read under
        # another, so it silently never shows on the card.
        _canonical_name = player.display_name
        try:
            _prow = await _db.get_player(str(player.id))
            if _prow and len(_prow) > 1 and (_prow[1] or '').strip():
                _canonical_name = _prow[1].strip()
        except Exception as e:
            print(f"[AWARD_MARKS] canonical-name lookup failed for {player.id}, using display_name: {e}")
        try:
            await _db.add_legacy_mark(_canonical_name, weapon, subclass, marks,
                                      discord_id=str(player.id))
        except Exception as e:
            await interaction.followup.send(f"\u274c DB error: {e}", ephemeral=True)
            return

        card_status = "and refreshed their card"
        try:
            from cogs.registry import create_or_update_registry_card
            await create_or_update_registry_card(interaction.guild, str(player.id), _canonical_name)
        except Exception as e:
            card_status = f"but card refresh failed: {e}"

        plural = 's' if marks != 1 else ''
        await interaction.followup.send(
            f"\u2705 Awarded **{marks} mark{plural}** on **{weapon}** to **{player.display_name}** {card_status}.",
            ephemeral=True
        )

    @app_commands.command(name="refresh_titles", description="Recalculate Butler Monthly title holders and reassign roles (mod only).")
    async def refresh_titles(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That’s not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            from cogs.favourites import calculate_butler_stats, update_title_roles
            from datetime import datetime, timezone, timedelta
            _now = datetime.now(timezone.utc)
            _week_start = (_now - timedelta(days=_now.weekday())).replace(hour=12, minute=0, second=0, microsecond=0)
            if _week_start > _now:
                _week_start -= timedelta(weeks=1)
            stats = await calculate_butler_stats(week_start=_week_start.timestamp(), week_end=_now.timestamp())
            await update_title_roles(interaction.guild, stats)
            await interaction.followup.send("✅ Title roles recalculated and reassigned.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
