import discord
from discord.ext import commands

import config
from utils import db as _db

MOD_ROLE_ID = config.MOD_ROLE_ID


async def mint_single_use_invite(guild, reason="Cigar Lounge join"):
    """Fresh single-use, 24h invite to a sensible landing channel. Returns the invite
    URL, or None if the bot can't create one anywhere. Channel priority: configured
    override -> guild Rules -> System -> Information Center -> any invitable channel."""
    ch = None
    cid = getattr(config, "JOIN_INVITE_CHANNEL_ID", 0)
    if cid:
        ch = guild.get_channel(int(cid))
    ch = ch or guild.rules_channel or guild.system_channel or guild.get_channel(config.CHALLENGE_RULES_CHANNEL_ID)
    if ch is None:
        for c in guild.text_channels:
            try:
                if c.permissions_for(guild.me).create_instant_invite:
                    ch = c
                    break
            except Exception:
                continue
    if ch is None:
        return None
    try:
        inv = await ch.create_invite(max_age=86400, max_uses=1, unique=True, reason=reason)
        return inv.url
    except Exception as e:
        print(f"[JOIN] invite mint failed: {e}")
        return None


class JoinRequestView(discord.ui.View):
    """Persistent Accept/Deny controls on a join-request card. The request is resolved
    from the message the buttons live on, so the ids survive restarts with no dynamic
    custom_id juggling and any number of cards can coexist."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _guard(self, interaction):
        roles = getattr(interaction.user, "roles", [])
        if not any(getattr(r, "id", 0) == MOD_ROLE_ID for r in roles):
            await interaction.response.send_message("Mods only.", ephemeral=True)
            return False
        return True

    async def _decide(self, interaction, status):
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        req = await _db.get_join_request_by_message(interaction.message.id)
        if not req:
            await interaction.followup.send("Couldn't find that request.", ephemeral=True)
            return
        if req["status"] != "pending":
            await interaction.followup.send(f"Already {req['status']}.", ephemeral=True)
            return
        invite = None
        if status == "accepted":
            invite = await mint_single_use_invite(interaction.guild, reason=f"Approved by {interaction.user}")
            if not invite:
                invite = getattr(config, "DISCORD_INVITE_URL", "") or None
        ok = await _db.decide_join_request(req["id"], status, str(interaction.user), invite)
        if not ok:
            await interaction.followup.send("Someone just handled this one.", ephemeral=True)
            return
        await self._finalise_card(interaction, status)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="join_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decide(interaction, "accepted")

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="join_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decide(interaction, "denied")

    async def _finalise_card(self, interaction, status):
        try:
            msg = interaction.message
            emb = msg.embeds[0] if msg.embeds else discord.Embed()
            if status == "accepted":
                emb.colour = 0x4fb3a1
                emb.add_field(name="Status", value=f"✅ Accepted by {interaction.user.mention}", inline=False)
            else:
                emb.colour = 0xd85a30
                emb.add_field(name="Status", value=f"⛔ Denied by {interaction.user.mention}", inline=False)
            for c in self.children:
                c.disabled = True
            await msg.edit(embed=emb, view=self)
        except Exception as e:
            print(f"[JOIN] card finalise failed: {e}")


class JoinCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Register the persistent view once so the buttons keep working after restarts.
        self.bot.add_view(JoinRequestView(self.bot))

    async def post_request(self, req_id, ign, note, discord_id=None, discord_username=None):
        """Post a join-request card to the admin channel; record its message id."""
        ch = self.bot.get_channel(config.ADMIN_CHANNEL_ID)
        if ch is None:
            print("[JOIN] admin channel not found")
            return False
        emb = discord.Embed(title="\U0001f3ab New join request", colour=0xe0a84c)
        if discord_id:
            who = f"<@{discord_id}>" + (f" (`{discord_username}`)" if discord_username else "")
            emb.add_field(name="Discord", value=who + f"\n`{discord_id}`", inline=False)
        emb.add_field(name="Name / IGN", value=(ign or "—")[:100], inline=False)
        if note:
            emb.add_field(name="Note", value=note[:1000], inline=False)
        emb.set_footer(text=f"Request #{req_id} · from the website" + (" · Discord-verified" if discord_id else ""))
        try:
            msg = await ch.send(embed=emb, view=JoinRequestView(self.bot),
                                allowed_mentions=discord.AllowedMentions.none())
        except Exception as e:
            print(f"[JOIN] post_request failed: {e}")
            return False
        await _db.set_join_request_message(req_id, msg.id)
        return True

    @commands.Cog.listener()
    async def on_member_join(self, member):
        gid = getattr(config, "GUEST_ROLE_ID", 0)
        if not gid or member.guild.id != config.GUILD_ID:
            return
        role = member.guild.get_role(int(gid))
        if role is None:
            return
        try:
            await member.add_roles(role, reason="New arrival — Guest until first 100-kill game")
        except Exception as e:
            print(f"[JOIN] guest role assign failed for {member}: {e}")


async def setup(bot):
    await bot.add_cog(JoinCog(bot))
