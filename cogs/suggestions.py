import time
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils import db as _db

MOD_ROLE_ID = config.MOD_ROLE_ID
_UPVOTE = "\U0001f44d"  # 👍


class SuggestionView(discord.ui.View):
    """Mod-only Shortlist / Use / Dismiss controls on a public suggestion card. Members
    upvote via the 👍 reaction; the buttons are gated to mods and resolve the suggestion
    from the message they live on, so they survive restarts."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _guard(self, interaction):
        roles = getattr(interaction.user, "roles", [])
        if not any(getattr(r, "id", 0) == MOD_ROLE_ID for r in roles):
            await interaction.response.send_message("Mods only — but you can 👍 to upvote it.", ephemeral=True)
            return False
        return True

    async def _act(self, interaction, status, colour, tag):
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        sug = await _db.get_bounty_suggestion_by_message(interaction.message.id)
        if not sug:
            await interaction.followup.send("Couldn't find that suggestion.", ephemeral=True)
            return
        changed = await _db.set_bounty_suggestion_status(sug["id"], status, str(interaction.user))
        _cog = self.bot.get_cog("SuggestionsCog")
        if _cog:
            _cog._board_dirty = True
        try:
            emb = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            emb.colour = colour
            emb.clear_fields()
            emb.add_field(name="Status", value=f"{tag} by {interaction.user.mention}", inline=False)
            _disable = status in ("used", "dismissed")
            for c in self.children:
                c.disabled = _disable
            await interaction.message.edit(embed=emb, view=self)
        except Exception as e:
            print(f"[SUGGEST] card update failed: {e}")
        if status == "used" and changed:
            await self._shoutout(interaction, sug)

    async def _shoutout(self, interaction, sug):
        try:
            who = f"<@{sug['discord_id']}>" if sug.get("discord_id") else (sug.get("name") or "someone")
            txt = (sug.get("text") or "").strip()
            snippet = (txt[:180] + "…") if len(txt) > 180 else txt
            await interaction.channel.send(
                f"{_UPVOTE} A community bounty suggestion has been chosen. {who}, the household will put "
                f"your idea to work: *{snippet}* The butler tips his hat.",
                allowed_mentions=discord.AllowedMentions(users=True))
        except Exception as e:
            print(f"[SUGGEST] shoutout failed: {e}")

    @discord.ui.button(label="Shortlist", emoji="⭐", style=discord.ButtonStyle.primary, custom_id="sug_shortlist")
    async def shortlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._act(interaction, "shortlisted", 0x5b8dd9, "⭐ Shortlisted")

    @discord.ui.button(label="Use", emoji="✅", style=discord.ButtonStyle.success, custom_id="sug_use")
    async def use(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._act(interaction, "used", 0x4fb3a1, "✅ Used")

    @discord.ui.button(label="Dismiss", emoji="\U0001f5d1️", style=discord.ButtonStyle.danger, custom_id="sug_dismiss")
    async def dismiss(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._act(interaction, "dismissed", 0xd85a30, "\U0001f5d1️ Dismissed")


class SuggestionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldown = {}  # discord_id -> last-suggest timestamp

    async def cog_load(self):
        self.bot.add_view(SuggestionView(self.bot))

    @app_commands.command(name="suggest_bounty", description="Suggest a bounty idea for the community to upvote.")
    @app_commands.describe(idea="Your bounty idea — weapons, theme, a twist. One or two sentences.")
    async def suggest_bounty(self, interaction: discord.Interaction, idea: str):
        idea = (idea or "").strip()
        if len(idea) < 6:
            await interaction.response.send_message("Give me a bit more to work with — a sentence or two.", ephemeral=True)
            return
        idea = idea[:500]
        ch_id = getattr(config, "BOUNTY_SUGGESTIONS_CHANNEL_ID", 0)
        channel = self.bot.get_channel(ch_id) if ch_id else None
        if channel is None:
            await interaction.response.send_message(
                "The suggestion box isn't set up yet — a mod needs to set `BOUNTY_SUGGESTIONS_CHANNEL_ID`.", ephemeral=True)
            return
        now = time.time()
        uid = str(interaction.user.id)
        if now - self._cooldown.get(uid, 0) < 60:
            await interaction.response.send_message("Easy — give it a minute between suggestions.", ephemeral=True)
            return
        try:
            if await _db.count_open_bounty_suggestions(uid) >= 3:
                await interaction.response.send_message(
                    "You've already got 3 suggestions in the box — let some resolve first.", ephemeral=True)
                return
        except Exception:
            pass
        await interaction.response.defer(ephemeral=True)
        name = interaction.user.display_name
        try:
            sid = await _db.create_bounty_suggestion(uid, name, idea)
        except Exception as e:
            await interaction.followup.send(f"Couldn't file that: {e}", ephemeral=True)
            return
        emb = discord.Embed(title="\U0001f4a1 Bounty suggestion", description=idea, colour=0xe0a84c)
        emb.set_footer(text=f"Suggested by {name} · 👍 to upvote · #{sid}")
        try:
            msg = await channel.send(embed=emb, view=SuggestionView(self.bot),
                                     allowed_mentions=discord.AllowedMentions.none())
            try:
                await msg.add_reaction(_UPVOTE)
            except Exception:
                pass
            await _db.set_bounty_suggestion_message(sid, msg.id)
        except Exception as e:
            await interaction.followup.send(f"Couldn't post it: {e}", ephemeral=True)
            return
        self._cooldown[uid] = now
        await interaction.followup.send(f"Filed it in {channel.mention} — the community can upvote it now. \U0001f3af", ephemeral=True)

    @app_commands.command(name="suggestions", description="List open bounty suggestions ranked by upvotes (mod only).")
    async def suggestions(self, interaction: discord.Interaction):
        if not any(r.id == MOD_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await _db.list_bounty_suggestions(statuses=["open", "shortlisted"], limit=25)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return
        if not rows:
            await interaction.followup.send("No open suggestions right now.", ephemeral=True)
            return
        ch_id = getattr(config, "BOUNTY_SUGGESTIONS_CHANNEL_ID", 0)
        channel = self.bot.get_channel(ch_id) if ch_id else None
        scored = []
        for s in rows:
            votes = 0
            if channel and s.get("message_id"):
                try:
                    m = await channel.fetch_message(int(s["message_id"]))
                    for r in m.reactions:
                        if str(r.emoji) == _UPVOTE:
                            votes = max(0, r.count - 1)  # drop the bot's seed reaction
                            break
                except Exception:
                    pass
            scored.append((votes, s))
        scored.sort(key=lambda x: -x[0])
        lines = []
        for votes, s in scored:
            star = "⭐ " if s["status"] == "shortlisted" else ""
            txt = (s["text"] or "").strip()
            snippet = (txt[:90] + "…") if len(txt) > 90 else txt
            link = ""
            if channel and s.get("message_id"):
                link = f" [·jump](https://discord.com/channels/{interaction.guild.id}/{channel.id}/{s['message_id']})"
            lines.append(f"{star}👍 **{votes}** — {snippet} *(by {s.get('name') or '—'})*{link}")
        emb = discord.Embed(title="\U0001f4a1 Open bounty suggestions", description="\n".join(lines[:25]), colour=0xe0a84c)
        await interaction.followup.send(embed=emb, ephemeral=True)


async def setup(bot):
    await bot.add_cog(SuggestionsCog(bot))
