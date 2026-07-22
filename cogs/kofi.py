import os
import json
import logging
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web

import config
from utils.db import (
    kofi_init, add_kofi_donation,
    get_kofi_total, get_kofi_dashboard_message, set_kofi_dashboard_message
)

log = logging.getLogger(__name__)

GOAL = config.KOFI_MONTHLY_GOAL
KOFI_URL = config.KOFI_URL


def _build_embed(total: float) -> discord.Embed:
    pct = min(total / GOAL, 1.0)
    filled = int(pct * 10)
    bar = "▓" * filled + "░" * (10 - filled)
    over = total > GOAL

    embed = discord.Embed(
        title="☕ Support the Cigar Lounge Butler",
        description=(
            f"The Butler runs on [Ko-fi]({KOFI_URL}) donations.\n"
            f"Running costs are **${GOAL:.0f}/month**.\n\n"
            f"**Raised so far:** ${total:.2f}\n"
            f"`{bar}` ${total:.2f} / ${GOAL:.0f}"
            + (" ✅" if over else "")
        ),
        color=0xFF5E5B,
    )
    embed.set_footer(text="Every bit helps keep the lights on.")
    return embed


class KofiCog(commands.Cog, name="KofiCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await kofi_init()

    async def update_dashboard(self):
        result = await get_kofi_dashboard_message()
        if not result:
            return
        channel_id, message_id = result
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                return
        total = await get_kofi_total()
        try:
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=_build_embed(total))
        except Exception:
            # Message is gone (deleted / stale id) — repost and save the new id so it self-heals.
            try:
                msg = await channel.send(embed=_build_embed(total))
                await set_kofi_dashboard_message(channel_id, msg.id)
                log.info("[KOFI] Dashboard message was missing — reposted.")
            except Exception as e:
                log.warning(f"[KOFI] Failed to update/repost dashboard: {e}")

    async def handle_webhook(self, request: web.Request) -> web.Response:
        try:
            data = await request.post()
            raw = data.get("data")
            if not raw:
                return web.Response(status=400, text="no data")

            payload = json.loads(raw)

            # Verify token
            expected = os.environ.get("KOFI_TOKEN", "")
            if expected and payload.get("verification_token") != expected:
                log.warning("[KOFI] Invalid verification token")
                return web.Response(status=403, text="forbidden")

            # Only handle donations (not shop orders etc.)
            if payload.get("type") not in ("Donation", "Subscription"):
                return web.Response(text="ok")

            transaction_id = payload.get("kofi_transaction_id", "")
            donor_name = payload.get("from_name", "Anonymous")
            amount = float(payload.get("amount", 0))
            currency = payload.get("currency", "USD")

            inserted = await add_kofi_donation(transaction_id, donor_name, amount, currency)
            if inserted:
                log.info(f"[KOFI] New donation: {donor_name} ${amount} {currency}")
                await self.update_dashboard()

            return web.Response(text="ok")
        except Exception as e:
            log.error(f"[KOFI] Webhook error: {e}")
            return web.Response(status=500, text="error")

    @app_commands.command(name="post_kofi_dashboard", description="Post the Ko-fi support dashboard in this channel (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_kofi_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        total = await get_kofi_total()
        msg = await interaction.channel.send(embed=_build_embed(total))
        await set_kofi_dashboard_message(interaction.channel_id, msg.id)
        await interaction.followup.send("Dashboard posted.", ephemeral=True)

    @app_commands.command(name="refresh_kofi", description="Recompute the Ko-fi total and update the dashboard (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def refresh_kofi(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.update_dashboard()
        total = await get_kofi_total()
        await interaction.followup.send(
            f"Dashboard refreshed. Current recorded total: **${total:.2f}**.\n"
            "If that's lower than the real Ko-fi total, a donation webhook was missed \u2014 "
            "use /add_kofi to record it.", ephemeral=True)

    @app_commands.command(name="add_kofi", description="Manually record a Ko-fi donation the webhook missed (admin only).")
    @app_commands.describe(amount="Donation amount (USD)", donor="Donor name")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_kofi(self, interaction: discord.Interaction, amount: float, donor: str = "Manual"):
        await interaction.response.defer(ephemeral=True)
        import time as _t
        inserted = await add_kofi_donation(f"manual-{int(_t.time())}", donor, amount, "USD")
        if not inserted:
            await interaction.followup.send("That entry already exists.", ephemeral=True)
            return
        await self.update_dashboard()
        total = await get_kofi_total()
        await interaction.followup.send(f"Recorded **${amount:.2f}** from {donor}. New total: **${total:.2f}**.", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = KofiCog(bot)
    await bot.add_cog(cog)
    # /kofi route is registered in bot.py (the router freezes before cogs load)
    # and dispatches to handle_webhook per request.
    log.info("[KOFI] Cog loaded — /kofi webhook dispatches via bot.py")
